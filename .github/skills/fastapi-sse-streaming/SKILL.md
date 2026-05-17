---
name: fastapi-sse-streaming
display_name: FastAPI SSE Streaming
description: >-
    Server-Sent Events streaming endpoints in FastAPI that push real-time AI response chunks
    to clients. Includes content-safe structured logging discipline that captures only metadata
    (counts, lengths, flags) and never message text or user content.
user-invocable: true
---

# Skill: FastAPI SSE Streaming with Content-Safe Structured Logging

## 1. Purpose

Implement **Server-Sent Events (SSE)** streaming endpoints in FastAPI that push real-time AI
response chunks to clients over a single long-lived HTTP connection.

Pairs with a **content-safe structured logging** discipline: every log entry captures only
metadata (counts, lengths, flags, event names) — never message text, audio bytes, or any
user-supplied content.

**Source:** [`backend/app/main.py`](../../../backend/app/main.py)

---

## 2. When to Use

- Streaming LLM / AI agent responses token-by-token to a browser or mobile client.
- Any endpoint where latency-to-first-byte matters more than waiting for a full response.
- Situations where the response length is unknown in advance (generative output, live logs).
- Compliance-sensitive deployments where PII / content must never appear in log sinks.

---

## 3. Key Concepts

### 3.1 `StreamingResponse` with `text/event-stream`

```python
from fastapi.responses import StreamingResponse

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(request),          # AsyncIterator[str]
        media_type="text/event-stream",
    )
```

`StreamingResponse` accepts any async generator that yields `str` frames.  
Setting `media_type="text/event-stream"` tells the browser this is an EventSource stream.

---

### 3.2 SSE Frame Format

Each frame **must** end with a blank line (`\n\n`) to signal the boundary to the client.

```python
def _format_sse(payload: ChatStreamEvent) -> str:
    return f"event: {payload.event}\ndata: {payload.model_dump_json()}\n\n"
```

Wire format received by the client for a single event:

```
event: message
data: {"event":"message","data":"Hello","conversation_id":"abc-123"}

```

---

### 3.3 `AsyncIterator[str]` Generator Pattern

The generator is the core of the stream. It wraps the upstream async source, formats each
event into an SSE frame, and handles lifecycle logging in `finally`.

```python
from collections.abc import AsyncIterator

async def _event_stream(request: ChatRequest) -> AsyncIterator[str]:
    request_summary = _summarize_request(request)
    logger.info("SSE stream initialization started: %s", request_summary)

    event_counts: Counter[str] = Counter()
    final_conversation_id = request.conversation_id
    last_event: str | None = None
    terminal_result_length: int | None = None

    try:
        async for event in orchestrator.stream_chat(request):
            payload = ChatStreamEvent(
                event=event.event,
                data=event.data,
                conversation_id=event.conversation_id,
            )
            event_counts[payload.event] += 1
            last_event = payload.event
            final_conversation_id = payload.conversation_id or final_conversation_id

            if payload.event in {"done", "error"}:
                terminal_result_length = len(payload.data)

            sse_frame = _format_sse(payload)
            logger.info("SSE event yielded: %s", _summarize_stream_event(
                payload,
                event_index=sum(event_counts.values()),
                sse_frame_length=len(sse_frame),
            ))
            yield sse_frame

        logger.info("SSE stream completed successfully: %s", _summarize_stream_result(
            request_summary=request_summary,
            event_counts=event_counts,
            last_event=last_event,
            final_conversation_id=final_conversation_id,
            terminal_result_length=terminal_result_length,
            status="completed",
        ))

    except Exception:
        logger.exception("SSE stream failed: %s", _summarize_stream_result(
            request_summary=request_summary,
            event_counts=event_counts,
            last_event=last_event,
            final_conversation_id=final_conversation_id,
            terminal_result_length=terminal_result_length,
            status="failed",
        ))
        raise  # always re-raise so FastAPI can close the connection cleanly

    finally:
        logger.info("SSE stream ended: %s", _summarize_stream_result(
            request_summary=request_summary,
            event_counts=event_counts,
            last_event=last_event,
            final_conversation_id=final_conversation_id,
            terminal_result_length=terminal_result_length,
            status="ended",
        ))
```

