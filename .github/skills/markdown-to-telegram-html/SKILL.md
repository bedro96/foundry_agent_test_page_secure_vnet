---
name: markdown-to-telegram-html
display_name: Markdown to Telegram Bot HTML
description: >-
    Convert AI-generated Markdown to the Telegram Bot HTML subset using marked with a
    custom Renderer. Handles inline pattern post-processing, URL sanitization, code block
    passthrough, and the hasRawMarkdown() pre-check heuristic.
user-invocable: true
---

# Skill: Markdown → Telegram Bot HTML

> Source of truth: `frontend/src/lib/markdown.ts`

---

## 1. Purpose

Convert AI-generated Markdown to the **Telegram Bot HTML subset** so it can be
sent via `sendMessage` / `editMessageText` with `parse_mode: "HTML"`.

Telegram supports only a small whitelist of HTML tags. This module:

1. Runs `marked` with a custom `Renderer` that emits only whitelisted tags.
2. Post-processes the resulting HTML string to catch **inline patterns** that
   `marked` leaves unconverted in flowing text (e.g., `**bold**` adjacent to
   non-ASCII characters or inside sentence fragments that the block parser
   does not recognise as standalone paragraphs).
3. Sanitizes every URL to prevent `javascript:` or other dangerous schemes
   from reaching Telegram's clickable `<a>` renderer.

---

## 2. When to Use

| Situation | Action |
|---|---|
| Sending an AI response verbatim | Always call `markdownToTelegramHtml()` |
| Short status message with no markup | Skip conversion — pass plain text |
| Deciding at runtime whether HTML is needed | Call `hasRawMarkdown(text)` first; only convert when it returns `true` |
| Storing or logging the raw model output | Keep raw Markdown; convert only at send time |

**Rule of thumb**: any string that may arrive from an LLM or be written by a
human using Markdown conventions should pass through this module before being
handed to the Telegram Bot API.

---

## 3. Telegram HTML Subset

Telegram's Bot API `parse_mode: "HTML"` supports only the following tags.
Every other tag is stripped or causes a parse error.

| Telegram Tag | Markdown Equivalent | Renderer Method |
|---|---|---|
| `<b>text</b>` | `**bold**` | `renderer.strong` |
| `<i>text</i>` | `*italic*` | `renderer.em` |
| `<s>text</s>` | `~~strikethrough~~` | `renderer.del` |
| `<code>text</code>` | `` `inline code` `` | `renderer.codespan` |
| `<pre>text</pre>` | ` ```block``` ` | `renderer.code` |
| `<a href="url">text</a>` | `[text](url)` / `![alt](url)` | `renderer.link` / `renderer.image` |

> **Images** have no visual equivalent in Telegram messages, so `renderer.image`
> falls back to `<a href="url">alt text</a>`.

---

## 4. Key Concepts

### 4.1 `createTelegramRenderer()`

A factory that returns a fully configured `marked` `Renderer` instance. Every
method maps one Markdown AST token to a valid Telegram HTML string.

```typescript
// Inline token → wrapping tag
renderer.strong = ({ tokens }) => `<b>${this.parser.parseInline(tokens)}</b>`;
renderer.em     = ({ tokens }) => `<i>${this.parser.parseInline(tokens)}</i>`;
renderer.del    = ({ tokens }) => `<s>${this.parser.parseInline(tokens)}</s>`;
renderer.codespan = ({ text }) => `<code>${escapeHtml(text)}</code>`;

// Block token → escaped content
renderer.code = ({ text, lang }) => {
  const escaped = escapeHtml(text);
  return lang
    ? `<pre><code class="language-${lang}">${escaped}</code></pre>\n`
    : `<pre>${escaped}</pre>\n`;
};

// Links and images — URL sanitized before embedding
renderer.link  = ({ href, tokens }) => { /* safeHref check */ };
renderer.image = ({ href, text })   => { /* safeHref check */ };

// Block elements that have no direct Telegram equivalent
renderer.paragraph  = ({ tokens }) => `${inner}\n\n`;      // no wrapping tag
renderer.heading    = ({ tokens }) => `<b>${inner}</b>\n\n`; // all levels → bold
renderer.listitem   = (item)       => `• ${inner}\n`;        // bullet character
renderer.list       = (token)      => `${items}\n`;          // items joined
renderer.blockquote = ({ tokens }) => `<i>${inner.trim()}</i>\n`; // italicised
renderer.table      = (token)      => /* TSV: tabs + newlines */;
renderer.br         = ()           => "\n";
renderer.hr         = ()           => "───────────────\n";
```

**Key design decisions**:

- `paragraph` emits the inner content directly with trailing `\n\n` instead of
  wrapping in `<p>` (not supported by Telegram).
