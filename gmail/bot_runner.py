import time
import logging
import uuid

from providers.base import BotProvider, VexaUnavailableError, VexaError
from database.session import SessionLocal
from database.models import Meeting

logger = logging.getLogger(__name__)

POLL_INTERVAL = 30


def run_bot(meet_url: str, provider: BotProvider) -> None:
    meeting_id = uuid.uuid4().hex[:8]
    db = SessionLocal()
    try:
        meeting = Meeting(id=meeting_id, url=meet_url, status="joining")
        db.add(meeting)
        db.commit()

        try:
            provider.join_by_url(meet_url, meeting_id)
            meeting.status = "active"
            db.commit()
            logger.info(f"Bot joined {meet_url} (meeting {meeting_id})")
        except (VexaUnavailableError, VexaError) as e:
            meeting.status = "failed"
            db.commit()
            logger.error(f"Failed to join {meet_url}: {e}")
            return

        if _save_transcript_if_ready(meeting, provider, db):
            return

        while True:
            time.sleep(POLL_INTERVAL)
            if _save_transcript_if_ready(meeting, provider, db):
                return

    finally:
        db.close()


def _save_transcript_if_ready(meeting: Meeting, provider: BotProvider, db) -> bool:
    try:
        if not provider.is_transcript_ready(meeting.id):
            return False
        transcript = provider.get_transcript(meeting.id)
        if not transcript:
            return False
        meeting.transcript = transcript
        meeting.status = "complete"
        db.commit()
        logger.info(f"Transcript saved for meeting {meeting.id}")
        return True
    except Exception as e:
        logger.warning(f"Transcript check error for {meeting.id}: {e}")
        return False