Key lifecycle points:
| Block | Runs when | Status logged |
|-------|-----------|---------------|
| `try` body completes normally | Upstream exhausted | `"completed"` |
| `except Exception` | Any unhandled error | `"failed"` |
| `finally` | **Always** (success or failure) | `"ended"` |

---

### 3.4 Event Types

| Event name | Meaning |
|------------|---------|
| `status` | Stream phase / progress update (e.g. "thinking…") |
| `message` | Incremental AI output chunk |
| `error` | Stream-level error, stream will close |
| `done` | Stream finished; may carry final metadata |

Detect terminal events to capture result size:

```python
if payload.event in {"done", "error"}:
    terminal_result_length = len(payload.data)
```

---

### 3.5 Content-Safe Logging: `_summarize_request()`

Never pass `request` directly to a logger. Extract only structural metadata.

```python
from collections import Counter
from typing import Any

def _summarize_request(request: ChatRequest) -> dict[str, Any]:
    """Return a content-safe request summary for SSE boundary logging."""
    role_counts = Counter(message.role for message in request.messages)
    return {
        "conversation_id": request.conversation_id,         # ID is safe; content is not
        "conversation_id_present": bool(request.conversation_id),
        "message_count": len(request.messages),
        "system_message_count": role_counts.get("system", 0),
        "user_message_count": role_counts.get("user", 0),
        "assistant_message_count": role_counts.get("assistant", 0),
        "metadata_key_count": len(request.metadata or {}),
    }
```

`Counter[str]` over `message.role` groups messages by role without touching `.content`.

---

### 3.6 Content-Safe Logging: `_summarize_stream_event()`

Per-event log captures shape and size — not payload content.

```python
def _summarize_stream_event(
    payload: ChatStreamEvent,
    *,
    event_index: int,
    sse_frame_length: int,
) -> dict[str, Any]:
    """Return a content-safe summary for a streamed SSE event."""
    return {
        "event_index": event_index,
        "event": payload.event,
        "conversation_id": payload.conversation_id,
        "conversation_id_present": bool(payload.conversation_id),
        "payload_fields": sorted(payload.model_dump().keys()),  # field names, not values
        "data_length": len(payload.data),                       # byte count, not content
        "sse_frame_length": sse_frame_length,
    }
```

---

### 3.7 `Counter[str]` for Event Tracking

```python
from collections import Counter

event_counts: Counter[str] = Counter()

# Inside the loop:
event_counts[payload.event] += 1          # increment by event type

# Totals:
total = sum(event_counts.values())        # total events yielded
breakdown = dict(event_counts)            # {"message": 42, "done": 1}
```

---

### 3.8 `_summarize_stream_result()` — Final Summary

Aggregates the complete stream lifecycle into a single loggable dict.

```python
def _summarize_stream_result(
    *,
    request_summary: dict[str, Any],
    event_counts: Counter[str],
    last_event: str | None,
    final_conversation_id: str | None,
    terminal_result_length: int | None,
    status: str,           # "completed" | "failed" | "ended"
) -> dict[str, Any]:
    """Return a final stream summary without exposing payload contents."""
    return {
        "status": status,
        "request_conversation_id": request_summary["conversation_id"],
        "final_conversation_id": final_conversation_id,
        "event_count": sum(event_counts.values()),
        "event_counts": dict(event_counts),
        "last_event": last_event,
        "terminal_result_length": terminal_result_length,
    }
```

`status` values:
- `"completed"` — upstream exhausted without error (logged in `try` block after the loop)
- `"failed"` — exception was raised (logged in `except`)
- `"ended"` — always logged in `finally`, regardless of success or failure

