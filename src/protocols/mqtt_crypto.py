"""The AES-CTR encryption used on the MQTT/UDP audio channel."""

from __future__ import annotations

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def aes_ctr_encrypt(key: bytes, nonce: bytes, plaintext: bytes) -> bytes:
    """AES-CTR encryption.

    Args:
        key: the key
        nonce: the initial vector (the same one used to decrypt)
        plaintext: the plaintext
    """
    cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
    encryptor = cipher.encryptor()
    return encryptor.update(plaintext) + encryptor.finalize()


def aes_ctr_decrypt(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    """AES-CTR decryption.

    Args:
        key: the key
        nonce: the same nonce that was used to encrypt
        ciphertext: the ciphertext
    """
    cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
    decryptor = cipher.decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


def build_audio_nonce(aes_nonce_hex: str, audio_len: int, sequence: int) -> str:
    """Build the nonce for a UDP audio packet, as a hex string.

    Layout: a fixed 4-hex prefix, then 4 hex of length, 16 hex of the original nonce, and 8 hex of sequence number
    """
    return (
        aes_nonce_hex[:4]
        + format(audio_len, "04x")
        + aes_nonce_hex[8:24]
        + format(sequence, "08x")
    )
