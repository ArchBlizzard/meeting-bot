import httpx
from urllib.parse import urlparse
from providers.base import BotProvider, VexaUnavailableError, VexaError


def extract_native_meeting_id(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.split("/")[-1]


class VexaProvider(BotProvider):
    """Real Vexa bot provider. Requires Vexa running via Docker (see github.com/Vexa-ai/vexa). Note issue #407."""

    def __init__(self, vexa_url: str, api_key: str):
        self.vexa_url = vexa_url.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        }
        self._native_ids: dict[str, str] = {}

    def join_by_url(self, url: str, meeting_id: str) -> str:
        native_id = extract_native_meeting_id(url)

        try:
            response = httpx.post(
                f"{self.vexa_url}/bots",
                headers=self.headers,
                json={
                    "platform": "google_meet",
                    "native_meeting_id": native_id,
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
            raise VexaUnavailableError(
                f"Vexa request timed out at {self.vexa_url}."
            )

        if not response.is_success:
            raise VexaError(
                f"Vexa returned {response.status_code}: {response.text}"
            )

        self._native_ids[meeting_id] = native_id

        return meeting_id

    def join_by_email(self, email: str, meeting_id: str) -> str:
        try:
            response = httpx.post(
                f"{self.vexa_url}/bots",
                headers=self.headers,
                json={
                    "platform": "google_meet",
                    "bot_email": email,
                    "meeting_id": meeting_id,
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
            raise VexaUnavailableError(
                f"Vexa request timed out at {self.vexa_url}."
            )

        if not response.is_success:
            raise VexaError(
                f"Vexa returned {response.status_code}: {response.text}"
            )

        return meeting_id

    def get_transcript(self, meeting_id: str) -> str:
        native_id = self._native_ids.get(meeting_id, meeting_id)

        try:
            response = httpx.get(
                f"{self.vexa_url}/transcripts/google_meet/{native_id}",
                headers=self.headers,
                timeout=30.0,
            )
        except httpx.ConnectError:
            raise VexaUnavailableError(
                f"Cannot connect to Vexa at {self.vexa_url}."
            )
        except httpx.TimeoutException:
            raise VexaUnavailableError(
                "Vexa transcript request timed out."
            )

        if not response.is_success:
            raise VexaError(
                f"Vexa returned {response.status_code}: {response.text}"
            )

        data = response.json()
        if isinstance(data, list):
            return "\n".join(
                f"{seg.get('speaker', 'Unknown')}: {seg.get('text', '')}"
                for seg in data
            )
        return data.get("transcript", "")

    def is_transcript_ready(self, meeting_id: str) -> bool:
        native_id = self._native_ids.get(meeting_id, meeting_id)

        try:
            response = httpx.get(
                f"{self.vexa_url}/bots/{native_id}",
                headers=self.headers,
                timeout=10.0,
            )
            if not response.is_success:
                return False
            return response.json().get("status") == "complete"
        except Exception:
            return False

    def health(self) -> dict:
        try:
            response = httpx.get(
                f"{self.vexa_url}/health",
                headers=self.headers,
                timeout=5.0,
            )
            if not response.is_success:
                return {
                    "status": "degraded",
                    "detail": (
                        f"Vexa server is reachable but /health returned {response.status_code}. "
                        "See github.com/Vexa-ai/vexa/issues/407."
                    ),
                }
        except httpx.ConnectError:
            return {
                "status": "unavailable",
                "detail": (
                    f"Cannot connect to Vexa at {self.vexa_url}. "
                    "Start Vexa with: cd vexa && make lite. "
                    "See github.com/Vexa-ai/vexa/issues/407. "
                    "Set BOT_PROVIDER=mock to run without Vexa."
                ),
            }
        except httpx.TimeoutException:
            return {
                "status": "unavailable",
                "detail": f"Vexa health check timed out at {self.vexa_url}.",
            }

        try:
            probe = httpx.get(
                f"{self.vexa_url}/bots/health-probe-000",
                headers=self.headers,
                timeout=5.0,
            )
            if probe.status_code >= 500:
                return {
                    "status": "degraded",
                    "detail": (
                        f"Vexa server is up but bot API returned {probe.status_code}. "
                        "Bot joining is likely broken. "
                        "See github.com/Vexa-ai/vexa/issues/407."
                    ),
                }
        except Exception:
            pass

        return {
            "status": "ok",
            "detail": f"Vexa reachable at {self.vexa_url} and bot API is responding.",
        }
