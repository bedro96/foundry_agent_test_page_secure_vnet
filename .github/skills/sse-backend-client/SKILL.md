---
name: sse-backend-client
display_name: SSE Backend Client
description: >-
    TypeScript utility module that wraps fetch POST with SSE streaming via AsyncGenerator,
    handles buffer stitching, block parsing, stream teardown, and non-streaming JSON
    transcription endpoints. Use when consuming SSE from a backend or calling transcription APIs.
user-invocable: true
---

# SSE Backend Client Skill

> Source: `frontend/src/lib/backend.ts`

---

## 1. Purpose

TypeScript utility module that:

- Exposes an **`AsyncGenerator`** (`streamBackendChat`) that wraps a `fetch` POST and streams Server-Sent Events (SSE) back to the caller chunk-by-chunk, handling buffer stitching, block parsing, and stream teardown automatically.
- Exposes a **non-streaming** helper (`transcribeBackendAudio`) for the JSON transcription endpoint, with structured error extraction and type-guard validation.

Both helpers resolve the backend base URL and inject an optional API key header from environment variables so callers never touch raw `fetch` configuration.

---

## 2. When to Use

Use this skill when you need to:

- **Consume SSE from a backend** without reaching for an SSE library—`fetch` + `ReadableStream` is enough.
- **Parse SSE blocks** that may arrive split across multiple network chunks (the buffer-split pattern handles this transparently).
- **Implement clean stream teardown**: the generator's `finally` block guarantees that `reader.cancel()` and `reader.releaseLock()` are called even when the caller `break`s out of `for await`.
- **Call a non-streaming JSON endpoint** with structured error handling that extracts a `detail` field from FastAPI-style error bodies.

---

## 3. Type Definitions

```ts
/** A plain-text content part for multimodal messages. */
export type TextContentPart = {
  type: "input_text";
  text: string;
};

/** An image content part (URL + optional fidelity hint). */
export type ImageContentPart = {
  type: "input_image";
  image_url: string;
  detail?: "low" | "high" | "auto" | "original";
};

/** Union of all content part types — used inside BackendChatMessage. */
export type ContentPart = TextContentPart | ImageContentPart;

/**
 * A single chat turn.
 * `content` is either a plain string (common case) or an array of
 * ContentParts for multimodal payloads (image + text mixed).
 */
export type BackendChatMessage = {
  role: "system" | "user" | "assistant";
  content: string | ContentPart[];
};

/**
 * Request body for POST /api/chat/stream.
 * `conversation_id` is omitted on the first turn; the server returns one
 * that should be echoed back on subsequent turns.
 */
export type BackendChatRequest = {
  messages: BackendChatMessage[];
  conversation_id?: string;
  metadata?: Record<string, string>;
};

/**
 * A single parsed SSE frame yielded by streamBackendChat.
 * - "status"  → informational progress update (not shown as a chat message)
 * - "message" → incremental assistant token or full assistant turn
 * - "error"   → terminal error from the backend
 * - "done"    → stream is finished; generator returns after yielding this
 */
export type BackendStreamEvent = {
  event: "status" | "message" | "error" | "done";
  data: string;
  conversation_id?: string | null;
};

/** Request body for POST /api/speech/transcribe. */
export type BackendTranscriptionRequest = {
  audio_base64: string;   // Base-64 encoded audio bytes
  mime_type: string;      // e.g. "audio/webm;codecs=opus"
  file_name?: string;     // Optional hint used by the backend
  language?: string;      // BCP-47 language code, e.g. "ko"
};

/** Successful response from the transcription endpoint. */
export type BackendTranscriptionResponse = {
  text: string;           // Transcribed text (always non-empty on success)
  language: string;       // Detected or requested language code
};
```

---

## 4. Key Concepts

### 4.1 SSE Generator

```ts
export async function* streamBackendChat(
  payload: BackendChatRequest,
): AsyncGenerator<BackendStreamEvent, void, undefined> {
  const response = await fetch(`${getBackendBaseUrl()}/api/chat/stream`, {
    method: "POST",
    headers: buildBackendHeaders(),
    body: JSON.stringify(payload),
    cache: "no-store",  // never serve a cached streaming response
  });

  if (!response.ok || !response.body) {
    throw new Error(`Backend request failed with status ${response.status}`);
  }
  // ... reader loop below
}
```

The generator is the public API. Callers iterate it with `for await`:

```ts
for await (const event of streamBackendChat(payload)) {
  if (event.event === "message") appendToken(event.data);
  if (event.event === "status")  showStatus(event.data);
}
// reader is fully closed here — no manual cleanup needed
```

---

### 4.2 SSE Block Parsing

