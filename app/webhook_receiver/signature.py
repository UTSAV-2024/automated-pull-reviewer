import hashlib
import hmac


def verify_signature(payload: bytes, signature_header: str | None, secret: str) -> bool:
    """Verify a GitHub `X-Hub-Signature-256` header against the raw request body."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
