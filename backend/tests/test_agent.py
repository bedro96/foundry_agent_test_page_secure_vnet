from __future__ import annotations

import os
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from azure.core.exceptions import ResourceNotFoundError

from app.agent import AzureAIFoundryAgent
from app.config import get_settings


class ResolveAgentTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)

    async def test_resolve_agent_uses_env_instructions_when_creating_new_agent(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AZURE_AI_AGENT_NAME": "factory-test-agent",
                "AZURE_AI_AGENT_INSTRUCTIONS": "System instruction from env",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            agent = AzureAIFoundryAgent(get_settings())
            agents_client = SimpleNamespace(
                get=AsyncMock(side_effect=ResourceNotFoundError("agent missing")),
            )
            project_client = SimpleNamespace(agents=agents_client)

            agent._build_tools = AsyncMock(return_value=[])

            captured: dict[str, object] = {}

            async def fake_create_agent_version(project_client_arg, definition, config_hash):
                captured["project_client"] = project_client_arg
                captured["definition"] = definition
                captured["config_hash"] = config_hash
                return {"created": True}

            agent._create_agent_version = fake_create_agent_version

            result = await agent._resolve_agent(project_client)

        self.assertEqual(result, {"created": True})
        self.assertIs(captured["project_client"], project_client)
        self.assertEqual(captured["definition"].instructions, "System instruction from env")
        self.assertEqual(captured["definition"].model, agent._settings.azure_ai_model)
        self.assertTrue(captured["config_hash"])
        agents_client.get.assert_awaited_once_with(agent_name="factory-test-agent")