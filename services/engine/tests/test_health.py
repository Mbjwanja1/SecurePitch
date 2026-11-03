import pytest
from fastapi.testclient import TestClient

from app.main import create_app

KEY = "test-key-that-is-long-enough-for-the-engine-1234"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ENGINE_INTERNAL_KEY", KEY)
    return TestClient(create_app())


def test_health_is_public(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ping_rejects_missing_key(client: TestClient) -> None:
    assert client.get("/v1/ping").status_code == 401


def test_ping_rejects_wrong_key(client: TestClient) -> None:
    assert client.get("/v1/ping", headers={"X-Internal-Key": "wrong"}).status_code == 401


def test_ping_accepts_correct_key(client: TestClient) -> None:
    r = client.get("/v1/ping", headers={"X-Internal-Key": KEY})
    assert r.status_code == 200
    assert r.json()["pong"] is True


def test_ping_fails_closed_without_configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENGINE_INTERNAL_KEY", raising=False)
    r = TestClient(create_app()).get("/v1/ping", headers={"X-Internal-Key": ""})
    assert r.status_code == 503


def test_docs_hidden_outside_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGINE_ENV", "prod")
    monkeypatch.setenv("ENGINE_INTERNAL_KEY", KEY)
    prod = TestClient(create_app())
    assert prod.get("/docs").status_code == 401  # the gate answers before anything is revealed
    assert prod.get("/docs", headers={"X-Internal-Key": KEY}).status_code == 404


def test_docs_public_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGINE_ENV", "dev")
    monkeypatch.setenv("ENGINE_INTERNAL_KEY", KEY)
    assert TestClient(create_app()).get("/docs").status_code == 200


def test_oversized_upload_rejected_end_to_end(client: TestClient) -> None:
    r = client.post(
        "/v1/ping",
        content=b"x" * (6 * 1024 * 1024 + 1),
        headers={"X-Internal-Key": KEY},
    )
    assert r.status_code == 413
