"""
Encryption utilities for passwords and OAuth tokens.
Uses Fernet symmetric encryption from the cryptography library.
"""
import os
import base64
import hashlib
from cryptography.fernet import Fernet

KEY_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "secret.key")


def _get_or_create_key() -> bytes:
    """Load or generate encryption key."""
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    return key


fernet = Fernet(_get_or_create_key())


def encrypt(plain_text: str) -> str:
    """Encrypt a string, return base64-encoded ciphertext."""
    return fernet.encrypt(plain_text.encode()).decode()


def decrypt(cipher_text: str) -> str:
    """Decrypt base64-encoded ciphertext."""
    return fernet.decrypt(cipher_text.encode()).decode()


def md5_hash(data: bytes) -> str:
    """Compute MD5 hash of data."""
    return hashlib.md5(data).hexdigest()