```ts
const parseBlock = (block: string): BackendStreamEvent | null => {
  let eventName = "message";        // SSE default when no "event:" line
  const dataLines: string[] = [];

  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    if (line.startsWith("data:"))  dataLines.push(line.slice(5).trim());
  }

  if (dataLines.length === 0) return null;  // comment-only or empty block

  // Multi-line data values are joined with "\n" before JSON.parse
  const parsed = JSON.parse(dataLines.join("\n")) as Partial<BackendStreamEvent>;

  return {
    event: (parsed.event ?? eventName) as BackendStreamEvent["event"],
    data: typeof parsed.data === "string" ? parsed.data : "",
    conversation_id: parsed.conversation_id ?? null,
  };
};
```

- `event:` line sets the frame type; if absent it defaults to `"message"`.
- Multiple `data:` lines are joined with `"\n"` before `JSON.parse`—this matches the SSE spec for multi-line values.
- The `event` field inside the JSON payload takes precedence over the SSE `event:` line when both are present.

---

### 4.3 Buffer Management

```ts
const decoder = new TextDecoder();
let buffer = "";

while (true) {
  const { done, value } = await reader.read();

  if (value) {
    // stream: true = keep internal shift-state across calls (multi-byte UTF-8)
    buffer += decoder.decode(value, { stream: !done });
  } else if (done) {
    // Flush any remaining bytes held in the decoder's internal state
    buffer += decoder.decode();
  }

  // SSE blocks are separated by a blank line (\n\n)
  const blocks = buffer.split("\n\n");
  // The last element may be an incomplete block — keep it in the buffer
  buffer = blocks.pop() ?? "";

  for (const block of blocks) {
    const event = parseBlock(block);
    if (event) {
      yield event;
      if (event.event === "done") return; // stop consuming immediately
    }
  }

  if (done) break;
}

// Flush any trailing content that arrived without a final \n\n
if (buffer.trim()) {
  const event = parseBlock(buffer);
  if (event) yield event;
}
```

Key insight: `buffer.split("\n\n")` always produces at least one element. `blocks.pop()` removes and stores the last (potentially incomplete) element back into `buffer`, so the next chunk continues from where the previous one left off.

---

### 4.4 Stream Cleanup

```ts
let readerClosed = false;

const cancelReader = async (): Promise<void> => {
  if (readerClosed) return;   // idempotency guard
  readerClosed = true;
  try {
    await reader.cancel();    // signals the browser to abort the HTTP body
  } catch (_error) {
    // Ignore — caller may have already consumed the stream to completion
  }
};

const releaseReaderLock = (): void => {
  try {
    reader.releaseLock();     // frees the ReadableStream for GC
  } catch (_error) {
    // Ignore — stream may already be closed
  }
};

try {
  // ... read loop ...
} finally {
  await cancelReader();       // always cancel first
  releaseReaderLock();        // then release
}
```

See Section 6 for a detailed explanation of why both steps and the `readerClosed` flag are required.

---

### 4.5 Early Termination on `done`

```ts
if (event.event === "done") return;
```

This `return` statement inside the generator causes it to terminate cleanly (the `finally` block still executes). Without it, the loop would continue calling `reader.read()` on a stream the server has already logically closed, wasting a network round-trip and potentially reading stale bytes.

---

### 4.6 API Key Header Injection

```ts
function buildBackendHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  const apiKey = process.env.BACKEND_API_KEY;
  if (apiKey) {
    headers["x-api-key"] = apiKey;
  } else {
    console.warn("[backend] BACKEND_API_KEY is not set; requests will be sent without an API key header");
  }

  return headers;
}
```

- The `x-api-key` header is only injected when `BACKEND_API_KEY` is present.
- A `console.warn` fires on every missing-key call — useful for catching misconfigured deployments early.

---

### 4.7 Base URL Resolution

```ts
function getBackendBaseUrl(): string {
  return process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://backend:8000";
}
```

Priority: `BACKEND_URL` (server-only) → `NEXT_PUBLIC_BACKEND_URL` (also exposed to browser) → `http://backend:8000` (Docker Compose service name default).

---

### 4.8 Transcription Endpoint

```ts
export async function transcribeBackendAudio(
  payload: BackendTranscriptionRequest,
): Promise<BackendTranscriptionResponse> {
  const response = await fetch(`${getBackendBaseUrl()}/api/speech/transcribe`, {
    method: "POST",
    headers: buildBackendHeaders(),
    body: JSON.stringify(payload),
    cache: "no-store",
  });

  let parsedBody: unknown = null;
  try {
    parsedBody = await response.json();
  } catch {
    parsedBody = null;
  }

  if (!response.ok) {
    // Extract FastAPI-style "detail" field from error body when available
    const detail =
      parsedBody && typeof parsedBody === "object" &&
      "detail" in parsedBody && typeof parsedBody.detail === "string"
        ? parsedBody.detail
        : `Backend transcription request failed with status ${response.status}`;
    throw new Error(detail);
  }

  // Type guard: validates shape before treating as BackendTranscriptionResponse
  if (!isBackendTranscriptionResponse(parsedBody)) {
    throw new Error("Backend transcription returned an invalid response.");
  }

  // Reject whitespace-only transcriptions (silence, noise, etc.)
  if (!parsedBody.text.trim()) {
    throw new Error("Backend transcription returned empty text.");
  }

  return parsedBody;
}
```

