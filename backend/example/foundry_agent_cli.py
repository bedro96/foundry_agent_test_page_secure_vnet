# flake8: noqa: E501
# pylint: disable=logging-fstring-interpolation, unused-import
"""Sample console application demonstrating the creation of an agent with Bing Grounding Tool and 
handling streaming responses
"""

import datetime
import os
import asyncio
import json
import sys
import logging
import logging.handlers
from pathlib import Path
import structlog
from structlog.stdlib import ProcessorFormatter
from dotenv import load_dotenv
from termcolor import cprint
from azure.identity.aio import DefaultAzureCredential, ClientSecretCredential
from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import (
    BingGroundingTool,                   # Tool wrapper for using Bing Grounding within an agent, allowing the agent to perform real-time web searches with grounding
    BingGroundingSearchToolParameters,  # Parameters for configuring the Bing Grounding Tool, including which search configurations to use
    BingGroundingSearchConfiguration,   # Configuration for Bing Grounding Tool to specify which Bing connection to use
    PromptAgentDefinition,              # Definition for a prompt-based agent that can utilize tools like Bing Grounding
    WebSearchPreviewTool,               # Web Search Preview Tool for real-time web search capabilities with user location context
    ApproximateLocation,                # Optional location information for web search preview tool to provide more relevant search results based on user's location
    BrowserAutomationPreviewTool,        # Tool wrapper for using Browser Automation within an agent, allowing the agent to perform automated web interactions
    BrowserAutomationToolParameters,    # Parameters for configuring the Browser Automation Tool, including which browser settings to use
    BrowserAutomationToolConnectionParameters # Parameters for connecting the Browser Automation Tool to a specific browser instance
)
from azure.core.exceptions import ResourceNotFoundError

# .env file is expected to be in the parent directory of this script (i.e., the backend/ directory) with necessary configuration values such as AZURE_AI_PROJECT_ENDPOINT, AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_AI_MODEL, BING_GROUNDING_CONNECTION_NAME, etc.
BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"

load_dotenv(dotenv_path=ENV_FILE, override=True)
# from custom_logging import set_logger

FILE_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | %(module)s:%(lineno)d | %(message)s"
)

