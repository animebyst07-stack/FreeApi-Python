import base64
import hashlib
import hmac
import os
import secrets
import uuid

from freeapi.config import SESSION_SECRET


def uuid4():
    return str(uuid.uuid4())


def generate_api_key():
    return 'fa_sk_' + secrets.token_hex(32)


def mask_key(value):
    if not value or len(value) <= 14:
        return value
    return value[:7] + '•' * 16 + value[-3:]


def key_bytes():
    return hashlib.sha256(SESSION_SECRET.encode()).digest()


def stream(nonce, length):
    result = b''
    counter = 0
    while len(result) < length:
        result += hmac.new(key_bytes(), nonce + counter.to_bytes(8, 'big'), hashlib.sha256).digest()
        counter += 1
    return result[:length]


def encrypt_text(text):
    if text is None:
        return None
    raw = text.encode('utf-8')
    nonce = os.urandom(16)
    encrypted = bytes(a ^ b for a, b in zip(raw, stream(nonce, len(raw))))
    mac = hmac.new(key_bytes(), nonce + encrypted, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + mac + encrypted).decode('ascii')


def decrypt_text(value):
    if not value:
        return None
    data = base64.urlsafe_b64decode(value.encode('ascii'))
    nonce, mac, encrypted = data[:16], data[16:48], data[48:]
    expected = hmac.new(key_bytes(), nonce + encrypted, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError('Неверная подпись зашифрованных данных')
    return bytes(a ^ b for a, b in zip(encrypted, stream(nonce, len(encrypted)))).decode('utf-8')
