"""Generate an API key and the API_KEYS entry for it.

    python -m scripts.hash_api_key <name> <viewer|researcher|operator|admin>

Prints the plaintext key ONCE (give it to the user) and the
`name:role:sha256hex` entry to add to API_KEYS. The plaintext is never stored.
"""
from __future__ import annotations

import secrets
import sys

from app.core.security import Role, hash_api_key


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[2].upper() not in Role.__members__:
        print(__doc__)
        return 2
    name, role = argv[1], argv[2].lower()
    key = secrets.token_urlsafe(32)
    print(f"API key (store securely, shown once): {key}")
    print(f"API_KEYS entry: {name}:{role}:{hash_api_key(key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
