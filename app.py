import logging
import os
import re
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from flask import Flask, Response, g, jsonify, request

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_PATH = "users.db"
DEFAULT_PORT = 8091
SLOW_TASK_DELAY_SEC = 5
# Lightweight check: no whitespace, exactly one "@", and a dot in the domain.
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# ASCII digits only (no sign, spaces or underscores). 19 digits keeps int()
# cheap; the bound below is the largest value SQLite can store as INTEGER.
USER_ID_PATTERN = re.compile(r"[0-9]{1,19}")
MAX_USER_ID = 2**63 - 1


def database_path_from_env() -> str:
    return os.environ.get("DATABASE_PATH") or DEFAULT_DATABASE_PATH


app = Flask(__name__)
app.config["DATABASE_PATH"] = database_path_from_env()

_active_users_lock = threading.Lock()
_active_users: list[dict[str, Any]] = []


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE_PATH"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exception: BaseException | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def internal_error_response() -> tuple[Response, int]:
    return jsonify(error="internal server error"), 500


@app.errorhandler(sqlite3.Error)
def handle_database_error(exc: sqlite3.Error) -> tuple[Response, int]:
    # Unexpected database failures (unopenable file, missing table, ...) stay
    # JSON like the rest of the API. Details go to the server log only; the
    # client never sees SQL text or exception messages. Expected conditions
    # (400/404/409) are returned by the views themselves and never reach here.
    logger.error("unexpected database error", exc_info=exc)
    return internal_error_response()


def init_db() -> None:
    database_path = app.config["DATABASE_PATH"]
    # The data directory (e.g. /app/data in Docker) must exist before SQLite
    # can create the database file inside it.
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE
            )
            """
        )
        conn.commit()


def parse_user_id(uid: str) -> int | None:
    if not USER_ID_PATTERN.fullmatch(uid):
        return None
    user_id = int(uid)
    if not 1 <= user_id <= MAX_USER_ID:
        return None
    return user_id


def validate_user_payload(
    data: Any,
) -> tuple[tuple[str, str], None] | tuple[None, str]:
    if not isinstance(data, dict):
        return None, "request body must be a JSON object"

    name = data.get("name")
    email = data.get("email")

    if not isinstance(name, str) or not name.strip():
        return None, "name must be a non-empty string"

    if not isinstance(email, str) or not email.strip():
        return None, "email must be a non-empty string"

    name = name.strip()
    # Emails are stored lowercased so duplicates are detected case-insensitively.
    email = email.strip().lower()

    if not EMAIL_PATTERN.fullmatch(email):
        return None, "email format is invalid"

    return (name, email), None


def row_to_user(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "name": row["name"], "email": row["email"]}


def add_active_user(user: dict[str, Any]) -> bool:
    with _active_users_lock:
        if any(active["id"] == user["id"] for active in _active_users):
            return False
        _active_users.append(user)
        return True


def get_active_users() -> list[dict[str, Any]]:
    with _active_users_lock:
        return list(_active_users)


def run_slow_task() -> None:
    time.sleep(SLOW_TASK_DELAY_SEC)
    logger.info("slow background task finished")


@app.route("/health")
def health() -> tuple[Response, int]:
    return jsonify(status="ok"), 200


@app.route("/adduser", methods=["POST"])
def add_user() -> tuple[Response, int]:
    data = request.get_json(silent=True)
    validated, error = validate_user_payload(data)
    if error:
        return jsonify(error=error), 400

    name, email = validated
    db = get_db()

    try:
        cursor = db.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            (name, email),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify(error="email already exists"), 409

    user_id = cursor.lastrowid
    return jsonify(
        message="user added",
        user={"id": user_id, "name": name, "email": email},
    ), 201


@app.route("/user/<uid>")
def get_user(uid: str) -> tuple[Response, int]:
    user_id = parse_user_id(uid)
    if user_id is None:
        return jsonify(error="invalid user id"), 400

    row = get_db().execute(
        "SELECT id, name, email FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()

    if row is None:
        return jsonify(error="user not found"), 404

    return jsonify(row_to_user(row)), 200


@app.route("/activate/<uid>", methods=["POST"])
def activate(uid: str) -> tuple[Response, int]:
    user_id = parse_user_id(uid)
    if user_id is None:
        return jsonify(error="invalid user id"), 400

    row = get_db().execute(
        "SELECT id, name, email FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()

    if row is None:
        return jsonify(error="user not found"), 404

    user = row_to_user(row)
    added = add_active_user(user)
    message = "user activated" if added else "user already active"

    return jsonify(message=message, user=user), 200


@app.route("/active")
def list_active() -> tuple[Response, int]:
    return jsonify(users=get_active_users()), 200


@app.route("/slow")
def slow() -> tuple[Response, int]:
    # Educational demo only: an in-process daemon thread. The task is not
    # durable, is lost if the process stops, and there is no limit on how many
    # can run at once. Not a pattern for real background workloads.
    thread = threading.Thread(target=run_slow_task, daemon=True)
    thread.start()
    return jsonify(status="processing", message="task accepted"), 202


@app.route("/wrong")
def wrong() -> tuple[Response, int]:
    try:
        _ = 10 / 0
    except ZeroDivisionError:
        logger.exception("controlled error demonstration")
        return internal_error_response()

    return jsonify(), 200


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Not run at import time, so importing this module (tests, tooling) never
    # touches the filesystem.
    init_db()
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    app.run(host="0.0.0.0", port=port, debug=False)
