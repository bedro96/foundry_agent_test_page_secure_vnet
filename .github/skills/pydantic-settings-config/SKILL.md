---
name: pydantic-settings-config
display_name: Pydantic-Settings Configuration
description: >-
    Type-safe application settings loaded from environment variables and .env files using
    pydantic-settings. Covers AliasChoices for renamed vars, blank-string normalization,
    lru_cache singleton pattern, and field validation.
user-invocable: true
---

# Skill: Pydantic-Settings Configuration

## Purpose

Type-safe application settings loaded from environment variables (and an optional `.env` file) using **pydantic-settings**. All settings are validated at startup, provide IDE autocompletion, and fail fast with clear messages when required values are missing or malformed.

---

## When to Use

Use this skill whenever you need to:

- Load configuration from environment variables in a Python backend service.
- Support both a local `.env` file (development) and real env vars (production / Docker / Azure).
- Rename env vars without breaking existing deployments (`AliasChoices`).
- Normalize blank strings injected by orchestrators (Docker, Azure App Service) that set `""` instead of omitting a variable.
- Guarantee a single settings instance is constructed per process (`lru_cache`).

---

## Key Concepts

### 1. Path Resolution

Resolve paths relative to the source file, not the working directory, so the backend finds `.env` regardless of where the process is launched:

```python
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]  # repo/backend/
ENV_FILE = BACKEND_DIR / ".env"
```

### 2. Eager `.env` Loading

Call `load_dotenv` **before** `Settings()` is instantiated so environment variables are present when pydantic-settings reads them. `override=True` ensures `.env` values win over any stale shell exports during local development:

```python
from dotenv import load_dotenv

load_dotenv(dotenv_path=ENV_FILE, override=True)
```

### 3. `BaseSettings` Subclass with `SettingsConfigDict`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),      # fallback file path for pydantic-settings itself
        env_file_encoding="utf-8",
        extra="ignore",              # silently drop unknown env vars (safe in prod)
    )
```

`extra="ignore"` prevents `ValidationError` when the process environment contains keys not declared in `Settings`.

### 4. `Field` with `validation_alias`

Map a Python attribute name to its env var name. Use `validation_alias` (not `alias`) so the field is still accessible by its Python name in code:

```python
from pydantic import Field

app_env: str = Field(default="production", validation_alias="APP_ENV")
```

### 5. Optional String Pattern

For optional credentials / endpoints use `str | None = Field(default=None, ...)`:

```python
backend_api_key: str | None = Field(default=None, validation_alias="BACKEND_API_KEY")
azure_speech_endpoint: str | None = Field(default=None, validation_alias="AZURE_SPEECH_ENDPOINT")
```

### 6. `AliasChoices` for Renamed or Aliased Env Vars

When a variable has been renamed across environments (or two names co-exist), list them in priority order. The first name found in the environment wins:

```python
from pydantic import AliasChoices

azure_ai_project_endpoint: str | None = Field(
    default=None,
    validation_alias=AliasChoices(
        "AZURE_AI_PROJECT_ENDPOINT",
        "AZURE_OPENAI_PROJECT_ENDPOINT",   # legacy name, still accepted
    ),
)

azure_ai_model: str = Field(
    default="gpt-4o",
    validation_alias=AliasChoices(
        "AZURE_AI_MODEL_DEPLOYMENT_NAME",
        "AZURE_AI_MODEL",
        "MODEL_DEPLOYMENT_NAME",
    ),
)
```

### 7. `@field_validator` for Blank-String Normalization

Docker Compose, Azure App Service, and CI systems often set env vars to `""` instead of omitting them. Without normalization `""` passes `str | None` validation and your code later sees a non-`None` empty string:

```python
from pydantic import field_validator

@field_validator(
    "backend_api_key",
    "azure_ai_project_endpoint",
    "azure_tenant_id",
    "azure_client_id",
    "azure_client_secret",
    "azure_speech_endpoint",
    "backend_public_url",
    "bing_grounding_connection_name",
    "browser_automation_project_connection_id",
    mode="before",
)
@classmethod
def _normalize_optional_strings(cls, value: str | None) -> str | None:
    """Treat blank optional environment variables as unset (→ None)."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
```

`mode="before"` runs the validator on the raw input before type coercion, which is required here because the raw value may be `""`.

### 8. `lru_cache` Singleton

Wrap `get_settings()` with `lru_cache(maxsize=1)` so the `Settings` object is constructed exactly once per process. All callers share the same instance with zero overhead after the first call:

```python
from functools import lru_cache

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings singleton for the process lifetime."""
    _log_env_file_status()
    return Settings()
