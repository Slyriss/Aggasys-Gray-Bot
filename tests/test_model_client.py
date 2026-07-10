import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BOT_DIR = os.path.join(ROOT, "bot")
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

sys.modules.pop("model_client", None)
import model_client


class ModelClientTests(unittest.TestCase):
    def test_deepseek_payload_uses_openai_compatible_shape(self):
        payload = model_client._openai_payload(
            messages=[{"role": "user", "content": "hello"}],
            system="system",
            user_memory=None,
            temperature=0.2,
            stream=False,
        )

        self.assertEqual(payload["model"], model_client.DEEPSEEK_MODEL)
        self.assertEqual(payload["temperature"], 0.2)
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "system"})

    def test_openai_text_extractors_handle_chat_and_stream_chunks(self):
        text = model_client._extract_openai_text({
            "choices": [{"message": {"content": "answer"}}],
        })
        delta = model_client._extract_openai_delta({
            "choices": [{"delta": {"content": "chunk"}}],
        })

        self.assertEqual(text, "answer")
        self.assertEqual(delta, "chunk")

    def test_deepseek_url_targets_chat_completions_endpoint(self):
        self.assertTrue(model_client._deepseek_chat_url().endswith("/chat/completions"))


if __name__ == "__main__":
    unittest.main()
