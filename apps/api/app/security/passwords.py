"""Password hashing (A2) — Argon2id via `argon2-cffi`, OWASP's current
primary recommendation. No custom cryptography: salt generation, the KDF
itself, its cost parameters and constant-time verification are all the
library's own; this module only adapts its API to this codebase's shape.

Never logs a plaintext password, a hash, or any part of either.
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# argon2-cffi's own defaults (time_cost=3, memory_cost=64 MiB, parallelism=4)
# are already OWASP-aligned; kept explicit here only so a future tuning
# decision has one obvious place to change, not because the defaults are
# wrong.
_hasher = PasswordHasher()

# A bound on the input, not a truncation: Argon2 itself has no short
# secret-length limit (unlike bcrypt's 72-byte cutoff), but a request body
# of unbounded size is still an untrusted-input concern in its own right.
MAX_PASSWORD_LENGTH = 256


class PasswordTooLongError(ValueError):
    """Raised before hashing/verifying — never silently truncated."""


def hash_password(plain_password: str) -> str:
    """Returns an encoded Argon2id hash (algorithm, parameters and salt are
    all embedded in the returned string, per argon2-cffi's own format —
    nothing extra needs to be stored alongside it)."""
    if len(plain_password) > MAX_PASSWORD_LENGTH:
        raise PasswordTooLongError(f"Password exceeds {MAX_PASSWORD_LENGTH} characters.")
    return _hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time verification (argon2-cffi's own). Never raises for a
    wrong password or a malformed/foreign hash — both simply return False,
    so a caller never needs a second exception-handling path to treat
    "wrong password" and "corrupt hash" identically, which is the correct
    external behavior for a login attempt either way."""
    if len(plain_password) > MAX_PASSWORD_LENGTH:
        return False
    try:
        return _hasher.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False
    except Exception:  # noqa: BLE001 — a malformed/foreign hash must never raise into a login attempt
        return False
