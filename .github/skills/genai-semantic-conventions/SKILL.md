---
name: genai-semantic-conventions
description: GenAI OpenTelemetry semantic conventions for Azure AI Foundry agent tracing in Application Insights.
---

# GenAI Semantic Conventions

## Context
When instrumenting Azure AI Foundry agent calls with OpenTelemetry and exporting traces
to Azure Application Insights, spans must carry standardised GenAI semantic attributes so
that App Insights can surface them in the **GenAI** tab and allow filtering/grouping.

This knowledge applies whenever you create custom spans around `invoke_agent`,
conversation management, or tool execution in the Foundry agent flow.

## Key Facts
- Standard attributes used in this project:

  | Attribute | Example Value | Notes |
  |-----------|--------------|-------|
  | `gen_ai.operation.name` | `invoke_agent` | `invoke_agent` for agent calls, `chat` for direct chat |
  | `gen_ai.system` | `az.ai.agents` | SDK system identifier |
  | `gen_ai.provider.name` | `microsoft.foundry` | Always `microsoft.foundry` for Foundry agents |
  | `gen_ai.agent.name` | `my-agent` | From `settings.azure_ai_agent_name` |
  | `gen_ai.agent.id` | `asst_abc123` | The agent's server-assigned ID |
  | `gen_ai.request.model` | `gpt-4o` | From `settings.azure_ai_model` |
  | `gen_ai.conversation.id` | `thread_xyz` | Thread / conversation ID |
  | `gen_ai.usage.input_tokens` | `1234` | Token usage from the response |
  | `gen_ai.usage.output_tokens` | `567` | Token usage from the response |
  | `gen_ai.tool.name` | `get_weather` | For tool-call child spans |
  | `gen_ai.tool.type` | `mcp_call` | Distinguishes MCP vs built-in tools |

- **Span naming convention**: `invoke_agent {agent_name}` — the operation name followed
  by the agent display name.
- Child spans for tool calls nest under the agent span and carry `gen_ai.tool.*` attributes.
- Conversation spans track `gen_ai.conversation.id` for multi-turn grouping.

## Code Examples
```python
# Creating an agent invocation span
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

with _tracer.start_as_current_span(
    f"invoke_agent {agent_name}",
    attributes={
        "gen_ai.operation.name": "invoke_agent",
        "gen_ai.system": "az.ai.agents",
        "gen_ai.provider.name": "microsoft.foundry",
        "gen_ai.agent.name": agent_name,
        "gen_ai.request.model": model_name,
        "gen_ai.conversation.id": conversation_id or "",
    },
) as span:
    # ... agent call ...
    span.set_attribute("gen_ai.agent.id", agent.id)
    span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
```

```python
# Tool execution child span
with _tracer.start_as_current_span(
    f"tool-call:{tool_name}",
    attributes={
        "gen_ai.agent.name": agent_name,
        "gen_ai.provider.name": "microsoft.foundry",
        "gen_ai.tool.name": tool_name,
        "gen_ai.tool.type": "mcp_call",
        "gen_ai.conversation.id": conversation_id or "",
    },
) as tool_span:
    # ... tool execution ...
    tool_span.set_attribute("gen_ai.tool.duration_ms", elapsed_ms)
    tool_span.set_attribute("gen_ai.tool.status", "success")
```

## Common Pitfalls
- Using non-standard attribute names (e.g. `ai.agent_name` instead of
  `gen_ai.agent.name`) — App Insights won't recognise them for GenAI filtering.
- Omitting `gen_ai.conversation.id` — breaks multi-turn trace grouping.
- Setting `gen_ai.system` to a free-form string — must match SDK conventions
  (`az.ai.agents`) for correlation with auto-instrumented spans from
  `AIProjectInstrumentor`.
- Forgetting token usage attributes — App Insights cost dashboards rely on them.

## References
- File: `backend/app/agent.py` (lines 720–845 for span creation, 1600–1735 for tool spans)
- File: `backend/app/telemetry.py` (OpenTelemetry + Azure Monitor setup)
