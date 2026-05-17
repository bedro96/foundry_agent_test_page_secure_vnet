---
name: azure-ai-foundry-agent
display_name: Azure AI Foundry Agent Integration
description: >-
    Full lifecycle of streaming chat responses from an Azure AI Projects prompt agent,
    including agent resolution, version drift detection, conversation management,
    MCP tool auto-approval, and SSE event emission using azure-ai-projects and openai SDKs.
user-invocable: true
---

# Skill: Azure AI Foundry Agent Integration

## 1. Purpose

This skill encapsulates the full lifecycle of streaming chat responses from an **Azure AI Projects prompt agent** — including agent resolution, version drift detection, conversation management, MCP tool auto-approval, and SSE event emission — using the `azure-ai-projects` and `openai` async Python SDKs.

---

## 2. When to Use This Skill

Use this skill when:

- Integrating an Azure AI Foundry **prompt agent** into a Python async backend (FastAPI, etc.).
- You need **streaming** token-by-token responses from the Responses API.
- Your agent uses grounding tools such as **Bing Search**, **Web Search Preview**, or **Browser Automation**.
- You need **idempotent agent creation** — create only when missing or configuration has drifted.
- Conversations must be **reused across turns** rather than recreated per message.
- Requests may trigger **MCP tool approval flows** that must be auto-approved without user intervention.
- Content may be **multimodal** (text + image URLs).
- Authentication uses either a **service principal** (`ClientSecretCredential`) or **`DefaultAzureCredential`** fallback.

---

## 3. Key Concepts

### 3.1 `AIProjectClient` Lifecycle

Always use `AIProjectClient` as an async context manager for proper connection cleanup. The `openai_client` must be obtained exclusively through `project_client.get_openai_client()` — never instantiate `AzureOpenAI` directly.

```python
from azure.ai.projects.aio import AIProjectClient

async with AIProjectClient(
    endpoint=settings.azure_ai_project_endpoint,
    credential=credential,
) as project_client:
    async with project_client.get_openai_client(
        timeout=settings.request_timeout_seconds
    ) as openai_client:
        # All agent and conversation operations happen here
        ...
```

---

### 3.2 Agent Lookup — Create on `ResourceNotFoundError`

Attempt to `get` the agent first. Only create it when it does not yet exist. After lookup, retrieve the latest version explicitly via `list_versions` because `get()` may return the agent object without a resolved version field.

```python
from azure.core.exceptions import ResourceNotFoundError

try:
    await project_client.agents.get(agent_name=settings.azure_ai_agent_name)
    latest_version = await _get_latest_agent_version(project_client, settings.azure_ai_agent_name)
except ResourceNotFoundError:
    latest_version = None  # Will trigger creation below

async def _get_latest_agent_version(project_client, agent_name):
    async for version in project_client.agents.list_versions(
        agent_name=agent_name, order="desc", limit=1
    ):
        return version
    return None
```

---

### 3.3 Agent Version Drift Detection (Hash-Based)

Before creating a new agent version, compute a `sha256` hash of the normalized definition (model + instructions + sorted tools). Compare it against the `agent_config_hash` stored in the existing version's `metadata`. If hashes match, reuse the existing version to avoid unnecessary version churn.

```python
import hashlib, json

_AGENT_CONFIG_HASH_KEY = "agent_config_hash"

def _build_agent_config_hash(normalized_definition: dict) -> str:
    encoded = json.dumps(normalized_definition, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def _normalize_definition_for_comparison(definition) -> dict:
    serialized = _safe_serialize(definition)
    tools = serialized.get("tools") or []
    tools = sorted(tools, key=lambda t: json.dumps(_safe_serialize(t), sort_keys=True))
    return {
        "kind": serialized.get("kind"),
        "model": serialized.get("model"),
        "instructions": serialized.get("instructions"),
        "tools": tools,
    }

def _agent_version_matches_expected(latest_version, expected_definition, expected_hash) -> bool:
    serialized = _safe_serialize(latest_version)
    metadata = serialized.get("metadata", {})
    if isinstance(metadata, dict) and metadata.get(_AGENT_CONFIG_HASH_KEY) == expected_hash:
        return True  # Fast path via stored hash
    # Fallback: structural comparison of definitions
    return _normalize_definition_for_comparison(
        serialized.get("definition")
    ) == expected_definition

# Create a new version when drift is detected:
await project_client.agents.create_version(
    agent_name=settings.azure_ai_agent_name,
    definition=definition,
    metadata={_AGENT_CONFIG_HASH_KEY: config_hash},
    description="LLM chat backend agent",
)
```

