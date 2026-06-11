import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Set

from gmail.client import GmailClient
from gmail.parser import extract_meet_url
from gmail.bot_runner import run_bot
from database.session import SessionLocal
from database.models import SeenEmail
from providers.base import BotProvider

logger = logging.getLogger(__name__)


class GmailWatcher:
    """Polls Gmail for Meet invites and dispatches one bot thread per invite via ThreadPoolExecutor."""

    def __init__(
        self,
        gmail_client: GmailClient,
        provider: BotProvider,
        query: str,
        poll_interval: int = 30,
        max_concurrent_bots: int = 10,
    ):
        self.gmail = gmail_client
        self.provider = provider
        self.query = query
        self.poll_interval = poll_interval
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrent_bots, thread_name_prefix="bot-runner"
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_poll_at: float | None = None

    def _load_seen_ids(self) -> Set[str]:
        db = SessionLocal()
        try:
            return {row.email_id for row in db.query(SeenEmail.email_id).all()}
        finally:
            db.close()

    def _mark_seen(self, email_id: str) -> None:
        db = SessionLocal()
        try:
            if not db.query(SeenEmail).filter(SeenEmail.email_id == email_id).first():
                db.add(SeenEmail(email_id=email_id))
                db.commit()
        finally:
            db.close()

    def _poll(self) -> None:
        seen_ids = self._load_seen_ids()
        logger.info(f"Gmail watcher started — {len(seen_ids)} seen IDs loaded from DB")

        while not self._stop_event.is_set():
            try:
                messages = self.gmail.list_messages(self.query)
                self._last_poll_at = time.time()
                logger.debug(f"Polled Gmail: {len(messages)} matching messages")

                for msg in messages:
                    email_id = msg["id"]
                    if email_id in seen_ids:
                        continue

                    # Persist before dispatching so a mid-loop crash doesn't reprocess this email on restart.
                    seen_ids.add(email_id)
                    self._mark_seen(email_id)

                    try:
                        body = self.gmail.get_message_body(email_id)
                        meet_url = extract_meet_url(body)
                        if meet_url:
                            logger.info(f"Meet invite detected: {meet_url} — dispatching bot")
                            self._executor.submit(run_bot, meet_url, self.provider)
                    except Exception as e:
                        logger.error(f"Error processing email {email_id}: {e}")

            except Exception as e:
                logger.error(f"Gmail poll error: {e}")

            self._stop_event.wait(self.poll_interval)

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll, daemon=True, name="gmail-watcher"
        )
        self._thread.start()
        logger.info("Gmail watcher thread started")

    def stop(self) -> None:
        self._stop_event.set()
        self._executor.shutdown(wait=False)
        logger.info("Gmail watcher stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_poll_at(self) -> float | None:
        return self._last_poll_at
