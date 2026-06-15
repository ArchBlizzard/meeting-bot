import json
import pytest
from unittest.mock import MagicMock

from brain.claude import ClaudeBrain
from database.models import Meeting


TRANSCRIPT = "Alice: hello\nBob: hi there"


def make_brain(db=None):
    client = MagicMock()
    if db is None:
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
    return ClaudeBrain(client=client, db=db, model="claude-opus-4-8"), client


# ── Digest generation ─────────────────────────────────────────────────────────

class TestDigest:
    def test_generates_digest_from_transcript(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        brain, client = make_brain(db)
        fake = {"summary": "A short meeting.", "action_items": ["Bob to do X"], "decisions": ["Use JWT"]}
        client.messages.create.return_value.content = [MagicMock(text=json.dumps(fake))]

        result = brain.generate_digest("mtg-1", TRANSCRIPT)

        assert result["summary"] == "A short meeting."
        assert "Bob to do X" in result["action_items"]

    def test_returns_cached_digest_without_calling_claude(self):
        db = MagicMock()
        cached = {"summary": "cached", "action_items": [], "decisions": []}
        m = Meeting(id="mtg-1", digest=json.dumps(cached))
        db.query.return_value.filter.return_value.first.return_value = m

        brain, client = make_brain(db)
        result = brain.generate_digest("mtg-1", TRANSCRIPT)

        client.messages.create.assert_not_called()
        assert result["summary"] == "cached"

    def test_handles_markdown_fenced_json(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        brain, client = make_brain(db)
        fake = {"summary": "ok", "action_items": [], "decisions": []}
        fenced = f"```json\n{json.dumps(fake)}\n```"
        client.messages.create.return_value.content = [MagicMock(text=fenced)]

        result = brain.generate_digest("mtg-1", TRANSCRIPT)
        assert result["summary"] == "ok"

    def test_caches_result_in_db(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        brain, client = make_brain(db)
        fake = {"summary": "s", "action_items": [], "decisions": []}
        client.messages.create.return_value.content = [MagicMock(text=json.dumps(fake))]

        brain.generate_digest("mtg-1", TRANSCRIPT)

        db.add.assert_called_once()
        db.commit.assert_called_once()


# ── Q&A ───────────────────────────────────────────────────────────────────────

class TestAsk:
    def test_returns_answer_for_valid_question(self):
        brain, client = make_brain()
        client.messages.create.return_value.content = [MagicMock(text="Bob said hi.")]

        result = brain.ask("mtg-1", "What did Bob say?", TRANSCRIPT)
        assert result == "Bob said hi."

    def test_calls_claude_with_transcript_in_prompt(self):
        brain, client = make_brain()
        client.messages.create.return_value.content = [MagicMock(text="answer")]

        brain.ask("mtg-1", "question?", TRANSCRIPT)

        call_kwargs = client.messages.create.call_args
        user_content = call_kwargs.kwargs["messages"][0]["content"]
        assert "Alice: hello" in user_content
        assert "question?" in user_content

    def test_does_not_cache_answers(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        brain, client = make_brain(db)
        client.messages.create.return_value.content = [MagicMock(text="answer")]

        brain.ask("mtg-1", "question?", TRANSCRIPT)

        db.add.assert_not_called()
        db.commit.assert_not_called()