---

### 3.4 `openai_client` — Never Instantiate `AzureOpenAI` Directly

The `openai_client` is always obtained from the project client, which binds it to the correct Foundry endpoint, auth token, and API version. Instantiating `AzureOpenAI` or `AsyncAzureOpenAI` directly bypasses Foundry's agent routing.

```python
# ✅ Correct
async with project_client.get_openai_client(timeout=60.0) as openai_client:
    ...

# ❌ Never do this
from openai import AsyncAzureOpenAI
openai_client = AsyncAzureOpenAI(azure_endpoint=..., api_key=...)
```

---

### 3.5 Conversation Lifecycle — Create Once, Reuse Across Turns

A conversation is created exactly once per session by writing the initial user message into it. On subsequent turns, pass the existing `conversation_id` back to `responses.create` — do **not** include the user input again in `items` to avoid duplicating the turn.

```python
# First turn — create conversation with initial user message
conversation = await openai_client.conversations.create(
    items=[{"type": "message", "role": "user", "content": user_content}],
)
conversation_id = conversation.id  # Persist and return to client

# Subsequent turns — pass conversation_id and new user input
resp_result = await openai_client.responses.create(
    conversation=conversation_id,
    input=user_input,          # New user message only
    stream=True,
    extra_body={"agent_reference": extra_agent},
)

# First turn, after create() — do NOT pass input again (already in items)
resp_result = await openai_client.responses.create(
    conversation=conversation_id,
    stream=True,
    extra_body={"agent_reference": extra_agent},
)
```

---

### 3.6 Streaming via `responses.create` with Agent Reference

Pass the agent reference via `extra_body`. Include `stream=True` and optionally per-request `instructions` for system-message override. Use `tool_choice="allow"` only when the API requires it for the agent configuration.

```python
extra_agent = {"type": "agent_reference", "name": agent_name}
if agent_version:
    extra_agent["version"] = str(agent_version)

resp_result = await openai_client.responses.create(
    conversation=conversation_id,
    input=user_input,                        # Omit on first turn (already in conversation)
    instructions=response_instructions,      # Optional; from system messages
    stream=True,
    extra_body={"agent_reference": extra_agent},
)
```

---

### 3.7 Event Handling — Stream Consumption

Consume stream events with `async for`. Handle the following event types:

| `item.type` string | Action |
|---|---|
| `response.created` | Emit a `status` event: "Azure AI response started." |
| `response.output_text.delta` | Emit a `message` event with `item.delta` (incremental token) |
| `response.output_text.done` | Emit a `message` event with `item.text` (if no deltas were already sent) |
| `response.output_item.added` | Emit `status` for MCP approval requests or tool call start |
| `response.output_item.done` | Emit `status` for tool completion; fallback text emission if no deltas |
| `response.content_part.done` | Extract `url_citation` annotations; emit `status` for each source |
| `response.completed` | Log token usage; emit `status` with input/output/total token counts |

```python
async for item in resp_result:
    item_type = getattr(item, "type", "")

    if item_type == "response.output_text.delta":
        yield AgentEvent(event="message", data=item.delta, conversation_id=conversation_id)

    elif item_type in {"response.output_text", "response.output_text.done"}:
        if not already_emitted(item):
            yield AgentEvent(event="message", data=item.text, conversation_id=conversation_id)

    elif item_type == "response.content_part.done":
        for citation in extract_url_citations(item.part):
            yield AgentEvent(event="status", data=citation, conversation_id=conversation_id)

    elif item_type == "response.completed":
        usage = getattr(getattr(item, "response", None), "usage", None)
        if usage:
            summary = f"Token usage - input: {usage.input_tokens}, output: {usage.output_tokens}, total: {usage.total_tokens}"
            yield AgentEvent(event="status", data=summary, conversation_id=conversation_id)
```