The `isBackendTranscriptionResponse` type guard:

```ts
function isBackendTranscriptionResponse(value: unknown): value is BackendTranscriptionResponse {
  return (
    value !== null &&
    typeof value === "object" &&
    "text" in value && typeof value.text === "string" &&
    "language" in value && typeof value.language === "string"
  );
}
```

---

## 5. SSE Wire Protocol

This client expects the standard SSE wire format — blank-line-separated frames, each frame containing one `event:` line and one or more `data:` lines:

```
event: status\n
data: {"event":"status","data":"Connecting","conversation_id":"conv-1"}\n
\n
event: message\n
data: {"event":"message","data":"Hello","conversation_id":"conv-1"}\n
\n
event: done\n
data: {"event":"done","data":"","conversation_id":"conv-1"}\n
\n
```

### Edge cases handled

| Scenario | Handling |
|---|---|
| Block split across two TCP chunks | `buffer` accumulates bytes; only complete blocks (ending in `\n\n`) are parsed |
| Missing `event:` line | Defaults to `"message"` |
| Multi-line `data:` value | All `data:` lines joined with `"\n"` before `JSON.parse` |
| Trailing content without final `\n\n` | Flushed after the read loop exits |
| `event` field inside JSON vs SSE `event:` line | JSON field wins (inner `parsed.event ?? eventName`) |

---

## 6. Stream Cleanup Pattern

### Why both `cancel()` and `releaseLock()` are needed

| Step | What it does | Why it matters |
|---|---|---|
| `reader.cancel()` | Signals the browser to abort the HTTP response body | Stops the network transfer and frees the underlying TCP connection |
| `reader.releaseLock()` | Releases the exclusive lock the `ReadableStreamDefaultReader` holds on the `ReadableStream` | Allows the `ReadableStream` object itself to be garbage collected |

Calling `releaseLock()` *before* `cancel()` would abort the cancellation — the lock is required to issue the cancel signal. The correct order is always **cancel first, release second**.

### Why `readerClosed` is needed

`reader.cancel()` is async. If the caller breaks early out of `for await` (e.g., user navigated away), the generator's `finally` block fires immediately. Without the `readerClosed` flag, a second caller into `cancelReader` (from a race or retry) could call `cancel()` on an already-cancelled reader, potentially throwing. The flag makes `cancelReader` idempotent.

---

## 7. Do / Don't

### DO ✅

- **Always iterate via `for await ... of streamBackendChat(payload)`** — the generator owns its own cleanup; you never need to close the reader manually.
- **Set `cache: "no-store"`** on every streaming fetch — browsers may otherwise cache the first response body and serve stale bytes on repeat calls.
- **Use `decoder.decode(value, { stream: true })`** for all chunks except the last — this preserves multi-byte UTF-8 character boundaries across chunk boundaries.
- **Check `event.event === "error"`** and surface it to the user — the generator yields error events rather than throwing, so unchecked loops silently swallow them.
- **Echo `conversation_id` back** on subsequent turns — capture it from the first non-null `BackendStreamEvent.conversation_id` and include it in `BackendChatRequest.conversation_id`.

### DON'T ❌

- **Don't call `reader.releaseLock()` before `reader.cancel()`** — the lock is required to issue the cancel signal; releasing first breaks cleanup.
- **Don't ignore `done` events** — return immediately when `event.event === "done"` to avoid reading stale bytes after the server has logically closed the stream.
- **Don't construct your own `fetch` for `/api/chat/stream`** — always use `streamBackendChat`; ad-hoc callers miss buffer management and cleanup.
- **Don't call `response.text()` or `response.json()` on a streaming response** — they consume the entire body synchronously and break the SSE flow.
- **Don't cache the result of `getBackendBaseUrl()`** across requests — environment variables can be reconfigured between deploys; re-read each time.

---

## 8. Environment Variables

| Variable | Scope | Default | Description |
|---|---|---|---|
| `BACKEND_URL` | Server-only (not exposed to browser) | — | Primary backend base URL. Takes precedence over `NEXT_PUBLIC_BACKEND_URL`. |
| `NEXT_PUBLIC_BACKEND_URL` | Server + browser | — | Fallback backend URL. Exposed to the client bundle — do not put secrets here. |
| `BACKEND_API_KEY` | Server-only | — | Injected as `x-api-key` header. A warning is logged if absent. |

Resolution order: `BACKEND_URL` → `NEXT_PUBLIC_BACKEND_URL` → `http://backend:8000`
