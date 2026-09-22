"""Opaque session and CSRF token generation (A2) — `secrets.token_urlsafe`,
Python's own CSPRNG-backed generator; no custom randomness or encoding.

DB REPRESENTATION. A session's raw token is a bearer credential exactly like
a password: this codebase never stores it — only `hash_token`'s SHA-256
digest is persisted (see app.db.models.user_session.UserSession.token_hash),
so a read of the `user_sessions` table (a backup, a compromised replica, a
stray log of a query) can never itself be used to log in as anyone. The raw
token exists only in the `Set-Cookie` response once, and in the browser's
cookie jar after that. SHA-256 (not Argon2/bcrypt) is the right primitive
here — unlike a password, a session token is already 256 bits of uniform
random entropy, not a low-entropy human-chosen secret, so it needs a fast
collision-resistant digest for O(1) lookup, not a deliberately slow KDF.

The CSRF token is generated the same way but stored in plain (not hashed) on
the `UserSession` row — see app.dependencies' CSRF check for why: it is
compared for equality against a header the client echoes back, never looked
up as a credential on its own, so hashing it would add cost without adding
security.
"""

import hashlib
import secrets

# 32 bytes -> 256 bits of entropy before the URL-safe base64 encoding
# token_urlsafe applies (its output is longer than 32 characters as a
# result) — comfortably beyond any feasible guessing/brute-force budget.
TOKEN_BYTES = 32


def generate_token() -> str:
    """A fresh, unguessable opaque token — used for both session and CSRF
    tokens (they serve different purposes but have identical entropy
    requirements)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 hex digest — deterministic, so a session token can be looked
    up by its hash without ever storing the token itself. Never used for
    passwords (see app.security.passwords for why those need Argon2, not a
    fast hash)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
