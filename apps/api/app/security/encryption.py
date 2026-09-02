"""Symmetric encryption for Credential.encrypted_value. Real crypto, not a
placeholder — Section 19 of the master context rules out anything that
merely looks like it works. What's genuinely out of scope for this phase
is any real OAuth/provider flow that would produce a secret worth
encrypting in the first place.
"""

from cryptography.fernet import Fernet, InvalidToken


class CredentialCipher:
    def __init__(self, key: bytes | str) -> None:
        if isinstance(key, str):
            key = key.encode("utf-8")
        self._fernet = Fernet(key)

    @staticmethod
    def generate_key() -> str:
        """Convenience for provisioning a new CREDENTIAL_ENCRYPTION_KEY —
        not called anywhere at runtime."""
        return Fernet.generate_key().decode("utf-8")

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("credential could not be decrypted: wrong key or corrupted value") from exc
