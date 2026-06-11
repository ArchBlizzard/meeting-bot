from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
import uuid
import json
import asyncio

from database.models import Meeting, SeenEmail
from database.session import get_db, SessionLocal
from providers.base import BotProvider, VexaUnavailableError, VexaError
from brain.claude import ClaudeBrain

router = APIRouter()


class JoinRequest(BaseModel):
    url: Optional[str] = None
    email: Optional[str] = None


class JoinResponse(BaseModel):
    meeting_id: str
    status: str
    mode: str
    message: str


class MeetingStatusResponse(BaseModel):
    meeting_id: str
    status: str
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


class VexaHealthResponse(BaseModel):
    provider: str
    status: str
    detail: str


def get_provider() -> BotProvider:
    from main import provider
    return provider


def get_brain(db: Session = Depends(get_db)) -> ClaudeBrain:
    from main import get_claude_brain
    return get_claude_brain(db)


@router.post("/meeting/join", response_model=JoinResponse)
def join_meeting(
    body: JoinRequest,
    db: Session = Depends(get_db),
    bot: BotProvider = Depends(get_provider),
):
    """
    Manually trigger a bot to join a meeting.

    Pass `url` to join immediately via a Google Meet link:
    `{ "url": "https://meet.google.com/xxx-xxxx-xxx" }`

    Pass `email` to register the bot's dedicated Google account for calendar-invite auto-join.
    The meeting stays `active` until Vexa joins and the transcript is ready — poll
    `GET /meeting/{id}/status` to check progress:
    `{ "email": "bot@centralagent.ai" }`

    If `GMAIL_ENABLED=true`, the Gmail watcher handles the email flow automatically
    and this endpoint is only needed for manual or programmatic triggers.
    """
    if not body.url and not body.email:
        raise HTTPException(
            status_code=422,
            detail="Provide either 'url' (immediate join) or 'email' (calendar-invite auto-join).",
        )

    meeting_id = uuid.uuid4().hex[:8]
    mode = "url" if body.url else "email"

    meeting = Meeting(
        id=meeting_id,
        url=body.url,
        email=body.email,
        status="joining",
    )
    db.add(meeting)
    db.commit()

    try:
        if body.url:
            bot.join_by_url(body.url, meeting_id)
        else:
            bot.join_by_email(body.email, meeting_id)
    except VexaUnavailableError as e:
        meeting.status = "failed"
        db.commit()
        raise HTTPException(status_code=503, detail=str(e))
    except VexaError as e:
        meeting.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail=str(e))

    if mode == "url":
        try:
            transcript = bot.get_transcript(meeting_id)
            meeting.transcript = transcript
            meeting.status = "complete"
        except Exception:
            meeting.status = "active"
        finally:
            db.commit()
        message = "Bot joined. Transcript is ready — call /digest or /ask."
    else:
        meeting.status = "active"
        db.commit()
        message = (
            "Bot email registered. Waiting for calendar invite. "
            "Poll GET /meeting/{id}/status until transcript_ready is true, "
            "then call /digest or /ask."
        )

    return JoinResponse(
        meeting_id=meeting_id,
        status=meeting.status,
        mode=mode,
        message=message,
    )


@router.get("/meeting/{meeting_id}/status", response_model=MeetingStatusResponse)
def get_meeting_status(
    meeting_id: str,
    db: Session = Depends(get_db),
    bot: BotProvider = Depends(get_provider),
):
    """
    Poll transcript availability for a meeting.

    Returns `transcript_ready: true` once the bot has left and the full transcript
    is stored. Call `/digest` or `/ask` once ready. Most useful for the async
    email flow where the bot joins only after a calendar invite arrives.
    """
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found.")

    if meeting.status == "active" and not meeting.transcript:
        ready = bot.is_transcript_ready(meeting_id)
        if ready:
            try:
                transcript = bot.get_transcript(meeting_id)
                if transcript:
                    meeting.transcript = transcript
                    meeting.status = "complete"
                    db.commit()
            except Exception:
                pass

    return MeetingStatusResponse(
        meeting_id=meeting_id,
        status=meeting.status,
        transcript_ready=bool(meeting.transcript),
    )


@router.get("/meeting/{meeting_id}/digest", response_model=DigestResponse)
def get_digest(
    meeting_id: str,
    db: Session = Depends(get_db),
    brain: ClaudeBrain = Depends(get_brain),
):
    """
    Generate a post-meeting digest: summary, action items, and decisions.

    Uses Claude Opus 4.8 over the full transcript — no chunking, 1M context handles
    meetings of any length. The result is cached in SQLite; repeated calls return
    instantly without re-invoking Claude.
    """
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found.")

    if not meeting.transcript:
        raise HTTPException(
            status_code=400,
            detail="Transcript not yet available. Poll GET /meeting/{id}/status first.",
        )

    try:
        digest = brain.generate_digest(meeting_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
    db: Session = Depends(get_db),
    brain: ClaudeBrain = Depends(get_brain),
):
    """
    Ask a natural-language question about a completed meeting.

    Claude Opus 4.8 receives the full transcript in a single call — no chunking
    or retrieval needed. Handles transcripts from meetings of any length.
    """
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found.")

    try:
        answer = brain.ask(meeting_id, body.question)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to answer question: {str(e)}")

    return AskResponse(
        meeting_id=meeting_id,
        question=body.question,
        answer=answer,
    )


@router.get("/health/vexa", response_model=VexaHealthResponse)
def vexa_health(bot: BotProvider = Depends(get_provider)):
    """
    Two-stage health check on the bot provider.

    Stage 1 checks whether the Vexa server is reachable. Stage 2 probes the bot API.
    Returns `ok`, `degraded` (server up but bot API broken — see Vexa issue #407),
    or `unavailable`. Always returns `ok` when `BOT_PROVIDER=mock`.
    """
    result = bot.health()
    return VexaHealthResponse(
        provider=bot.__class__.__name__,
        status=result["status"],
        detail=result["detail"],
    )


@router.get("/gmail/status")
async def gmail_status(stream: bool = False, db: Session = Depends(get_db)):
    """
    Status of the Gmail watcher (auto-join flow).

    Shows whether the watcher thread is running, how many bots are currently active,
    total invite emails processed, and the timestamp of the last poll.
    Enable the watcher by setting `GMAIL_ENABLED=true` in `.env` and providing
    OAuth2 credentials via `credentials.json`.

    Add `?stream=true` to receive a continuous Server-Sent Events stream that pushes
    a fresh status object every poll cycle. The stream stays open until the client
    disconnects.
    """
    from main import watcher
    from config import get_settings
    settings = get_settings()

    def _snapshot(session: Session) -> dict:
        active_bots = session.query(Meeting).filter(Meeting.status.in_(["joining", "active"])).count()
        seen_total = session.query(SeenEmail).count()
        return {
            "enabled": settings.GMAIL_ENABLED,
            "running": watcher.is_running if watcher else False,
            "active_bots": active_bots,
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
