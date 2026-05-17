---
name: mcp-jsonrpc-client
description: Lightweight MCP JSON-RPC 2.0 client over Streamable HTTP using httpx, independent from Foundry agent SDK.
---

# MCP JSON-RPC Client

## Context
This project includes a standalone MCP (Model Context Protocol) client that speaks
JSON-RPC 2.0 over Streamable HTTP. It is used by the MCP validation page to connect to
arbitrary MCP servers, list their tools, and execute tool calls — all independently of
the Foundry agent SDK.

Use this knowledge when building or modifying the MCP test/validation feature, or when
adding new MCP server integrations.

## Key Facts
- **Transport**: `httpx.AsyncClient` for async HTTP — no MCP SDK dependency.
- **Protocol**: JSON-RPC 2.0 with three main methods:
  - `initialize` — handshake with `protocolVersion: "2025-03-26"`
  - `tools/list` — enumerate available tools
  - `tools/call` — execute a specific tool with arguments
- After `initialize`, a `notifications/initialized` notification is sent before any
  further requests.
- Session continuity: the server may return an `mcp-session-id` header that must be
  forwarded on subsequent requests.
- **Response parsing** handles both plain `application/json` and `text/event-stream` (SSE)
  content types — the last `data:` line with a `result` key is extracted.

### Data Classes
- `McpTiming` — timing breakdown (total, initialize, list_tools, tool_call,
  server_execution) in milliseconds.
- `McpConnectResult` — tools list + timing.
- `McpCallResult` — tool result + timing.

### Authentication
Configured at construction time via `auth_type`:
- `"none"` — no auth headers
- `"api_key"` — custom header name + value (e.g. `x-api-key: abc123`)
- Bearer tokens can be sent by setting `auth_header="Authorization"` and
  `auth_value="Bearer <token>"`.

### Return Types
- `McpClient.list_tools()` returns `McpConnectResult`
- `McpClient.call_tool()` returns `McpCallResult`
- The FastAPI endpoints in `backend/app/main.py` convert those dataclass results into
  `dict[str, Any]` responses (`{"tools": ..., "timing": ...}`, `{"result": ..., "timing": ...}`)
  so the HTTP layer avoids `ResponseValidationError` while the client code still keeps
  typed timing/result objects internally.

## Code Examples
```python
from app.mcp_service import McpClient

client = McpClient(
    server_url="https://mcp.example.com/mcp",
    auth_type="api_key",
    auth_header="x-api-key",
    auth_value="my-secret-key",
)

# List tools (includes initialize handshake)
connect_result = await client.list_tools()
for tool in connect_result.tools:
    print(tool["name"], tool.get("description", ""))

# Call a specific tool
call_result = await client.call_tool(
    tool_name="get_weather",
    arguments={"location": "Seoul"},
)
print(call_result.result)
print(f"Total: {call_result.timing.total_ms:.1f}ms")
```

### Server timing extraction
The client automatically reads server-side execution time from response headers:
- `x-execution-time`
- `x-response-time`
- W3C `server-timing` (`dur=...`)

## Common Pitfalls
- Using the MCP Python SDK instead of raw httpx — this client intentionally avoids the
  SDK to keep the dependency footprint small and to control SSE parsing.
- Forgetting the `notifications/initialized` step — some MCP servers reject `tools/list`
  if the notification was not sent after `initialize`.
- Setting `max_redirects` too high — MCP servers may 307-redirect on POST which can
  cause infinite loops; the client uses `max_redirects=0`.
- Returning strict-typed models from FastAPI endpoints — use `dict[str, Any]` to avoid
  `ResponseValidationError` on mixed-shape MCP responses.

## References
- File: `backend/app/mcp_service.py` (full implementation)
- File: `backend/app/main.py` (FastAPI endpoints: `/api/mcp/connect`, `/api/mcp/execute`)
- File: `frontend/src/app/mcp-test/page.tsx` (frontend MCP validation page)
