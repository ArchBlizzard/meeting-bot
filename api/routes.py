from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
import json
import asyncio

from database.models import SeenEmail
from database.session import get_db, SessionLocal
from providers.base import BotProvider, VexaUnavailableError, VexaError
from brain.claude import ClaudeBrain

router = APIRouter()


class JoinRequest(BaseModel):
    url: Optional[str] = None
    email: Optional[str] = None


class JoinResponse(BaseModel):
    meeting_id: str
    mode: str
    message: str


class MeetingStatusResponse(BaseModel):
    meeting_id: str
    transcript_ready: bool


class DigestResponse(BaseModel):
    meeting_id: str
    summary: str
    action_items: list[str]
    decisions: list[str]


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    meeting_id: str
    question: str
    answer: str


def get_provider() -> BotProvider:
    from main import provider
    return provider


def get_brain(db: Session = Depends(get_db)) -> ClaudeBrain:
    from main import get_claude_brain
    return get_claude_brain(db)


@router.post("/meeting/join", response_model=JoinResponse)
def join_meeting(
    body: JoinRequest,
    bot: BotProvider = Depends(get_provider),
):
    """
    Trigger a bot to join a meeting.

    Pass `url` to join immediately via a Google Meet link.
    Pass `email` to register the bot email for calendar-invite auto-join.
    The meeting ID returned matches the ID shown in the Vexa dashboard.
    """
    if not body.url and not body.email:
        raise HTTPException(
            status_code=422,
            detail="Provide either 'url' (immediate join) or 'email' (calendar-invite auto-join).",
        )

    mode = "url" if body.url else "email"

    try:
        if body.url:
            meeting_id = bot.join_by_url(body.url)
            message = "Bot joined. Poll GET /meeting/{id}/status until transcript_ready is true, then call /digest or /ask."
        else:
            meeting_id = bot.join_by_email(body.email)
            message = (
                "Gmail watcher is active. Invite the bot email to a Google Meet — "
                "the watcher will detect the calendar invite and join automatically. "
                "Check GET /gmail/status to confirm the watcher is running."
            )
    except VexaUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except VexaError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return JoinResponse(meeting_id=meeting_id, mode=mode, message=message)


@router.get("/meeting/{meeting_id}/status", response_model=MeetingStatusResponse)
def get_meeting_status(
    meeting_id: str,
    bot: BotProvider = Depends(get_provider),
):
    """Poll transcript availability. When transcript_ready is true, call /digest or /ask."""
    ready = bot.is_transcript_ready(meeting_id)
    return MeetingStatusResponse(meeting_id=meeting_id, transcript_ready=ready)


@router.get("/meeting/{meeting_id}/digest", response_model=DigestResponse)
def get_digest(
    meeting_id: str,
    bot: BotProvider = Depends(get_provider),
    brain: ClaudeBrain = Depends(get_brain),
):
    """
    Generate a post-meeting digest: summary, action items, and decisions.

    Uses Claude Opus 4.8 over the full transcript — no chunking, 1M context handles
    meetings of any length. Result is cached — repeated calls return instantly.
    """
    if not bot.is_transcript_ready(meeting_id):
        raise HTTPException(
            status_code=400,
            detail="Transcript not yet available. Poll GET /meeting/{id}/status first.",
        )

    try:
        transcript = bot.get_transcript(meeting_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch transcript: {str(e)}")

    if not transcript:
        raise HTTPException(status_code=400, detail="Transcript is empty.")

    try:
        digest = brain.generate_digest(meeting_id, transcript)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate digest: {str(e)}")

    return DigestResponse(
        meeting_id=meeting_id,
        summary=digest.get("summary", ""),
        action_items=digest.get("action_items", []),
        decisions=digest.get("decisions", []),
    )


@router.post("/meeting/{meeting_id}/ask", response_model=AskResponse)
def ask_question(
    meeting_id: str,
    body: AskRequest,
    bot: BotProvider = Depends(get_provider),
    brain: ClaudeBrain = Depends(get_brain),
):
    """
    Ask a natural-language question about a completed meeting.

    Claude Opus 4.8 receives the full transcript in a single call — no chunking.
    """
    try:
        transcript = bot.get_transcript(meeting_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch transcript: {str(e)}")

    if not transcript:
        raise HTTPException(
            status_code=400,
            detail="Transcript not available yet. Poll GET /meeting/{id}/status first.",
        )

    try:
        answer = brain.ask(meeting_id, body.question, transcript)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to answer question: {str(e)}")

    return AskResponse(meeting_id=meeting_id, question=body.question, answer=answer)


@router.get("/meetings")
def list_meetings(bot: BotProvider = Depends(get_provider)):
    """
    List recent meetings. For Vexa provider, proxies directly to Vexa's meeting history.
    """
    from providers.vexa import VexaProvider
    if not isinstance(bot, VexaProvider):
        return []

    import httpx
    try:
        response = httpx.get(
            f"{bot.vexa_url}/bots",
            headers=bot.headers,
            timeout=10.0,
        )
        if response.is_success:
            data = response.json()
            meetings = data.get("meetings", data) if isinstance(data, dict) else data
            return [
                {
                    "meeting_id": m.get("native_meeting_id"),
                    "vexa_id": m.get("id"),
                    "status": m.get("status"),
                    "start_time": m.get("start_time"),
                }
                for m in meetings
                if m.get("native_meeting_id")
            ]
    except Exception:
        pass
    return []


@router.get("/gmail/status")
async def gmail_status(stream: bool = False, db: Session = Depends(get_db)):
    """
    Status of the Gmail watcher (auto-join flow).

    Add `?stream=true` to receive a live Server-Sent Events stream updated every poll cycle.
    Open in browser or use: curl -N "http://localhost:8000/gmail/status?stream=true"
    """
    from main import watcher
    from config import get_settings
    settings = get_settings()

    def _snapshot(session: Session) -> dict:
        seen_total = session.query(SeenEmail).count()
        return {
            "enabled": settings.GMAIL_ENABLED,
            "running": watcher.is_running if watcher else False,
            "seen_emails_total": seen_total,
            "poll_interval_seconds": settings.GMAIL_POLL_INTERVAL,
            "last_poll_at": watcher.last_poll_at if watcher else None,
        }

    if not stream:
        return _snapshot(db)

    async def event_stream():
        try:
            while True:
                session = SessionLocal()
                try:
                    data = _snapshot(session)
                finally:
                    session.close()
                yield f"data: {json.dumps(data)}\n\n"
                await asyncio.sleep(settings.GMAIL_POLL_INTERVAL)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
