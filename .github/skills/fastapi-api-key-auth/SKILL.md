---
name: fastapi-api-key-auth
display_name: FastAPI API Key Authentication Middleware
description: >-
    Production-only API key authentication middleware for FastAPI using Starlette
    BaseHTTPMiddleware. Enforces x-api-key header on /api/** paths in production,
    with path-based bypass and non-production pass-through.
user-invocable: true
---

# Skill: FastAPI API Key Authentication Middleware

## 1. Purpose

`APIKeyAuthMiddleware` provides **production-only API key authentication** for FastAPI applications using Starlette's `BaseHTTPMiddleware`.  
It enforces that all requests to `/api/**` paths carry a valid `x-api-key` header in production, while letting public paths and non-production environments pass through unconditionally.

Source: [`backend/app/auth.py`](../../backend/app/auth.py)

---

## 2. When to Use

Apply this pattern when:

- You have a FastAPI backend that exposes both **public** and **protected** endpoints.
- You want a single, centralized auth gate instead of per-route `Depends()` decorators.
- You need auth to be **a no-op in development/staging** (no token required locally) but **enforced in production**.
- You use a simple shared secret (`x-api-key`) rather than per-user JWT tokens (e.g., a Telegram bot backend called only by a trusted frontend/worker).

---

## 3. Key Concepts

### 3.1 Middleware Structure

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from fastapi import Request
from app.config import Settings

class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings
        self._excluded_paths = {"/", "/health", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        ...
```

`settings` is injected at registration time so the middleware is fully testable without patching globals.

---

### 3.2 Excluded Paths Set

```python
self._excluded_paths = {"/", "/health", "/docs", "/openapi.json", "/redoc"}
```

These paths always bypass auth, regardless of environment or API key presence.  
They cover health checks and the OpenAPI/Swagger UI so they remain publicly accessible.

---

### 3.3 Path-Based Bypass: Non-`/api` Paths Are Public

```python
if request.url.path in self._excluded_paths or not request.url.path.startswith("/api"):
    return await call_next(request)
```

Any path that does **not** start with `/api` is treated as public.  
This enables endpoints like `/audio/{token}` to serve content without an API key — the path prefix acts as an implicit visibility contract:

| Path prefix | Auth enforced? |
|-------------|---------------|
| `/api/...`  | ✅ Yes (in production) |
| `/audio/...` | ❌ No — public |
| `/health`   | ❌ No — excluded set |
| `/docs`     | ❌ No — excluded set |

---

### 3.4 Non-Production Bypass

```python
if self._settings.app_env != "production":
    logger.debug("Non-production environment (%s), skipping API key auth", self._settings.app_env)
    return await call_next(request)
```

When `APP_ENV` is anything other than `"production"` (e.g., `"development"`, `"staging"`), the middleware is a transparent pass-through. No API key is required locally.

---

### 3.5 `x-api-key` Header Check

```python
expected_api_key = self._settings.backend_api_key  # BACKEND_API_KEY env var

if not expected_api_key:
    # Production with no key configured → fail safe
    return JSONResponse(status_code=503, content={"detail": "API key authentication is not configured on the server."})

received_api_key = request.headers.get("x-api-key")
if received_api_key == expected_api_key:
    return await call_next(request)  # ✅ Valid

return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key."})
```

- **503** — production deployment misconfiguration (key not set); fail-safe prevents unauthenticated access.
- **401** — client sent wrong or no key.

---

### 3.6 Registering the Middleware

```python
# In your FastAPI app factory / main.py
from app.auth import APIKeyAuthMiddleware
from app.config import get_settings

settings = get_settings()
app.add_middleware(APIKeyAuthMiddleware, settings=settings)
```

Middleware is applied globally. No per-route decoration needed.

---

## 4. Auth Decision Matrix

| `APP_ENV`      | `BACKEND_API_KEY` set | `x-api-key` sent & correct | Result  |
|----------------|-----------------------|-----------------------------|---------|
| `development`  | any                   | any                         | **200** (pass-through) |
| `staging`      | any                   | any                         | **200** (pass-through) |
| `production`   | ❌ No                 | any                         | **503** Server misconfiguration |
| `production`   | ✅ Yes                | ✅ Correct                  | **200** Authorized |
| `production`   | ✅ Yes                | ❌ Wrong / missing          | **401** Unauthorized |

---

## 5. Making an Endpoint Public

To expose an endpoint **without** API key auth, route it outside `/api`:

```python
# ✅ Public — path does not start with /api
@app.get("/audio/{token}")
async def serve_audio(token: str): ...

# 🔒 Protected — requires x-api-key in production
@app.post("/api/chat")
async def chat(body: ChatRequest): ...
```

No code change in the middleware is needed — the path prefix convention is the sole gate.  
If you need a new public path that does start with `/api`, add it to `_excluded_paths` explicitly and document the reason.

---

## 6. Do / Don't

### ✅ Do

- Keep all **internal/protected** endpoints under `/api/` so auth is applied automatically.
- Inject `settings` via `add_middleware(APIKeyAuthMiddleware, settings=settings)` — never read env vars directly inside `dispatch`.
- Set `BACKEND_API_KEY` in the production environment before deploying — the 503 guard will surface misconfiguration early.
- Use structured logging (`logger.debug/info/warning/error`) in `dispatch` so auth decisions are auditable without printing sensitive key values.

### ❌ Don't

- Don't add per-route `Depends(verify_api_key)` decorators when this middleware is active — it duplicates enforcement.
- Don't put the raw `BACKEND_API_KEY` value in source code, Docker images, or committed `.env` files.
- Don't add new "public `/api/`" paths to `_excluded_paths` without a documented justification — prefer routing them under a non-`/api` prefix instead.
- Don't rely on this middleware for **per-user** or **role-based** access control — it is a shared-secret gate, not a user identity system.

---

## 7. Environment Variables

| Variable           | Required in prod | Default      | Description |
|--------------------|-----------------|--------------|-------------|
| `BACKEND_API_KEY`  | ✅ Yes           | `None`       | Shared secret compared against `x-api-key` header. Blank values are normalized to `None` by the settings validator. |
| `APP_ENV`          | Recommended      | `production` | Controls whether auth is enforced. Any value other than `"production"` disables auth entirely. |

Both variables are managed via `pydantic-settings` in `app/config.py`:

```python
app_env: str = Field(default="production", validation_alias="APP_ENV")
backend_api_key: str | None = Field(default=None, validation_alias="BACKEND_API_KEY")
```

Blank strings are normalized to `None` by `_normalize_optional_strings`, so `BACKEND_API_KEY=` (empty) is treated as unset.

---

## 8. Testing This Middleware

Use `unittest.IsolatedAsyncioTestCase` with `httpx.AsyncClient` + `ASGITransport` to test the middleware in-process without a live server:

```python
import unittest
import httpx
from fastapi import FastAPI
from app.auth import APIKeyAuthMiddleware
from app.config import Settings

def make_app(app_env: str, api_key: str | None) -> FastAPI:
    app = FastAPI()
    settings = Settings(APP_ENV=app_env, BACKEND_API_KEY=api_key)
    app.add_middleware(APIKeyAuthMiddleware, settings=settings)

    @app.get("/api/protected")
    async def protected():
        return {"ok": True}

    @app.get("/audio/test")
    async def public_audio():
        return {"ok": True}

    return app

class TestAPIKeyAuth(unittest.IsolatedAsyncioTestCase):

    async def test_production_valid_key(self):
        app = make_app("production", "secret")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/protected", headers={"x-api-key": "secret"})
        self.assertEqual(resp.status_code, 200)

    async def test_production_missing_key_returns_401(self):
        app = make_app("production", "secret")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/protected")
        self.assertEqual(resp.status_code, 401)

    async def test_production_no_key_configured_returns_503(self):
        app = make_app("production", None)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/protected", headers={"x-api-key": "anything"})
        self.assertEqual(resp.status_code, 503)

    async def test_dev_skips_auth(self):
        app = make_app("development", None)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/protected")
        self.assertEqual(resp.status_code, 200)

    async def test_public_audio_path_no_auth(self):
        app = make_app("production", "secret")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/audio/test")  # no x-api-key header
        self.assertEqual(resp.status_code, 200)
```

Run with:
```bash
cd backend && python -m pytest tests/test_auth.py -v
```
