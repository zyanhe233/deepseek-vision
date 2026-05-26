# deepseek-vision

**Vision, web search, and OpenAI-compatible proxy for DeepSeek models.**

DeepSeek's API is text-only and Anthropic-shaped. Most agent frameworks (Cline,
Cherry Studio, LangChain, Claude Code, Cursor) expect:

- Multimodal input (images, screenshots, PDFs)
- Built-in `web_search` / `web_fetch` tools
- The OpenAI `/v1/chat/completions` interface

This proxy adds all three, so a single DeepSeek API key plugs into any tool
that supports Claude or GPT-4.

---

## Quick start

### Docker

```bash
cp .env.example .env
# Fill in at minimum: MASTER_API_KEY, DEEPSEEK_API_KEY
docker build -t deepseek-vision .
docker run --env-file .env -p 8000:8000 deepseek-vision
```

### Local (uv)

```bash
cp .env.example .env
uv sync
uv run python main.py
```

### Local (pip)

```bash
cp .env.example .env
pip install -e .
python main.py
```

The proxy listens on `http://localhost:8000` by default.

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/messages` | Anthropic Messages API |
| `POST` | `/v1/messages/count_tokens` | Token counting |
| `POST` | `/v1/chat/completions` | OpenAI Chat Completions API |
| `GET`  | `/v1/models` | List available models |
| `GET`  | `/health` | Liveness check |

All endpoints require the `x-api-key` header (Anthropic style) **or**
`Authorization: Bearer <key>` (OpenAI style).

---

## How it works

```
Client (Anthropic SDK / OpenAI SDK / LangChain / Cline)
    │
    ├─ POST /v1/chat/completions  ──►  OpenAI → Anthropic conversion
    │                                         │
    └─ POST /v1/messages  ───────────────────►┤
                                              │
                                    Vision middleware
                                    (image blocks → text descriptions
                                     via your vision model)
                                              │
                                    web_search / web_fetch middleware
                                    (Anthropic tool protocol → Tavily/Brave
                                     → results injected back into context)
                                              │
                                    DeepSeek upstream
                                    (Anthropic Messages API)
                                              │
                                    Response → caller format
```

---

## Vision

Configure any OpenAI-compatible vision endpoint to describe images before
forwarding the request to DeepSeek:

```env
VISION_BASE_URL=https://api.openai.com/v1
VISION_API_KEY=sk-...
VISION_MODEL=gpt-4o-mini
```

When configured, every `image` content block in the request is replaced with a
`[Image N] <description>` text block. Multiple images are processed in parallel.

Compatible vision backends (anything with an OpenAI-compatible `/v1/chat/completions`):
- OpenAI (`gpt-4o`, `gpt-4o-mini`)
- Qwen-VL (`qwen-vl-max`, `qwen-vl-plus`)
- GLM-4V, InternVL, LLaVA via vLLM
- Any self-hosted OpenAI-compatible server

When `VISION_*` is not set, image blocks are forwarded as-is (useful if your
upstream already supports vision).

---

## Web search & web fetch

Add the `web_search` or `web_fetch` tool to your request using the Anthropic
tool protocol. The proxy intercepts the tool calls, performs the actual
search/fetch, and feeds results back — DeepSeek never needs to leave its
text-generation role.

### web_search

Uses a two-round architecture: the model plans all queries in one shot (parallel
execution), then synthesises the results into a final answer. Sources are
automatically cited with `[N]` markers.

Configure Tavily (recommended) or Brave:

```env
WEB_SEARCH_PROVIDER=tavily
TAVILY_API_KEY=tvly-...
# or
WEB_SEARCH_PROVIDER=brave
BRAVE_API_KEY=BSA-...
```

### web_fetch

Fetches URLs with SSRF protection and DNS pinning. Supports HTML, plain text,
and PDF (base64-forwarded). Results are cited with `[Document N]` markers.

No additional configuration needed beyond enabling the tool in your request.

---

## Model configuration

By default the proxy exposes `deepseek-chat` and `deepseek-reasoner`. Customise
via `DEEPSEEK_MODELS` (comma-separated, optionally with `client-id:upstream-id`
aliasing):

```env
# Bare names (client ID == upstream ID)
DEEPSEEK_MODELS=deepseek-chat,deepseek-reasoner

# With aliasing
DEEPSEEK_MODELS=fast:deepseek-chat,smart:deepseek-reasoner
```

Add a second Anthropic-compatible upstream via `EXTRA_BACKEND_*`:

```env
EXTRA_BACKEND_NAME=my-provider
EXTRA_BACKEND_BASE_URL=https://api.example.com/anthropic
EXTRA_BACKEND_API_KEY=sk-...
EXTRA_BACKEND_MODELS=model-a,model-b
```

---

## Configuration reference

| Variable | Default | Description |
|----------|---------|-------------|
| `MASTER_API_KEY` | *(required)* | Comma-separated list of accepted API keys |
| `DEEPSEEK_API_KEY` | *(required)* | DeepSeek API key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/anthropic` | DeepSeek Messages endpoint |
| `DEEPSEEK_MODELS` | `deepseek-chat,deepseek-reasoner` | Models to expose |
| `EXTRA_BACKEND_NAME` | — | Name for the optional extra upstream |
| `EXTRA_BACKEND_BASE_URL` | — | Base URL of the extra upstream |
| `EXTRA_BACKEND_API_KEY` | — | API key for the extra upstream |
| `EXTRA_BACKEND_MODELS` | — | Models to expose from the extra upstream |
| `VISION_BASE_URL` | — | OpenAI-compatible vision endpoint base URL |
| `VISION_API_KEY` | — | API key for the vision endpoint |
| `VISION_MODEL` | — | Vision model name (e.g. `gpt-4o-mini`) |
| `VISION_PROMPT` | *(built-in)* | System prompt sent to the vision model |
| `WEB_SEARCH_PROVIDER` | `tavily` | Search provider (`tavily` or `brave`) |
| `TAVILY_API_KEY` | — | Tavily API key |
| `BRAVE_API_KEY` | — | Brave Search API key |
| `WEB_SEARCH_MAX_RESULTS` | `5` | Max results per search query |
| `WEB_SEARCH_DEFAULT_MAX_USES` | `3` | Max search calls per request |
| `WEB_FETCH_DEFAULT_MAX_USES` | `5` | Max fetch calls per request |
| `WEB_FETCH_DEFAULT_MAX_CONTENT_TOKENS` | `100000` | Max content length per fetch |
| `PORT` | `8000` | Server port |
| `LOG_LEVEL` | `INFO` | Logging level |
| `UPSTREAM_TIMEOUT` | `900` | Non-streaming request timeout (seconds) |
| `UPSTREAM_STREAM_TIMEOUT` | `1200` | Streaming request timeout (seconds) |
| `STREAM_PING_INTERVAL_SEC` | `10` | SSE keep-alive ping interval |
| `SLOW_REQUEST_THRESHOLD_MS` | `20000` | Dump diagnostics for requests slower than this |
| `DEBUG_UPSTREAM` | `false` | Log full upstream request bodies |

---

## Roadmap

- [ ] `/v1/embeddings` endpoint
- [ ] SearXNG search provider (self-hosted)
- [ ] Streaming tool calls in OpenAI compat mode
- [ ] Anthropic-native vision provider support

---

## License

MIT
