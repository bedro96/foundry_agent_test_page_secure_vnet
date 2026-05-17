---
name: conversation-state
display_name: Conversation State
description: >-
    In-process Map that associates Telegram chat/user/thread scopes with Azure AI Foundry
    conversation IDs for multi-turn conversations across separate webhook invocations.
    Covers key format, upsert semantics, and streaming integration patterns.
user-invocable: true
---

# Skill: Conversation State

**Source:** `frontend/src/lib/conversation-state.ts`

---

## 1. Purpose

An in-process `Map<string, string>` that associates each Telegram chat/user/thread scope with an Azure AI Foundry **conversation ID**, enabling multi-turn conversations across separate webhook invocations.

Each Telegram message arrives as an independent HTTP request with no shared request-level context. This module bridges those invocations by mapping a stable **conversation key** (derived from the Telegram message) to the opaque `conversation_id` returned by the Azure AI Foundry backend. On subsequent messages, the stored ID is re-sent to the backend so it can recover the conversation history and continue the same thread.

---

## 2. When to Use

- When a backend AI service (e.g., Azure AI Foundry / Responses API) issues **persistent conversation IDs** that must be threaded across multiple user messages.
- When Telegram **forum topics / threads** (`message_thread_id`) need **isolated conversation contexts** — users in different topics of the same group should not share a conversation thread.
- When the backend may omit `conversation_id` on some stream events (e.g., intermediate deltas) and the client must preserve the last-known ID.

---

## 3. Conversation Key Format

```
"${chatId}:${userId}:${threadId}"
```

Built by `getConversationKey()` in `bot.ts`:

```ts
function getConversationKey(ctx: Context): string {
  const chatId = String(ctx.chat?.id ?? "unknown");
  const userId = String(ctx.from?.id ?? "unknown");
  const message = ctx.message;
  const threadId =
    message && "message_thread_id" in message
      ? String(message.message_thread_id ?? "root")
      : "root";
  return `${chatId}:${userId}:${threadId}`;
}
```

| Component  | Source                              | Purpose                                                                 |
|------------|-------------------------------------|-------------------------------------------------------------------------|
| `chatId`   | `ctx.chat?.id`                      | Identifies the Telegram chat (group or DM)                              |
| `userId`   | `ctx.from?.id`                      | Isolates conversations per user within a shared group chat              |
| `threadId` | `message.message_thread_id` or `"root"` | Isolates forum topic threads; `"root"` for the main/non-topic chat  |

**Example:** `"123456789:-987654321:root"` — group chat `123456789`, user `-987654321`, main thread.

---

## 4. API Reference

### `getConversationIdForKey(conversationKey: string): string | undefined`

Pure read-only lookup. Returns the stored conversation ID for the given key, or `undefined` if no conversation has been started yet for that scope.

```ts
import { getConversationIdForKey } from "@/lib/conversation-state";

const existingId = getConversationIdForKey("123:456:root");
// → "conv-abc"  (if previously stored)
// → undefined   (if this is the first message for this scope)
```

---

### `rememberConversationId(conversationKey: string, conversationId?: string | null): string | undefined`

Upsert helper used on every stream event. Behaviour depends on `conversationId`:

| `conversationId` value | Behaviour                                               | Return value          |
|------------------------|---------------------------------------------------------|-----------------------|
| Truthy string          | `map.set(key, conversationId)` — stores new/updated ID | The new `conversationId` |
| Falsy (`null` / `undefined` / `""`) | No write; reads existing value from map  | Stored ID or `undefined` |

**Why:** The Foundry backend omits `conversation_id` on many intermediate stream events (e.g., text deltas). By no-op-ing on falsy values, we preserve the last successfully stored ID without overwriting it with `undefined`.

---

### `resetConversationState(): void`

Clears the entire map. Intended for test isolation — call in `beforeEach` to prevent state leaking between test cases.

```ts
import { resetConversationState } from "@/lib/conversation-state";

beforeEach(() => {
  resetConversationState();
});
```

