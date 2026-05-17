---
name: python-test
display_name: Python Backend Testing Guide
description: >-
    Testing guide for the Python backend using pytest with IsolatedAsyncioTestCase.
    Covers test patterns for FastAPI endpoints, Azure AI agent orchestration, SSE streaming,
    speech transcription, and content-safe logging validation.
user-invocable: true
---

# Python Backend Testing Guide

> **Living testing guide** for `telegram-bot-project/backend`.  
> Answers: _What should be tested, and how should it be tested?_

---

## 1. Overview

### Stack

| Layer | Tool |
|---|---|
| Test runner | `unittest` (stdlib) |
| Async tests | `unittest.IsolatedAsyncioTestCase` |
| Mocking | `unittest.mock` — `patch`, `AsyncMock`, `MagicMock` |
| HTTP client (endpoint tests) | `httpx.AsyncClient` + `httpx.ASGITransport` |
| HTTP client (integration) | `aiohttp` |
| Dependencies | `uv` (see `pyproject.toml`) |

### Commands

```bash
# Run all unit tests (quiet)
cd backend && uv run python -m unittest discover -s tests -q

# Run a single test file verbosely
cd backend && uv run python -m unittest tests.test_agent -v

# Compile check (catches import errors without running tests)
cd backend && uv run python -m compileall app tests -q

# Run integration tests (requires env vars — see §4)
AZURE_SPEECH_INTEGRATION_TEST=1 \
  cd backend && uv run python -m unittest tests.test_speech_integration -v
```

### Project layout

```
backend/
├── app/
│   ├── agent.py          ← Azure AI Foundry agent orchestration
│   ├── auth.py           ← APIKeyAuthMiddleware
│   ├── config.py         ← Settings (pydantic-settings)
│   ├── main.py           ← FastAPI app, SSE endpoint, speech endpoint
│   ├── models.py         ← ChatRequest, ChatMessage, AgentEvent
│   └── speech.py         ← Audio vault, transcription, ffmpeg helpers
└── tests/
    ├── test_agent.py             ← Unit tests for agent.py helpers & stream loop
    ├── test_main.py              ← Unit tests for FastAPI endpoints & middleware
    ├── test_speech.py            ← Unit tests for speech.py helpers
    └── test_speech_integration.py ← Integration / E2E tests (env-gated)
```

---

## 2. What To Test (by module)

### `app/agent.py`

#### Helper functions (pure / sync)

| Function | What to assert |
|---|---|
| `_extract_latest_user_input` | Returns last `user` message content; raises `RuntimeError` when no user message present |
| `_extract_latest_user_content` | Normalizes legacy `"text"` / `"image_url"` parts to `"input_text"` / `"input_image"` wire format |
| `_build_response_kwargs` | Omits `input` key for new conversations (`user_input=None`); wraps multimodal content as `{"type":"message","role":"user","content":[...]}` for existing conversations; sets `extra_body["agent_reference"]` |
| `_prepare_response_input` | Passes MCP approval items through as-is (they are already top-level response items) |
| `_extract_annotation_messages` | Returns `[]` for content with no annotations; formats `url_citation` as `"Source: {title} - {url}"` |
| `_extract_output_item_messages` | Extracts text from completed `output_text` content parts |
| `_format_mcp_approval_message` | Renders `"Tool approval requested for {name} on {server_label}. Auto-approving and continuing..."` |
| `_build_mcp_approval_input` | Returns list of `{"type":"mcp_approval_response","approval_request_id":…,"approve":True}` items |
| `_format_activity_status` | Renders `"Calling tool {name} on {server}…"` / `"… completed."` / `"… failed: {error}"` |
| `_format_unexpected_error` | Includes exception type and message |
| `_format_bad_request_error` | Includes the `OpenAIBadRequestError` message string |
| `_build_response_instructions` | Joins all `system` role messages with `"\n\n"` |
| `_content_is_multimodal` | `True` when any part has type `input_image`; `False` for text-only or plain string |
| `_extract_text_from_multimodal` | Joins all `input_text` parts; returns `"Image attached."` when none present |

#### Agent resolution (`AzureAIFoundryAgent._resolve_agent`)