- All heading levels (`#`, `##`, …) collapse to `<b>` — Telegram has no
  heading hierarchy.
- Lists use the Unicode bullet `•` instead of `<ul>/<li>`.
- Tables become TSV because Telegram has no table tag.

---

### 4.2 `postProcessHtml(html)`

A character-by-character post-processor applied **after** `marked` has run.

```typescript
function postProcessHtml(html: string): string {
  const parts: string[] = [];
  let i = 0;
  while (i < html.length) {
    if (html[i] === '<') {
      // ① <pre> or <code> block — copy verbatim, do NOT touch content
      const blockMatch = html.slice(i).match(
        /^<(pre|code)(\s[^>]*)?>[\s\S]*?<\/\1>/i
      );
      if (blockMatch) {
        parts.push(blockMatch[0]);
        i += blockMatch[0].length;
        continue;
      }
      // ② Any other tag — pass through unchanged
      const tagEnd = html.indexOf('>', i);
      parts.push(tagEnd === -1 ? html.slice(i) : html.slice(i, tagEnd + 1));
      i = tagEnd === -1 ? html.length : tagEnd + 1;
    } else {
      // ③ Plain text segment between tags — run inline fixups
      const nextTag = html.indexOf('<', i);
      const segment = nextTag === -1 ? html.slice(i) : html.slice(i, nextTag);
      parts.push(fixInlineMarkdown(segment));
      i = nextTag === -1 ? html.length : nextTag;
    }
  }
  return parts.join('');
}
```

**Why this step is needed**: `marked`'s block parser sometimes leaves inline
Markdown patterns untouched when they appear adjacent to non-ASCII characters,
mid-sentence, or inside table cells. `postProcessHtml` ensures those surviving
`**...**` / `*...*` patterns are converted to `<b>`/`<i>` without corrupting
already-rendered HTML tags.

---

### 4.3 `fixInlineMarkdown(text)`

Applies three sequential regex replacements to **text-only segments** (never
called inside HTML tags or code blocks):

```typescript
function fixInlineMarkdown(text: string): string {
  // 1. Bold: **text** — /gs allows content to span newlines
  let result = text.replace(/\*\*([^*]+?)\*\*/gs, '<b>$1</b>');

  // 2. Italic: *text* — negative lookahead/lookbehind excludes **
  result = result.replace(/(?<!\*)\*([^*\n]+?)\*(?!\*)/g, '<i>$1</i>');

  // 3. Markdown links [text](https://…) — URL sanitized inline
  result = result.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    (_m, linkText, href) => {
      const safeHref = sanitizeTelegramHref(href);
      if (!safeHref) return escapeHtml(linkText);
      return `<a href="${safeHref}">${escapeHtml(linkText)}</a>`;
    },
  );
  return result;
}
```

Order matters: bold (`**`) must be replaced before italic (`*`) to prevent the
single-asterisk pattern from matching half of a bold marker.

---

### 4.4 `sanitizeTelegramHref(href)`

Validates a URL before embedding it in `href="…"`.

```typescript
function sanitizeTelegramHref(href?: string | null): string | null {
  const trimmedHref = href?.trim();
  if (!trimmedHref) return null;
  if (/^(https?:\/\/|tg:\/\/)/i.test(trimmedHref)) {
    return escapeHtmlAttribute(trimmedHref);   // safe to embed
  }
  return null;   // reject everything else (javascript:, data:, etc.)
}
```

**Allowed schemes**: `http://`, `https://`, `tg://` (Telegram deep links).  
**Rejected**: `javascript:`, `data:`, `vbscript:`, relative paths, bare
hostnames — all return `null`, and callers fall back to plain link text.

---

### 4.5 `escapeHtml()` and `escapeHtmlAttribute()`

Minimal HTML escape helpers used whenever untrusted content is embedded in
HTML output:

```typescript
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeHtmlAttribute(text: string): string {
  return escapeHtml(text).replace(/"/g, "&quot;");
}
```

`escapeHtmlAttribute` is used for `href` values; `escapeHtml` for text content
inside tags.

---

### 4.6 `hasRawMarkdown(text)`

Lightweight pre-check — returns `true` when the string contains patterns that
`markdownToTelegramHtml` would convert:

```typescript
export function hasRawMarkdown(text: string): boolean {
  return (
    /\*\*[^*]+\*\*/.test(text) ||               // **bold**
    /(?<!\*)\*[^*\n]+\*(?!\*)/.test(text) ||     // *italic*
    /\[[^\]]+\]\(https?:\/\/[^)]+\)/.test(text)  // [text](url)
  );
}
```

Use this to avoid the overhead of a full `marked` parse when the text is
almost certainly plain text (e.g., short status messages).

