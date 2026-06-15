import json
from anthropic import Anthropic
from sqlalchemy.orm import Session
from database.models import Meeting

SYSTEM_PROMPT = """You are a meeting assistant. You have been given a full transcript of a meeting.
Your job is to help users understand what happened in the meeting accurately and concisely."""

DIGEST_PROMPT = """Analyze the following meeting transcript and return a JSON object with exactly these keys:
- "summary": a concise 2-4 sentence summary of the meeting
- "action_items": a list of strings, each describing a specific action item with owner and deadline if mentioned
- "decisions": a list of strings, each describing a key decision that was made

Return only valid JSON, no additional text.

Transcript:
{transcript}"""

QA_PROMPT = """Using the meeting transcript below, answer the following question as accurately as possible.
If the answer is not in the transcript, say so clearly.

Question: {question}

Transcript:
{transcript}"""


class ClaudeBrain:
    """Digest generation and Q&A over full transcripts. No chunking — Opus 4.8's 1M context handles 2-3h meetings natively."""

    def __init__(self, client: Anthropic, db: Session, model: str):
        self.client = client
        self.db = db
        self.model = model

    def generate_digest(self, meeting_id: str, transcript: str) -> dict:
        meeting = self.db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if meeting and meeting.digest:
            return json.loads(meeting.digest)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": DIGEST_PROMPT.format(transcript=transcript)}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        digest = json.loads(raw)

        if not meeting:
            meeting = Meeting(id=meeting_id)
            self.db.add(meeting)
        meeting.digest = json.dumps(digest)
        self.db.commit()

        return digest

    def ask(self, meeting_id: str, question: str, transcript: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": QA_PROMPT.format(question=question, transcript=transcript)}],
        )
        return response.content[0].text.strip()
