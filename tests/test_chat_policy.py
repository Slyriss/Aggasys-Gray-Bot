import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BOT_DIR = os.path.join(ROOT, "bot")
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

from hermes.chat_policy import should_process_message, strip_bot_mention


def fake_update(chat_type="private", text="hello", reply_user=None):
    reply = SimpleNamespace(from_user=reply_user) if reply_user else None
    return SimpleNamespace(
        effective_chat=SimpleNamespace(type=chat_type),
        message=SimpleNamespace(text=text, caption=None, reply_to_message=reply),
    )


class ChatPolicyTests(unittest.TestCase):
    def test_private_chat_processes_without_mention(self):
        update = fake_update(chat_type="private", text="hello")

        self.assertTrue(should_process_message(update, bot_username="GrayBot", bot_id=99))

    def test_group_chat_ignores_unmentioned_text(self):
        update = fake_update(chat_type="group", text="hello team")

        self.assertFalse(should_process_message(update, bot_username="GrayBot", bot_id=99))

    def test_group_chat_processes_bot_mention(self):
        update = fake_update(chat_type="supergroup", text="@GrayBot summarize this")

        self.assertTrue(should_process_message(update, bot_username="GrayBot", bot_id=99))

    def test_group_chat_processes_reply_to_bot(self):
        reply_user = SimpleNamespace(id=99, username="GrayBot")
        update = fake_update(chat_type="group", text="yes please", reply_user=reply_user)

        self.assertTrue(should_process_message(update, bot_username="GrayBot", bot_id=99))

    def test_strip_bot_mention_removes_leading_mention(self):
        stripped = strip_bot_mention("@GrayBot, summarize this", "GrayBot")

        self.assertEqual(stripped, "summarize this")


if __name__ == "__main__":
    unittest.main()
