import os
import sys
import unittest
from unittest.mock import AsyncMock, patch


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BOT_DIR = os.path.join(ROOT, "bot")
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

import tools
from hermes import ActionStatus


class ToolPolicyBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_read_only_tool_executes_and_is_audited(self):
        with patch.object(tools, "record_decision", AsyncMock()) as record:
            result = await tools.run_tool("calculator", {"expression": "12 * 15"})

        self.assertEqual(result, "12 * 15 = 180")
        record.assert_awaited_once()
        decision = record.await_args.args[0]
        self.assertEqual(decision.status, ActionStatus.ALLOWED)
        self.assertEqual(decision.action.name, "calculator")

    async def test_unknown_tool_is_blocked_before_execution(self):
        with patch.object(tools, "record_decision", AsyncMock()) as record:
            result = await tools.run_tool("export_secret_report", {"query": "payroll"})

        self.assertIn("Hermes blocked this action", result)
        self.assertIn("allowed action registry", result)
        record.assert_awaited_once()
        decision = record.await_args.args[0]
        self.assertEqual(decision.status, ActionStatus.DENIED)
        self.assertEqual(decision.action.name, "export_secret_report")

    async def test_confirmation_required_tool_name_does_not_execute_without_approval(self):
        with patch.object(tools, "record_decision", AsyncMock()) as record:
            result = await tools.run_tool("send_external_message", {"recipient": "client"})

        self.assertIn("Hermes needs confirmation", result)
        self.assertIn("send_external_message", result)
        record.assert_awaited_once()
        decision = record.await_args.args[0]
        self.assertEqual(decision.status, ActionStatus.NEEDS_CONFIRMATION)


if __name__ == "__main__":
    unittest.main()
