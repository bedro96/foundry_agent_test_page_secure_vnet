---
name: next-test
display_name: Next.js / TypeScript Frontend Testing Guide
description: >-
    Frontend testing guide using Node.js built-in node:test and node:assert/strict with
    experimental-strip-types. Covers SSE stream testing, fetch mocking, Telegram context
    fixtures, Sharp integration tests, and conversation state isolation patterns.
user-invocable: true
---

# Next.js / TypeScript Frontend — Testing Guide

> **Living document.** Update this file whenever a new module or test pattern is added.

---

## 1. Overview

### Testing stack

| Concern | Tool |
|---|---|
| Test runner | Node.js built-in `node:test` |
| Assertion | Node.js built-in `node:assert/strict` |
| TypeScript | `--experimental-strip-types` (no compilation step) |
| Image fixtures | `sharp` (real dependency, no mock) |
| HTTP | `global.fetch` override (no mock library) |

**No Jest. No Vitest. No ts-jest. No test framework at all beyond `node:test`.**

### Run commands

```bash
# Run all tests
node --test --experimental-strip-types tests/*.test.ts

# Type-check + bundle (catches TS errors the test runner doesn't)
npm run build
```

### Key dependencies (from `package.json`)

```json
{
  "dependencies": {
    "marked": "^17.0.5",
    "next": "16.2.3",
    "react": "19.2.4",
    "react-dom": "19.2.4",
    "sharp": "^0.34.5",
    "telegraf": "^4.16.3"
  },
  "devDependencies": {
    "@types/node": "^22.13.14",
    "typescript": "^5.8.2"
  }
}
```

`sharp` is a real production dependency used in image tests — **do not mock it**.

---

## 2. What To Test (organised by module)

### `lib/backend.ts` — `streamBackendChat`

`streamBackendChat` is an async generator that reads a Server-Sent Events (SSE) stream and yields parsed event objects.

| Scenario | Key assertions |
|---|---|
| **Happy path** | All events yielded in order; `reader.cancel()` + `reader.releaseLock()` each called exactly once after `done` event |
| **Split SSE chunk** | SSE block split across two network reads → still parsed and yielded correctly; reader closed once |
| **Malformed JSON payload** | Incomplete JSON object in `data:` line → `assert.rejects`; reader closed exactly once |
| **Non-JSON data field** | `data: not-json-at-all` → `assert.rejects`; reader closed exactly once |
| **HTTP failure (503, `ok: false`)** | Throws with `/Backend request failed with status 503/`; reader **NOT** cancelled (body is `null`) → cancel = 0, releaseLock = 0 |

**Reader cleanup is non-negotiable.** Every error path must still call `cancel` and `releaseLock` unless the body itself is null.

---

### `lib/backend.ts` — `transcribeBackendAudio`

`transcribeBackendAudio` sends audio as base64 to the backend and returns `{ text, language }`.

| Scenario | Key assertions |
|---|---|
| **Happy path** | Returns `{ text, language }` matching backend JSON |
| **Backend error with `detail`** | `ok: false`, JSON has `{ detail: "..." }` → throws with that detail string |
| **Empty/whitespace transcript** | `ok: true`, `text: "   "` → throws matching `/empty text/` |

---

### `lib/conversation-state.ts`

| Scenario | Key assertions |
|---|---|
| **`null` / `undefined` new ID** | `rememberConversationId(key, undefined)` returns existing stored ID unchanged |
| **New ID provided** | `rememberConversationId(key, "conv-new")` stores and returns it; `getConversationIdForKey(key)` confirms |

**`resetConversationState()` must be called at the top of every test** — the module stores state in module-level variables that survive between test runs.

---

### `lib/markdown.ts`

`markdownToTelegramHtml` converts Markdown to the HTML subset accepted by Telegram's Bot API.

| Scenario | Key assertions |
|---|---|
| **Bold adjacent to Korean/CJK** | `한국어**text**` and `**text**이다` → both produce `<b>text</b>` |
| **Bold adjacent to punctuation** | `-**item**` and `• **item**` → `<b>item</b>` |
| **Normal bold** | `**bold**` → `<b>bold</b>` |
| **Normal italic** | `*italic*` → `<i>italic</i>` |
| **Markdown link** | `[here](https://example.com)` → `<a href="https://example.com">here</a>` |
| **Loose list items** | `- item1\n\n- item2` → no raw `**` in output; both items present |
| **Code block passthrough** | ` ```\n**not bold**\n``` ` → `**not bold**` preserved verbatim; `<b>` absent |