---

### 4.7 Module-level Singleton

```typescript
const telegramMarked = new Marked({
  renderer: createTelegramRenderer(),
  async: false,
});
```

The `Marked` instance is created **once at module load time** and reused for
every call to `markdownToTelegramHtml()`. This avoids the overhead of
constructing a new renderer on every invocation.  
`async: false` is required because callers use the synchronous `parse()` API.

---

### 4.8 Public Entry Point

```typescript
export function markdownToTelegramHtml(markdown: string): string {
  if (!markdown.trim()) return markdown;           // fast-path empty strings
  const html = telegramMarked.parse(markdown) as string;
  return postProcessHtml(html).trim();
}
```

The `.trim()` at the end removes the trailing `\n\n` that block-level renderers
append to the last paragraph so Telegram messages have no leading/trailing
whitespace.

---

## 5. Code Block Safety

`postProcessHtml` detects `<pre>` and `<code>` blocks with a regex and **copies
them verbatim** into the output, skipping the `fixInlineMarkdown` call entirely
for their content.

**Why this matters**: code blocks routinely contain `**`, `*`, and `[...](...)`
patterns that are part of the program text, not Markdown formatting. Running
`fixInlineMarkdown` inside them would corrupt the code:

```
// source code (inside a fenced block)
const bold = text.replace(/\*\*([^*]+?)\*\*/gs, '<b>$1</b>');
//                        ^^ these stars must NOT become <b> tags
```

The same applies to inline `<code>` spans. The renderer's `codespan` method
calls `escapeHtml()` on the raw content, and `postProcessHtml` then treats the
resulting `<code>…</code>` as a tag to pass through, so inline fixups never
reach code content.

---

## 6. Do / Don't

### DO ✅

| Rule | Reason |
|---|---|
| Call `hasRawMarkdown(text)` before deciding to convert | Avoids a full `marked` parse for plain-text messages |
| Call `escapeHtml()` on any user-controlled string you insert directly into HTML | Prevents `<` / `>` from breaking the tag structure |
| Call `escapeHtmlAttribute()` when embedding values in `href="…"` | Prevents `"` from breaking out of the attribute |
| Use `sanitizeTelegramHref()` for every URL, whether from `marked` or `fixInlineMarkdown` | Blocks `javascript:` and other dangerous schemes |
| Keep `async: false` on the `Marked` singleton | `markdownToTelegramHtml` is synchronous; mixing async breaks the cast |

### DON'T ❌

| Rule | Reason |
|---|---|
| Don't emit HTML tags not in the Telegram whitelist (e.g., `<div>`, `<span>`, `<h1>`, `<ul>`, `<li>`, `<p>`) | Telegram strips unknown tags, silently breaking layout |
| Don't skip URL sanitization for "known safe" sources | LLM output can include adversarial URLs; always sanitize |
| Don't call `fixInlineMarkdown` on already-parsed HTML | It would double-convert content already wrapped in `<b>` / `<i>` |
| Don't set `async: true` on the `Marked` instance | Breaks the synchronous `parse()` call in `markdownToTelegramHtml` |
| Don't create a new `Marked` instance per call | Renderer construction is not free; use the module singleton |

---

## 7. Extension Points

### Adding a new Markdown element

1. **Identify the `marked` token type** — consult the
   [marked Renderer docs](https://marked.js.org/using_pro#renderer) for the
   method name and token shape.

2. **Check the Telegram HTML whitelist** — if the desired visual effect maps to
   `<b>`, `<i>`, `<s>`, `<code>`, `<pre>`, or `<a>`, proceed. If not, choose
   the closest supported tag or fall back to plain text.

3. **Override the renderer method** inside `createTelegramRenderer()`:

   ```typescript
   // Example: render <mark>highlight</mark> as <b> (closest available)
   renderer.mark = function ({ tokens }: Tokens.Mark): string {
     const inner = this.parser.parseInline(tokens);
     return `<b>${inner}</b>`;
   };
   ```

4. **Escape content** with `escapeHtml()` for text content, or
   `escapeHtmlAttribute()` for attribute values.

5. **If the new pattern also appears inline** (i.e., `marked`'s block parser may
   miss it), add a regex to `fixInlineMarkdown()` following the same bold/italic
   pattern — ensure it runs *before* any overlapping patterns.

6. **Update `hasRawMarkdown()`** if the new pattern should count as "raw
   Markdown" for the pre-check heuristic.

7. **Write a unit test** covering:
   - Happy path: pattern converted correctly
   - Edge case: pattern inside a `<pre>` block (must be left unchanged)
   - Failure path: malformed pattern emits safe plain text, not broken HTML