---

### 3.8 MCP Auto-Approval

When the agent requires MCP tool approval, the API emits a `response.output_item.added` event containing an item of type `mcp_approval_request`. Capture the `id` of each approval request, then issue a follow-up `responses.create` with `mcp_approval_response` items. Repeat until no new approval requests are pending. Guard against infinite loops by tracking already-approved IDs.

```python
# Build approval input for follow-up call
def _build_mcp_approval_input(approval_request_ids: list[str]) -> list[dict]:
    return [
        {
            "type": "mcp_approval_response",
            "approval_request_id": aid,
            "approve": True,
        }
        for aid in approval_request_ids
    ]

# Approval loop (simplified)
auto_approved_ids: set[str] = set()
while True:
    resp_result = await openai_client.responses.create(**response_kwargs)
    pending_approvals: list[dict] = []

    async for item in resp_result:
        if getattr(item, "type", "") == "response.output_item.added":
            output_item = getattr(item, "item", None)
            if getattr(output_item, "type", None) == "mcp_approval_request":
                aid = getattr(output_item, "id", None)
                if aid:
                    pending_approvals.append({"id": aid})
        # ... handle other events

    new_approvals = [a for a in pending_approvals if a["id"] not in auto_approved_ids]
    if not new_approvals:
        break  # Done

    auto_approved_ids.update(a["id"] for a in new_approvals)
    response_kwargs = _build_response_kwargs(
        conversation_id=conversation_id,
        extra_agent=extra_agent,
        response_instructions=None,    # Skip instructions on approval rounds
        user_input=_build_mcp_approval_input([a["id"] for a in new_approvals]),
    )
```

**Stale MCP approval recovery:** If the API returns HTTP 400 with `"MCP approval requests do not have an approval"`, reset to a fresh conversation and retry:

```python
except OpenAIBadRequestError as exc:
    if "MCP approval requests do not have an approval" in str(exc):
        conversation_id, _ = await _create_fresh_conversation(openai_client, request)
        response_kwargs = _build_response_kwargs(conversation_id=conversation_id, ...)
        resp_result = await openai_client.responses.create(**response_kwargs)
    else:
        raise
```

---

### 3.9 Tool Grounding

Build tools by resolving the Bing connection from the project's connection registry. Optionally include browser automation when a connection ID is configured.

```python
from azure.ai.projects.models import (
    ApproximateLocation,
    BingGroundingSearchConfiguration,
    BingGroundingSearchToolParameters,
    BingGroundingTool,
    BrowserAutomationPreviewTool,
    BrowserAutomationToolConnectionParameters,
    BrowserAutomationToolParameters,
    WebSearchPreviewTool,
)

# Resolve Bing connection ID from named connection
bing_connection = await project_client.connections.get(settings.bing_grounding_connection_name)

tools = [
    BingGroundingTool(
        bing_grounding=BingGroundingSearchToolParameters(
            search_configurations=[
                BingGroundingSearchConfiguration(project_connection_id=bing_connection.id),
            ]
        )
    ),
    WebSearchPreviewTool(
        user_location=ApproximateLocation(country="KR", city="Seoul", region="Seoul"),
    ),
]

# Optional: browser automation
if settings.browser_automation_project_connection_id:
    tools.append(
        BrowserAutomationPreviewTool(
            browser_automation_preview=BrowserAutomationToolParameters(
                connection=BrowserAutomationToolConnectionParameters(
                    project_connection_id=settings.browser_automation_project_connection_id,
                )
            )
        )
    )
```

---

### 3.10 Annotation Extraction — `url_citation`

