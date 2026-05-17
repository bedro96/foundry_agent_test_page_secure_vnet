---
name: pydantic-request-models
display_name: Pydantic Request Models
description: >-
    Type-safe API request/response modeling with Pydantic v2. Covers multimodal content
    (text + images), discriminated unions for polymorphic payloads, cross-field validation,
    streaming event shapes, and legacy client compatibility.
user-invocable: true
---

# Skill: Pydantic Request Models

## 1. Purpose

Type-safe API request/response modeling with **Pydantic v2**.  
Covers multimodal content (text + images), discriminated unions for polymorphic payloads, cross-field validation, and streaming event shapes.

Canonical source: `backend/app/models.py`

---

## 2. When to Use

Use this skill when you need to:

- Model API request/response payloads with strict runtime validation
- Accept **polymorphic content** (e.g., text or image parts in one field) via discriminated unions
- Support **legacy client formats** alongside new formats without breaking changes
- Validate cross-field constraints (e.g., "content must not be empty string or empty list")
- Define streaming event envelopes with a fixed set of event types

---

## 3. Key Concepts

### 3.1 `Literal` Type as Discriminator

Use `Literal` to tag each variant of a union so Pydantic can pick the right model during parsing.

```python
from typing import Literal
from pydantic import BaseModel, Field

class TextContentPart(BaseModel):
    type: Literal["input_text"] = "input_text"   # discriminator + default
    text: str = Field(min_length=1)

class LegacyTextContentPart(BaseModel):
    type: Literal["text"] = "text"
    text: str = Field(min_length=1)
```

The default value means serialized output includes `type` automatically.  
Pydantic uses `type` to route incoming JSON to the correct model.

---

### 3.2 `Union` of Content Parts

```python
from typing import Union

ContentPart = Union[
    TextContentPart,
    LegacyTextContentPart,
    ImageUrlContentPart,
    LegacyImageUrlContentPart,
]
```

A single `list[ContentPart]` field accepts **mixed part types** in one message, enabling multimodal payloads.

---

### 3.3 Legacy Compatibility — Nested Detail Object

Some clients send images with a nested object instead of a flat URL string.  
Model the nested structure explicitly rather than coercing it:

```python
class LegacyImageUrlDetail(BaseModel):
    url: str  # data:image/jpeg;base64,... or https URL

class LegacyImageUrlContentPart(BaseModel):
    type: Literal["image_url"] = "image_url"
    image_url: LegacyImageUrlDetail          # nested, unlike ImageUrlContentPart
```

Modern equivalent (flat):

```python
class ImageUrlContentPart(BaseModel):
    type: Literal["input_image"] = "input_image"
    image_url: str                           # flat URL or data URI
    detail: Literal["low", "high", "auto", "original"] = "auto"
```

---

### 3.4 `@field_validator` for Cross-Field / Type-Dependent Validation

Use `@field_validator` when validation logic depends on the **runtime type** of a value, or when `Field(...)` constraints alone cannot express the rule.

```python
from pydantic import field_validator

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"] = "user"
    content: Union[str, list[ContentPart]] = Field(...)

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: Union[str, list]) -> Union[str, list]:
        if isinstance(v, str) and not v.strip():
            raise ValueError("content must not be empty")
        if isinstance(v, list) and len(v) == 0:
            raise ValueError("content list must not be empty")
        return v
```

> `Field(min_length=1)` only applies to `str`; it cannot guard an empty `list[ContentPart]`.  
> `@field_validator` handles both branches in one place.

---

### 3.5 `Field(min_length=1)` for Inline String Constraints

For simple string fields, express constraints inline:

```python
audio_base64: str = Field(min_length=1)
mime_type: str = Field(min_length=1)
language: str = Field(default="ko-KR", min_length=2)
```

Prefer `Field` constraints over validators for single-type, single-rule cases — it's shorter and self-documenting in the schema.

---

### 3.6 Optional Fields with `str | None = None`

Use the union shorthand (Python 3.10+) for nullable optionals:

```python
conversation_id: str | None = None
metadata: dict[str, str] | None = None
file_name: str | None = None
```

---

### 3.7 `ChatRequest` — Top-Level Request Envelope

```python
class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)   # at least one message
    conversation_id: str | None = None                  # reuse existing conversation
    metadata: dict[str, str] | None = None              # arbitrary key-value context
```

---

### 3.8 `ChatStreamEvent` — Streaming Response Envelope

```python
class ChatStreamEvent(BaseModel):
    event: Literal["status", "message", "error", "done"]
    data: str
    conversation_id: str | None = None
```

`event` is a closed enum via `Literal`; adding a new event type is a deliberate, explicit change.

---

### 3.9 `TranscriptionRequest` / `TranscriptionResponse`

```python
class TranscriptionRequest(BaseModel):
    audio_base64: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    file_name: str | None = None
    language: str = Field(default="ko-KR", min_length=2)

class TranscriptionResponse(BaseModel):
    text: str
    language: str
```

---

### 3.10 `HealthResponse` — Sentinel Status Field

```python
class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"   # always "ok" when alive; presence proves health
    app_name: str
    environment: str
```

Using `Literal["ok"]` means any other value is a validation error — the field is self-validating.