def configure_logging() -> logging.Logger:
    """Configure process-wide logging based on the configured app mode."""

    is_development = os.getenv("APP_ENV") == "production"
    level = logging.DEBUG if is_development else logging.WARNING

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    # --- File handler (unchanged) ---
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_filename = os.path.join(
        log_dir, f"app_log_{datetime.datetime.now().strftime('%Y%m%d')}.log"
    )
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_filename, when="midnight", interval=1, backupCount=0, encoding="utf-8"
    )
    file_handler.suffix = "%Y%m%d"
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt="[%X]"))
    root_logger.addHandler(file_handler)

    # --- structlog configuration ---
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if is_development:
        # Add module/lineno callsite info in development
        shared_processors.insert(
            1,
            structlog.processors.CallsiteParameterAdder(
                [
                    structlog.processors.CallsiteParameter.MODULE,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
        )

    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # --- Console handler: JSON via structlog ---
    console_formatter = ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Suppress overly verbose logs from third-party libraries
    logging.getLogger("uvicorn").setLevel(level)
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(level)
    logging.getLogger("httpx").setLevel(level if is_development else logging.INFO)
    logging.getLogger("azure").setLevel(level)
    logging.getLogger("azure.core").setLevel(level)
    logging.getLogger("azure.identity").setLevel(level)
    logging.getLogger("azure.core.pipeline.transport").setLevel(level)
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
        level
    )

    logger = logging.getLogger(os.getenv("APP_LOGGER_NAME", "default_logger"))
    logger.setLevel(level)
    logger.propagate = True
    logger.debug("logging configured", extra={"app_mode": os.getenv("APP_ENV")})
    return logger

def _safe_serialize(obj):
    # Return a JSON-serializable representation of obj for logging
    if obj is None or isinstance(obj, (str, int, float, bool, list, dict)):
        return obj
    # Prefer SDK conversion helpers
    # Pydantic v2+: prefer `model_dump()` when available
    if hasattr(obj, 'model_dump'):
        try:
            return obj.model_dump()
        except Exception:
            pass
    # SDK/legacy helpers
    if hasattr(obj, 'as_dict'):
        try:
            return obj.as_dict()
        except Exception:
            pass
    # Older Pydantic versions expose `dict()`; keep as a last-resort fallback
    if hasattr(obj, 'dict'):
        try:
            return obj.dict()
        except Exception:
            pass
    # Try vars()
    try:
        return vars(obj)
    except Exception:
        return repr(obj)
# automatically pass app name to logger for better log file naming
# logger = set_logger(app_name=os.path.splitext(os.path.basename(__file__))[0])
# 환경변수에서 설정값 읽기
PROJECT_ENDPOINT = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
MODEL_DEPLOYMENT_NAME = os.getenv("AZURE_AI_MODEL", "gpt-4o") # Intended to miss and use default "gpt-4o"
BING_GROUNDING_CONNECTION_NAME = os.getenv("BING_GROUNDING_CONNECTION_NAME")

async def main():
    # Configure logging
    logger = configure_logging()
    logger.info("Starting Foundry Agent CLI application")
    # 인증 및 클라이언트 초기화
    # credential = DefaultAzureCredential()
    credential = ClientSecretCredential(
        tenant_id=os.getenv("AZURE_TENANT_ID"),
        client_id=os.getenv("AZURE_CLIENT_ID"),
        client_secret=os.getenv("AZURE_CLIENT_SECRET")
    )
    if not PROJECT_ENDPOINT or not MODEL_DEPLOYMENT_NAME or not BING_GROUNDING_CONNECTION_NAME:
        raise RuntimeError("Missing required environment variables: PROJECT_ENDPOINT, MODEL_DEPLOYMENT_NAME, BING_GROUNDING_CONNECTION_NAME")

    async with AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential) as project_client:
        # Bing 연결 ID 조회
        conn = await project_client.connections.get(BING_GROUNDING_CONNECTION_NAME)
        bing_conn_id = conn.id
        logger.info(f"Bing Grounding Connection ID: {bing_conn_id}")
        # playwright connection id from Microsoft Foundry Portal.
        playwright_connection_id = os.getenv("BROWSER_AUTOMATION_PROJECT_CONNECTION_ID")        
        # agent name in new Microsoft Foundry Portal.
        my_agent_name = "mcp-test-agent"
        try:
            existing_agent = await project_client.agents.get(agent_name=my_agent_name)
        except ResourceNotFoundError:
            existing_agent = None

        if existing_agent is None:
            logger.info(f"Agent '{my_agent_name}' not found. Creating new agent.")
            agent = await project_client.agents.create_version(
                agent_name=my_agent_name,
                definition=PromptAgentDefinition(
                    kind="prompt",
                    model=MODEL_DEPLOYMENT_NAME,
                    instructions="Use Bing grounding for real-time info especially date and time. \
                                Always, try to include citations.  \
                                Use Web Search for additional information. Always provide a \
                                final  answer based on the latest information.",
                    tools=[
                        BingGroundingTool(
                            bing_grounding=BingGroundingSearchToolParameters(
                                search_configurations=[
                                    BingGroundingSearchConfiguration(
                                        project_connection_id=bing_conn_id
                                    )
                                ]
                            )
                        ),
                        WebSearchPreviewTool(
                            user_location=ApproximateLocation(country="KR", city="Seoul", region="Seoul")
                        ),
                        BrowserAutomationPreviewTool(
                            browser_automation_preview=BrowserAutomationToolParameters(
                                connection=BrowserAutomationToolConnectionParameters(
                                    project_connection_id=playwright_connection_id,
                                )
                            )
                        )        
                    ]
                ),
                description="Bing grounding tool & Web Search",
            )
            logger.info(f"agent created with name: {agent.name}, version: {agent.version}")
        else:
            logger.info(f"Agent '{my_agent_name}' found. Existing agent will be used.")
            # Create a new version under the existing agent to update tool configuration\
            agent = existing_agent
            logger.info(f"Agent name: {agent.name} will be utilized")

        openai_client = project_client.get_openai_client()
        # Create conversation (await if the SDK returns a coroutine)
        _conversion_id = None
        while True:
            cprint("Please enter message to send to agent (or 'exit' to quit).", "magenta", attrs=["bold"])
            cprint("YOU :  ", "cyan", attrs=["bold"], end='')
            try:
                user_input = input()
                if user_input.lower() in ["quit", "exit"]:
                    logger.info("Exiting the conversation loop.")
                    sys.exit(1)
                if user_input.strip() == "":
                    logger.info("Empty input received and ignored.")
                    continue  # 빈 메시지는 무시
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received, exiting conversation loop.")
                cprint("\nExiting...", "red", attrs=["bold"])
                break
            except EOFError:
                logger.info("EOF received, exiting conversation loop.")
                cprint("\nExiting...", "red", attrs=["bold"])
                sys.exit(1)
                # Add user message to thread.
            # Ensure we have a conversation id. Create one once and reuse it.
            if _conversion_id is None:
                conversation = await openai_client.conversations.create(
                    items=[
                        { 'type': 'message', 'role': 'user', 'content': user_input }
                    ]
                )
                _conversion_id = conversation.id
            # Note: instead of calling a nonexistent `add_message`, we'll send the user's input
            # directly to `responses.create` below using `conversation=_conversion_id`.

            # Create response (may be streaming). If it's an async iterable, use async for; otherwise iterate normally.
            # Determine agent name/version for agent_reference; some SDK objects (AgentDetails)
            # don't have a single 'version' attribute, so list versions and pick the latest.
            agent_name = getattr(agent, 'name', None)
            agent_version = getattr(agent, 'version', None)
            if agent_version is None and agent_name:
                versions = []
                try:
                    async for v in project_client.agents.list_versions(agent_name=agent_name):
                        versions.append(v)
                except Exception:
                    versions = []
                if versions:
                    latest = versions[-1]
                    agent_version = getattr(latest, 'version', None)
            extra_agent = {"type": "agent_reference", "name": agent_name}
            if agent_version:
                extra_agent["version"] = agent_version

            # Send the user input to the Responses API; include conversation id when available
            if _conversion_id is not None:
                resp_result = await openai_client.responses.create(
                    conversation=_conversion_id,
                    input=user_input,
                    extra_body={"agent_reference": extra_agent},
                    stream=True,
                    tool_choice="required"  # required to ensure tools are used when agent is specified
                )
            else:
                resp_result = await openai_client.responses.create(
                    input=user_input,
                    extra_body={"agent_reference": extra_agent},
                    stream=True, 
                    tool_choice="required"
                )

            # Print response in real-time as it arrives (support async iterator or regular iterator)
            async for item in resp_result:
                if getattr(item,'type') == 'response.output_text.delta' and item.delta:
                    logger.info(f"Delta: {json.dumps(_safe_serialize(item.delta), indent=2, ensure_ascii=False)}")
                    cprint(item.delta,'green', end='')
                elif getattr(item,'type') == 'response.output_text' and item.text:
                    logger.info(f"Final text: {json.dumps(_safe_serialize(item.text), indent=2, ensure_ascii=False)}")
                    cprint(item.text,'magenta')
                elif getattr(item,'type') == 'response.output_text.done' and item.text:
                    logger.info(f"Complete output: {json.dumps(_safe_serialize(item.text), indent=2, ensure_ascii=False)}")
                    cprint("",'blue')
                elif getattr(item,'type') == 'response.completed' and item.response.usage:
                    logger.info(f"input_tokens: {getattr(item.response.usage, 'input_tokens', 'N/A')}, output_tokens: {getattr(item.response.usage, 'output_tokens', 'N/A')}, total_tokens: {getattr(item.response.usage, 'total_tokens', 'N/A')}")
                    cprint(f"\ninput_tokens: {getattr(item.response.usage, 'input_tokens', 'N/A')}, output_tokens: {getattr(item.response.usage, 'output_tokens', 'N/A')}, total_tokens: {getattr(item.response.usage, 'total_tokens', 'N/A')}",'yellow')
                    logger.info("Response completed successfully.")
                elif getattr(item, 'type') == 'response.created' and item.response.id:
                    logger.info(f"Response creation event received with response ID: {item.response.id}")
                    cprint("✨ : ",'green', attrs=["bold"], end='')
                elif getattr(item, 'type') == 'response.in_progress' and item.response.id:
                    logger.info(f"Response in progress event received with response ID: {item.response.id}")
                elif getattr(item, 'type') == 'response.output_item.added' and item.item.type:
                    logger.info(f"New output item added. Type: {json.dumps(_safe_serialize(item.item.type), indent=2, ensure_ascii=False)}")
                elif getattr(item, 'type') == 'response.content_part.added' and item.part:
                    logger.info(f"New content part added: {json.dumps(_safe_serialize(item.part), indent=2, ensure_ascii=False)}")
                elif getattr(item, 'type') == 'response.content_part.done' and item.part:
                    for annotation in _safe_serialize(item.part).get('annotations', []):
                        # cprint(f"\n[Annotation: {annotation} ", 'cyan', end='')
                        annotation_type = annotation.get("type") if isinstance(annotation, dict) else getattr(annotation, "type", None)
                        if annotation_type == 'url_citation':
                            title = annotation.get('title', 'N/A') if isinstance(annotation, dict) else getattr(annotation, 'title', 'N/A')
                            url = annotation.get('url', 'N/A') if isinstance(annotation, dict) else getattr(annotation, 'url', 'N/A')
                            cprint(f"\n[Annotation: {title} - {url} ] ", 'cyan', end='')
                    logger.info(f"Content part completed: {json.dumps(_safe_serialize(item.part), indent=2, ensure_ascii=False)}")
                elif getattr(item, 'type') == 'response.output_item.done' and item.item.type:
                    logger.info(f"Output item completed. Type: {json.dumps(_safe_serialize(item.item.type), indent=2, ensure_ascii=False)}")
                else:
                    logger.info(f"Unfiltered other items : {json.dumps(_safe_serialize(item), indent=2, ensure_ascii=False)}")
            
        await credential.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Suppress traceback on Ctrl+C; log to file only
        pass