"""Smoke-test for the running Flask API."""

import os
import sys
import time

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8091"
BASE_URL = os.environ.get("API_BASE_URL", DEFAULT_BASE_URL)
TIMEOUT = 10


def report(name: str, passed: bool, detail: str = "") -> bool:
    status = "OK" if passed else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return passed


def parse_json(response: requests.Response) -> dict:
    content_type = response.headers.get("Content-Type", "")
    if "application/json" not in content_type:
        return {}
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def main() -> int:
    results: list[bool] = []
    created_user_id: int | None = None

    try:
        response = requests.get(f"{BASE_URL}/health", timeout=TIMEOUT)
        body = parse_json(response)
        results.append(
            report(
                "GET /health",
                response.status_code == 200 and body.get("status") == "ok",
                f"status={response.status_code}, body={body}",
            )
        )

        unique_suffix = int(time.time() * 1000)
        payload = {
            "name": "Smoke Test User",
            "email": f"smoke_{unique_suffix}@example.com",
        }
        response = requests.post(
            f"{BASE_URL}/adduser",
            json=payload,
            timeout=TIMEOUT,
        )
        body = parse_json(response)
        created_user_id = body.get("user", {}).get("id")
        results.append(
            report(
                "POST /adduser",
                response.status_code == 201 and created_user_id is not None,
                f"status={response.status_code}, user_id={created_user_id}",
            )
        )

        if created_user_id is not None:
            response = requests.get(
                f"{BASE_URL}/user/{created_user_id}",
                timeout=TIMEOUT,
            )
            body = parse_json(response)
            results.append(
                report(
                    f"GET /user/{created_user_id}",
                    response.status_code == 200
                    and body.get("id") == created_user_id
                    and body.get("name") == payload["name"]
                    and body.get("email") == payload["email"],
                    f"status={response.status_code}, body={body}",
                )
            )
        else:
            results.append(
                report("GET /user/<id>", False, "skipped: user was not created")
            )

        response = requests.get(f"{BASE_URL}/user/999999", timeout=TIMEOUT)
        body = parse_json(response)
        results.append(
            report(
                "GET /user/999999",
                response.status_code == 404 and "error" in body,
                f"status={response.status_code}, body={body}",
            )
        )

        if created_user_id is not None:
            response = requests.post(
                f"{BASE_URL}/activate/{created_user_id}",
                timeout=TIMEOUT,
            )
            body = parse_json(response)
            results.append(
                report(
                    f"POST /activate/{created_user_id}",
                    response.status_code == 200 and "user" in body,
                    f"status={response.status_code}, body={body}",
                )
            )
        else:
            results.append(
                report(
                    "POST /activate/<id>",
                    False,
                    "skipped: user was not created",
                )
            )

        response = requests.get(f"{BASE_URL}/active", timeout=TIMEOUT)
        body = parse_json(response)
        users = body.get("users", [])
        active_ids = [user.get("id") for user in users if isinstance(user, dict)]
        active_ok = response.status_code == 200 and isinstance(users, list)
        if created_user_id is not None:
            active_ok = active_ok and created_user_id in active_ids
        results.append(
            report(
                "GET /active",
                active_ok,
                f"status={response.status_code}, active_ids={active_ids}",
            )
        )

        response = requests.get(f"{BASE_URL}/slow", timeout=TIMEOUT)
        body = parse_json(response)
        results.append(
            report(
                "GET /slow",
                response.status_code == 202,
                f"status={response.status_code}, body={body}",
            )
        )

        response = requests.get(f"{BASE_URL}/wrong", timeout=TIMEOUT)
        body = parse_json(response)
        results.append(
            report(
                "GET /wrong",
                response.status_code == 500 and "error" in body,
                f"status={response.status_code}, body={body}",
            )
        )

    except requests.RequestException as exc:
        print(f"[FAIL] API connection — {exc}")
        print(f"Make sure the server is running at {BASE_URL}")
        return 1

    passed = sum(results)
    total = len(results)
    print(f"\n{passed}/{total} checks passed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
