import os
import sys
import unittest
from pathlib import Path


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT_PATH = Path(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class HarnessPromptTests(unittest.TestCase):
    def test_router_prompt_forbids_invented_or_side_effect_tools(self):
        agent_py = (ROOT_PATH / "bot" / "agent.py").read_text(encoding="utf-8")

        self.assertIn("Choose only a tool listed above", agent_py)
        self.assertIn("Never invent tool names", agent_py)
        self.assertIn("Do not route requests to spend money", agent_py)
        self.assertIn('{"tool": null}', agent_py)

    def test_system_prompt_contains_hermes_operating_guardrails(self):
        prompts_py = (ROOT_PATH / "bot" / "prompts.py").read_text(encoding="utf-8")

        self.assertIn("Hermes operating guardrails", prompts_py)
        self.assertIn("explicit approval through Hermes", prompts_py)
        self.assertIn("Supply ordering is intentionally not implemented yet", prompts_py)
        self.assertIn("untrusted content", prompts_py)


if __name__ == "__main__":
    unittest.main()
