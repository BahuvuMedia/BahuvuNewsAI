"""
BahuvuNewsAI - Telugu Speech Normalizer
=======================================

TTS-only Telugu normalization.

This module prepares approved Telugu newsroom narration for speech synthesis.
It must never be used for display text, headlines, captions, or graphics.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


MODULE_VERSION = "1.0.0"

SPACE_RE = re.compile(r"[ \t]+")
MULTIBLANK_RE = re.compile(r"\n{3,}")
ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
LATIN_TOKEN_RE = re.compile(r"(?<![A-Za-z])([A-Za-z][A-Za-z.]*)(?![A-Za-z])")


@dataclass(frozen=True, slots=True)
class SpeechNormalizationResult:
    original_text: str
    speech_text: str
    replacements: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.original_text != self.speech_text


# Longest and most specific expressions must appear first.
#
# These replacements affect speech only. Display text is never changed.
SPEECH_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    # Bahuvu News brand pronunciation.
    ("BAHUVU NEWS", "\u0c2c\u0c3e\u0c39\u0c41\u0c35\u0c41 \u0c28\u0c4d\u0c2f\u0c42\u0c38\u0c4d"),
    ("Bahuvu News", "\u0c2c\u0c3e\u0c39\u0c41\u0c35\u0c41 \u0c28\u0c4d\u0c2f\u0c42\u0c38\u0c4d"),
    ("bahuvu news", "\u0c2c\u0c3e\u0c39\u0c41\u0c35\u0c41 \u0c28\u0c4d\u0c2f\u0c42\u0c38\u0c4d"),
    ("BAHUVU", "\u0c2c\u0c3e\u0c39\u0c41\u0c35\u0c41"),
    ("Bahuvu", "\u0c2c\u0c3e\u0c39\u0c41\u0c35\u0c41"),
    ("bahuvu", "\u0c2c\u0c3e\u0c39\u0c41\u0c35\u0c41"),
    ("\u0c2c\u0c39\u0c41\u0c35\u0c41", "\u0c2c\u0c3e\u0c39\u0c41\u0c35\u0c41"),

    # News pronunciation.
    ("NEWS", "\u0c28\u0c4d\u0c2f\u0c42\u0c38\u0c4d"),
    ("News", "\u0c28\u0c4d\u0c2f\u0c42\u0c38\u0c4d"),
    ("news", "\u0c28\u0c4d\u0c2f\u0c42\u0c38\u0c4d"),
    ("\u0c28\u0c3f\u0c2f\u0c42\u0c38\u0c4d", "\u0c28\u0c4d\u0c2f\u0c42\u0c38\u0c4d"),

    # Minister pronunciation guidance for Azure Telugu.
    ("\u0c2e\u0c41\u0c16\u0c4d\u0c2f\u0c2e\u0c02\u0c24\u0c4d\u0c30\u0c3f",
     "\u0c2e\u0c41\u0c16\u0c4d\u0c2f \u0c2e\u0c28\u0c4d\u200c\u0c24\u0c4d\u0c30\u0c3f"),
    ("\u0c2a\u0c4d\u0c30\u0c27\u0c3e\u0c28\u0c2e\u0c02\u0c24\u0c4d\u0c30\u0c3f",
     "\u0c2a\u0c4d\u0c30\u0c27\u0c3e\u0c28 \u0c2e\u0c28\u0c4d\u200c\u0c24\u0c4d\u0c30\u0c3f"),
    ("\u0c15\u0c47\u0c02\u0c26\u0c4d\u0c30\u0c2e\u0c02\u0c24\u0c4d\u0c30\u0c3f",
     "\u0c15\u0c47\u0c02\u0c26\u0c4d\u0c30 \u0c2e\u0c28\u0c4d\u200c\u0c24\u0c4d\u0c30\u0c3f"),
    ("\u0c2e\u0c02\u0c24\u0c4d\u0c30\u0c3f",
     "\u0c2e\u0c28\u0c4d\u200c\u0c24\u0c4d\u0c30\u0c3f"),

    # Common broadcast acronyms.
    ("GDP", "\u0c1c\u0c40\u0c21\u0c40\u0c2a\u0c40"),
    ("G.D.P.", "\u0c1c\u0c40\u0c21\u0c40\u0c2a\u0c40"),
    ("AI", "\u0c0f\u0c10"),
    ("A.I.", "\u0c0f\u0c10"),
    ("CEO", "\u0c38\u0c40\u0c08\u0c13"),
    ("C.E.O.", "\u0c38\u0c40\u0c08\u0c13"),
    ("MP", "\u0c0e\u0c02\u0c2a\u0c40"),
    ("M.P.", "\u0c0e\u0c02\u0c2a\u0c40"),
    ("MLA", "\u0c0e\u0c2e\u0c4d\u0c2e\u0c46\u0c32\u0c4d\u0c2f\u0c47"),
    ("M.L.A.", "\u0c0e\u0c2e\u0c4d\u0c2e\u0c46\u0c32\u0c4d\u0c2f\u0c47"),
    ("MLC", "\u0c0e\u0c2e\u0c4d\u0c2e\u0c46\u0c32\u0c4d\u0c38\u0c40"),
    ("M.L.C.", "\u0c0e\u0c2e\u0c4d\u0c2e\u0c46\u0c32\u0c4d\u0c38\u0c40"),
    ("PM", "\u0c2a\u0c40\u0c0e\u0c02"),
    ("P.M.", "\u0c2a\u0c40\u0c0e\u0c02"),
    ("CM", "\u0c38\u0c40\u0c0e\u0c02"),
    ("C.M.", "\u0c38\u0c40\u0c0e\u0c02"),
    ("IPS", "\u0c10\u0c2a\u0c40\u0c0e\u0c38\u0c4d"),
    ("IAS", "\u0c10\u0c0f\u0c0e\u0c38\u0c4d"),
    ("CBI", "\u0c38\u0c40\u0c2c\u0c40\u0c10"),
    ("NIA", "\u0c0e\u0c28\u0c4d\u0c10\u0c0f"),
    ("BJP", "\u0c2c\u0c40\u0c1c\u0c47\u0c2a\u0c40"),
    ("TDP", "\u0c1f\u0c40\u0c21\u0c40\u0c2a\u0c40"),
    ("TRS", "\u0c1f\u0c40\u0c06\u0c30\u0c4d\u0c0e\u0c38\u0c4d"),
    ("BRS", "\u0c2c\u0c40\u0c06\u0c30\u0c4d\u0c0e\u0c38\u0c4d"),
    ("YSRCP", "\u0c35\u0c48\u0c0e\u0c38\u0c4d\u0c38\u0c3e\u0c30\u0c4d\u0c38\u0c40\u0c2a\u0c40"),
)


def _replace_case_insensitive(
    text: str,
    old: str,
    new: str,
) -> tuple[str, int]:
    if old.isascii():
        return re.subn(
            re.escape(old),
            lambda _match: new,
            text,
            flags=re.IGNORECASE,
        )

    count = text.count(old)
    return text.replace(old, new), count


def _normalize_punctuation(text: str) -> str:
    text = text.replace("\u0964", ".")
    text = text.replace("\u0965", ".")
    text = text.replace("\u2026", "...")
    text = text.replace("\u2013", "-")
    text = text.replace("\u2014", "-")

    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:])(?=\S)", r"\1 ", text)
    text = re.sub(r"([.!?])(?=\S)", r"\1 ", text)
    text = re.sub(r"([.!?])\1{2,}", r"\1", text)

    # Semicolons are usually spoken more naturally as light pauses.
    text = text.replace(";", ",")

    return text


def normalize_for_speech_with_report(
    value: str,
) -> SpeechNormalizationResult:
    original = str(value or "")
    text = original.replace("\r\n", "\n").replace("\r", "\n")

    # Remove invisible characters except the non-joiner deliberately inserted
    # by pronunciation replacements below.
    text = ZERO_WIDTH_RE.sub("", text)

    replacements: list[str] = []

    for old, new in SPEECH_REPLACEMENTS:
        updated, count = _replace_case_insensitive(text, old, new)
        if count:
            text = updated
            replacements.append(f"{old} -> {new} ({count})")

    text = _normalize_punctuation(text)

    lines: list[str] = []
    for line in text.splitlines():
        cleaned = SPACE_RE.sub(" ", line).strip()

        if not cleaned:
            lines.append("")
            continue

        # A complete narration line should end with speakable punctuation.
        if cleaned[-1] not in ".!?,":
            cleaned += "."

        lines.append(cleaned)

    text = "\n".join(lines)
    text = MULTIBLANK_RE.sub("\n\n", text).strip()

    return SpeechNormalizationResult(
        original_text=original,
        speech_text=text,
        replacements=tuple(replacements),
    )


def normalize_for_speech(value: str) -> str:
    return normalize_for_speech_with_report(value).speech_text


def _run_self_test() -> None:
    sample = (
        "BAHUVU NEWS. "
        "\u0c2e\u0c41\u0c16\u0c4d\u0c2f\u0c2e\u0c02\u0c24\u0c4d\u0c30\u0c3f "
        "GDP, AI \u0c17\u0c41\u0c30\u0c3f\u0c02\u0c1a\u0c3f "
        "\u0c2e\u0c3e\u0c1f\u0c4d\u0c32\u0c3e\u0c21\u0c3e\u0c30\u0c41"
    )

    result = normalize_for_speech_with_report(sample)

    assert "\u0c2c\u0c3e\u0c39\u0c41\u0c35\u0c41" in result.speech_text
    assert "\u0c28\u0c4d\u0c2f\u0c42\u0c38\u0c4d" in result.speech_text
    assert "\u0c2e\u0c28\u0c4d\u200c\u0c24\u0c4d\u0c30\u0c3f" in result.speech_text
    assert "\u0c1c\u0c40\u0c21\u0c40\u0c2a\u0c40" in result.speech_text
    assert "\u0c0f\u0c10" in result.speech_text

    print("BahuvuNewsAI Telugu speech normalizer")
    print(f"Module version  : {MODULE_VERSION}")
    print(f"Changed         : {result.changed}")
    print(f"Replacements    : {len(result.replacements)}")
    print(f"Speech text     : {result.speech_text}")
    print("Telugu speech normalizer self-test passed.")


if __name__ == "__main__":
    _run_self_test()
