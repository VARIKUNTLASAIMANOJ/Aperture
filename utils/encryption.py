"""
AES-256-GCM field-level encryption for PII data.
Key material is loaded from environment (never hardcoded).
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_key() -> bytes:
    """Load AES-256 key from environment variable (must be 32 bytes, base64-encoded)."""
    raw = os.environ.get("PII_ENCRYPTION_KEY_B64")
    if not raw:
        raise EnvironmentError("PII_ENCRYPTION_KEY_B64 env var is required but not set.")
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise ValueError("PII_ENCRYPTION_KEY_B64 must decode to exactly 32 bytes for AES-256.")
    return key


def encrypt_pii(plaintext: str) -> str:
    """
    Encrypt a PII string using AES-256-GCM.
    Returns a base64-encoded string: nonce(12) || ciphertext+tag.
    """
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    blob = nonce + ct
    return base64.b64encode(blob).decode()


def decrypt_pii(encrypted_b64: str) -> str:
    """
    Decrypt an AES-256-GCM encrypted PII blob.
    Raises cryptography.exceptions.InvalidTag if tampered.
    """
    key = _get_key()
    aesgcm = AESGCM(key)
    blob = base64.b64decode(encrypted_b64)
    nonce, ct = blob[:12], blob[12:]
    return aesgcm.decrypt(nonce, ct, None).decode()