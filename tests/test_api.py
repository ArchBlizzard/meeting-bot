import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from main import app
from providers.mock import MockBotProvider
from providers.base import VexaUnavailableError
from database.session import get_db


@pytest.fixture
def client(tmp_path):
    """Test client with in-memory SQLite and mock provider."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.models import Base
    import main

    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    main.provider = MockBotProvider()
    app.dependency_overrides[get_db] = override_db

    with TestClient(app) as c:
        yield c, TestSession

    app.dependency_overrides.clear()


# ── POST /meeting/join ────────────────────────────────────────────────────────

class TestJoinEndpoint:
    def test_join_by_url_returns_200(self, client):
        c, _ = client
        resp = c.post("/meeting/join", json={"url": "https://meet.google.com/abc-defg-hij"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["meeting_id"] == "abc-defg-hij"
        assert data["mode"] == "url"
        assert "message" in data

    def test_join_by_email_returns_200(self, client):
        c, _ = client
        resp = c.post("/meeting/join", json={"email": "bot@centralagent.ai"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["meeting_id"].startswith("mock-")
        assert data["mode"] == "email"

    def test_join_with_neither_returns_422(self, client):
        c, _ = client
        resp = c.post("/meeting/join", json={})
        assert resp.status_code == 422

    def test_join_returns_503_when_vexa_unavailable(self, client):
        import main
        c, _ = client
        bad = MagicMock()
        bad.join_by_url.side_effect = VexaUnavailableError("Vexa is down")
        main.provider = bad
        resp = c.post("/meeting/join", json={"url": "https://meet.google.com/abc"})
        assert resp.status_code == 503
        main.provider = MockBotProvider()


# ── GET /meeting/{id}/status ──────────────────────────────────────────────────

class TestStatusEndpoint:
    def test_url_join_transcript_immediately_ready(self, client):
        c, _ = client
        join = c.post("/meeting/join", json={"url": "https://meet.google.com/abc-defg-hij"})
        mid = join.json()["meeting_id"]
        resp = c.get(f"/meeting/{mid}/status")
        assert resp.status_code == 200
        assert resp.json()["transcript_ready"] is True

    def test_email_join_transcript_not_ready_immediately(self, client):
        c, _ = client
        join = c.post("/meeting/join", json={"email": "bot@centralagent.ai"})
        mid = join.json()["meeting_id"]
        resp = c.get(f"/meeting/{mid}/status")
        assert resp.status_code == 200
        assert resp.json()["transcript_ready"] is False

    def test_unknown_meeting_id_returns_200(self, client):
        # MockBotProvider treats unknown IDs as URL-flow (always ready)
        c, _ = client
        resp = c.get("/meeting/nonexistent-id/status")
        assert resp.status_code == 200
        assert "transcript_ready" in resp.json()


# ── GET /meeting/{id}/digest ──────────────────────────────────────────────────

class TestDigestEndpoint:
    def test_returns_digest_for_ready_meeting(self, client):
        c, _ = client
        join = c.post("/meeting/join", json={"url": "https://meet.google.com/abc-defg-hij"})
        mid = join.json()["meeting_id"]

        fake = {"summary": "Short.", "action_items": ["Do X"], "decisions": ["Use Y"]}
        with patch("brain.claude.ClaudeBrain.generate_digest", return_value=fake):
            resp = c.get(f"/meeting/{mid}/digest")

        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"] == "Short."
        assert "Do X" in data["action_items"]
        assert "Use Y" in data["decisions"]

    def test_returns_400_when_transcript_not_ready(self, client):
        c, _ = client
        join = c.post("/meeting/join", json={"email": "bot@centralagent.ai"})
        mid = join.json()["meeting_id"]
        # Email-flow meeting: transcript NOT ready within the delay window
        resp = c.get(f"/meeting/{mid}/digest")
        assert resp.status_code == 400


# ── POST /meeting/{id}/ask ────────────────────────────────────────────────────

class TestAskEndpoint:
    def test_returns_answer_for_ready_meeting(self, client):
        c, _ = client
        join = c.post("/meeting/join", json={"url": "https://meet.google.com/abc-defg-hij"})
        mid = join.json()["meeting_id"]

        with patch("brain.claude.ClaudeBrain.ask", return_value="Bob said hello."):
            resp = c.post(f"/meeting/{mid}/ask", json={"question": "What did Bob say?"})

        assert resp.status_code == 200
        assert resp.json()["answer"] == "Bob said hello."
        assert resp.json()["question"] == "What did Bob say?"

    def test_not_ready_email_meeting_returns_400_on_ask(self, client):
        c, _ = client
        join = c.post("/meeting/join", json={"email": "bot@centralagent.ai"})
        mid = join.json()["meeting_id"]
        # Transcript empty because email-flow delay hasn't elapsed
        resp = c.post(f"/meeting/{mid}/ask", json={"question": "anything?"})
        assert resp.status_code == 400


# ── GET /meetings ─────────────────────────────────────────────────────────────

class TestMeetingsEndpoint:
    def test_returns_empty_list_for_mock_provider(self, client):
        c, _ = client
        resp = c.get("/meetings")
        assert resp.status_code == 200
        assert resp.json() == []


# ── GET /gmail/status ─────────────────────────────────────────────────────────

class TestGmailStatus:
    def test_returns_status_when_disabled(self, client):
        c, _ = client
        resp = c.get("/gmail/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "running" in data
        assert "seen_emails_total" in data
