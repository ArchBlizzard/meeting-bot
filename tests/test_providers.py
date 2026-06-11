import time
import pytest
from unittest.mock import MagicMock, patch
import httpx

from providers.mock import MockBotProvider, MOCK_EMAIL_FLOW_DELAY
from providers.vexa import VexaProvider
from providers.base import VexaUnavailableError, VexaError


MEETING_ID = "test-meeting-123"


# ── MockBotProvider ───────────────────────────────────────────────────────────

class TestMockBotProvider:
    def setup_method(self):
        self.provider = MockBotProvider()

    def test_join_by_url_returns_meeting_id(self):
        result = self.provider.join_by_url("https://meet.google.com/abc", MEETING_ID)
        assert result == MEETING_ID

    def test_join_by_email_returns_meeting_id(self):
        result = self.provider.join_by_email("bot@centralagent.ai", MEETING_ID)
        assert result == MEETING_ID

    def test_url_flow_transcript_immediately_ready(self):
        self.provider.join_by_url("https://meet.google.com/abc", MEETING_ID)
        assert self.provider.is_transcript_ready(MEETING_ID) is True

    def test_url_flow_get_transcript_returns_content(self):
        self.provider.join_by_url("https://meet.google.com/abc", MEETING_ID)
        transcript = self.provider.get_transcript(MEETING_ID)
        assert isinstance(transcript, str)
        assert len(transcript) > 0

    def test_email_flow_transcript_not_ready_immediately(self):
        self.provider.join_by_email("bot@centralagent.ai", MEETING_ID)
        assert self.provider.is_transcript_ready(MEETING_ID) is False

    def test_email_flow_get_transcript_returns_empty_before_delay(self):
        self.provider.join_by_email("bot@centralagent.ai", MEETING_ID)
        transcript = self.provider.get_transcript(MEETING_ID)
        assert transcript == ""

    def test_email_flow_transcript_ready_after_delay(self):
        self.provider.join_by_email("bot@centralagent.ai", MEETING_ID)
        # Simulate time passing by backdating the registration
        self.provider._email_meetings[MEETING_ID] -= MOCK_EMAIL_FLOW_DELAY
        assert self.provider.is_transcript_ready(MEETING_ID) is True
        assert len(self.provider.get_transcript(MEETING_ID)) > 0

    def test_mock_health_returns_ok(self):
        result = self.provider.health()
        assert result["status"] == "ok"

    def test_mock_transcript_has_realistic_content(self):
        self.provider.join_by_url("https://meet.google.com/abc", MEETING_ID)
        transcript = self.provider.get_transcript(MEETING_ID)
        assert ":" in transcript  # speaker format
        assert len(transcript.splitlines()) > 5


# ── VexaProvider ──────────────────────────────────────────────────────────────

