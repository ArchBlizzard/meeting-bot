import json
import pytest
from unittest.mock import MagicMock, patch

from brain.claude import ClaudeBrain
from database.models import Meeting


def make_brain(db):
    client = MagicMock()
    return ClaudeBrain(client=client, db=db, model="claude-opus-4-8"), client


def make_meeting(id="mtg-1", transcript="Alice: hello\nBob: hi", digest=None):
    m = Meeting(id=id, url="https://meet.google.com/abc", status="complete")
    m.transcript = transcript
    m.digest = digest
    return m


# ── Digest generation ─────────────────────────────────────────────────────────

class TestDigest:
    def test_generates_digest_from_transcript(self):
        db = MagicMock()
        meeting = make_meeting()
        db.query.return_value.filter.return_value.first.return_value = meeting

        brain, client = make_brain(db)

        fake_digest = {"summary": "A short meeting.", "action_items": ["Bob to do X"], "decisions": ["Use JWT"]}
        client.messages.create.return_value.content = [MagicMock(text=json.dumps(fake_digest))]

        result = brain.generate_digest("mtg-1")

        assert result["summary"] == "A short meeting."
        assert "Bob to do X" in result["action_items"]
        assert "Use JWT" in result["decisions"]

    def test_returns_cached_digest_without_calling_claude(self):
        db = MagicMock()
        cached = {"summary": "cached", "action_items": [], "decisions": []}
        meeting = make_meeting(digest=json.dumps(cached))
        db.query.return_value.filter.return_value.first.return_value = meeting

        brain, client = make_brain(db)
        result = brain.generate_digest("mtg-1")

        client.messages.create.assert_not_called()
        assert result["summary"] == "cached"

    def test_raises_if_meeting_not_found(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        brain, _ = make_brain(db)
        with pytest.raises(ValueError, match="not found"):
            brain.generate_digest("nonexistent")

    def test_raises_if_no_transcript(self):
        db = MagicMock()
        meeting = make_meeting(transcript=None)
        db.query.return_value.filter.return_value.first.return_value = meeting

        brain, _ = make_brain(db)
        with pytest.raises(ValueError, match="No transcript"):
            brain.generate_digest("mtg-1")

    def test_handles_markdown_fenced_json(self):
        db = MagicMock()
        meeting = make_meeting()
        db.query.return_value.filter.return_value.first.return_value = meeting

        brain, client = make_brain(db)
        fake_digest = {"summary": "ok", "action_items": [], "decisions": []}
        fenced = f"```json\n{json.dumps(fake_digest)}\n```"
        client.messages.create.return_value.content = [MagicMock(text=fenced)]

        result = brain.generate_digest("mtg-1")
        assert result["summary"] == "ok"


# ── Q&A ───────────────────────────────────────────────────────────────────────

class TestAsk:
    def test_returns_answer_for_valid_question(self):
        db = MagicMock()
        meeting = make_meeting()
        db.query.return_value.filter.return_value.first.return_value = meeting

        brain, client = make_brain(db)
        client.messages.create.return_value.content = [MagicMock(text="Bob said hi.")]

        result = brain.ask("mtg-1", "What did Bob say?")
        assert result == "Bob said hi."

    def test_returns_graceful_message_for_empty_transcript(self):
        db = MagicMock()
        meeting = make_meeting(transcript=None)
        db.query.return_value.filter.return_value.first.return_value = meeting

        brain, client = make_brain(db)
        result = brain.ask("mtg-1", "What happened?")

        client.messages.create.assert_not_called()
        assert "no transcript" in result.lower()

    def test_raises_if_meeting_not_found(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        brain, _ = make_brain(db)
        with pytest.raises(ValueError, match="not found"):
            brain.ask("nonexistent", "anything?")
