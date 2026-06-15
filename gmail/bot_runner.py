import time
import logging
from urllib.parse import urlparse

from providers.base import BotProvider, VexaUnavailableError, VexaError

logger = logging.getLogger(__name__)

POLL_INTERVAL = 30


def run_bot(meet_url: str, provider: BotProvider) -> None:
    try:
        meeting_id = provider.join_by_url(meet_url)
        logger.info(f"Bot joined {meet_url} (meeting {meeting_id})")
    except (VexaUnavailableError, VexaError) as e:
        logger.error(f"Failed to join {meet_url}: {e}")
        return

    while True:
        try:
            if provider.is_transcript_ready(meeting_id):
                logger.info(f"Transcript ready for meeting {meeting_id}")
                return
        except Exception as e:
            logger.warning(f"Transcript check error for {meeting_id}: {e}")
        time.sleep(POLL_INTERVAL)