When a `response.content_part.done` event fires, extract `url_citation` annotations from `item.part` to surface source links as status messages.

```python
def _extract_annotation_messages(part) -> list[str]:
    annotations = _safe_serialize(part)
    if not isinstance(annotations, dict):
        return []
    messages = []
    for annotation in annotations.get("annotations", []):
        annotation_type = annotation.get("type") if isinstance(annotation, dict) else getattr(annotation, "type", None)
        if annotation_type != "url_citation":
            continue
        title = annotation.get("title") if isinstance(annotation, dict) else getattr(annotation, "title", None)
        url = annotation.get("url") if isinstance(annotation, dict) else getattr(annotation, "url", None)
        if title and url:
            messages.append(f"Source: {title} - {url}")
        elif url:
            messages.append(f"Source: {url}")
    return messages
```

---

### 3.11 Credential — `ClientSecretCredential` vs `DefaultAzureCredential`

Prefer `ClientSecretCredential` when all three service principal variables are set. Fall back to `DefaultAzureCredential` for managed identity, Azure CLI, or workload identity environments. Always call `await credential.close()` in the `finally` block.

```python
from azure.identity.aio import ClientSecretCredential, DefaultAzureCredential

def _build_credential(settings) -> ClientSecretCredential | DefaultAzureCredential:
    if settings.azure_tenant_id and settings.azure_client_id and settings.azure_client_secret:
        return ClientSecretCredential(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
    return DefaultAzureCredential()

# Usage with cleanup:
credential = _build_credential(settings)
try:
    async with AIProjectClient(endpoint=..., credential=credential) as project_client:
        ...
finally:
    await credential.close()
```

**Partial service principal guard:** If only some of the three SP variables are set, raise a `RuntimeError` before attempting any network calls:

```python
provided = [name for name, val in sp_vars.items() if val]
if 0 < len(provided) < 3:
    raise RuntimeError("Incomplete Azure service principal configuration. Missing: " + ...)
```

---

### 3.12 Multimodal Content — Image Parts

Detect image parts in the user message and forward them verbatim to `conversations.create`. Convert content parts to the Responses API input schema (`input_text` / `input_image`).

```python
def _content_is_multimodal(content) -> bool:
    if not isinstance(content, list):
        return False
    return any(
        _safe_serialize(part).get("type") in {"input_image", "image_url"}
        for part in content
        if isinstance(_safe_serialize(part), dict)
    )

def _normalize_content_parts_for_responses(content: list) -> list[dict]:
    normalized = []
    for part in content:
        s = _safe_serialize(part)
        if not isinstance(s, dict):
            continue
        if s.get("type") in {"input_text", "text"} and s.get("text", "").strip():
            normalized.append({"type": "input_text", "text": s["text"].strip()})
        elif s.get("type") in {"input_image", "image_url"}:
            image_url = s.get("image_url")
            if isinstance(image_url, dict):
                image_url = image_url.get("url")
            if image_url:
                normalized.append({"type": "input_image", "image_url": image_url, "detail": s.get("detail") or "auto"})
    return normalized

# Multimodal content passed directly to conversation creation:
conversation = await openai_client.conversations.create(
    items=[{"type": "message", "role": "user", "content": latest_user_content}],
)
```

---

## 4. Do / Don't

### ✅ DO

- **Create `AIProjectClient` and `openai_client` via async context managers** to ensure connections and auth tokens are cleaned up, even on error.
- **Reuse the conversation ID across turns.** Create the conversation once and store `conversation.id` on the client side. On first-turn creation, omit `input` from `responses.create` (the message is already in the conversation `items`).
- **Store a `sha256` config hash in agent version metadata.** This enables fast drift detection without deserializing the entire definition on every request.
- **Guard MCP approval loops with an `auto_approved_ids` set.** If the same approval ID appears after being approved, break immediately to avoid infinite loops.
- **Call `await credential.close()` in `finally`.** Both `ClientSecretCredential` and `DefaultAzureCredential` hold background token-refresh tasks that must be cancelled.

### ❌ DON'T

