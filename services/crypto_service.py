"""
crypto_service.py
-----------------
Encryption/decryption for sensitive data at rest.
Uses Fernet (AES-128-CBC + HMAC-SHA256) with key derived from
ENCRYPTION_KEY env var (preferred) or SECRET_KEY (fallback).
"""

import os
import base64
import hashlib
from cryptography.fernet import Fernet

_KEY_CACHE = None


def _get_fernet_key():
    global _KEY_CACHE
    if _KEY_CACHE:
        return _KEY_CACHE

    # Use explicit ENCRYPTION_KEY if provided
    raw = os.environ.get('ENCRYPTION_KEY')
    if raw:
        try:
            key = raw.encode() if isinstance(raw, str) else raw
            Fernet(key)
            _KEY_CACHE = key
            return key
        except Exception:
            pass

    # Fallback: derive from SECRET_KEY
    secret = os.environ.get('SECRET_KEY')
    if not secret or secret == 'dev-secret-key-change-in-production':
        import warnings
        warnings.warn(
            'CRITICAL: Using default SECRET_KEY for encryption. '
            'Set a strong ENCRYPTION_KEY in production!'
        )
        secret = secret or 'default-fallback-secret-key-12345'

    hashed = hashlib.sha256(secret.encode()).digest()
    derived = base64.urlsafe_b64encode(hashed)
    _KEY_CACHE = derived
    return derived


def encrypt_data(data: str) -> str:
    """Encrypt a string and return a secure base64 token."""
    if not data:
        return ''
    try:
        key = _get_fernet_key()
        return Fernet(key).encrypt(data.encode()).decode()
    except Exception as e:
        print(f'[crypto] encrypt error: {e}')
        return ''


def decrypt_data(token: str) -> str:
    """Decrypt a token and return plaintext."""
    if not token:
        return ''
    try:
        key = _get_fernet_key()
        return Fernet(key).decrypt(token.encode()).decode()
    except Exception as e:
        print(f'[crypto] decrypt error: {e}')
        return ''


def health_check():
    """
    Verify encryption key is functional.
    Returns (ok: bool, message: str).
    """
    try:
        test = encrypt_data('health-check')
        result = decrypt_data(test)
        if result != 'health-check':
            return False, 'Encryption round-trip failed'
        key = os.environ.get('ENCRYPTION_KEY')
        if not key:
            return False, 'Using derived key (SECRET_KEY) — set ENCRYPTION_KEY for security'
        return True, 'Encryption is healthy'
    except Exception as e:
        return False, f'Encryption error: {e}'
