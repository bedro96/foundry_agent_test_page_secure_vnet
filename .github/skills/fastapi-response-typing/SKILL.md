---
name: fastapi-response-typing
description: FastAPI response type annotation best practices to avoid ResponseValidationError on mixed-shape responses.
---

# FastAPI Response Typing

## Context
FastAPI uses Pydantic to validate **return values** against the declared return type
annotation. When a response shape doesn't exactly match the annotation, FastAPI raises a
`ResponseValidationError` which surfaces as an HTTP 500 — and this error is **not**
caught by custom exception handlers registered with `@app.exception_handler(...)`.

This knowledge applies when writing FastAPI endpoint return type annotations, especially
for endpoints that proxy external services (MCP servers, Azure APIs) with unpredictable
response shapes.

## Key Facts
- FastAPI validates return type annotations **strictly** at response time.
- `dict[str, list[...]]` means **every** value in the dict must be a list — if any value
  is a string, int, or nested dict, validation fails.
- `dict[str, Any]` is the safe choice when response shapes are mixed or dynamic.
- `ResponseValidationError` results in HTTP 500 and **cannot** be caught by
  `@app.exception_handler(RequestValidationError)` — it's a different exception class.
- For endpoints with well-known shapes, prefer explicit Pydantic `BaseModel` response
  models for documentation and validation benefits.

## Code Examples
```python
# ❌ BAD — will fail if response has non-list values
@app.post("/api/mcp/connect")
async def mcp_connect(req: McpConnectRequest) -> dict[str, list[dict[str, Any]]]:
    return {
        "tools": [...],          # ✅ this is a list
        "timing": {...},         # ❌ this is a dict — ResponseValidationError!
        "server_url": "https://...",  # ❌ this is a string — ResponseValidationError!
    }

# ✅ GOOD — accepts any value types
@app.post("/api/mcp/connect")
async def mcp_connect(req: McpConnectRequest) -> dict[str, Any]:
    return {
        "tools": [...],
        "timing": {...},
        "server_url": "https://...",
    }

# ✅ ALSO GOOD — explicit Pydantic model when shape is known
from pydantic import BaseModel

class McpConnectResponse(BaseModel):
    tools: list[dict[str, Any]]
    timing: dict[str, float | None]
    server_url: str

@app.post("/api/mcp/connect", response_model=McpConnectResponse)
async def mcp_connect(req: McpConnectRequest) -> McpConnectResponse:
    ...
```

## Common Pitfalls
- Assuming `dict[str, list[...]]` is flexible — it's not; FastAPI + Pydantic enforce
  that **all** values must match the declared value type.
- Trying to catch `ResponseValidationError` with a custom exception handler — it's a
  different class from `RequestValidationError` and fires after the handler returns.
- Using overly specific generics like `dict[str, str | int | list[str]]` for dynamic
  API proxies — just use `dict[str, Any]`.
- Forgetting that the 500 error message includes "Response validation error" in the
  detail — search server logs for this string when debugging mysterious 500s.

## References
- File: `backend/app/main.py` (MCP endpoints using `dict[str, Any]` return types)
- File: `backend/app/mcp_service.py` (McpConnectResult / McpCallResult with `Any` fields)
- FastAPI docs: [Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/)
