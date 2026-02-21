"""Encrypt/decrypt broker credentials using Fernet symmetric encryption."""

from cryptography.fernet import Fernet
from app.config import settings


def _get_cipher() -> Fernet:
    if not settings.encryption_key:
        raise ValueError("ENCRYPTION_KEY not set in environment")
    return Fernet(settings.encryption_key.encode())


def encrypt(plain_text: str) -> str:
    """Encrypt a string and return base64 encoded ciphertext."""
    return _get_cipher().encrypt(plain_text.encode()).decode()


def decrypt(cipher_text: str) -> str:
    """Decrypt a base64 encoded ciphertext."""
    return _get_cipher().decrypt(cipher_text.encode()).decode()
