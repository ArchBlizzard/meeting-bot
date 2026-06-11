from abc import ABC, abstractmethod


class BotProviderError(Exception):
    """Base error for bot provider failures."""
    pass


class VexaUnavailableError(BotProviderError):
    """Raised when Vexa server cannot be reached."""
    pass


class VexaError(BotProviderError):
    """Raised when Vexa returns an error response."""
    pass


class BotProvider(ABC):
    """
    Abstract interface for meeting bot providers.
    Implement this to swap in any bot backend (Vexa, Recall.ai, etc.)
    """

    @abstractmethod
    def join_by_url(self, url: str, meeting_id: str) -> str:
        """
        Send a bot to join a meeting via URL.
        Bot joins immediately — transcript available shortly after.
        Returns the meeting_id.
        """
        pass

    @abstractmethod
    def join_by_email(self, email: str, meeting_id: str) -> str:
        """
        Register a bot email for auto-join on calendar invite.
        This is ASYNC — the bot joins only when the invite arrives.
        Meeting stays in 'active' status until transcript is ready.
        Poll GET /meeting/{id}/status to check progress.
        Returns the meeting_id.
        """
        pass

    @abstractmethod
    def get_transcript(self, meeting_id: str) -> str:
        """
        Retrieve the transcript for a completed meeting.
        Returns transcript as plain text, or empty string if not ready.
        """
        pass

    @abstractmethod
    def is_transcript_ready(self, meeting_id: str) -> bool:
        """
        Check whether the transcript is ready for a given meeting.
        Used for polling the advanced (email) flow.
        """
        pass

    @abstractmethod
    def health(self) -> dict:
        """
        Check connectivity to the bot provider.
        Returns { "status": "ok"|"degraded"|"unavailable", "detail": str }
        """
        pass
