import time
import uuid
from urllib.parse import urlparse
from providers.base import BotProvider

MOCK_TRANSCRIPT = """
[00:00:03] Sarah: Okay I think we're mostly here, let me just — can everyone hear me alright? Marcus, you good?

[00:00:08] Marcus: Yeah I can hear you. Priya's still showing as connecting on my end though.

[00:00:12] Priya: No I'm here, I'm here. Sorry, my headset died, I'm just on laptop audio. Can you hear me okay?

[00:00:17] Sarah: Yeah you're coming through fine. Okay let's just get started, Jake said he'll be a few minutes late, he's finishing up a deploy.

[00:00:24] Marcus: Cool. Elena, you joining today or is she—

[00:00:27] Elena: I'm here, sorry, I was muted. Hi everyone.

[00:00:30] Sarah: Great, okay so we've got a lot to cover today. I want to do a quick sprint review, then get into the API performance stuff because I know Marcus flagged that as urgent, then we need to make a call on the dashboard redesign timeline, and I also want to leave time at the end to talk about the Hendricks account situation.

[00:00:52] Marcus: Yeah Tom mentioned that to me too. He's in back-to-backs until eleven so probably won't make the first half.

[00:00:58] Sarah: Okay that's fine. So let's start with sprint review. Priya, you want to kick us off?

[00:01:06] Priya: Sure. The big one was the bulk export feature — that's fully live in production as of yesterday afternoon.

[00:01:21] Jake: [joins] Hey sorry, just got on, did I miss much?

[00:01:24] Sarah: No perfect timing, Priya's just doing sprint review.

[00:03:12] Marcus: We've been seeing significant latency spikes on the reporting endpoints. p99 is sitting around four seconds on the weekly summary queries, up from eight hundred milliseconds two weeks ago.

[00:03:30] Sarah: Four seconds? That's bad.

[00:03:33] Marcus: It's bad. It's specifically the enterprise accounts with large datasets.

[00:05:11] Marcus: My proposal is we schedule a maintenance window for this coming Sunday at two AM, run the index creation concurrently, and monitor it.

[00:07:03] Sarah: Okay so let's make that a thing. Marcus, does that work?

[00:07:16] Marcus: Yeah that works. Let's do 6-hour TTL to start, see how it goes.
""".strip()

MOCK_EMAIL_FLOW_DELAY = 10


class MockBotProvider(BotProvider):
    """Mock provider for tests and demos. URL flow is instant; email flow simulates async delay."""

    def __init__(self):
        self._email_meetings: dict[str, float] = {}

    def join_by_url(self, url: str) -> str:
        path = urlparse(url).path.strip("/")
        return path.split("/")[-1] or uuid.uuid4().hex[:8]

    def join_by_email(self, email: str) -> str:
        meeting_id = f"mock-{uuid.uuid4().hex[:6]}"
        self._email_meetings[meeting_id] = time.time()
        return meeting_id

    def is_transcript_ready(self, meeting_id: str) -> bool:
        if meeting_id not in self._email_meetings:
            return True
        return time.time() - self._email_meetings[meeting_id] >= MOCK_EMAIL_FLOW_DELAY

    def get_transcript(self, meeting_id: str) -> str:
        if not self.is_transcript_ready(meeting_id):
            return ""
        return MOCK_TRANSCRIPT
