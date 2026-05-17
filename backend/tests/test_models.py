from __future__ import annotations

from app.models import McpConnectRequest, McpExecuteRequest


def test_mcp_connect_accepts_private_url() -> None:
    """사설 IP 기반 MCP 서버 URL이 차단 없이 허용되는지 확인합니다."""
    request = McpConnectRequest.model_validate(
        {
            "server_url": "http://10.1.2.3:9000/mcp",
            "auth_type": "none",
            "auth_header": "x-api-key",
            "auth_value": "",
        }
    )
    assert str(request.server_url) == "http://10.1.2.3:9000/mcp"


def test_mcp_execute_accepts_localhost_url() -> None:
    """localhost MCP 서버 URL이 차단 없이 허용되는지 확인합니다."""
    request = McpExecuteRequest.model_validate(
        {
            "server_url": "http://localhost:8000/mcp",
            "auth_type": "none",
            "auth_header": "x-api-key",
            "auth_value": "",
            "tool_name": "ping",
            "arguments": {},
        }
    )
    assert str(request.server_url) == "http://localhost:8000/mcp"