| Scenario | Expected behaviour |
|---|---|
| Metadata hash matches | Reuse latest version; `create_version` not called |
| Definition matches (no hash) | Reuse latest version; `create_version` not called |
| Definition drifts (instructions changed) | `create_version` called; new version returned |
| Agent version list is empty | `_build_agent_reference` omits `"version"` key |

Use `_MockAsyncVersionIterator` for async iteration over agent versions (see §3).

#### Stream event deduplication (`AzureAIFoundryAgent._stream_events_from_item`)

| Scenario | Expected behaviour |
|---|---|
| `response.output_item.done` for a `message` item | Emits one `"message"` event with the text |
| `response.output_item.added` for `mcp_approval_request` | Emits one `"status"` event naming tool + server |
| `response.output_item.done` for `mcp_approval_request` | Emits **nothing** (approval status already sent on `.added`) |
| `response.output_item.added` for `mcp_call` | Emits one `"status"` event: `"Calling tool …"` |
| `response.output_text.delta` then `response.output_text.done` (same `item_id`) | Done event is **skipped** (delta already streamed) |
| `response.output_text.delta` then `response.output_item.done` (same `output_index`) | Done's content parts that **were** already streamed are skipped; additional parts still emitted |
| `response.output_item.done` with multi-part content, first part already delta-streamed | Only un-streamed parts emitted |

#### Conversation lifecycle

| Scenario | Expected behaviour |
|---|---|
| `request.conversation_id` is `None` / absent | `_create_fresh_conversation` called; `conversations.create` awaited once with first user message |
| `request.conversation_id` is set | `_ensure_conversation` returns existing ID; `conversations.create` **not** called |
| Multimodal content on new conversation | Content preserved as `"message"` item in `conversations.create` call |

#### Full stream loop (`AzureAIFoundryAgent.stream`)

- Multi-response runs (MCP approval triggers second `responses.create`): deduplication state resets between responses.
- `credential.close()` awaited exactly once even on exception.
- Both `"초기 응답"` (delta from first response) and `"후속 응답"` (done from second response) appear in final event list.

---

### `app/main.py`

#### `_summarize_request`

- Returns dict with: `conversation_id`, `conversation_id_present`, `message_count`, `system_message_count`, `user_message_count`, `assistant_message_count`, `metadata_key_count`.
- String representation **must not** contain any message body content.

#### SSE stream (`_event_stream`)

| Scenario | What to assert |
|---|---|
| Happy path (3 events) | 3 SSE chunks yielded; logs contain `"SSE event yielded"`, per-event index, final `event_counts`, `'status': 'completed'`, `'status': 'ended'` |
| Failure path (exception mid-stream) | `RuntimeError` propagates; logs contain `"SSE stream failed"`, `'status': 'failed'`, `'status': 'ended'` |
| Content safety | Logs never contain request content, event data payloads, or secret strings |

#### `/api/speech/transcribe` endpoint

| Scenario | Expected HTTP status |
|---|---|
| Decode + transcribe succeed | 200 with `{"text": "…", "language": "…"}` |
| `RuntimeError` from transcriber | 400 |

#### `/audio/{token}` endpoint

| Scenario | Expected HTTP status |
|---|---|
| Token exists in vault | 200; body equals stored bytes; `content-type: audio/wav` |
| Token does not exist | 404 |
| No `x-api-key` header present | 200 (audio route bypasses auth middleware) |

#### `APIKeyAuthMiddleware` (`app/auth.py`)

| `app_env` | `backend_api_key` | Header | Expected |
|---|---|---|---|
| `development` | `None` | — | 200 |
| `development` | `"secret"` | correct key | 200 |
| `development` | `"secret"` | wrong key | 200 (dev auth is off) |
| `production` | `"prod-secret"` | correct key | 200 |
| `production` | `"prod-secret"` | no header | 401 |
| `production` | `"prod-secret"` | wrong key | 401 |
| `production` | `None` | — | 503 (misconfigured) |
| `production` | `"secret"` | — (path `/health`) | 200 (excluded path) |

---

### `app/speech.py`

#### `_resolve_audio_extension`

- Filename suffix takes priority over MIME type: `("audio/ogg", "voice.oga")` → `".oga"`.

#### `_extract_transcript`

