"""Hash a local-admin password to seed ``MAGISTER_LOCAL_ADMIN_PASSWORD_HASH``.

Run as ``python -m magister_api.cli.hash_password`` inside the API container or
venv. The plaintext is read from **stdin** (one line, never echoed) so it can
be piped without landing in a shell history or process list:

    printf '%s' "$PW" | docker run --rm -i --entrypoint python \\
        ghcr.io/vita-brevis-gmbh/magister-api:latest \\
        -m magister_api.cli.hash_password

This reuses ``auth.passwords.hash_password`` — the same tuned argon2id
parameters the login path verifies against — so the emitted hash never
triggers a rehash-on-first-login. The ``magister-cli hash-password`` wrapper
stays available for repo checkouts; this module is the image-only path that
needs neither a checkout nor ``uv``.

Note: this module only exists in images built from this commit onward.
``scripts/install-magister.sh`` deliberately imports ``auth.passwords``
inline instead of shelling out to this module, so it also works against an
older published image that predates it.
"""

from __future__ import annotations

import sys

# Mirror the break-glass rule enforced by scripts/magister-cli.
MIN_PASSWORD_LENGTH = 12


def main(argv: list[str] | None = None) -> int:
    # No DB, no config, no FastAPI — hashing is pure, so importing here keeps
    # the module cheap to load under `python -m`.
    from magister_api.auth.passwords import hash_password

    password = sys.stdin.readline().rstrip("\n")

    if len(password) < MIN_PASSWORD_LENGTH:
        sys.stderr.write(
            f"Refusing to hash a password under {MIN_PASSWORD_LENGTH} characters — "
            "set a stronger one for an admin break-glass account.\n"
        )
        return 1

    sys.stdout.write(hash_password(password) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