- **Don't instantiate `AzureOpenAI` or `AsyncAzureOpenAI` directly.** Always use `project_client.get_openai_client()`, which handles Foundry-specific endpoint routing and auth.
- **Don't pass user input on the first turn after creating a conversation.** The initial message is already written into `items` during `conversations.create`; sending it again duplicates the turn in Foundry.
- **Don't create a new conversation on every request.** The `conversation_id` must persist across turns and be returned to the frontend so subsequent messages can continue the thread.
- **Don't log SDK objects directly via f-strings.** Use `_safe_serialize(obj)` first to safely handle objects that may not implement `__str__` cleanly, and avoid logging sensitive field values.
- **Don't skip the partial service-principal guard.** If `AZURE_TENANT_ID` is set without `AZURE_CLIENT_SECRET`, raise a `RuntimeError` before creating the credential — partial credentials cause confusing authentication failures at the network layer.

---

## 5. Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `AZURE_AI_PROJECT_ENDPOINT` | **Yes** | — | Azure AI Foundry project endpoint URL. Also accepted as `AZURE_OPENAI_PROJECT_ENDPOINT`. |
| `AZURE_AI_AGENT_NAME` | **Yes** | `telegram-bot-agent` | Name of the prompt agent to look up or create. |
| `BING_GROUNDING_CONNECTION_NAME` | **Yes** | — | Named connection in the Foundry project for Bing grounding. |
| `AZURE_TENANT_ID` | Cond. | `None` | Azure AD tenant ID (required if using service principal auth). |
| `AZURE_CLIENT_ID` | Cond. | `None` | Service principal client/application ID. |
| `AZURE_CLIENT_SECRET` | Cond. | `None` | Service principal client secret. |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | No | `gpt-4o` | Model deployment name for the agent. Also accepted as `AZURE_AI_MODEL` or `MODEL_DEPLOYMENT_NAME`. |
| `AZURE_AI_AGENT_INSTRUCTIONS` | No | `"You are a helpful Telegram bot assistant."` | System instructions for the prompt agent. |
| `BROWSER_AUTOMATION_PROJECT_CONNECTION_ID` | No | `None` | Foundry project connection ID for browser automation. Omit to disable the tool. |
| `REQUEST_TIMEOUT_SECONDS` | No | `60.0` | OpenAI client network timeout in seconds. |

> **Note:** All three of `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and `AZURE_CLIENT_SECRET` must be set together. Providing a partial set raises `RuntimeError` at startup.

---

## 6. Error Handling

All exceptions are caught in the outer `try/except` of `AzureAIFoundryAgent.stream()`. Each handler emits an `error` SSE event followed by a `done: failed` event, so the client always receives a terminal signal.

| Exception | Cause | User-Facing Message |
|---|---|---|
| `RuntimeError` | Missing env vars or incomplete service principal config | Exact error message from the validation layer |
| `CredentialUnavailableError` | No usable credential found (SP not set, no managed identity, no CLI login) | Prompts user to set `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` |
| `ClientAuthenticationError` | Credential rejected by Azure AD (wrong secret, expired, insufficient RBAC) | Instructs user to verify service principal access to the Foundry project |
| `ResourceNotFoundError` | Named Bing connection or browser automation connection not found | Instructs user to verify `BING_GROUNDING_CONNECTION_NAME` |
| `HttpResponseError` | Foundry API returned a non-2xx response | Generic Foundry request failure; check endpoint, model deployment, and tools |
| `OpenAIBadRequestError` | Responses API rejected the request (e.g., stale MCP approval) | If stale MCP approval: reset conversation and retry once; otherwise surface error |
| `Exception` (catch-all) | Unexpected integration failure | `{ExceptionType}: {first 300 chars of str(exc)}` |

```python
# Error event shape emitted to client
yield AgentEvent(event="error", data="<user-facing message>", conversation_id=conversation_id)
yield AgentEvent(event="done", data="failed", conversation_id=conversation_id)