---

## 5. `rememberConversationId` Upsert Semantics

```ts
// First call (new conversation): stores and returns "conv-abc"
rememberConversationId("123:456:root", "conv-abc"); // → "conv-abc"

// Intermediate stream events (no new id): returns stored "conv-abc"
rememberConversationId("123:456:root", null);       // → "conv-abc"
rememberConversationId("123:456:root", undefined);  // → "conv-abc"

// Backend updates conversation (rare): overwrites and returns new id
rememberConversationId("123:456:root", "conv-xyz"); // → "conv-xyz"
```

The function never stores `null` or `undefined` — it only stores truthy strings. This makes it safe to call unconditionally on every stream event without risk of clobbering a valid ID.

---

## 6. Streaming Integration Pattern

`streamTelegramReply` in `bot.ts` calls these functions as follows:

```ts
// Before streaming: seed with the conversation_id from the initial request
// (may be undefined on the very first user message)
let conversationId = rememberConversationId(conversationKey, request.conversation_id);

for await (const event of streamBackendChat(request)) {
  // Each event may carry an updated conversation_id (e.g., after the backend
  // creates a new Foundry conversation). Fall back to the last known value
  // with ?? conversationId so it's never lost even on events with no id.
  conversationId = rememberConversationId(conversationKey, event.conversation_id) ?? conversationId;

  if (event.event === "message") { /* accumulate text */ }
  if (event.event === "error") {
    // The conversation id is preserved on error so the next user turn
    // can recover inside the same Foundry conversation.
  }
}
```

**Key points:**
- `rememberConversationId` is called **before** the loop (to seed from `request.conversation_id`) and on **every event** inside the loop.
- The `?? conversationId` fallback guarantees `conversationId` is never set to `undefined` mid-stream.
- Even mid-stream ID changes (e.g., the backend starts a new conversation after a context reset) are captured immediately.

---

## 7. Lifecycle and Persistence

| Property            | Behaviour                                                                 |
|---------------------|---------------------------------------------------------------------------|
| **Storage**         | Node.js heap — a module-level `Map<string, string>`                       |
| **Scope**           | Single process; shared across all concurrent requests handled by that process |
| **Survives**        | Multiple webhook invocations within the same running server process       |
| **Lost on**         | Process restart, crash, deployment, or OOM kill                          |
| **Multi-instance**  | Each Node.js process has its own independent Map; IDs are NOT shared     |

**Implication:** In a horizontally-scaled deployment (multiple pods / processes), a user whose second message is routed to a different instance will start a brand-new Foundry conversation. For single-instance deployments (e.g., one Telegram bot webhook server), this is fully acceptable.

**Migration path for distributed deployments:** Replace `conversationIdsByChat` with a Redis `HSET`/`HGET` client (or equivalent durable KV store) and make `rememberConversationId` / `getConversationIdForKey` async.

---

## 8. Do / Don't

| | Rule |
|---|---|
| ✅ DO | Call `resetConversationState()` in `beforeEach` (or between test cases) to prevent Map state leaking across tests. |
| ✅ DO | Call `rememberConversationId` on **every** stream event, not just the first one — the backend may issue the `conversation_id` on a later event. |
| ✅ DO | Use the `?? conversationId` fallback pattern when assigning inside a loop to guard against overwriting a valid ID with `undefined`. |
| ✅ DO | Include all three components (`chatId`, `userId`, `threadId`) in the key — omitting `userId` would merge conversations for different users in the same group. |
| ❌ DON'T | Rely on this module for multi-instance / horizontally-scaled deployments — the Map is per-process and not shared. |
| ❌ DON'T | Store conversation **content** (messages, user data) here — only opaque keys and IDs belong in this module. |
| ❌ DON'T | Call `resetConversationState()` in production code paths — it clears all active conversation contexts globally. |
| ❌ DON'T | Construct conversation keys manually outside of `getConversationKey()` — centralise key construction to avoid format drift. |
