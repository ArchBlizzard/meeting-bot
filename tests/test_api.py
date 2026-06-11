import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from main import app
from providers.mock import MockBotProvider
from providers.base import VexaUnavailableError
from database.models import Meeting


@pytest.fixture
def client(tmp_path):
    """Test client with in-memory SQLite and mock provider."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.models import Base
    from database.session import get_db
    import main

    test_db_url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(test_db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    mock_provider = MockBotProvider()
    main.provider = mock_provider

    app.dependency_overrides[get_db] = override_db

    with TestClient(app) as c:
        yield c, TestSession

    app.dependency_overrides.clear()


# ── POST /meeting/join ────────────────────────────────────────────────────────

class TestJoinEndpoint:
    def test_join_by_url_returns_200(self, client):
        c, _ = client
        resp = c.post("/meeting/join", json={"url": "https://meet.google.com/abc"})
        assert resp.status_code == 200
        data = resp.json()
        assert "meeting_id" in data
        assert data["mode"] == "url"

    def test_join_by_email_returns_200(self, client):
        c, _ = client
        resp = c.post("/meeting/join", json={"email": "bot@centralagent.ai"})
        assert resp.status_code == 200
        data = resp.json()
        assert "meeting_id" in data
        assert data["mode"] == "email"

    def test_join_with_neither_returns_422(self, client):
        c, _ = client
        resp = c.post("/meeting/join", json={})
        assert resp.status_code == 422

    def test_join_returns_503_when_vexa_unavailable(self, client):
        import main
        c, _ = client
        bad_provider = MagicMock()
        bad_provider.join_by_url.side_effect = VexaUnavailableError("Vexa is down")
        bad_provider.get_transcript.return_value = ""
        main.provider = bad_provider

        resp = c.post("/meeting/join", json={"url": "https://meet.google.com/abc"})
        assert resp.status_code == 503

        # restore
        main.provider = MockBotProvider()

    def test_email_flow_returns_active_status(self, client):
        c, _ = client
        resp = c.post("/meeting/join", json={"email": "bot@centralagent.ai"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "email"
        assert data["status"] == "active"
        assert "Poll" in data["message"]

    def test_url_flow_returns_complete_status(self, client):
        c, _ = client
        resp = c.post("/meeting/join", json={"url": "https://meet.google.com/abc"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "complete"


# ── GET /meeting/{id}/digest ──────────────────────────────────────────────────

class TestDigestEndpoint:
    def _create_meeting(self, Session, **kwargs):
        db = Session()
        m = Meeting(
            id=kwargs.get("id", "test-id"),
            url="https://meet.google.com/abc",
            status="complete",
        )
        m.transcript = kwargs.get("transcript", "Alice: hi\nBob: hello")
        m.digest = kwargs.get("digest", None)
        db.add(m)
        db.commit()
        db.close()

    def test_returns_digest(self, client):
        c, Session = client
        self._create_meeting(Session, id="mtg-digest")

        fake = {"summary": "Short.", "action_items": ["Do X"], "decisions": ["Use Y"]}
        with patch("brain.claude.ClaudeBrain.generate_digest", return_value=fake):
            resp = c.get("/meeting/mtg-digest/digest")

        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"] == "Short."
        assert "Do X" in data["action_items"]

    def test_returns_404_for_unknown_meeting(self, client):
        c, _ = client
        resp = c.get("/meeting/nonexistent-id/digest")
        assert resp.status_code == 404

    def test_returns_400_when_no_transcript(self, client):
        c, Session = client
        db = Session()
        m = Meeting(id="no-transcript", url="https://meet.google.com/abc", status="active")
        m.transcript = None
        db.add(m)
        db.commit()
        db.close()

        resp = c.get("/meeting/no-transcript/digest")
        assert resp.status_code == 400


# ── POST /meeting/{id}/ask ────────────────────────────────────────────────────

class TestAskEndpoint:
    def _create_meeting(self, Session, id="ask-id"):
        db = Session()
        m = Meeting(id=id, url="https://meet.google.com/abc", status="complete")
        m.transcript = "Alice: hi\nBob: hello"
        db.add(m)
        db.commit()
        db.close()

    def test_returns_answer(self, client):
        c, Session = client
        self._create_meeting(Session)

        with patch("brain.claude.ClaudeBrain.ask", return_value="Bob said hello."):
            resp = c.post("/meeting/ask-id/ask", json={"question": "What did Bob say?"})

        assert resp.status_code == 200
        assert resp.json()["answer"] == "Bob said hello."
        assert resp.json()["question"] == "What did Bob say?"

    def test_returns_404_for_unknown_meeting(self, client):
        c, _ = client
        resp = c.post("/meeting/nonexistent/ask", json={"question": "anything?"})
        assert resp.status_code == 404


# ── GET /meeting/{id}/status ──────────────────────────────────────────────────

class TestStatusEndpoint:
    def test_returns_404_for_unknown_meeting(self, client):
        c, _ = client
        resp = c.get("/meeting/nonexistent/status")
        assert resp.status_code == 404

    def test_returns_active_before_transcript_ready(self, client):
        c, _ = client
        # Join via email — transcript not ready yet
        join_resp = c.post("/meeting/join", json={"email": "bot@centralagent.ai"})
        meeting_id = join_resp.json()["meeting_id"]

        status_resp = c.get(f"/meeting/{meeting_id}/status")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["transcript_ready"] is False
        assert data["status"] == "active"

    def test_returns_complete_after_url_join(self, client):
        c, _ = client
        join_resp = c.post("/meeting/join", json={"url": "https://meet.google.com/abc"})
        meeting_id = join_resp.json()["meeting_id"]

        status_resp = c.get(f"/meeting/{meeting_id}/status")
        assert status_resp.json()["transcript_ready"] is True


# ── GET /health/vexa ──────────────────────────────────────────────────────────

class TestVexaHealth:
    def test_mock_provider_returns_ok(self, client):
        c, _ = client
        resp = c.get("/health/vexa")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["provider"] == "MockBotProvider"
