import unittest
from pathlib import Path

from instruction_rendering import (
    TELEGRAM_MESSAGE_LIMIT,
    instruction_markdown_to_html,
    instruction_plain_text,
    split_telegram_messages,
)


class InstructionRenderingTests(unittest.TestCase):
    def test_current_guide_is_split_under_telegram_limit(self):
        guide = Path("instruction.md").read_text(encoding="utf-8")
        messages = split_telegram_messages(instruction_plain_text(guide))

        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message) <= TELEGRAM_MESSAGE_LIMIT for message in messages))
        self.assertTrue(all(message.strip() for message in messages))
        self.assertIn("Реєстрація та доступ", "\n".join(messages))
        self.assertIn("Команди та допомога", "\n".join(messages))

    def test_splits_at_preferred_boundaries_without_losing_text(self):
        text = "First paragraph.\n\nSecond paragraph.\nThird line."
        messages = split_telegram_messages(text, max_length=24)

        self.assertEqual(messages, ["First paragraph.", "Second paragraph.", "Third line."])

    def test_html_renderer_formats_guide_and_escapes_html(self):
        rendered = instruction_markdown_to_html(
            "# Guide\n\n**Bold** text\n\n- First\n- <script>alert(1)</script>"
        )

        self.assertIn("<h1>Guide</h1>", rendered)
        self.assertIn("<strong>Bold</strong> text", rendered)
        self.assertIn("<ul>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>", rendered)


if __name__ == "__main__":
    unittest.main()