The `finally` block **always** fires, so `"ended"` is your guaranteed audit trail entry.

---

## 4. Content-Safe Logging Rules

### Why

AI chat backends process user messages that may contain PII, confidential queries, or
regulated content. Logging raw message content creates compliance risk in log aggregation
systems (CloudWatch, Azure Monitor, Datadog, etc.) that may retain logs indefinitely.

### Rules

| Rule | Correct | Wrong |
|------|---------|-------|
| Log message counts, not content | `"user_message_count": 3` | `logger.info(message.content)` |
| Log data lengths, not data | `"data_length": len(payload.data)` | `logger.info(payload.data)` |
| Log field names, not values | `sorted(payload.model_dump().keys())` | `payload.model_dump()` |
| Never log audio | log `mime_type`, `bool(file_name)` | log `audio_bytes` or base64 |
| Conversation IDs are safe | log `conversation_id` freely | — |
| Use `Counter` over role, never content | `Counter(m.role for m in messages)` | `Counter(m.content …)` |

### Pattern for speech endpoints

```python
logger.info(
    "speech_transcribe() request started: mime_type=%s file_name_present=%s",
    request.mime_type,
    bool(request.file_name),     # presence flag, not the file name string
)
# NEVER: logger.info(request.audio_base64)
# NEVER: logger.info(transcript)
```

---

## 5. SSE Client Protocol

### What the browser receives

```
event: status\n
data: {"event":"status","data":"Thinking...","conversation_id":null}\n
\n
event: message\n
data: {"event":"message","data":"The answer is","conversation_id":"abc-123"}\n
\n
event: message\n
data: {"event":"message","data":" 42.","conversation_id":"abc-123"}\n
\n
event: done\n
data: {"event":"done","data":"","conversation_id":"abc-123"}\n
\n
```

### JavaScript EventSource client

```javascript
const source = new EventSource("/api/chat/stream");  // GET only; for POST use fetch()

// For POST (required for sending body):
const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, conversation_id }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value);
    for (const line of chunk.split("\n")) {
        if (line.startsWith("data: ")) {
            const payload = JSON.parse(line.slice(6));
            handleEvent(payload);           // { event, data, conversation_id }
        }
    }
}
```

### Frame anatomy

```
event: <event_name>\n       ← named event (maps to addEventListener type)
data: <json_string>\n       ← single JSON object, all fields on one line
\n                          ← blank line = end of this event frame
```

---

## 6. Endpoint Pattern — Full Route Skeleton