| Input | Expected |
|---|---|
| `{"DisplayText": "안녕하세요"}` | `"안녕하세요"` |
| `{"NBest": [{"Display": "테스트 음성"}]}` | `"테스트 음성"` |
| `{"RecognitionStatus": "NoMatch"}` | `None` |

#### `_extract_batch_transcript`

| Input | Expected |
|---|---|
| `{"combinedRecognizedPhrases": [{"display": "안녕하세요 세계"}]}` | `"안녕하세요 세계"` |
| `combinedRecognizedPhrases` empty, `recognizedPhrases` present | First `nBest[0].display` |
| Multiple `recognizedPhrases` segments | Space-joined |
| Both empty | `None` |

#### Audio vault (`vault_store` / `vault_get` / `vault_remove`)

| Scenario | Expected |
|---|---|
| `vault_store(b"data")` | Returns UUID string matching `/^[0-9a-f-]{36}$/` |
| `vault_get(token)` after store | Returns stored bytes |
| `vault_get("nonexistent-token")` | `None` |
| `vault_get(token)` after `vault_remove(token)` | `None` |

Always call `vault_remove` in `finally` blocks to avoid leaking state across tests.

#### `_require_endpoint` / `_require_backend_url`

- Raises `RuntimeError` whose message contains the env var name (`"AZURE_SPEECH_ENDPOINT"` / `"BACKEND_PUBLIC_URL"`).
- Strips trailing slash when value is set.

#### `_convert_audio_bytes_to_wav`

- `imageio_ffmpeg.get_ffmpeg_exe()` is called; its result is used as the first argument to `subprocess.run`.
- `"16000"` (target sample rate) appears in the command args.
- Returns the bytes written to the output path by the fake `subprocess.run`.

#### `AzureSpeechTranscriber.transcribe_audio_bytes`

| Scenario | Expected |
|---|---|
| Empty bytes | `RuntimeError` with `"empty"` in message |
| Non-empty bytes | Calls `_convert_audio_bytes_to_wav` then `_transcribe_wav_bytes`; returns transcript |

#### `AzureSpeechTranscriber._transcribe_wav_bytes` (full batch flow)

Happy path steps to verify (all HTTP calls mocked via fake `aiohttp.ClientSession`):

1. WAV bytes stored in vault → `vault_store` returns token.
2. `POST /transcriptions` returns `201` with `{"self": "…/job-123"}`.
3. Poll `GET /transcriptions/job-123` until `status == "Succeeded"` (mock `asyncio.sleep`).
4. `GET /transcriptions/job-123/files` returns file list with `kind == "Transcription"` and `contentUrl`.
5. `GET {contentUrl}` returns batch result.
6. `DELETE /transcriptions/job-123` called.
7. Vault token removed.
8. Returns transcript string from `_extract_batch_transcript`.

Failure paths:
- Missing `AZURE_SPEECH_ENDPOINT` → `RuntimeError` with `"AZURE_SPEECH_ENDPOINT"`.
- Missing `BACKEND_PUBLIC_URL` → `RuntimeError` with `"BACKEND_PUBLIC_URL"`.

Vault cleanup: after a successful run all tokens passed to `vault_store` must be absent from the vault.

---

### Integration tests (`test_speech_integration.py`)

These tests are **skipped by default**. Enable with env vars:

```bash
# Local ASGI tests (no real network)
AZURE_SPEECH_INTEGRATION_TEST=1 \
  uv run python -m unittest tests.test_speech_integration.AudioVaultEndpointIntegrationTest -v

# Full E2E against a deployed backend
AZURE_SPEECH_INTEGRATION_TEST=1 \
BACKEND_PUBLIC_URL=https://my-backend.example.com \
BACKEND_API_KEY=my-secret \
  uv run python -m unittest tests.test_speech_integration.DeployedBackendTranscriptionTest -v
```

| Class | Transport | Tests |
|---|---|---|
| `AudioVaultEndpointIntegrationTest` | `ASGITransport` (local) | `/audio/{token}` returns WAV; 404 after remove; bypasses API key middleware |
| `DeployedBackendTranscriptionTest` | Real `aiohttp` | Full round-trip: sine WAV → `/api/speech/transcribe` → 200 or `"no text"` 400 |

---

## 3. How To Test (patterns with code examples)

### Sync test

