# news/content_cleaner.py

"""
BahuvuNewsAI - Publisher Content Cleaner
========================================

Removes subscription prompts, newsletter promotions, navigation labels,
comment instructions and other publisher boilerplate before article text
enters ranking, scripting, translation or narration.

This module deliberately keeps raw_text available for traceability while
producing a separate newsroom-safe cleaned_text value.
"""

from __future__ import annotations

import html
import re
from typing import Iterable


MODULE_NAME = "BahuvuNewsAI Publisher Content Cleaner"
MODULE_VERSION = "1.0.0"


_LEADING_PREFIXES = (
    "subscribed with another email",
    "logout and login",
    "account subscription benefits",
    "premium stories",
    "editorials, opinions and more",
    "unlock these with subscription",
    "the view from india",
    "looking at world affairs",
    "first day first show",
    "news and reviews from the world of cinema",
    "today's cache",
    "todays cache",
    "your download of the top 5 technology stories",
    "science for all",
    "the weekly newsletter from science writers",
    "data point",
    "decoding the headlines with facts",
    "thedge",
    "at the cutting edge of education and careers",
    "health matters",
    "ramya kannan writes to you",
    "gender agenda",
    "stories from beyond the binary",
    "the hindu on books",
    "books of the week, reviews",
)

_TRAILING_PREFIXES = (
    "terms & conditions",
    "terms and conditions",
    "institutional subscriber",
    "comments have to be in english",
    "please abide by our community guidelines",
    "we have migrated to a new commenting platform",
    "if you are already a registered user of the hindu",
    "users can access their older comments",
)

_NOISE_PREFIXES = (
    "also watch",
    "also read",
    "follow here:",
    "photo credit:",
    "image used for representation",
)

_DATE_LINE_RE = re.compile(
    r"^(?:published|updated)\s*-\s*.+?\bIST\b(?:\s*-\s*.+)?$",
    flags=re.IGNORECASE,
)

_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _normalize_paragraph(value: str) -> str:
    value = html.unescape(str(value or ""))
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = (
        value.replace("â€œ", "“")
        .replace("â€", "”")
        .replace("â€™", "’")
        .replace("â€˜", "‘")
        .replace("â€¦", "…")
        .replace("â€”", "—")
        .replace("â€“", "–")
    )
    value = _WHITESPACE_RE.sub(" ", value)
    return value.strip()


def _starts_with_any(value: str, prefixes: Iterable[str]) -> bool:
    lowered = value.casefold()
    return any(lowered.startswith(prefix) for prefix in prefixes)


def clean_publisher_content(value: str) -> str:
    """Return newsroom-safe article copy without publisher boilerplate."""

    normalized = str(value or "").replace("\r\n", "\n").replace("\r", "\n")

    raw_parts = re.split(r"\n\s*\n", normalized)
    parts = [
        _normalize_paragraph(part)
        for part in raw_parts
        if _normalize_paragraph(part)
    ]

    cleaned: list[str] = []
    article_started = False

    for part in parts:
        lowered = part.casefold()

        if _starts_with_any(part, _TRAILING_PREFIXES):
            if article_started:
                break
            continue

        if _starts_with_any(part, _LEADING_PREFIXES):
            continue

        if _DATE_LINE_RE.match(part):
            article_started = True
            continue

        if _starts_with_any(part, _NOISE_PREFIXES):
            continue

        if (
            "photo credit:" in lowered
            and len(part.split()) <= 25
        ):
            continue

        # Taxonomy/footer rows usually contain many slash-separated labels.
        if part.count(" / ") >= 3 and len(part) < 350:
            continue

        # A useful article paragraph normally has sentence-level content.
        if not article_started:
            word_count = len(part.split())
            sentence_signal = any(mark in part for mark in (".", "”", "’", ":", ";"))

            if word_count >= 12 and sentence_signal:
                article_started = True
            else:
                continue

        cleaned.append(part)

    result = "\n\n".join(cleaned).strip()
    result = _BLANK_LINES_RE.sub("\n\n", result)

    return result


def assert_clean_content(value: str) -> None:
    """Raise when known publisher contamination remains."""

    lowered = str(value or "").casefold()

    forbidden = (
        "subscribed with another email",
        "account subscription benefits",
        "first day first show",
        "today's cache",
        "comments have to be in english",
        "we have migrated to a new commenting platform",
    )

    remaining = [marker for marker in forbidden if marker in lowered]

    if remaining:
        raise ValueError(
            "Publisher boilerplate remains after cleaning: "
            + ", ".join(remaining)
        )


def _run_self_test() -> None:
    sample = """
    Subscribed with another email? Logout and Login with that one.

    Account subscription benefits alongside Premium Stories.

    First Day First Show News and reviews from cinema.

    Today's Cache Your download of the top 5 technology stories.

    Updated - July 20, 2026 11:43 am IST - Mumbai

    Benchmark indices Sensex and Nifty declined in early trade on Monday.
    HDFC Bank shares fell after quarterly earnings were announced.

    Terms & conditions | Institutional Subscriber

    Comments have to be in English, and in full sentences.
    """

    cleaned = clean_publisher_content(sample)

    assert "Benchmark indices" in cleaned
    assert "HDFC Bank" in cleaned
    assert "Subscribed with another email" not in cleaned
    assert "Today's Cache" not in cleaned
    assert "Terms & conditions" not in cleaned

    assert_clean_content(cleaned)

    print(MODULE_NAME)
    print(f"Module version : {MODULE_VERSION}")
    print(f"Characters     : {len(cleaned)}")
    print("Publisher content cleaner self-test passed.")


if __name__ == "__main__":
    _run_self_test()
