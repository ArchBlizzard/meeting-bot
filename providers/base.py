from abc import ABC, abstractmethod


class BotProviderError(Exception):
    pass


class VexaUnavailableError(BotProviderError):
    pass


class VexaError(BotProviderError):
    pass


class BotProvider(ABC):

    @abstractmethod
    def join_by_url(self, url: str) -> str:
        """Send a bot to join a meeting via URL. Returns the native meeting ID."""
        pass

    @abstractmethod
    def join_by_email(self, email: str) -> str:
        """Register a bot email for calendar-invite auto-join. Returns the meeting identifier."""
        pass

    @abstractmethod
    def get_transcript(self, meeting_id: str) -> str:
        """Retrieve the full transcript for a completed meeting."""
        pass

    @abstractmethod
    def is_transcript_ready(self, meeting_id: str) -> bool:
        """Check whether the transcript is ready."""
        pass