```python
import logging
from collections import Counter
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from app.models import ChatRequest, ChatStreamEvent

logger = logging.getLogger(__name__)
app = FastAPI()


# ── SSE frame formatter ──────────────────────────────────────────────────────

def _format_sse(payload: ChatStreamEvent) -> str:
    return f"event: {payload.event}\ndata: {payload.model_dump_json()}\n\n"


# ── Content-safe log helpers ─────────────────────────────────────────────────

def _summarize_request(request: ChatRequest) -> dict[str, Any]:
    role_counts = Counter(m.role for m in request.messages)
    return {
        "conversation_id": request.conversation_id,
        "conversation_id_present": bool(request.conversation_id),
        "message_count": len(request.messages),
        "user_message_count": role_counts.get("user", 0),
        "assistant_message_count": role_counts.get("assistant", 0),
        "system_message_count": role_counts.get("system", 0),
        "metadata_key_count": len(request.metadata or {}),
    }


def _summarize_stream_result(
    *,
    request_summary: dict[str, Any],
    event_counts: Counter[str],
    last_event: str | None,
    final_conversation_id: str | None,
    terminal_result_length: int | None,
    status: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "request_conversation_id": request_summary["conversation_id"],
        "final_conversation_id": final_conversation_id,
        "event_count": sum(event_counts.values()),
        "event_counts": dict(event_counts),
        "last_event": last_event,
        "terminal_result_length": terminal_result_length,
    }


# ── Async generator ──────────────────────────────────────────────────────────

async def _event_stream(request: ChatRequest) -> AsyncIterator[str]:
    request_summary = _summarize_request(request)
    logger.info("SSE stream initialization started: %s", request_summary)

    event_counts: Counter[str] = Counter()
    final_conversation_id = request.conversation_id
    last_event: str | None = None
    terminal_result_length: int | None = None

    try:
        async for event in orchestrator.stream_chat(request):   # ← your upstream source
            payload = ChatStreamEvent(
                event=event.event,
                data=event.data,
                conversation_id=event.conversation_id,
            )
            event_counts[payload.event] += 1
            last_event = payload.event
            final_conversation_id = payload.conversation_id or final_conversation_id

            if payload.event in {"done", "error"}:
                terminal_result_length = len(payload.data)

            sse_frame = _format_sse(payload)
            yield sse_frame

        logger.info("SSE stream completed: %s", _summarize_stream_result(
            request_summary=request_summary, event_counts=event_counts,
            last_event=last_event, final_conversation_id=final_conversation_id,
            terminal_result_length=terminal_result_length, status="completed",
        ))
    except Exception:
        logger.exception("SSE stream failed: %s", _summarize_stream_result(
            request_summary=request_summary, event_counts=event_counts,
            last_event=last_event, final_conversation_id=final_conversation_id,
            terminal_result_length=terminal_result_length, status="failed",
        ))
        raise
    finally:
        logger.info("SSE stream ended: %s", _summarize_stream_result(
            request_summary=request_summary, event_counts=event_counts,
            last_event=last_event, final_conversation_id=final_conversation_id,
            terminal_result_length=terminal_result_length, status="ended",
        ))


# ── Route ────────────────────────────────────────────────────────────────────

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    logger.info("chat_stream() request started: %s", _summarize_request(request))
    return StreamingResponse(_event_stream(request), media_type="text/event-stream")
```

---

## 7. Do / Don't

### ✅ DO

1. **Always use `media_type="text/event-stream"`** — without it, browsers buffer the
   response and clients receive nothing until the connection closes.

2. **End every SSE frame with `\n\n`** — a single `\n` continues the current event;
   the double newline is the mandatory frame terminator.

3. **Re-raise exceptions after logging in `except`** — FastAPI needs the generator to
   raise (or return) to cleanly close the HTTP connection and free resources.

4. **Always have a `finally` block** — it is the only guaranteed place to log the end
   of a stream, whether it succeeds, fails, or is cancelled by the client.

5. **Log per-event metadata at `INFO`** — `event_index`, `event`, `sse_frame_length`
   give full observability into stream health without touching content.

6. **Use `Counter[str]` typed with the event name** — provides a typed, zero-default
   counter that accumulates a breakdown suitable for the final summary log.

7. **Capture `terminal_result_length` for `done`/`error` events** — knowing the size
   of the terminal payload helps debug truncated or oversized responses.

### ❌ DON'T

1. **Never log `message.content`, `payload.data` values, or `audio_bytes`** — these
   fields contain user-generated content that must not appear in log sinks.

2. **Never call `payload.model_dump()` in a log statement** — it serializes all field
   *values*. Use `sorted(payload.model_dump().keys())` (field names only) instead.

3. **Don't use `response_model=` on a streaming endpoint** — FastAPI cannot validate or
   serialize a generator; omit `response_model` or type-hint the return as
   `StreamingResponse`.

4. **Don't create `StreamingResponse` with `media_type="application/json"`** for SSE —
   clients will not parse it as an event stream.

5. **Don't swallow exceptions silently inside the generator** — a bare `except:
   pass` means the client hangs forever waiting for the next frame with no error signal.

6. **Don't log the full request object** — pass it through `_summarize_request()` first
   to strip all content fields before the dict reaches the logger.

7. **Don't forget to track `final_conversation_id`** — the upstream may assign a new
   conversation ID on the first response; always prefer the event's ID over the
   request's ID in subsequent logs.
