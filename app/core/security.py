from typing import Any

from app.data.database import db
from app.core.exceptions import ValidationError


def encrypt_value(plaintext: str) -> bytes:
    """
    Encrypt a plaintext string using PostgreSQL pgcrypto via the Database wrapper.
    """
    try:
        return db.encrypt(plaintext)
    except Exception as e:
        raise ValidationError(f"Encryption failed: {e}")


def decrypt_value(ciphertext: bytes) -> str:
    """
    Decrypt ciphertext bytes using PostgreSQL pgcrypto via the Database wrapper.
    """
    try:
        return db.decrypt(ciphertext)
    except Exception as e:
        raise ValidationError(f"Decryption failed: {e}")


def secure_compare(a: Any, b: Any) -> bool:
    """
    Securely compare two values (e.g., tokens) to mitigate timing attacks.
    """
    # Use constant-time comparison
    try:
        # Convert to bytes for comparison
        a_bytes = a.encode() if isinstance(a, str) else a
        b_bytes = b.encode() if isinstance(b, str) else b
        if not isinstance(a_bytes, (bytes, bytearray)) or not isinstance(b_bytes, (bytes, bytearray)):
            raise ValidationError("Values must be bytes or string types for secure comparison")
        # Python's built-in constant-time compare
        from hmac import compare_digest
        return compare_digest(a_bytes, b_bytes)
    except Exception as e:
        raise ValidationError(f"Secure compare error: {e}")