`hasRawMarkdown()` detection:

| Input | Expected |
|---|---|
| `**bold**` | `true` |
| `*italic*` | `true` |
| `[text](https://example.com)` | `true` |
| `plain text` | `false` |
| `<b>already bold</b>` | `false` |

---

### `lib/telegram-image.ts`

`prepareTelegramImageForAzure` ensures images are within Azure AI Vision's size limits.
Constants: `AZURE_AI_VISION_MAX_INPUT_BYTES` (hard input cap), `AZURE_AI_VISION_TARGET_MAX_BYTES` (≤ 40 KB output target).

| Scenario | Key assertions |
|---|---|
| **Already-safe JPEG (≤ 40 KB)** | `resized: false`; `outputBytes === source.length`; `buffer` identical to input |
| **Large noisy image (1024×1024, quality 92)** | `resized: true`; `outputBytes ≤ AZURE_AI_VISION_TARGET_MAX_BYTES`; output is valid JPEG with positive dimensions |
| **Oversized input (> `MAX_INPUT_BYTES`)** | Throws matching `/Image file is too large/` before any processing |
| **Empty buffer** | Throws matching `/Image file is empty/` |

These are **integration tests** — they exercise actual Sharp compression. Use real `sharp` to create fixture images.

---

### `lib/telegram-message.ts` — `editTelegramMessageWithMarkdownFallback`

This function implements a three-tier fallback: HTML edit → plain-text edit → `ctx.reply`.

| Scenario | `edited` | `editCalls.length` | `replyCalls` |
|---|---|---|---|
| **Markdown link → HTML `<a>` tag** | `true` | 1 (HTML) | `[]` |
| **`javascript:` link stripped** | `true` | 1 (HTML, stripped to text) | `[]` |
| **HTML edit succeeds** | `true` | 1 (HTML) | `[]` |
| **"message is not modified" error** | `true` | 1 (HTML) | `[]` — treated as success, no plain-text fallback |
| **HTML edit fails → plain-text fallback** | `true` | 2 (HTML + plain) | `[]` |
| **Both fail + `replyOnFailure: true` (default)** | `true` | 2 | `["**bold**"]` |
| **Both fail + `replyOnFailure: false`** | `false` | 2 | `[]` |
| **`allowPlainTextFallback: false` + HTML fails + `replyOnFailure: false`** | `false` | 1 (HTML only) | `[]` |
| **`ctx.chat` is `undefined` + `replyOnFailure: true`** | `true` | 0 | `["**bold**"]` |
| **`ctx.chat` is `undefined` + `replyOnFailure: false`** | `false` | 0 | `[]` |

Security: only `https://`, `http://`, and `tg://` URL schemes are allowed; `javascript:` is stripped, leaving only the link text.

---

## 3. How To Test (patterns with code examples)

### Basic test structure

```ts
import test from "node:test";
import assert from "node:assert/strict";

test("description of expected behaviour", async () => {
  // arrange
  const input = "**bold**";

  // act
  const result = markdownToTelegramHtml(input);

  // assert
  assert.match(result, /<b>bold<\/b>/);
});
```

---

### `global.fetch` override — save, replace, restore in `finally`

Always restore in `finally` to prevent test pollution even when assertions throw.

```ts
test("transcribeBackendAudio returns parsed text from the backend", async () => {
  const originalFetch = global.fetch;
  global.fetch = (async () =>
    ({
      ok: true,
      status: 200,
      async json() {
        return { text: "안녕하세요", language: "ko-KR" };
      },
    }) as Response) as typeof fetch;

  try {
    const result = await transcribeBackendAudio({
      audio_base64: Buffer.from("voice").toString("base64"),
      mime_type: "audio/ogg",
      file_name: "voice.oga",
      language: "ko-KR",
    });
    assert.deepEqual(result, { text: "안녕하세요", language: "ko-KR" });
  } finally {
    global.fetch = originalFetch;
  }
});
```

---

### `createMockFetch` — streaming SSE with chunk control and cleanup counters

Use a `counters` object **passed by reference** so the mock can mutate it:

