# Meeting Bot

A meeting bot that joins Google Meet calls using [Vexa.ai](https://github.com/Vexa-ai/vexa) and uses Claude Opus 4.8 to generate post-meeting digests and answer questions about the meeting. Built as a take-home assignment for CentralAgent.

---

## How It Works

1. The bot joins a Google Meet (by URL directly, or automatically via the Gmail watcher)
2. It captures the transcript
3. Ask for a digest or ask any question about the meeting

---

## Design Decisions

### 1. Vexa abstraction with mock fallback

Vexa is the bot infrastructure layer — it handles joining Google Meet calls via a headless browser. Rather than coupling directly to Vexa, we built a clean `BotProvider` interface with two implementations:

- `VexaProvider` — calls the real Vexa API. Bot actually joins the meeting.
- `MockProvider` — returns a realistic hardcoded transcript instantly. No bot joins, but the full Claude brain layer runs end-to-end.

Controlled by a single env var: `BOT_PROVIDER=vexa|mock`

> **Note:** Vexa is currently experiencing issues ([issue #407](https://github.com/Vexa-ai/vexa/issues/407)). The mock provider ensures the system runs end-to-end regardless of Vexa's status.

### 2. Gmail watcher for automatic invite-based joining

The assignment described an "advanced mode" where inviting a bot email to a calendar event would automatically trigger the bot to join. Vexa's documentation does not expose a bot email registration API - there is no documented endpoint for signing a Google account into Vexa and having it watch for calendar invites.

We implemented this differently: a Gmail watcher that polls your own Gmail inbox for emails containing Google Meet URLs, extracts the URL, and calls `join_by_url` on Vexa directly. This achieves the same result — the bot auto-joins any meeting you're invited to — without requiring any undocumented Vexa feature.

The `join_by_email` endpoint still exists in the API as a thin wrapper around Vexa's `bot_email` parameter, but it cannot be end-to-end tested because Vexa does not document how to set this up.

### 3. No chunking — Claude Opus 4.8 with 1M context

We deliberately do not chunk transcripts or use RAG. A 2-3 hour meeting transcript is ~50-100k tokens, well within Opus 4.8's 1M context window. The entire transcript is passed in a single API call.

Benefits: simpler architecture, better accuracy (no cross-chunk information loss), and natural Q&A over the full meeting record.

**Tradeoff:** If cutting costs by switching to a smaller model (e.g. Sonnet with 200k context), chunking or a RAG approach would need to be reintroduced. The model is configurable via `ANTHROPIC_MODEL`.

### 4. FastAPI over CLI

A CLI would be a dead end for integration. FastAPI gives REST endpoints any system can call, auto-generates interactive `/docs`, and fits the CentralAgent product context - a central hub other services connect to.

### 5. SQLite with digest caching

Transcripts are persisted in SQLite (via SQLAlchemy), surviving server restarts. Claude digest responses are cached — the first `/digest` call processes the transcript and stores the result; subsequent calls return the cached response without re-invoking Claude.

---

## Setup & Running

### Quick start (mock mode — no Vexa needed)

```bash
git clone <repo>
cd meeting-bot
cp .env.example .env       # add your ANTHROPIC_API_KEY
pip install -r requirements.txt
uvicorn main:app --reload
```

Visit **http://localhost:8000/docs** to test the API interactively in your browser.

### Running with real Vexa

Vexa is a self-hosted Docker service. Set it up first:

```bash
# Terminal 1 — set up and run Vexa
git clone https://github.com/Vexa-ai/vexa
cd vexa
make lite        # single container, quickest setup
                 # Vexa dashboard runs at http://localhost:3000
                 # Vexa API runs at http://localhost:8056

# Get your API key from the Vexa dashboard at http://localhost:3000
```

Then in your `.env`:
```
BOT_PROVIDER=vexa
VEXA_URL=http://localhost:8056
VEXA_API_KEY=your_vexa_key_here
```

> **Port note:** Vexa's API runs on port `8056`, not `3001`. Port `3001` is the Vexa dashboard UI.

> **Note:** Vexa is currently experiencing issues ([#407](https://github.com/Vexa-ai/vexa/issues/407)) — Google made a change to the Meet join flow that broke Vexa's bot admission logic. Use `BOT_PROVIDER=mock` if Vexa is unavailable.

### Enabling the Gmail watcher (auto-join)

The Gmail watcher polls your inbox for Google Meet invites and automatically dispatches a bot to join.

1. Go to [Google Cloud Console](https://console.cloud.google.com) → create a project → enable the Gmail API
2. Create OAuth2 credentials (Desktop app) → download as `credentials.json` → place it in the `meeting-bot/` directory
3. Set in `.env`:
```
GMAIL_ENABLED=true
```
4. Restart the server. On first run, a browser window opens for Gmail consent. The token is cached in `token.json` for all subsequent runs.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `BOT_PROVIDER` | `mock` | `vexa` or `mock` |
| `ANTHROPIC_API_KEY` | required | Your Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-opus-4-8` | Swappable (e.g. `claude-sonnet-4-6`) |
| `VEXA_URL` | `http://localhost:8056` | Vexa API URL |
| `VEXA_API_KEY` | `""` | Vexa API key (required when `BOT_PROVIDER=vexa`) |
| `DATABASE_URL` | `sqlite:///./meetings.db` | SQLite DB path |
| `GMAIL_ENABLED` | `false` | Enable Gmail watcher for auto-join |
| `GMAIL_CREDENTIALS_FILE` | `credentials.json` | OAuth2 credentials from Google Cloud Console |
| `GMAIL_TOKEN_FILE` | `token.json` | Cached OAuth2 token (auto-generated on first run) |
| `GMAIL_POLL_INTERVAL` | `5` | Seconds between inbox polls |
| `GMAIL_QUERY` | `meet.google.com newer_than:1d` | Gmail search query for invite detection |
| `GMAIL_MAX_CONCURRENT_BOTS` | `10` | Max simultaneous bot threads |

---

## API

### `GET /health`

Basic liveness check. Returns provider and model in use.

### `GET /health/vexa`

Two-stage health check — actively pings Vexa, does not assume status.

| Status | Meaning |
|---|---|
| `ok` | Server reachable, bot API responding |
| `degraded` | Server reachable but returning errors — bot joining likely broken |
| `unavailable` | Cannot reach Vexa server at all |

### `POST /meeting/join`

Manually trigger a bot to join a meeting.

**URL mode** — bot joins immediately:
```json
{ "url": "https://meet.google.com/xxx-xxxx-xxx" }
```

**Email mode** — registers the bot email with Vexa for calendar-invite auto-join. Note: this relies on an undocumented Vexa feature and cannot be verified end-to-end. The Gmail watcher is the recommended approach for automatic joining.
```json
{ "email": "bot@centralagent.ai" }
```

### `GET /meeting/{meeting_id}/status`

Poll transcript availability. When `transcript_ready` becomes `true`, call `/digest` or `/ask`.

### `GET /meeting/{meeting_id}/digest`

Returns a structured digest: summary, action items, decisions. Cached after the first call — subsequent calls return instantly without re-invoking Claude.

```json
{
  "meeting_id": "a3f8c291",
  "summary": "The team aligned on Q3 priorities...",
  "action_items": ["Bob to deliver API spec by June 20th"],
  "decisions": ["JWT chosen for authentication"]
}
```

### `POST /meeting/{meeting_id}/ask`

Ask any question about the meeting. Full transcript passed to Claude — no chunking.

```json
{ "question": "What did Alice say about the deadline?" }
```

### `GET /gmail/status`

Status of the Gmail watcher. Add `?stream=true` to receive a continuous Server-Sent Events stream updated every poll cycle.

```bash
# Single snapshot
curl http://localhost:8000/gmail/status

# Live stream (open in browser or use curl -N)
curl -N "http://localhost:8000/gmail/status?stream=true"
```

---

## Running Tests

```bash
pytest tests/ -v
```

All external calls (Vexa API, Anthropic API) are mocked - tests run without real credentials or services.

---

## What Works, What Doesn't

| Feature | Status |
|---|---|
| Mock provider (full end-to-end) | ✅ Working |
| Claude digest + Q&A | ✅ Working |
| SQLite persistence + caching | ✅ Working |
| Gmail watcher (auto-join on invite) | ✅ Working |
| Vexa URL-based join | ⚠ Implemented — depends on Vexa status ([#407](https://github.com/Vexa-ai/vexa/issues/407)) |
| Auth | ❌ Not implemented (see below) |

---

## Known Limitations & What I'd Do Next

This architecture is correct for a prototype. All bottlenecks are well-understood and solvable without changing the core design.

| Component | Current limit | Fix |
|---|---|---|
| Bot concurrency | 5-10 (Vexa on localhost, ~250MB RAM/bot) | Run Vexa fleet on VMs |
| Claude calls | 3-5 concurrent (synchronous, 15-30s each) | Celery + Redis async task queue |
| API throughput | ~20 req/sec (single Uvicorn worker) | gunicorn + multiple workers |
| Storage | SQLite (single writer) | PostgreSQL for multi-worker safety |
| Auth | None | API key middleware |

Digest caching already mitigates the Claude concurrency issue for repeated reads - the expensive call only happens once per meeting.
