import hmac
import os


def get_signing_key() -> bytes:
    return os.environ.get("DEMO_SIGNING_KEY", "").encode()


def sign(message: str) -> str:
    return hmac.new(get_signing_key(), message.encode(), "sha256").hexdigest()


def verify(message: str, signature: str) -> bool:
    return hmac.compare_digest(sign(message), signature)
