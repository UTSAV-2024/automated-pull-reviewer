import hashlib
import hmac

from fastapi.testclient import TestClient

from app.webhook_receiver.main import WEBHOOK_SECRET, create_app
from app.webhook_receiver.signature import verify_signature

PAYLOAD = b'{"action": "opened", "number": 1}'


def sign(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


class FakeQueue:
    """Records enqueue calls; mirrors the dedupe_and_enqueue contract."""

    def __init__(self):
        self.enqueued: list[str] = []
        self._seen: set[str] = set()

    async def dedupe_and_enqueue(self, delivery_id: str, payload: bytes) -> bool:
        if delivery_id in self._seen:
            return False
        self._seen.add(delivery_id)
        self.enqueued.append(delivery_id)
        return True


def make_client(queue: FakeQueue) -> TestClient:
    return TestClient(create_app(queue.dedupe_and_enqueue))


def test_verify_signature_accepts_matching_hmac():
    assert verify_signature(PAYLOAD, sign(PAYLOAD), WEBHOOK_SECRET)


def test_verify_signature_rejects_wrong_secret():
    assert not verify_signature(PAYLOAD, sign(PAYLOAD, secret="wrong"), WEBHOOK_SECRET)


def test_verify_signature_rejects_missing_header():
    assert not verify_signature(PAYLOAD, None, WEBHOOK_SECRET)


def test_valid_pull_request_webhook_is_accepted_and_enqueued():
    queue = FakeQueue()
    client = make_client(queue)

    response = client.post(
        "/webhooks/github",
        content=PAYLOAD,
        headers={
            "X-Hub-Signature-256": sign(PAYLOAD),
            "X-GitHub-Delivery": "delivery-1",
            "X-GitHub-Event": "pull_request",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert queue.enqueued == ["delivery-1"]


def test_invalid_signature_is_rejected():
    queue = FakeQueue()
    client = make_client(queue)

    response = client.post(
        "/webhooks/github",
        content=PAYLOAD,
        headers={
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Delivery": "delivery-1",
            "X-GitHub-Event": "pull_request",
        },
    )

    assert response.status_code == 401
    assert queue.enqueued == []


def test_missing_delivery_id_is_rejected():
    queue = FakeQueue()
    client = make_client(queue)

    response = client.post(
        "/webhooks/github",
        content=PAYLOAD,
        headers={
            "X-Hub-Signature-256": sign(PAYLOAD),
            "X-GitHub-Event": "pull_request",
        },
    )

    assert response.status_code == 400
    assert queue.enqueued == []


def test_non_pull_request_event_is_ignored_without_enqueueing():
    queue = FakeQueue()
    client = make_client(queue)

    response = client.post(
        "/webhooks/github",
        content=PAYLOAD,
        headers={
            "X-Hub-Signature-256": sign(PAYLOAD),
            "X-GitHub-Delivery": "delivery-1",
            "X-GitHub-Event": "issue_comment",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert queue.enqueued == []


def test_duplicate_delivery_id_is_not_enqueued_twice():
    queue = FakeQueue()
    client = make_client(queue)
    headers = {
        "X-Hub-Signature-256": sign(PAYLOAD),
        "X-GitHub-Delivery": "delivery-1",
        "X-GitHub-Event": "pull_request",
    }

    first = client.post("/webhooks/github", content=PAYLOAD, headers=headers)
    second = client.post("/webhooks/github", content=PAYLOAD, headers=headers)

    assert first.status_code == 200 and first.json()["status"] == "accepted"
    assert second.status_code == 200 and second.json()["status"] == "duplicate"
    assert queue.enqueued == ["delivery-1"]
