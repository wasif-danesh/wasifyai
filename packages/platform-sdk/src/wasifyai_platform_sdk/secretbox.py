"""Encrypts the few secrets we must keep ourselves (media provider API keys; ADR-0025).

LLM keys are kept by LiteLLM. These are not, so they are encrypted at rest with a key that comes
from the environment (`MEDIA_SECRETS_KEY`) and never from the database. Changing the key makes
saved secrets unreadable: enter them again."""

from cryptography.fernet import Fernet, InvalidToken


class SecretsUnavailable(Exception):
    """No usable encryption key, or a stored secret cannot be decrypted with it."""


class SecretBox:
    def __init__(self, key: str):
        try:
            self._fernet = Fernet(key.encode()) if key else None
        except ValueError:
            self._fernet = None  # not a valid key (for example the .env.example placeholder)

    @property
    def ready(self) -> bool:
        return self._fernet is not None

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()

    def encrypt(self, plain: str) -> str:
        if self._fernet is None:
            raise SecretsUnavailable("MEDIA_SECRETS_KEY is not set to a valid key (run make setup)")
        return self._fernet.encrypt(plain.encode()).decode()

    def decrypt(self, token: str) -> str:
        if self._fernet is None:
            raise SecretsUnavailable("MEDIA_SECRETS_KEY is not set to a valid key (run make setup)")
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise SecretsUnavailable(
                "a saved secret cannot be read with the current MEDIA_SECRETS_KEY; enter it again"
            ) from exc
