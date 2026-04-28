"""Verify V7.1 dashboard login -- end-to-end POST /api/v71/auth/login.

Username via argv. Password via ``getpass.getpass`` (hidden, no log).
Prints token expiry + masked snippets (never the full plaintext token).

Use this after ``create_admin.py`` to confirm the user can authenticate
before deploying the frontend.
"""

from __future__ import annotations

import getpass
import json
import sys
import urllib.error
import urllib.request

LOGIN_URL = "http://43.200.235.74:8080/api/v71/auth/login"


def _mask(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 12:
        return value[:3] + "***"
    return value[:6] + "***" + value[-4:]


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "ERROR: username missing -- run via verify_login.ps1",
            file=sys.stderr,
        )
        return 1
    username = sys.argv[1].strip()

    try:
        password = getpass.getpass("password (hidden): ")
    except (EOFError, KeyboardInterrupt):
        print("\nERROR: input aborted", file=sys.stderr)
        return 1
    if not password:
        print("ERROR: empty password", file=sys.stderr)
        return 1

    body = json.dumps(
        {"username": username, "password": password},
    ).encode("utf-8")
    password = ""  # noqa: F841 -- drop reference

    req = urllib.request.Request(
        LOGIN_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} from server")
        print(f"body: {e.read().decode('utf-8', errors='replace')}")
        return 1
    except urllib.error.URLError as e:
        print(f"connection failed: {e.reason}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {type(e).__name__}: {e}")
        return 1

    print(f"HTTP {status}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print(f"non-JSON body: {text[:200]}")
        return 1

    body_data = data.get("data") or {}
    if "access_token" in body_data:
        print(f"  access_token  : {_mask(body_data['access_token'])}")
        print(f"  refresh_token : {_mask(body_data.get('refresh_token', ''))}")
        print(f"  expires_in    : {body_data.get('expires_in')} seconds")
        print()
        print("OK: login succeeded (TOTP not required for this user)")
        return 0
    if "session_id" in body_data:
        print(f"  totp_session_id : {_mask(body_data['session_id'])}")
        print()
        print("INFO: login step 1 OK -- TOTP code required (step 2 not yet wired)")
        return 0

    print(f"unexpected response: {data}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
