from contextlib import asynccontextmanager
from fastapi import FastAPI
from anthropic import Anthropic
from sqlalchemy.orm import Session

from config import get_settings
from database.models import Base
from database.session import engine
from providers.base import BotProvider
from providers.mock import MockBotProvider
from providers.vexa import VexaProvider
from brain.claude import ClaudeBrain
from api.routes import router

settings = get_settings()


def _build_provider() -> BotProvider:
    if settings.BOT_PROVIDER == "vexa":
        return VexaProvider(vexa_url=settings.VEXA_URL, api_key=settings.VEXA_API_KEY)
    return MockBotProvider()


provider: BotProvider = _build_provider()

anthropic_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def get_claude_brain(db: Session) -> ClaudeBrain:
    return ClaudeBrain(
        client=anthropic_client,
        db=db,
        model=settings.ANTHROPIC_MODEL,
    )


watcher = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    global watcher
    if settings.GMAIL_ENABLED:
        from gmail.auth import get_credentials
        from gmail.client import GmailClient
        from gmail.watcher import GmailWatcher

        creds = get_credentials(settings.GMAIL_CREDENTIALS_FILE, settings.GMAIL_TOKEN_FILE)
        gmail_client = GmailClient(creds)
        watcher = GmailWatcher(
            gmail_client=gmail_client,
            provider=provider,
            query=settings.GMAIL_QUERY,
            poll_interval=settings.GMAIL_POLL_INTERVAL,
            max_concurrent_bots=settings.GMAIL_MAX_CONCURRENT_BOTS,
        )
        watcher.start()

    print(f"Meeting Bot started — provider: {settings.BOT_PROVIDER}, model: {settings.ANTHROPIC_MODEL}, gmail_watcher: {settings.GMAIL_ENABLED}")
    yield

    if watcher:
        watcher.stop()


app = FastAPI(
    title="Meeting Bot",
    description=(
        "Joins Google Meet calls via Vexa.ai and uses Claude Opus 4.8 to generate "
        "post-meeting digests and answer questions over the full transcript. "
        "Supports manual URL/email join and automatic Gmail-based invite detection."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "provider": settings.BOT_PROVIDER,
        "model": settings.ANTHROPIC_MODEL,
        "gmail_watcher": settings.GMAIL_ENABLED,
    }
