import importlib
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BOT_DIR = os.path.join(ROOT, "bot")
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

STUBBED_MODULES = ["model_client", "tools", "prompts", "context_engine", "url_ingester", "agent"]


async def _empty_stream():
    if False:
        yield ""


def _stream_completion(*args, **kwargs):
    return _empty_stream()


class AgentLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_modules = {name: sys.modules.get(name) for name in STUBBED_MODULES}
        for module_name in STUBBED_MODULES:
            sys.modules.pop(module_name, None)

        model_client = types.ModuleType("model_client")
        model_client.chat_completion = AsyncMock()
        model_client.stream_completion = _stream_completion
        sys.modules["model_client"] = model_client

        tools = types.ModuleType("tools")
        tools.run_tool = AsyncMock()
        tools.tools_description = lambda: "calculator"
        sys.modules["tools"] = tools

        prompts = types.ModuleType("prompts")
        prompts.SYSTEM_PROMPT = "system"
        sys.modules["prompts"] = prompts

        context_engine = types.ModuleType("context_engine")
        context_engine.get_context = AsyncMock(return_value="")
        sys.modules["context_engine"] = context_engine

        url_ingester = types.ModuleType("url_ingester")
        url_ingester.extract_urls = lambda text: []
        url_ingester.fetch_url_text = AsyncMock()
        sys.modules["url_ingester"] = url_ingester

        self.agent = importlib.import_module("agent")

    async def asyncTearDown(self):
        for module_name, original in self.original_modules.items():
            if original is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original

    async def test_tool_success_log_omits_tool_result_text(self):
        with patch.object(self.agent, "_route", AsyncMock(return_value=("calculator", {"expression": "1+1"}, "calc"))), \
             patch.object(self.agent, "run_tool", AsyncMock(return_value="result with sk-secret-value")), \
             patch.object(self.agent.logger, "info") as log_info:
            await self.agent.run_agent("1+1", [], [])

        logged = " ".join(str(arg) for call in log_info.call_args_list for arg in call.args)
        self.assertIn("result_chars", logged)
        self.assertNotIn("sk-secret-value", logged)

    async def test_url_context_log_omits_path_query_and_credentials(self):
        with patch.object(self.agent, "extract_urls", return_value=["https://user:secret@example.com/path?token=sk-secret"]), \
             patch.object(self.agent, "fetch_url_text", AsyncMock(return_value=("Title", "content"))), \
             patch.object(self.agent.logger, "info") as log_info:
            await self.agent._fetch_url_context("see https://user:secret@example.com/path?token=sk-secret")

        logged = " ".join(str(arg) for call in log_info.call_args_list for arg in call.args)
        self.assertIn("example.com", logged)
        self.assertNotIn("sk-secret", logged)
        self.assertNotIn("/path", logged)

    async def test_tool_failure_log_omits_exception_message(self):
        with patch.object(self.agent, "_route", AsyncMock(return_value=("calculator", {"expression": "1+1"}, "calc"))), \
             patch.object(self.agent, "run_tool", AsyncMock(side_effect=RuntimeError("sk-secret-value"))), \
             patch.object(self.agent.logger, "error") as log_error:
            await self.agent.run_agent("1+1", [], [])

        logged = " ".join(str(arg) for call in log_error.call_args_list for arg in call.args)
        self.assertIn("RuntimeError", logged)
        self.assertNotIn("sk-secret-value", logged)


if __name__ == "__main__":
    unittest.main()
