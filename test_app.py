"""Isolated unit tests for the Flask API (standard-library unittest only).

Every test gets its own temporary SQLite database and an empty in-memory
active-users list, so tests never share state and never touch users.db.

Run:
    python -m unittest test_app -v

For a check against an already running server, see test_endpoints.py.
"""

import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from unittest import mock

import app as app_module


class ApiTestCase(unittest.TestCase):
    """Base class: temporary database + clean process-local state per test."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_dir = tmp.name
        self.db_path = os.path.join(self.tmp_dir, "test_users.db")

        for patcher in (
            mock.patch.dict(app_module.app.config, {"DATABASE_PATH": self.db_path}),
            mock.patch.object(app_module, "_active_users", []),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        app_module.init_db()
        self.client = app_module.app.test_client()

    def add_user(self, name="Alice", email="alice@example.com"):
        return self.client.post("/adduser", json={"name": name, "email": email})

    def post_raw(self, body, content_type="application/json"):
        return self.client.post("/adduser", data=body, content_type=content_type)

    def db_rows(self, sql, params=()):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(sql, params).fetchall()

    def user_count(self) -> int:
        return self.db_rows("SELECT COUNT(*) AS n FROM users")[0]["n"]

    def assert_json_error(self, response, status, message=None):
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        self.assertEqual(response.mimetype, "application/json")
        body = response.get_json()
        self.assertIsInstance(body.get("error"), str)
        if message is not None:
            self.assertEqual(body["error"], message)


class HealthTests(ApiTestCase):
    def test_health_returns_json_200(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(response.get_json(), {"status": "ok"})


class AddUserTests(ApiTestCase):
    def test_valid_user_returns_201(self):
        response = self.add_user()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(
            response.get_json(),
            {
                "message": "user added",
                "user": {"id": 1, "name": "Alice", "email": "alice@example.com"},
            },
        )
        self.assertEqual(self.user_count(), 1)

    def test_different_emails_get_different_ids(self):
        first = self.add_user(email="a@example.com").get_json()["user"]["id"]
        second = self.add_user(email="b@example.com").get_json()["user"]["id"]
        self.assertEqual((first, second), (1, 2))

    def test_name_and_email_are_trimmed(self):
        response = self.add_user(name="  Bob  ", email=" \tbob@example.com\n ")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.get_json()["user"],
            {"id": 1, "name": "Bob", "email": "bob@example.com"},
        )

    def test_email_is_lowercased_before_storage(self):
        response = self.add_user(email="Case@Test.Example")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["user"]["email"], "case@test.example")
        self.assertEqual(
            [row["email"] for row in self.db_rows("SELECT email FROM users")],
            ["case@test.example"],
        )
        self.assertEqual(
            self.client.get("/user/1").get_json()["email"], "case@test.example"
        )

    def test_exact_duplicate_returns_409(self):
        self.assertEqual(self.add_user().status_code, 201)
        response = self.add_user()
        self.assert_json_error(response, 409, "email already exists")
        self.assertEqual(self.user_count(), 1)

    def test_duplicate_with_different_name_returns_409(self):
        self.add_user(name="Alice")
        self.assert_json_error(self.add_user(name="Other"), 409, "email already exists")

    def test_duplicate_differing_only_by_case_returns_409(self):
        cases = [
            ("Case@Test.Example", "case@test.example"),
            ("beta@test.example", "Beta@Test.Example"),
            ("gamma@test.example", "  GAMMA@TEST.EXAMPLE \n"),
        ]
        for stored_so_far, (first, second) in enumerate(cases, start=1):
            with self.subTest(first=first, second=second):
                self.assertEqual(self.add_user(email=first).status_code, 201)
                self.assert_json_error(
                    self.add_user(email=second), 409, "email already exists"
                )
                self.assertEqual(self.user_count(), stored_so_far)

    def test_email_with_whitespace_is_rejected(self):
        bad_emails = [
            "a @b.com",
            "a@ b.com",
            "a@b .com",
            "a@b. com",
            "a@b.c om",
            "a b@c.com",
            "a\t@b.com",
            "a\n@b.com",
        ]
        for email in bad_emails:
            with self.subTest(email=email):
                self.assert_json_error(
                    self.add_user(email=email), 400, "email format is invalid"
                )
        self.assertEqual(self.user_count(), 0)

    def test_malformed_email_is_rejected(self):
        bad_emails = [
            "plainaddress",
            "a@b",
            "@b.com",
            "a@",
            "a@@b.com",
            "a@b@c.com",
            "a@b.",
        ]
        for email in bad_emails:
            with self.subTest(email=email):
                self.assert_json_error(
                    self.add_user(email=email), 400, "email format is invalid"
                )
        self.assertEqual(self.user_count(), 0)

    def test_missing_body_is_rejected(self):
        response = self.client.post("/adduser")
        self.assert_json_error(response, 400, "request body must be a JSON object")

    def test_body_without_json_content_type_is_rejected(self):
        response = self.post_raw(
            '{"name": "A", "email": "a@b.com"}', content_type="text/plain"
        )
        self.assert_json_error(response, 400, "request body must be a JSON object")
        self.assertEqual(self.user_count(), 0)

    def test_malformed_json_is_rejected(self):
        for body in ("{bad", '{"name": "A",}', ""):
            with self.subTest(body=body):
                self.assert_json_error(
                    self.post_raw(body), 400, "request body must be a JSON object"
                )
        self.assertEqual(self.user_count(), 0)

    def test_non_object_json_is_rejected(self):
        bodies = ("null", "[]", '"text"', "42", "true", '[{"name":"A","email":"a@b.com"}]')
        for body in bodies:
            with self.subTest(body=body):
                self.assert_json_error(
                    self.post_raw(body), 400, "request body must be a JSON object"
                )
        self.assertEqual(self.user_count(), 0)

    def test_missing_fields_are_rejected(self):
        cases = [
            ({}, "name must be a non-empty string"),
            ({"email": "a@b.com"}, "name must be a non-empty string"),
            ({"name": "A"}, "email must be a non-empty string"),
        ]
        for payload, message in cases:
            with self.subTest(payload=payload):
                response = self.client.post("/adduser", json=payload)
                self.assert_json_error(response, 400, message)
        self.assertEqual(self.user_count(), 0)

    def test_blank_strings_are_rejected(self):
        for blank in ("", "   ", "\t\n"):
            with self.subTest(blank=blank):
                self.assert_json_error(
                    self.add_user(name=blank), 400, "name must be a non-empty string"
                )
                self.assert_json_error(
                    self.add_user(email=blank), 400, "email must be a non-empty string"
                )
        self.assertEqual(self.user_count(), 0)

    def test_wrong_field_types_are_rejected(self):
        for value in (123, 1.5, True, None, ["a"], {"x": 1}):
            with self.subTest(value=value):
                self.assert_json_error(
                    self.add_user(name=value), 400, "name must be a non-empty string"
                )
                self.assert_json_error(
                    self.add_user(email=value), 400, "email must be a non-empty string"
                )
        self.assertEqual(self.user_count(), 0)


class GetUserTests(ApiTestCase):
    def test_existing_user_is_returned(self):
        self.add_user(name="Alice", email="alice@example.com")
        response = self.client.get("/user/1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(
            response.get_json(),
            {"id": 1, "name": "Alice", "email": "alice@example.com"},
        )

    def test_missing_user_returns_404(self):
        self.assert_json_error(self.client.get("/user/999"), 404, "user not found")

    def test_invalid_ids_return_400(self):
        invalid_ids = [
            "abc",
            "0",
            "-1",
            "1.5",
            "1e3",
            "+1",
            "1_0",
            "%201",  # " 1"
            "٣",  # ARABIC-INDIC DIGIT THREE: int() accepts it, we do not
            str(2**63),  # larger than SQLite's INTEGER; must not become a 500
            "9" * 5000,
        ]
        self.add_user()
        for uid in invalid_ids:
            with self.subTest(uid=uid[:30]):
                self.assert_json_error(
                    self.client.get(f"/user/{uid}"), 400, "invalid user id"
                )

    def test_largest_sqlite_id_is_valid_but_missing(self):
        self.assert_json_error(
            self.client.get(f"/user/{2**63 - 1}"), 404, "user not found"
        )


class ActivateTests(ApiTestCase):
    def test_post_activates_user(self):
        self.add_user()
        response = self.client.post("/activate/1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(
            response.get_json(),
            {
                "message": "user activated",
                "user": {"id": 1, "name": "Alice", "email": "alice@example.com"},
            },
        )

    def test_repeated_activation_is_reported_and_harmless(self):
        self.add_user()
        self.client.post("/activate/1")
        response = self.client.post("/activate/1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["message"], "user already active")
        self.assertEqual(len(self.client.get("/active").get_json()["users"]), 1)

    def test_missing_user_returns_404(self):
        self.assert_json_error(self.client.post("/activate/999"), 404, "user not found")
        self.assertEqual(self.client.get("/active").get_json(), {"users": []})

    def test_invalid_ids_return_400(self):
        for uid in ("abc", "0", "-1", "+1", "1_0", str(2**63)):
            with self.subTest(uid=uid):
                self.assert_json_error(
                    self.client.post(f"/activate/{uid}"), 400, "invalid user id"
                )

    def test_get_is_not_supported(self):
        self.add_user()
        response = self.client.get("/activate/1")
        self.assertEqual(response.status_code, 405)
        allowed = response.headers["Allow"]
        self.assertIn("POST", allowed)
        self.assertNotIn("GET", allowed)
        # The rejected GET must not have activated anything.
        self.assertEqual(self.client.get("/active").get_json(), {"users": []})


class ActiveTests(ApiTestCase):
    def test_no_active_users_initially(self):
        response = self.client.get("/active")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"users": []})

    def test_activated_user_appears_once(self):
        self.add_user()
        self.client.post("/activate/1")
        self.client.post("/activate/1")
        response = self.client.get("/active")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"users": [{"id": 1, "name": "Alice", "email": "alice@example.com"}]},
        )

    def test_only_activated_users_are_listed(self):
        self.add_user(email="a@example.com")
        self.add_user(email="b@example.com")
        self.client.post("/activate/2")
        users = self.client.get("/active").get_json()["users"]
        self.assertEqual([user["id"] for user in users], [2])


class DatabaseSchemaTests(ApiTestCase):
    """A freshly created database must have the intended constraints.

    The previously tracked users.db had an older schema, and CREATE TABLE IF
    NOT EXISTS silently kept it, hiding the NOT NULL / UNIQUE definitions.
    """

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return closing(conn)

    def test_name_and_email_are_not_null(self):
        with self.connect() as conn:
            columns = {row["name"]: row for row in conn.execute("PRAGMA table_info(users)")}
        self.assertEqual(set(columns), {"id", "name", "email"})
        self.assertEqual(columns["id"]["pk"], 1)
        self.assertEqual(columns["name"]["notnull"], 1)
        self.assertEqual(columns["email"]["notnull"], 1)

    def test_email_has_unique_constraint(self):
        with self.connect() as conn:
            unique_index_columns = [
                [col["name"] for col in conn.execute(f'PRAGMA index_info("{index["name"]}")')]
                for index in conn.execute("PRAGMA index_list(users)")
                if index["unique"]
            ]
        self.assertIn(["email"], unique_index_columns)

    def test_database_rejects_null_and_duplicate_values(self):
        with self.connect() as conn:
            conn.execute("INSERT INTO users (name, email) VALUES ('A', 'a@example.com')")
            for sql in (
                "INSERT INTO users (name, email) VALUES (NULL, 'b@example.com')",
                "INSERT INTO users (name, email) VALUES ('B', NULL)",
                "INSERT INTO users (name, email) VALUES ('B', 'a@example.com')",
            ):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(sql)

    def test_init_db_is_idempotent_and_keeps_data(self):
        self.add_user()
        app_module.init_db()
        self.assertEqual(self.user_count(), 1)

    def test_init_db_creates_missing_data_directory(self):
        nested = os.path.join(self.tmp_dir, "data", "deeper", "users.db")
        with mock.patch.dict(app_module.app.config, {"DATABASE_PATH": nested}):
            app_module.init_db()
        self.assertTrue(os.path.isfile(nested))


class DatabasePathTests(unittest.TestCase):
    def test_default_path_when_env_is_unset_or_empty(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("DATABASE_PATH", None)
            self.assertEqual(app_module.database_path_from_env(), "users.db")
            os.environ["DATABASE_PATH"] = ""
            self.assertEqual(app_module.database_path_from_env(), "users.db")

    def test_env_overrides_path(self):
        with mock.patch.dict(os.environ, {"DATABASE_PATH": "/app/data/users.db"}):
            self.assertEqual(app_module.database_path_from_env(), "/app/data/users.db")


class DatabaseFailureTests(ApiTestCase):
    """Unexpected database errors must stay JSON and must not leak details."""

    REQUESTS = (
        ("POST", "/adduser", {"json": {"name": "A", "email": "a@example.com"}}),
        ("GET", "/user/1", {}),
        ("POST", "/activate/1", {}),
    )

    def assert_generic_json_500(self, response, leaked):
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(response.get_json(), {"error": "internal server error"})
        text = response.get_data(as_text=True)
        for secret in leaked:
            self.assertNotIn(secret, text)

    def run_all_requests(self, leaked):
        for method, url, kwargs in self.REQUESTS:
            with self.subTest(request=f"{method} {url}"):
                with self.assertLogs(app_module.logger, level="ERROR") as logs:
                    response = self.client.open(url, method=method, **kwargs)
                self.assert_generic_json_500(response, leaked)
                # Traceback / details are kept server-side.
                self.assertIn("sqlite3.", "\n".join(logs.output))

    def test_unopenable_database_returns_json_500(self):
        unopenable = os.path.join(self.tmp_dir, "missing_dir", "users.db")
        with mock.patch.dict(app_module.app.config, {"DATABASE_PATH": unopenable}):
            self.run_all_requests(leaked=["missing_dir", "unable to open"])

    def test_missing_table_returns_json_500_without_sql_details(self):
        uninitialised = os.path.join(self.tmp_dir, "uninitialised.db")
        with mock.patch.dict(app_module.app.config, {"DATABASE_PATH": uninitialised}):
            self.run_all_requests(leaked=["no such table", "users", "SELECT", "INSERT"])

    def test_failure_message_is_not_exposed(self):
        boom = sqlite3.OperationalError("SELECT secret FROM hidden_table exploded")
        with mock.patch.object(app_module, "get_db", side_effect=boom):
            with self.assertLogs(app_module.logger, level="ERROR"):
                response = self.client.get("/user/1")
        self.assert_generic_json_500(response, ["secret", "hidden_table", "exploded"])

    def test_expected_errors_are_not_turned_into_500(self):
        self.add_user()
        self.assertEqual(self.add_user().status_code, 409)
        self.assertEqual(self.client.get("/user/999").status_code, 404)
        self.assertEqual(self.client.get("/user/abc").status_code, 400)
        self.assertEqual(self.client.post("/adduser", json={}).status_code, 400)

    def test_wrong_endpoint_is_a_controlled_json_500(self):
        with self.assertLogs(app_module.logger, level="ERROR"):
            response = self.client.get("/wrong")
        self.assert_generic_json_500(response, ["ZeroDivisionError", "division"])


class SlowTests(ApiTestCase):
    def test_slow_accepts_task_on_a_daemon_thread(self):
        started = threading.Event()
        seen = {}

        def fake_task():
            seen["daemon"] = threading.current_thread().daemon
            started.set()

        with mock.patch.object(app_module, "run_slow_task", fake_task):
            response = self.client.get("/slow")

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.get_json(),
            {"status": "processing", "message": "task accepted"},
        )
        self.assertTrue(started.wait(timeout=5), "background task did not start")
        self.assertTrue(seen["daemon"])


if __name__ == "__main__":
    unittest.main()