```python
class MyTests(unittest.TestCase):
    def test_happy_path(self) -> None:
        result = my_pure_function("input")
        self.assertEqual(result, "expected")

    def test_edge_case_empty(self) -> None:
        self.assertIsNone(my_pure_function(""))

    def test_failure_raises(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "ENV_VAR_NAME"):
            my_function_needing_env()
```

### Async test

```python
class MyAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_behavior(self) -> None:
        result = await my_async_function()
        self.assertEqual(result, "expected")
```

### Settings fixture (avoid `.env` dependency)

```python
from types import SimpleNamespace

def _settings(**overrides):
    return SimpleNamespace(
        azure_speech_endpoint="https://ep.cognitiveservices.azure.com/",
        azure_speech_language="ko-KR",
        backend_public_url="https://backend.example.com",
        request_timeout_seconds=30,
        **overrides,
    )

# Usage: test missing endpoint
def test_require_endpoint_raises(self) -> None:
    service = AzureSpeechTranscriber(_settings(azure_speech_endpoint=None))
    with self.assertRaisesRegex(RuntimeError, "AZURE_SPEECH_ENDPOINT"):
        service._require_endpoint()
```

### Mocking async methods

```python
from unittest.mock import AsyncMock, patch

with patch.object(service, "_get_bearer_token", new=AsyncMock(return_value="tok")):
    result = await service._transcribe_wav_bytes(b"wav", language="ko-KR")
```

### Mocking `aiohttp.ClientSession` (fake context manager classes)

```python
import json as json_mod

class FakeResponse:
    def __init__(self, status: int, body: dict):
        self.status = status
        self._body = body

    async def text(self) -> str:
        return json_mod.dumps(self._body)

    async def json(self) -> dict:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    def post(self, url, **kw):
        return FakeResponse(201, {"self": "https://ep/transcriptions/job-1"})

    def get(self, url, **kw):
        if "files" in url:
            return FakeResponse(200, {"values": [
                {"kind": "Transcription", "links": {"contentUrl": "https://blob/r"}}
            ]})
        if "blob/r" in url:
            return FakeResponse(200, {"combinedRecognizedPhrases": [{"display": "안녕하세요"}]})
        return FakeResponse(200, {"status": "Succeeded"})

    def delete(self, url, **kw):
        return FakeResponse(204, {})


with (
    patch.object(service, "_get_bearer_token", new=AsyncMock(return_value="fake-token")),
    patch("aiohttp.ClientSession", return_value=FakeSession()),
    patch("asyncio.sleep", new=AsyncMock()),   # skip polling delays
):
    result = await service._transcribe_wav_bytes(b"wav-bytes", language="ko-KR")
```

### FastAPI endpoint testing via `ASGITransport`

```python
from httpx import ASGITransport, AsyncClient
from app.main import app, settings

async def test_speech_endpoint_success(self) -> None:
    with (
        mock.patch("app.main.speech_transcriber.decode_base64_audio", return_value=b"audio"),
        mock.patch(
            "app.main.speech_transcriber.transcribe_audio_bytes",
            new=mock.AsyncMock(return_value="음성 인식 결과"),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/speech/transcribe",
                headers={"x-api-key": settings.backend_api_key or ""},
                json={
                    "audio_base64": "dm9pY2U=",
                    "mime_type": "audio/ogg",
                    "file_name": "voice.oga",
                    "language": "ko-KR",
                },
            )
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.json(), {"text": "음성 인식 결과", "language": "ko-KR"})
```

### Building a minimal FastAPI app for middleware tests

```python
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from app.auth import APIKeyAuthMiddleware
from app.config import Settings

settings = Settings(APP_ENV="production", BACKEND_API_KEY="prod-secret")
inner = FastAPI()

@inner.get("/api/chat/stream")
async def _handler():
    return JSONResponse({"ok": True})

inner.add_middleware(APIKeyAuthMiddleware, settings=settings)
```

### Conditional integration test

```python
import os, unittest

_ENABLED = os.environ.get("AZURE_SPEECH_INTEGRATION_TEST") == "1"

@unittest.skipUnless(_ENABLED, "Set AZURE_SPEECH_INTEGRATION_TEST=1 to run")
class MyIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_call(self) -> None: ...
```

### Content-safety assertion (logs must not leak secrets)

