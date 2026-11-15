"""Reset a local account password using direct administrator access to its database."""
from __future__ import annotations

import getpass
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import hash_password
from app.config import DATABASE_PATH, DATABASE_URL
from app.repository import SQLiteRepository

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")


def reset_password(repository, username: str, password: str) -> bool:
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("Username must be 3-40 letters, numbers, dots, underscores, or hyphens.")
    if not 8 <= len(password) <= 128:
        raise ValueError("Password must be between 8 and 128 characters.")
    return repository.update_user_password(username, hash_password(password))


def main() -> int:
    username = input("Account username: ").strip()
    password = getpass.getpass("New password (input hidden): ")
    confirmation = getpass.getpass("Confirm new password: ")
    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 1

    if DATABASE_URL:
        from app.postgres_repository import PostgresRepository

        repository = PostgresRepository(DATABASE_URL)
    else:
        repository = SQLiteRepository(DATABASE_PATH)
    repository.initialize()

    try:
        changed = reset_password(repository, username, password)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not changed:
        print("No account with that username was found.", file=sys.stderr)
        return 1

    print("Password updated. Sign in with the new password.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
