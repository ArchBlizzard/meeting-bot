import re

# Standard Google Meet URL format: https://meet.google.com/abc-defg-hij
_MEET_URL_RE = re.compile(
    r"https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}",
    re.IGNORECASE,
)


def extract_meet_url(text: str) -> str | None:
    match = _MEET_URL_RE.search(text)
    return match.group(0) if match else None