---

## 4. Multimodal Content Model

| Class | `type` discriminator | Key fields | Format |
|---|---|---|---|
| `TextContentPart` | `"input_text"` | `text: str` | Modern |
| `LegacyTextContentPart` | `"text"` | `text: str` | Legacy |
| `ImageUrlContentPart` | `"input_image"` | `image_url: str`, `detail` | Modern (flat) |
| `LegacyImageUrlContentPart` | `"image_url"` | `image_url: LegacyImageUrlDetail` | Legacy (nested) |

**`ImageUrlContentPart.detail` values:**

| Value | Meaning |
|---|---|
| `"low"` | Low-res token budget |
| `"high"` | High-res tile processing |
| `"auto"` | Model decides |
| `"original"` | Pass image as-is |

**Example multimodal message payload:**

```json
{
  "role": "user",
  "content": [
    { "type": "input_text", "text": "What is in this image?" },
    { "type": "input_image", "image_url": "data:image/jpeg;base64,/9j/...", "detail": "auto" }
  ]
}
```

---

## 5. Validation Patterns

### When to use `Field` constraints

- Single-type fields with simple bounds: `min_length`, `max_length`, `gt`, `ge`, `lt`, `le`, `pattern`
- Self-documenting, appears in JSON Schema / OpenAPI output automatically

```python
text: str = Field(min_length=1)
language: str = Field(default="ko-KR", min_length=2)
messages: list[ChatMessage] = Field(min_length=1)
```

### When to use `@field_validator`

- Value is a `Union` type and logic differs per branch
- Validation requires calling `.strip()` or other runtime methods
- Cross-field dependency (use `model_validator` for multi-field)

```python
@field_validator("content")
@classmethod
def content_not_empty(cls, v: Union[str, list]) -> Union[str, list]:
    if isinstance(v, str) and not v.strip():
        raise ValueError("content must not be empty")
    if isinstance(v, list) and len(v) == 0:
        raise ValueError("content list must not be empty")
    return v
```

### `model_validator` (when you need multiple fields)

```python
from pydantic import model_validator

class MyModel(BaseModel):
    start: int
    end: int

    @model_validator(mode="after")
    def start_before_end(self) -> "MyModel":
        if self.start >= self.end:
            raise ValueError("start must be less than end")
        return self
```

---

## 6. Do / Don't

| ✅ DO | ❌ DON'T |
|---|---|
| Use `Literal["value"] = "value"` as both discriminator and default | Use plain `str` for type tags — no discrimination, no schema docs |
| Define `Union[ModelA, ModelB, ...]` type alias for reuse across fields | Inline long unions repeatedly — hard to extend and easy to miss a variant |
| Use `@field_validator` for cross-type / cross-branch validation | Use `@field_validator` for simple bounds that `Field(min_length=...)` already handles |
| Keep legacy models alongside modern ones to avoid breaking old clients | Delete legacy models without a deprecation window |
| Use `str \| None = None` shorthand for optional nullable fields | Use `Optional[str]` (requires importing `Optional` and is more verbose in Python 3.10+) |
| Express streaming event types with `Literal["status", "message", "error", "done"]` | Use plain `str` for event — allows typos and makes exhaustive handling impossible |
| Name nested detail models explicitly (`LegacyImageUrlDetail`) | Use `dict[str, str]` for nested structured data — loses type safety and schema |

---

## 7. Adding New Content Types

Follow these steps when extending `ContentPart` with a new variant:

### Step 1 — Define the new model

```python
class AudioContentPart(BaseModel):
    type: Literal["input_audio"] = "input_audio"  # unique discriminator
    audio_url: str
    format: Literal["mp3", "wav", "ogg"] = "mp3"
```

### Step 2 — Add to the `ContentPart` union

```python
ContentPart = Union[
    TextContentPart,
    LegacyTextContentPart,
    ImageUrlContentPart,
    LegacyImageUrlContentPart,
    AudioContentPart,              # ← append here
]
```

> **Order matters for ambiguous types.** Pydantic tries each variant left-to-right; more specific models should come before looser ones. `Literal` discriminators make this unambiguous, so order is a tiebreaker only.

### Step 3 — Update downstream consumers

- Backend route handlers that iterate `message.content` and dispatch on `part.type`
- Frontend type definitions (TypeScript discriminated union)
- OpenAPI schema docs / Swagger UI (regenerate if auto-generated)

### Step 4 — Add tests

```python
def test_audio_content_part_roundtrip():
    raw = {"type": "input_audio", "audio_url": "https://...", "format": "wav"}
    part = TypeAdapter(ContentPart).validate_python(raw)
    assert isinstance(part, AudioContentPart)
    assert part.format == "wav"

def test_audio_content_part_in_message():
    msg = ChatMessage(role="user", content=[
        TextContentPart(text="Transcribe this"),
        AudioContentPart(audio_url="https://..."),
    ])
    assert len(msg.content) == 2
```

---

## References

- Source: `backend/app/models.py`
- Pydantic v2 docs: https://docs.pydantic.dev/latest/
- Discriminated unions: https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions
- `field_validator`: https://docs.pydantic.dev/latest/concepts/validators/#field-validators