# Success terminal event
yield AgentEvent(event="done", data="complete", conversation_id=conversation_id)
```

The credential is always closed in `finally`, regardless of success or failure.

---

## 7. Example Code Skeleton

A minimal but complete example showing the full flow from credential creation to stream consumption:

```python
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import (
    ApproximateLocation,
    BingGroundingSearchConfiguration,
    BingGroundingSearchToolParameters,
    BingGroundingTool,
    PromptAgentDefinition,
    WebSearchPreviewTool,
)
from azure.core.exceptions import ResourceNotFoundError
from azure.identity.aio import ClientSecretCredential, DefaultAzureCredential
from openai import BadRequestError as OpenAIBadRequestError

logger = logging.getLogger(__name__)
_AGENT_CONFIG_HASH_KEY = "agent_config_hash"


def _safe_serialize(obj: Any) -> Any:
    """Return a JSON-serializable representation of an SDK object for logging."""
    if obj is None or isinstance(obj, (str, int, float, bool, list, dict)):
        return obj
    for method in ("model_dump", "as_dict", "dict"):
        if hasattr(obj, method):
            try:
                return getattr(obj, method)()
            except Exception:
                pass
    try:
        return vars(obj)
    except TypeError:
        return repr(obj)


async def run_agent_stream(
    *,
    endpoint: str,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    agent_name: str,
    model: str,
    instructions: str,
    bing_connection_name: str,
    conversation_id: str | None,
    user_input: str,
) -> AsyncIterator[dict]:
    """Full agent stream lifecycle: credential → client → agent → conversation → stream."""

    # 1. Build credential
    if tenant_id and client_id and client_secret:
        credential: ClientSecretCredential | DefaultAzureCredential = ClientSecretCredential(
            tenant_id=tenant_id, client_id=client_id, client_secret=client_secret
        )
    else:
        credential = DefaultAzureCredential()

    try:
        # 2. Create project client and openai_client
        async with AIProjectClient(endpoint=endpoint, credential=credential) as project_client:
            async with project_client.get_openai_client(timeout=60.0) as openai_client:

                # 3. Resolve or create the prompt agent
                agent = await _resolve_agent(
                    project_client, agent_name, model, instructions, bing_connection_name
                )

                # 4. Build agent reference for Responses API
                agent_version = getattr(agent, "version", None)
                extra_agent: dict[str, str] = {"type": "agent_reference", "name": agent_name}
                if agent_version:
                    extra_agent["version"] = str(agent_version)

                # 5. Create or reuse conversation
                created_now = False
                if not conversation_id:
                    conversation = await openai_client.conversations.create(
                        items=[{"type": "message", "role": "user", "content": user_input}],
                    )
                    conversation_id = conversation.id
                    created_now = True
                    yield {"event": "status", "data": "Conversation created.", "conversation_id": conversation_id}

                # 6. Build responses.create kwargs
                kwargs: dict[str, Any] = {
                    "conversation": conversation_id,
                    "stream": True,
                    "extra_body": {"agent_reference": extra_agent},
                }
                # On first turn the user message is already in the conversation
                if not created_now:
                    kwargs["input"] = user_input

                # 7. Stream with MCP auto-approval loop
                auto_approved_ids: set[str] = set()
                while True:
                    try:
                        resp_result = await openai_client.responses.create(**kwargs)
                    except OpenAIBadRequestError as exc:
                        if "MCP approval requests do not have an approval" in str(exc):
                            conversation = await openai_client.conversations.create(
                                items=[{"type": "message", "role": "user", "content": user_input}]
                            )
                            conversation_id = conversation.id
                            kwargs = {
                                "conversation": conversation_id,
                                "stream": True,
                                "extra_body": {"agent_reference": extra_agent},
                            }
                            resp_result = await openai_client.responses.create(**kwargs)
                        else:
                            raise

                    pending_approvals: list[str] = []
                    async for item in resp_result:
                        item_type = getattr(item, "type", "")

                        # Capture MCP approval requests for auto-approval
                        if item_type == "response.output_item.added":
                            output_item = getattr(item, "item", None)
                            if getattr(output_item, "type", None) == "mcp_approval_request":
                                aid = getattr(output_item, "id", None)
                                if aid:
                                    pending_approvals.append(aid)
                                    yield {"event": "status", "data": "Auto-approving MCP tool...", "conversation_id": conversation_id}

                        # Emit incremental token deltas
                        elif item_type == "response.output_text.delta" and getattr(item, "delta", None):
                            yield {"event": "message", "data": item.delta, "conversation_id": conversation_id}

                        # Emit URL citations as source status messages
                        elif item_type == "response.content_part.done" and getattr(item, "part", None):
                            annotations = _safe_serialize(item.part).get("annotations", [])
                            for ann in annotations:
                                if isinstance(ann, dict) and ann.get("type") == "url_citation":
                                    title = ann.get("title", "")
                                    url = ann.get("url", "")
                                    if url:
                                        source_msg = f"Source: {title} - {url}" if title else f"Source: {url}"
                                        yield {"event": "status", "data": source_msg, "conversation_id": conversation_id}

                        # Log token usage on completion
                        elif item_type == "response.completed":
                            usage = getattr(getattr(item, "response", None), "usage", None)
                            if usage:
                                yield {
                                    "event": "status",
                                    "data": (
                                        f"Token usage - input: {usage.input_tokens}, "
                                        f"output: {usage.output_tokens}, total: {usage.total_tokens}"
                                    ),
                                    "conversation_id": conversation_id,
                                }

                    # Approve new MCP requests; break when none remain
                    new_approvals = [aid for aid in pending_approvals if aid not in auto_approved_ids]
                    if not new_approvals:
                        break
                    auto_approved_ids.update(new_approvals)
                    kwargs = {
                        "conversation": conversation_id,
                        "stream": True,
                        "extra_body": {"agent_reference": extra_agent},
                        "input": [
                            {"type": "mcp_approval_response", "approval_request_id": aid, "approve": True}
                            for aid in new_approvals
                        ],
                    }

                yield {"event": "done", "data": "complete", "conversation_id": conversation_id}

    finally:
        await credential.close()


