import httpx
from urllib.parse import urlparse
from providers.base import BotProvider, VexaUnavailableError, VexaError


def extract_native_meeting_id(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.split("/")[-1]


class VexaProvider(BotProvider):

    def __init__(self, vexa_url: str, api_key: str):
        self.vexa_url = vexa_url.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        }

    def join_by_url(self, url: str) -> str:
        native_id = extract_native_meeting_id(url)
        try:
            response = httpx.post(
                f"{self.vexa_url}/bots",
                headers=self.headers,
                json={
                    "platform": "google_meet",
                    "native_meeting_id": native_id,
                    "authenticated": True,
                    "bot_name": "Schrödinger",
                    "automatic_leave": {"max_time_left_alone": 60000},
                },
                timeout=30.0,
            )
        except httpx.ConnectError:
            raise VexaUnavailableError(
                f"Cannot connect to Vexa at {self.vexa_url}. "
                "Is Vexa running? Run: cd vexa && make lite. "
                "Or set BOT_PROVIDER=mock to run without Vexa."
            )
        except httpx.TimeoutException:
            raise VexaUnavailableError(f"Vexa request timed out at {self.vexa_url}.")

        if not response.is_success:
            raise VexaError(f"Vexa returned {response.status_code}: {response.text}")

        return native_id

    def join_by_email(self, email: str) -> str:
        # Vexa has no email-monitoring API. Auto-join is handled entirely by
        # the Gmail watcher (gmail/watcher.py), which polls Gmail for calendar
        # invites and calls join_by_url when it finds a meet.google.com link.
        # This endpoint just acknowledges the registration — no Vexa call.
        return f"gmail-watcher:{email}"

    def get_transcript(self, meeting_id: str) -> str:
        try:
            response = httpx.get(
                f"{self.vexa_url}/transcripts/google_meet/{meeting_id}",
                headers=self.headers,
                timeout=30.0,
            )
        except httpx.ConnectError:
            raise VexaUnavailableError(f"Cannot connect to Vexa at {self.vexa_url}.")
        except httpx.TimeoutException:
            raise VexaUnavailableError("Vexa transcript request timed out.")

        if not response.is_success:
            raise VexaError(f"Vexa returned {response.status_code}: {response.text}")

        data = response.json()
        segments = data.get("segments", [])
        if isinstance(segments, list) and segments:
            return "\n".join(
                f"{seg.get('speaker', 'Unknown')}: {seg.get('text', '')}"
                for seg in segments
            )
        return ""

    def is_transcript_ready(self, meeting_id: str) -> bool:
        try:
            response = httpx.get(
                f"{self.vexa_url}/transcripts/google_meet/{meeting_id}",
                headers=self.headers,
                timeout=10.0,
            )
            if not response.is_success:
                return False
            return response.json().get("status") == "completed"
        except Exception:
            return False