class TestVexaProvider:
    def setup_method(self):
        self.provider = VexaProvider(vexa_url="http://localhost:8056", api_key="test-key")

    def test_join_by_url_calls_correct_endpoint(self):
        mock_response = MagicMock()
        mock_response.is_success = True
        with patch("httpx.post", return_value=mock_response) as mock_post:
            self.provider.join_by_url("https://meet.google.com/abc-defg-hij", MEETING_ID)
            mock_post.assert_called_once_with(
                "http://localhost:8056/bots",
                headers={"Content-Type": "application/json", "X-API-Key": "test-key"},
                json={"platform": "google_meet", "native_meeting_id": "abc-defg-hij"},
                timeout=30.0,
            )

    def test_join_by_url_extracts_native_id_from_url(self):
        from providers.vexa import extract_native_meeting_id
        assert extract_native_meeting_id("https://meet.google.com/abc-defg-hij") == "abc-defg-hij"
        assert extract_native_meeting_id("https://meet.google.com/abc-defg-hij?authuser=0") == "abc-defg-hij"

    def test_join_by_email_calls_correct_endpoint(self):
        mock_response = MagicMock()
        mock_response.is_success = True
        with patch("httpx.post", return_value=mock_response) as mock_post:
            self.provider.join_by_email("bot@centralagent.ai", MEETING_ID)
            mock_post.assert_called_once_with(
                "http://localhost:8056/bots",
                headers={"Content-Type": "application/json", "X-API-Key": "test-key"},
                json={"platform": "google_meet", "bot_email": "bot@centralagent.ai", "meeting_id": MEETING_ID},
                timeout=30.0,
            )

    def test_join_by_url_raises_when_vexa_unavailable(self):
        with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(VexaUnavailableError):
                self.provider.join_by_url("https://meet.google.com/abc-defg-hij", MEETING_ID)

    def test_join_by_url_raises_on_timeout(self):
        with patch("httpx.post", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(VexaUnavailableError):
                self.provider.join_by_url("https://meet.google.com/abc-defg-hij", MEETING_ID)

    def test_join_by_url_raises_on_error_response(self):
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        with patch("httpx.post", return_value=mock_response):
            with pytest.raises(VexaError):
                self.provider.join_by_url("https://meet.google.com/abc-defg-hij", MEETING_ID)

    def test_get_transcript_calls_correct_endpoint(self):
        # First join so native_id is stored
        join_response = MagicMock()
        join_response.is_success = True
        with patch("httpx.post", return_value=join_response):
            self.provider.join_by_url("https://meet.google.com/abc-defg-hij", MEETING_ID)

        transcript_response = MagicMock()
        transcript_response.is_success = True
        transcript_response.json.return_value = [
            {"speaker": "Alice", "text": "Hello"},
            {"speaker": "Bob", "text": "Hi"},
        ]
        with patch("httpx.get", return_value=transcript_response) as mock_get:
            result = self.provider.get_transcript(MEETING_ID)
            mock_get.assert_called_once_with(
                "http://localhost:8056/transcripts/google_meet/abc-defg-hij",
                headers={"Content-Type": "application/json", "X-API-Key": "test-key"},
                timeout=30.0,
            )
            assert "Alice: Hello" in result
            assert "Bob: Hi" in result

    def test_is_transcript_ready_returns_true_when_complete(self):
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"status": "complete"}
        with patch("httpx.get", return_value=mock_response):
            assert self.provider.is_transcript_ready(MEETING_ID) is True

    def test_is_transcript_ready_returns_false_when_active(self):
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"status": "active"}
        with patch("httpx.get", return_value=mock_response):
            assert self.provider.is_transcript_ready(MEETING_ID) is False

    def test_is_transcript_ready_returns_false_on_error(self):
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            assert self.provider.is_transcript_ready(MEETING_ID) is False

    def test_health_returns_ok_when_vexa_reachable(self):
        health_ok = MagicMock()
        health_ok.is_success = True
        probe_ok = MagicMock()
        probe_ok.status_code = 404
        with patch("httpx.get", side_effect=[health_ok, probe_ok]):
            result = self.provider.health()
            assert result["status"] == "ok"

    def test_health_returns_degraded_when_health_endpoint_missing(self):
        health_404 = MagicMock()
        health_404.is_success = False
        health_404.status_code = 404
        with patch("httpx.get", return_value=health_404):
            result = self.provider.health()
            assert result["status"] == "degraded"
            assert "407" in result["detail"]

    def test_health_returns_degraded_when_bot_api_broken(self):
        health_ok = MagicMock()
        health_ok.is_success = True
        probe_broken = MagicMock()
        probe_broken.status_code = 500
        with patch("httpx.get", side_effect=[health_ok, probe_broken]):
            result = self.provider.health()
            assert result["status"] == "degraded"
            assert "407" in result["detail"]

    def test_health_returns_unavailable_when_vexa_down(self):
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            result = self.provider.health()
            assert result["status"] == "unavailable"
            assert "8056" in result["detail"]