async def _resolve_agent(
    project_client: AIProjectClient,
    agent_name: str,
    model: str,
    instructions: str,
    bing_connection_name: str,
) -> Any:
    """Fetch the existing agent or create a new version when missing or drifted."""

    bing_connection = await project_client.connections.get(bing_connection_name)
    tools = [
        BingGroundingTool(
            bing_grounding=BingGroundingSearchToolParameters(
                search_configurations=[
                    BingGroundingSearchConfiguration(project_connection_id=bing_connection.id)
                ]
            )
        ),
        WebSearchPreviewTool(
            user_location=ApproximateLocation(country="KR", city="Seoul", region="Seoul")
        ),
    ]

    definition = PromptAgentDefinition(
        kind="prompt", model=model, instructions=instructions, tools=tools
    )
    normalized = {
        "kind": "prompt",
        "model": model,
        "instructions": instructions,
        "tools": sorted(
            [_safe_serialize(t) for t in tools],
            key=lambda t: json.dumps(t, sort_keys=True),
        ),
    }
    config_hash = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()

    try:
        await project_client.agents.get(agent_name=agent_name)
        async for version in project_client.agents.list_versions(
            agent_name=agent_name, order="desc", limit=1
        ):
            version_meta = _safe_serialize(version).get("metadata", {})
            if isinstance(version_meta, dict) and version_meta.get("agent_config_hash") == config_hash:
                logger.info("Reusing existing agent version: %s", getattr(version, "version", None))
                return version
            break  # Config has drifted; fall through to create
    except ResourceNotFoundError:
        logger.info("Agent not found; creating: %s", agent_name)

    return await project_client.agents.create_version(
        agent_name=agent_name,
        definition=definition,
        metadata={"agent_config_hash": config_hash},
        description="Backend agent",
    )
```

---

*Source: `backend/app/agent.py` — `AzureAIFoundryAgent` class and associated module-level helpers.*
