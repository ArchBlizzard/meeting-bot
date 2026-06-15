import time
import pytest
from unittest.mock import MagicMock, patch
import httpx

from providers.mock import MockBotProvider, MOCK_EMAIL_FLOW_DELAY
from providers.vexa import VexaProvider, extract_native_meeting_id
from providers.base import VexaUnavailableError, VexaError


# ── MockBotProvider ───────────────────────────────────────────────────────────

class TestMockBotProvider:
    def setup_method(self):
        self.provider = MockBotProvider()

    def test_join_by_url_extracts_native_id(self):
        result = self.provider.join_by_url("https://meet.google.com/abc-defg-hij")
        assert result == "abc-defg-hij"

    def test_join_by_url_unknown_path_returns_last_segment(self):
        result = self.provider.join_by_url("https://meet.google.com/xyz")
        assert result == "xyz"

    def test_join_by_email_returns_mock_prefixed_id(self):
        result = self.provider.join_by_email("bot@centralagent.ai")
        assert result.startswith("mock-")

    def test_url_flow_transcript_immediately_ready(self):
        meeting_id = self.provider.join_by_url("https://meet.google.com/abc-defg-hij")
        assert self.provider.is_transcript_ready(meeting_id) is True

    def test_url_flow_get_transcript_returns_content(self):
        meeting_id = self.provider.join_by_url("https://meet.google.com/abc-defg-hij")
        transcript = self.provider.get_transcript(meeting_id)
        assert isinstance(transcript, str)
        assert len(transcript) > 0

    def test_email_flow_transcript_not_ready_immediately(self):
        meeting_id = self.provider.join_by_email("bot@centralagent.ai")
        assert self.provider.is_transcript_ready(meeting_id) is False

    def test_email_flow_get_transcript_returns_empty_before_delay(self):
        meeting_id = self.provider.join_by_email("bot@centralagent.ai")
        transcript = self.provider.get_transcript(meeting_id)
        assert transcript == ""

    def test_email_flow_transcript_ready_after_delay(self):
        meeting_id = self.provider.join_by_email("bot@centralagent.ai")
        self.provider._email_meetings[meeting_id] -= MOCK_EMAIL_FLOW_DELAY
        assert self.provider.is_transcript_ready(meeting_id) is True
        assert len(self.provider.get_transcript(meeting_id)) > 0

    def test_mock_transcript_has_speaker_format(self):
        meeting_id = self.provider.join_by_url("https://meet.google.com/abc-defg-hij")
        transcript = self.provider.get_transcript(meeting_id)
        assert ":" in transcript
        assert len(transcript.splitlines()) > 5


# ── extract_native_meeting_id ─────────────────────────────────────────────────

class TestExtractNativeMeetingId:
    def test_standard_url(self):
        assert extract_native_meeting_id("https://meet.google.com/abc-defg-hij") == "abc-defg-hij"

    def test_url_with_query_params(self):
        assert extract_native_meeting_id("https://meet.google.com/abc-defg-hij?authuser=0") == "abc-defg-hij"

    def test_url_with_trailing_slash(self):
        assert extract_native_meeting_id("https://meet.google.com/abc-defg-hij/") == "abc-defg-hij"


# ── VexaProvider ──────────────────────────────────────────────────────────────

class TestVexaProvider:
    def setup_method(self):
        self.provider = VexaProvider(vexa_url="http://localhost:8056", api_key="test-key")
        self.headers = {"Content-Type": "application/json", "X-API-Key": "test-key"}

    def test_join_by_url_returns_native_id(self):
        mock_response = MagicMock()
        mock_response.is_success = True
        with patch("httpx.post", return_value=mock_response):
            result = self.provider.join_by_url("https://meet.google.com/abc-defg-hij")
            assert result == "abc-defg-hij"

    def test_join_by_url_sends_correct_payload(self):
        mock_response = MagicMock()
        mock_response.is_success = True
        with patch("httpx.post", return_value=mock_response) as mock_post:
            self.provider.join_by_url("https://meet.google.com/abc-defg-hij")
            mock_post.assert_called_once_with(
                "http://localhost:8056/bots",
                headers=self.headers,
                json={
                    "platform": "google_meet",
                    "native_meeting_id": "abc-defg-hij",
                    "authenticated": True,
                    "bot_name": "Meeting Bot",
                    "automatic_leave": {"max_time_left_alone": 60000},
                },
                timeout=30.0,
            )

    def test_join_by_email_returns_watcher_handle_without_calling_vexa(self):
        # Vexa has no email-monitoring API — join_by_email must NOT call Vexa.
        with patch("httpx.post") as mock_post:
            result = self.provider.join_by_email("bot@centralagent.ai")
            mock_post.assert_not_called()
        assert result == "gmail-watcher:bot@centralagent.ai"

    def test_join_by_url_raises_when_vexa_unavailable(self):
        with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(VexaUnavailableError):
                self.provider.join_by_url("https://meet.google.com/abc-defg-hij")

    def test_join_by_url_raises_on_timeout(self):
        with patch("httpx.post", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(VexaUnavailableError):
                self.provider.join_by_url("https://meet.google.com/abc-defg-hij")

    def test_join_by_url_raises_on_error_response(self):
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        with patch("httpx.post", return_value=mock_response):
            with pytest.raises(VexaError):
                self.provider.join_by_url("https://meet.google.com/abc-defg-hij")

    def test_get_transcript_calls_correct_endpoint(self):
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {
            "status": "completed",
            "segments": [
                {"speaker": "Alice", "text": "Hello"},
                {"speaker": "Bob", "text": "Hi"},
            ],
        }
        with patch("httpx.get", return_value=mock_response) as mock_get:
            result = self.provider.get_transcript("abc-defg-hij")
            mock_get.assert_called_once_with(
                "http://localhost:8056/transcripts/google_meet/abc-defg-hij",
                headers=self.headers,
                timeout=30.0,
            )
            assert "Alice: Hello" in result
            assert "Bob: Hi" in result

    def test_get_transcript_returns_empty_when_no_segments(self):
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"status": "completed", "segments": []}
        with patch("httpx.get", return_value=mock_response):
            assert self.provider.get_transcript("abc-defg-hij") == ""

    def test_is_transcript_ready_returns_true_when_completed(self):
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"status": "completed"}
        with patch("httpx.get", return_value=mock_response):
            assert self.provider.is_transcript_ready("abc-defg-hij") is True

    def test_is_transcript_ready_returns_false_when_active(self):
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"status": "active"}
        with patch("httpx.get", return_value=mock_response):
            assert self.provider.is_transcript_ready("abc-defg-hij") is False

    def test_is_transcript_ready_returns_false_on_error(self):
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            assert self.provider.is_transcript_ready("abc-defg-hij") is False
