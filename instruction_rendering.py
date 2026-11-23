"""Formatting helpers for the user guide in Telegram and the web app."""

import html
import re


TELEGRAM_MESSAGE_LIMIT = 3800


def instruction_plain_text(markdown_text: str) -> str:
    """Remove the small subset of Markdown used in instruction.md for Telegram."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", markdown_text, flags=re.DOTALL)
    text = re.sub(r"(?m)^#{1,6}\s+", "", text)
    return text.strip()


def split_telegram_messages(text: str, max_length: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Split text into safe-sized Telegram messages, preferring paragraph boundaries."""
    if max_length <= 0:
        raise ValueError("max_length must be positive")

    remaining = text.strip()
    messages = []
    while remaining:
        if len(remaining) <= max_length:
            messages.append(remaining)
            break

        boundary = remaining.rfind("\n\n", 0, max_length + 1)
        if boundary < 0:
            boundary = remaining.rfind("\n", 0, max_length + 1)
        if boundary < 0:
            boundary = remaining.rfind(" ", 0, max_length + 1)
        if boundary <= 0:
            boundary = max_length

        messages.append(remaining[:boundary].rstrip())
        remaining = remaining[boundary:].lstrip()

    return messages


def _inline_html(text: str) -> str:
    escaped = html.escape(text, quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def instruction_markdown_to_html(markdown_text: str) -> str:
    """Render the headings, paragraphs, lists, and bold text used by the guide."""
    rendered = []
    open_list = None

    def close_list():
        nonlocal open_list
        if open_list:
            rendered.append(f"</{open_list}>")
            open_list = None

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            close_list()
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            close_list()
            level = len(heading.group(1))
            rendered.append(f"<h{level}>{_inline_html(heading.group(2))}</h{level}>")
            continue

        item = re.match(r"^(?:[-*]\s+|\d+\.\s+)(.+)$", line)
        if item:
            ordered = bool(re.match(r"^\d+\.", line))
            list_type = "ol" if ordered else "ul"
            if open_list != list_type:
                close_list()
                rendered.append(f"<{list_type}>")
                open_list = list_type
            rendered.append(f"<li>{_inline_html(item.group(1))}</li>")
            continue

        close_list()
        rendered.append(f"<p>{_inline_html(line)}</p>")

    close_list()
    return "\n".join(rendered)