```ts
type ReaderResult = { done: boolean; value?: Uint8Array };

function createMockFetch(
  chunks: Array<string | ReaderResult>,
  counters: { cancelCalls: number; releaseLockCalls: number },
  responseOverrides: Partial<Pick<Response, "ok" | "status" | "body">> = {},
): typeof fetch {
  return (async (_input: RequestInfo | URL, _init?: RequestInit) =>
    ({
      ok: true,
      status: 200,
      body: {
        getReader() {
          return {
            async read(): Promise<ReaderResult> {
              const nextChunk = chunks.shift();
              if (!nextChunk) return { done: true };
              if (typeof nextChunk === "string") {
                return { done: false, value: new TextEncoder().encode(nextChunk) };
              }
              return nextChunk;
            },
            async cancel(): Promise<void> { counters.cancelCalls += 1; },
            releaseLock(): void { counters.releaseLockCalls += 1; },
          };
        },
      },
      ...responseOverrides,
    }) as Response) as typeof fetch;
}
```

Usage:

```ts
test("streamBackendChat closes the SSE reader after a done event", async () => {
  const originalFetch = global.fetch;
  const counters = { cancelCalls: 0, releaseLockCalls: 0 };
  global.fetch = createMockFetch(
    [
      'event: status\ndata: {"event":"status","data":"Connecting","conversation_id":"conv-1"}\n\n',
      'event: done\ndata: {"event":"done","data":"complete","conversation_id":"conv-1"}\n\n',
    ],
    counters,
  );

  try {
    const events = [];
    for await (const event of streamBackendChat({ messages: [{ role: "user", content: "hello" }] })) {
      events.push(event);
    }
    assert.deepEqual(events, [
      { event: "status", data: "Connecting", conversation_id: "conv-1" },
      { event: "done", data: "complete", conversation_id: "conv-1" },
    ]);
    assert.equal(counters.cancelCalls, 1);     // must be cleaned up
    assert.equal(counters.releaseLockCalls, 1);
  } finally {
    global.fetch = originalFetch;
  }
});
```

---

### Assert async rejection

```ts
await assert.rejects(
  async () => {
    for await (const _event of streamBackendChat(req)) { /* consume */ }
  },
  /Backend request failed with status 503/,
);
```

For a rejection without a specific message check:

```ts
await assert.rejects(async () => {
  for await (const _event of streamBackendChat(req)) {}
});
```

---

### Telegram context fixture — minimal, no Telegraf import

```ts
type EditCall = {
  chatId: number | string;
  messageId: number;
  text: string;
  extra?: { parse_mode: "HTML" };
};

function createContext(
  editImplementation: (call: EditCall) => Promise<unknown>,
  options?: { chatId?: number | string; withChat?: boolean },
) {
  const chatId = options && "chatId" in options ? options.chatId : 123;
  const withChat = options?.withChat ?? true;
  const editCalls: EditCall[] = [];
  const replyCalls: string[] = [];

  return {
    ctx: {
      chat: withChat ? { id: chatId ?? 123 } : undefined,
      reply: async (text: string) => { replyCalls.push(text); },
      telegram: {
        editMessageText: async (
          nextChatId: number | string,
          messageId: number,
          _inlineMessageId: undefined,
          text: string,
          extra?: { parse_mode: "HTML" },
        ) => {
          const call = { chatId: nextChatId, messageId, text, extra };
          editCalls.push(call);
          return editImplementation(call);
        },
      },
    },
    editCalls,
    replyCalls,
  };
}
```

Capture `editCalls` and `replyCalls` for assertion after the function under test returns:

```ts
test("falls back to plain text when HTML edit fails", async () => {
  let attempts = 0;
  const { ctx, editCalls, replyCalls } = createContext(async () => {
    attempts += 1;
    if (attempts === 1) throw new Error("HTML parse failed");
  });

  const edited = await editTelegramMessageWithMarkdownFallback(ctx, 77, "**bold**");

  assert.equal(edited, true);
  assert.equal(editCalls.length, 2);
  assert.equal(editCalls[0]?.extra?.parse_mode, "HTML");
  assert.equal(editCalls[1]?.extra, undefined); // plain text, no parse_mode
  assert.deepEqual(replyCalls, []);
});
```

---

### Sharp real image tests — no mocking

Create fixture images using Sharp directly:

