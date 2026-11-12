import base64
import secrets
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import (
    TokenEncryptionConfigurationError,
    get_token_encryption_keys,
)


class TokenDecryptionError(Exception):
    pass


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def encrypt_token(value: str, account_id: UUID, token_type: str) -> str:
    current_id, keys = get_token_encryption_keys()
    nonce = secrets.token_bytes(12)
    aad = f"mailmind:gmail:{account_id}:{token_type}".encode("utf-8")
    ciphertext = AESGCM(keys[current_id]).encrypt(
        nonce, value.encode("utf-8"), aad
    )
    return f"v1.{current_id}.{_encode(nonce)}.{_encode(ciphertext)}"


def decrypt_token(value: str, account_id: UUID, token_type: str) -> str:
    try:
        version, key_id, encoded_nonce, encoded_ciphertext = value.split(".", 3)
    except ValueError as error:
        raise TokenDecryptionError("Stored Gmail credential is invalid") from error
    if version != "v1":
        raise TokenDecryptionError("Stored Gmail credential version is unsupported")
    try:
        _, keys = get_token_encryption_keys()
    except TokenEncryptionConfigurationError:
        raise
    key = keys.get(key_id)
    if key is None:
        raise TokenDecryptionError("Stored Gmail credential key is unavailable")
    try:
        nonce = _decode(encoded_nonce)
        ciphertext = _decode(encoded_ciphertext)
        if len(nonce) != 12:
            raise TokenDecryptionError("Stored Gmail credential nonce is invalid")
        aad = f"mailmind:gmail:{account_id}:{token_type}".encode("utf-8")
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad)
        return plaintext.decode("utf-8")
    except (InvalidTag, UnicodeDecodeError, ValueError) as error:
        raise TokenDecryptionError("Stored Gmail credential failed authentication") from error


def uses_current_key(value: str) -> bool:
    try:
        version, key_id, _, _ = value.split(".", 3)
    except ValueError as error:
        raise TokenDecryptionError("Stored Gmail credential is invalid") from error
    if version != "v1":
        raise TokenDecryptionError("Stored Gmail credential version is unsupported")
    current_id, _ = get_token_encryption_keys()
    return key_id == current_id