```python
with self.assertLogs("app.main", level="INFO") as captured:
    await do_something_with_secret_content()

logs = "\n".join(captured.output)
self.assertNotIn("secret-content", logs)
self.assertNotIn("audio-bytes-base64", logs)
```

### Azure SDK async iterator mock

Use `_MockAsyncVersionIterator` for mocking `project_client.agents.list_versions(...)`:

```python
class _MockAsyncVersionIterator:
    def __init__(self, *items):
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)
```

### Azure SDK async context manager mock

Use `_MockAsyncContextManager` for mocking `project_client.get_openai_client(...)`:

```python
class _MockAsyncContextManager:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, exc_type, exc, tb):
        return None
```

### Vault cleanup in tests

```python
from app.speech import vault_store, vault_remove, vault_get

token = vault_store(b"test-wav")
try:
    # ... test logic ...
    self.assertEqual(vault_get(token), b"test-wav")
finally:
    vault_remove(token)   # always clean up
```

---

## 4. Test Coverage Checklist

Use this checklist when writing new tests or reviewing PRs:

- [ ] **Happy path** — expected inputs produce expected outputs
- [ ] **Edge cases** — empty bytes (`b""`), `None` fields, blank strings, empty message lists, no annotations
- [ ] **Failure paths** — missing env vars raise `RuntimeError` containing the env var name; ffmpeg subprocess failure; aiohttp timeout
- [ ] **Content safety** — logs never contain message bodies, audio bytes, base64 payloads, or API keys
- [ ] **Cleanup** — vault entries removed after use; HTTP connections closed; credential `close()` awaited
- [ ] **Auth** — production vs development behaviour tested; correct HTTP status codes (200 / 401 / 503)
- [ ] **Async finally blocks** — verify `finally` executes on both success and exception paths
- [ ] **Deduplication** — stream event deduplication state resets between consecutive Azure `responses.create` calls
- [ ] **Agent resolution** — hash-match reuse and definition-drift creation both covered

---

## 5. Mock Strategy

### Narrow boundary mocking

Prefer `patch.object(instance, "method")` over patching by module path — it survives refactors:

```python
# Good — patches the instance method directly
with mock.patch.object(service, "_get_bearer_token", new=AsyncMock(return_value="tok")):
    ...

# Acceptable — patches module-level import (use when instance is not available)
with mock.patch("app.speech.vault_store", side_effect=capturing_store):
    ...
```

### Speed up polling loops

```python
with mock.patch("asyncio.sleep", new=AsyncMock()):
    result = await service._transcribe_wav_bytes(b"wav", language="ko-KR")
```

### Spy on vault tokens

To verify cleanup without losing control of token values:

```python
stored_tokens: list[str] = []
original_store = __import__("app.speech", fromlist=["vault_store"]).vault_store

def capturing_store(wav_bytes: bytes) -> str:
    token = original_store(wav_bytes)
    stored_tokens.append(token)
    return token

with mock.patch("app.speech.vault_store", side_effect=capturing_store):
    await service._transcribe_wav_bytes(b"data", language="ko-KR")

for tok in stored_tokens:
    self.assertIsNone(vault_get(tok), f"Token {tok} was not cleaned up")
```

### Patching `AIProjectClient` for full stream loop tests

```python
with mock.patch("app.agent.AIProjectClient", return_value=_MockAsyncContextManager(project_client)):
    events = [event async for event in agent.stream(request)]
```

### Collecting async generator output

```python
events = [event async for event in agent._stream_events_from_item(item, "conv-id", set())]
# Then assert on events list
```

---

## 6. Quick Reference: Key Assertions

```python
# Env-var errors include the var name
self.assertRaisesRegex(RuntimeError, "AZURE_SPEECH_ENDPOINT")

# UUID token format
import re
self.assertRegex(token, r"^[0-9a-f-]{36}$")

# Logs contain lifecycle markers but not content
self.assertIn("SSE event yielded", logs)
self.assertNotIn("secret-payload", logs)

# Agent reference structure
self.assertEqual(extra_agent["type"], "agent_reference")
self.assertEqual(extra_agent["name"], "configured-agent")

# Async mock call counts
openai_client.responses.create.assert_awaited_count(2)
credential.close.assert_awaited_once()
```
