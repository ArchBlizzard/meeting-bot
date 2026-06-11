import base64
from typing import List, Dict

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


class GmailClient:
    def __init__(self, creds: Credentials, user_id: str = "me"):
        self.service = build("gmail", "v1", credentials=creds)
        self.user_id = user_id

    def list_messages(self, query: str) -> List[Dict]:
        """
        Return every message matching `query`, paginating through all pages.
        Fixes the silent-drop bug: never stops at an arbitrary maxResults cap.
        """
        messages = []
        kwargs: Dict = dict(userId=self.user_id, q=query, maxResults=100)

        while True:
            resp = self.service.users().messages().list(**kwargs).execute()
            messages.extend(resp.get("messages", []))
            next_token = resp.get("nextPageToken")
            if not next_token:
                break
            kwargs["pageToken"] = next_token

        return messages

    def get_message_body(self, message_id: str) -> str:
        msg = self.service.users().messages().get(
            userId=self.user_id, id=message_id, format="full"
        ).execute()
        return self._extract_text(msg.get("payload", {}))

    def _extract_text(self, payload: dict) -> str:
        mime = payload.get("mimeType", "")
        text = ""

        if mime in ("text/plain", "text/html"):
            data = payload.get("body", {}).get("data", "")
            if data:
                text += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        for part in payload.get("parts", []):
            text += self._extract_text(part)

        return text