```

---

## Field Reference

| Python Field | Env Var(s) | Type | Default |
|---|---|---|---|
| `app_name` | *(hardcoded)* | `str` | `"telegram-bot-backend"` |
| `app_env` | `APP_ENV` | `str` | `"production"` |
| `backend_api_key` | `BACKEND_API_KEY` | `str \| None` | `None` |
| `azure_ai_project_endpoint` | `AZURE_AI_PROJECT_ENDPOINT`, `AZURE_OPENAI_PROJECT_ENDPOINT` | `str \| None` | `None` |
| `azure_tenant_id` | `AZURE_TENANT_ID` | `str \| None` | `None` |
| `azure_client_id` | `AZURE_CLIENT_ID` | `str \| None` | `None` |
| `azure_client_secret` | `AZURE_CLIENT_SECRET` | `str \| None` | `None` |
| `azure_speech_endpoint` | `AZURE_SPEECH_ENDPOINT` | `str \| None` | `None` |
| `azure_speech_language` | `AZURE_SPEECH_LANGUAGE` | `str` | `"ko-KR"` |
| `backend_public_url` | `BACKEND_PUBLIC_URL` | `str \| None` | `None` |
| `azure_ai_model` | `AZURE_AI_MODEL_DEPLOYMENT_NAME`, `AZURE_AI_MODEL`, `MODEL_DEPLOYMENT_NAME` | `str` | `"gpt-4o"` |
| `azure_ai_agent_name` | `AZURE_AI_AGENT_NAME` | `str` | `"telegram-bot-agent"` |
| `azure_ai_agent_instructions` | `AZURE_AI_AGENT_INSTRUCTIONS` | `str` | `"You are a helpful Telegram bot assistant."` |
| `bing_grounding_connection_name` | `BING_GROUNDING_CONNECTION_NAME` | `str \| None` | `None` |
| `browser_automation_project_connection_id` | `BROWSER_AUTOMATION_PROJECT_CONNECTION_ID` | `str \| None` | `None` |
| `request_timeout_seconds` | `REQUEST_TIMEOUT_SECONDS` | `float` | `60.0` |

---

## Blank String Normalization — Why It Matters

Container orchestrators (Docker Compose `environment:`, Azure App Service Application Settings, GitHub Actions `env:`) frequently set variables to empty string `""` instead of omitting them entirely. Without the `_normalize_optional_strings` validator your code would receive:

```python
settings.azure_client_secret  # → ""  (truthy check passes, auth call fails later)
```

After normalization:

```python
settings.azure_client_secret  # → None  (callers can do `if settings.azure_client_secret:`)
```

This converts a silent runtime failure into predictable `None`-guarded behaviour that can be caught early with a clear log message.

---

## Do / Don't

| ✅ Do | ❌ Don't |
|---|---|
| Use `AliasChoices` when a variable was renamed so old deployments keep working | Rename a variable and break all existing `.env` files silently |
| Use `Field(default=None, ...)` for optional secrets; check `if settings.x:` before use | Hardcode fallback values for secrets (e.g. `default="my-secret"`) |
| Add new optional fields to `_normalize_optional_strings` if they accept blank strings | Leave blank-string normalization out — Docker/Azure will silently pass `""` |
| Call `get_settings()` everywhere (cached); never call `Settings()` directly in business code | Instantiate `Settings()` multiple times — it reads disk/env on every call |
| Set `extra="ignore"` so undeclared env vars don't crash the app in production | Use `extra="forbid"` in production — orchestrators inject many extra env vars |
| Use `validation_alias` (not `alias`) to keep Pythonic attribute names in code | Use bare `alias` — it breaks attribute access by Python name |
| Resolve `ENV_FILE` with `Path(__file__).resolve().parents[N]` | Use relative paths like `Path(".env")` — they depend on CWD |

---

## Testing

Override individual settings without reading `.env` by passing values directly to the `Settings` constructor (pydantic-settings accepts constructor kwargs that bypass env lookup):

```python
# tests/test_config.py
import pytest
from app.config import Settings

def test_defaults():
    s = Settings(APP_ENV="test")   # only APP_ENV is overridden; rest use defaults
    assert s.app_env == "test"
    assert s.request_timeout_seconds == 60.0

def test_blank_string_normalized_to_none():
    s = Settings(BACKEND_API_KEY="   ")
    assert s.backend_api_key is None

def test_alias_choices_legacy_name():
    s = Settings(AZURE_OPENAI_PROJECT_ENDPOINT="https://legacy.example.com")
    assert s.azure_ai_project_endpoint == "https://legacy.example.com"
```

For tests that use `get_settings()` (the cached singleton), clear the cache first:

```python
from app.config import get_settings

def test_with_cached_settings(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "staging")
    s = get_settings()
    assert s.app_env == "staging"
    get_settings.cache_clear()   # clean up so other tests are not affected
```

Use `types.SimpleNamespace` when you only need a duck-typed settings object (e.g. for mocking in integration tests that never touch `get_settings`):

```python
from types import SimpleNamespace

fake_settings = SimpleNamespace(
    azure_ai_model="gpt-4o-mini",
    azure_ai_agent_name="test-agent",
    request_timeout_seconds=5.0,
)
```

---

## Dependencies

```toml
# pyproject.toml
[project]
dependencies = [
  "pydantic>=2.12.5",
  "pydantic-settings==2.13.1",
  "python-dotenv",   # provides load_dotenv
]
```

Install with `uv`:

```bash
uv add "pydantic-settings==2.13.1" python-dotenv
```