```ts
import sharp from "sharp";

// Solid-colour JPEG (small, well below 40 KB)
const smallJpeg = await sharp({
  create: { width: 128, height: 128, channels: 3, background: { r: 240, g: 200, b: 160 } },
})
  .jpeg({ quality: 80 })
  .toBuffer();

// High-entropy noise JPEG (large, forces compression)
function createNoiseBuffer(width: number, height: number): Buffer {
  const buffer = Buffer.allocUnsafe(width * height * 3);
  for (let i = 0; i < buffer.length; i++) buffer[i] = Math.floor(Math.random() * 256);
  return buffer;
}

const largeJpeg = await sharp(createNoiseBuffer(1024, 1024), {
  raw: { width: 1024, height: 1024, channels: 3 },
})
  .jpeg({ quality: 92 })
  .toBuffer();
```

Assert output is valid JPEG with readable metadata:

```ts
const metadata = await sharp(prepared.buffer).metadata();
assert.equal(metadata.format, "jpeg");
assert.ok((metadata.width ?? 0) > 0);
assert.ok((metadata.height ?? 0) > 0);
```

---

### Conversation state isolation

```ts
import { resetConversationState } from "../src/lib/conversation-state.ts";

test("stores a new conversation id", () => {
  resetConversationState(); // always call first — module state persists between tests
  const stored = rememberConversationId("22222:33333:root", "conv-new");
  assert.equal(stored, "conv-new");
});
```

---

### Call-count tracking without a spy library

Use a closure variable instead of `sinon.spy` or similar:

```ts
let attempts = 0;
const { ctx } = createContext(async (call) => {
  attempts += 1;
  if (call.extra?.parse_mode === "HTML") {
    throw new Error("message is not modified: ...");
  }
});

await editTelegramMessageWithMarkdownFallback(ctx, 42, "**bold**");

assert.equal(attempts, 1); // only the HTML branch ran
```

---

## 4. Test Coverage Checklist

Use this checklist when adding a new module or new code path:

- [ ] **Happy path** — normal inputs produce correct outputs
- [ ] **Edge cases** — empty strings, `null`/`undefined` IDs, zero-length buffers, whitespace-only strings
- [ ] **Failure paths** — HTTP errors, parse errors, oversized inputs, network failures
- [ ] **Stream cleanup** — `reader.cancel()` and `reader.releaseLock()` always called (even on error); verify via `counters`
- [ ] **State isolation** — `resetConversationState()` called at the start of each conversation-state test
- [ ] **Fallback chains** — every branch of the HTML edit → plain-text edit → reply chain is exercised
- [ ] **Security** — unsafe URL schemes (`javascript:`, `data:`, `vbscript:`) are stripped; only `https?://` and `tg://` pass through
- [ ] **Content safety** — content inside code blocks (` ``` `) passes through unchanged; Markdown patterns inside `<pre>` are not converted
- [ ] **`global.fetch` restoration** — `finally` block restores original fetch after every test that overrides it

---

## 5. Mock Strategy

### `global.fetch` override

```
const orig = global.fetch;
global.fetch = myMock;
try { ... } finally { global.fetch = orig; }
```

- Always use `try/finally` — never rely on assertion success.
- Type the cast as `... as typeof fetch` to satisfy TypeScript without a mock library.

### `createMockFetch` with counters

- Pass a `counters` object **by reference** so the mock closure mutates the same object the test reads.
- Use `chunks.shift()` to simulate sequential network reads, including split SSE blocks.
- Use `responseOverrides` to inject `ok: false`, custom `status`, or `body: null` for HTTP failure tests.

### `createContext` for Telegram

- Use closures (`editCalls`, `replyCalls`) to capture side effects.
- Accept an `editImplementation` callback so individual tests control success/failure/call-counting.
- Set `withChat: false` to simulate the `ctx.chat === undefined` branch.

### Sharp — real integration

- **Do not mock `sharp`.**  These tests verify that actual JPEG compression produces valid output below the threshold.
- Use `createNoiseBuffer` (random pixel data) to ensure the encoder cannot achieve trivial compression — forces the resize path.

### No spy/stub libraries

Track call counts with a plain `let attempts = 0` closure variable and conditional `throw` inside the `editImplementation` callback.  This is sufficient for all current test patterns without introducing a dependency on `sinon`, `jest.fn()`, or similar.
