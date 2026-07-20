# news/telugu_editorial_desk.py
"""BahuvuNewsAI deterministic Telugu editorial desk and pre-TTS quality gate."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

MODULE_VERSION = "1.0.0"

TELUGU_RE = re.compile(r"[\u0C00-\u0C7F]")
LATIN_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9'._-]*\b")
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
NUMBER_RE = re.compile(r"\d+(?:[.,:/-]\d+)*(?:\s*%)?")
LIST_PREFIX_RE = re.compile(r"(?m)^\s*(?:[-*•]+\s*|\(?\d{1,3}[.)]\s+)")
SPACE_RE = re.compile(r"[ \t]+")
MULTIBLANK_RE = re.compile(r"\n{3,}")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?।])\s+")


class EditorialDeskError(RuntimeError):
    pass


class EditorialValidationError(EditorialDeskError):
    pass


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True, frozen=True)
class EditorialInput:
    headline: str
    intro: str
    body: str
    closing: str = ""
    language: str = "te"
    source_id: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class QualityIssue:
    code: str
    severity: Severity
    field_name: str
    message: str
    evidence: str = ""


@dataclass(slots=True, frozen=True)
class EditorialSettings:
    max_headline_chars: int = 120
    max_sentence_chars: int = 230
    minimum_telugu_ratio: float = 0.60
    maximum_latin_word_ratio: float = 0.18
    strict: bool = True
    allowed_latin_words: tuple[str, ...] = (
        "AI", "COVID", "GDP", "GST", "ISRO", "NASA", "FIR", "CBI",
        "ED", "CEO", "CM", "PM", "MP", "MLA", "IPL", "T20", "ODI",
        "UN", "US", "UK", "EU", "UPI", "ATM", "WiFi", "YouTube",
        "Google", "Microsoft", "OpenAI",
    )


@dataclass(slots=True)
class EditorialResult:
    headline: str
    intro: str
    body: str
    closing: str
    language: str = "te"
    approved: bool = False
    issues: list[QualityIssue] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def narration(self) -> str:
        return "\n\n".join(
            item.strip() for item in (self.intro, self.body, self.closing)
            if item.strip()
        )

    @property
    def errors(self) -> list[QualityIssue]:
        return [x for x in self.issues if x.severity == Severity.ERROR]


BOILERPLATE = (
    "subscribed with another email", "logout and login",
    "account subscription benefits", "premium stories",
    "unlock these with subscription", "the view from india",
    "first day first show", "today's cache",
    "your download of the top 5 technology stories",
    "read more", "click here", "advertisement",
)

PHRASE_REWRITES = (
    # Mechanical passive constructions -> natural Telugu newsroom wording.
    ("\u0c1a\u0c30\u0c4d\u0c1a\u0c3f\u0c02\u0c1a\u0c2c\u0c21\u0c3f\u0c02\u0c26\u0c3f",
     "\u0c1a\u0c30\u0c4d\u0c1a \u0c1c\u0c30\u0c3f\u0c17\u0c3f\u0c02\u0c26\u0c3f"),
    ("\u0c1a\u0c30\u0c4d\u0c1a\u0c3f\u0c02\u0c1a\u0c2c\u0c21\u0c4d\u0c21\u0c3e\u0c2f\u0c3f",
     "\u0c1a\u0c30\u0c4d\u0c1a \u0c1c\u0c30\u0c3f\u0c17\u0c3f\u0c02\u0c26\u0c3f"),
    ("\u0c28\u0c3f\u0c30\u0c4d\u0c23\u0c2f\u0c3f\u0c02\u0c1a\u0c2c\u0c21\u0c3f\u0c02\u0c26\u0c3f",
     "\u0c28\u0c3f\u0c30\u0c4d\u0c23\u0c2f\u0c02 \u0c24\u0c40\u0c38\u0c41\u0c15\u0c41\u0c28\u0c4d\u0c28\u0c3e\u0c30\u0c41"),
    ("\u0c2a\u0c4d\u0c30\u0c15\u0c1f\u0c3f\u0c02\u0c1a\u0c2c\u0c21\u0c3f\u0c02\u0c26\u0c3f",
     "\u0c2a\u0c4d\u0c30\u0c15\u0c1f\u0c3f\u0c02\u0c1a\u0c3e\u0c30\u0c41"),
    ("\u0c24\u0c46\u0c32\u0c3f\u0c2f\u0c1c\u0c47\u0c2f\u0c2c\u0c21\u0c3f\u0c02\u0c26\u0c3f",
     "\u0c24\u0c46\u0c32\u0c3f\u0c2a\u0c3e\u0c30\u0c41"),
    ("\u0c1a\u0c46\u0c2a\u0c4d\u0c2a\u0c2c\u0c21\u0c3f\u0c02\u0c26\u0c3f",
     "\u0c24\u0c46\u0c32\u0c3f\u0c2a\u0c3e\u0c30\u0c41"),
    ("\u0c35\u0c46\u0c32\u0c4d\u0c32\u0c21\u0c3f\u0c02\u0c1a\u0c2c\u0c21\u0c3f\u0c02\u0c26\u0c3f",
     "\u0c35\u0c46\u0c32\u0c4d\u0c32\u0c21\u0c3f\u0c02\u0c1a\u0c3e\u0c30\u0c41"),
    ("\u0c38\u0c4d\u0c2a\u0c37\u0c4d\u0c1f\u0c02 \u0c1a\u0c47\u0c2f\u0c2c\u0c21\u0c3f\u0c02\u0c26\u0c3f",
     "\u0c38\u0c4d\u0c2a\u0c37\u0c4d\u0c1f\u0c02 \u0c1a\u0c47\u0c36\u0c3e\u0c30\u0c41"),

    # Orders, notices and official actions.
    ("\u0c1c\u0c3e\u0c30\u0c40 \u0c1a\u0c47\u0c2f\u0c2c\u0c21\u0c3f\u0c02\u0c26\u0c3f",
     "\u0c1c\u0c3e\u0c30\u0c40 \u0c1a\u0c47\u0c36\u0c3e\u0c30\u0c41"),
    ("\u0c1c\u0c3e\u0c30\u0c40 \u0c1a\u0c47\u0c2f\u0c2c\u0c21\u0c4d\u0c21\u0c3e\u0c2f\u0c3f",
     "\u0c1c\u0c3e\u0c30\u0c40 \u0c1a\u0c47\u0c36\u0c3e\u0c30\u0c41"),
    ("\u0c06\u0c26\u0c47\u0c36\u0c3e\u0c32\u0c41 \u0c07\u0c35\u0c4d\u0c35\u0c2c\u0c21\u0c4d\u0c21\u0c3e\u0c2f\u0c3f",
     "\u0c06\u0c26\u0c47\u0c36\u0c3e\u0c32\u0c41 \u0c1c\u0c3e\u0c30\u0c40 \u0c1a\u0c47\u0c36\u0c3e\u0c30\u0c41"),
    ("\u0c39\u0c46\u0c1a\u0c4d\u0c1a\u0c30\u0c3f\u0c15\u0c32\u0c41 \u0c1c\u0c3e\u0c30\u0c40 \u0c1a\u0c47\u0c2f\u0c2c\u0c21\u0c4d\u0c21\u0c3e\u0c2f\u0c3f",
     "\u0c39\u0c46\u0c1a\u0c4d\u0c1a\u0c30\u0c3f\u0c15\u0c32\u0c41 \u0c1c\u0c3e\u0c30\u0c40 \u0c1a\u0c47\u0c36\u0c3e\u0c30\u0c41"),

    # Implementation and administrative actions.
    ("\u0c05\u0c2e\u0c32\u0c41 \u0c1a\u0c47\u0c2f\u0c2c\u0c21\u0c41\u0c24\u0c41\u0c02\u0c26\u0c3f",
     "\u0c05\u0c2e\u0c32\u0c41 \u0c1a\u0c47\u0c38\u0c4d\u0c24\u0c3e\u0c30\u0c41"),
    ("\u0c05\u0c2e\u0c32\u0c41 \u0c1a\u0c47\u0c2f\u0c2c\u0c21\u0c3f\u0c02\u0c26\u0c3f",
     "\u0c05\u0c2e\u0c32\u0c41 \u0c1a\u0c47\u0c36\u0c3e\u0c30\u0c41"),
    ("\u0c2a\u0c4d\u0c30\u0c3e\u0c30\u0c02\u0c2d\u0c3f\u0c02\u0c1a\u0c2c\u0c21\u0c3f\u0c02\u0c26\u0c3f",
     "\u0c2a\u0c4d\u0c30\u0c3e\u0c30\u0c02\u0c2d\u0c3f\u0c02\u0c1a\u0c3e\u0c30\u0c41"),
    ("\u0c0f\u0c30\u0c4d\u0c2a\u0c3e\u0c1f\u0c41 \u0c1a\u0c47\u0c2f\u0c2c\u0c21\u0c3f\u0c02\u0c26\u0c3f",
     "\u0c0f\u0c30\u0c4d\u0c2a\u0c3e\u0c1f\u0c41 \u0c1a\u0c47\u0c36\u0c3e\u0c30\u0c41"),
    ("\u0c28\u0c3f\u0c30\u0c4d\u0c35\u0c39\u0c3f\u0c02\u0c1a\u0c2c\u0c21\u0c3f\u0c02\u0c26\u0c3f",
     "\u0c28\u0c3f\u0c30\u0c4d\u0c35\u0c39\u0c3f\u0c02\u0c1a\u0c3e\u0c30\u0c41"),

    # Review, approval and investigation.
    ("\u0c2a\u0c30\u0c3f\u0c36\u0c40\u0c32\u0c3f\u0c02\u0c1a\u0c2c\u0c21\u0c41\u0c24\u0c41\u0c02\u0c26\u0c3f",
     "\u0c2a\u0c30\u0c3f\u0c36\u0c40\u0c32\u0c3f\u0c38\u0c4d\u0c24\u0c3e\u0c30\u0c41"),
    ("\u0c2a\u0c30\u0c3f\u0c17\u0c23\u0c3f\u0c02\u0c1a\u0c2c\u0c21\u0c41\u0c24\u0c41\u0c02\u0c26\u0c3f",
     "\u0c2a\u0c30\u0c3f\u0c36\u0c40\u0c32\u0c3f\u0c38\u0c4d\u0c24\u0c3e\u0c30\u0c41"),
    ("\u0c05\u0c28\u0c41\u0c2e\u0c24\u0c3f\u0c02\u0c1a\u0c2c\u0c21\u0c3f\u0c02\u0c26\u0c3f",
     "\u0c05\u0c28\u0c41\u0c2e\u0c24\u0c3f \u0c07\u0c1a\u0c4d\u0c1a\u0c3e\u0c30\u0c41"),
    ("\u0c06\u0c2e\u0c4b\u0c26\u0c3f\u0c02\u0c1a\u0c2c\u0c21\u0c3f\u0c02\u0c26\u0c3f",
     "\u0c06\u0c2e\u0c4b\u0c26\u0c02 \u0c32\u0c2d\u0c3f\u0c02\u0c1a\u0c3f\u0c02\u0c26\u0c3f"),
    ("\u0c26\u0c30\u0c4d\u0c2f\u0c3e\u0c2a\u0c4d\u0c24\u0c41 \u0c1a\u0c47\u0c2f\u0c2c\u0c21\u0c41\u0c24\u0c4b\u0c02\u0c26\u0c3f",
     "\u0c26\u0c30\u0c4d\u0c2f\u0c3e\u0c2a\u0c4d\u0c24\u0c41 \u0c15\u0c4a\u0c28\u0c38\u0c3e\u0c17\u0c41\u0c24\u0c4b\u0c02\u0c26\u0c3f"),

    # Common machine-translation constructions.
    ("\u0c08 \u0c35\u0c3f\u0c37\u0c2f\u0c02\u0c32\u0c4b \u0c05\u0c24\u0c28\u0c41 \u0c24\u0c46\u0c32\u0c3f\u0c2a\u0c3e\u0c30\u0c41",
     "\u0c08 \u0c35\u0c3f\u0c37\u0c2f\u0c3e\u0c28\u0c4d\u0c28\u0c3f \u0c06\u0c2f\u0c28 \u0c35\u0c46\u0c32\u0c4d\u0c32\u0c21\u0c3f\u0c02\u0c1a\u0c3e\u0c30\u0c41"),
    ("\u0c08 \u0c35\u0c3f\u0c37\u0c2f\u0c02\u0c32\u0c4b \u0c06\u0c2e\u0c46 \u0c24\u0c46\u0c32\u0c3f\u0c2a\u0c3e\u0c30\u0c41",
     "\u0c08 \u0c35\u0c3f\u0c37\u0c2f\u0c3e\u0c28\u0c4d\u0c28\u0c3f \u0c06\u0c2e\u0c46 \u0c35\u0c46\u0c32\u0c4d\u0c32\u0c21\u0c3f\u0c02\u0c1a\u0c3e\u0c30\u0c41"),
    ("\u0c05\u0c28\u0c3f \u0c05\u0c24\u0c28\u0c41 \u0c05\u0c28\u0c4d\u0c28\u0c3e\u0c30\u0c41",
     "\u0c05\u0c28\u0c3f \u0c06\u0c2f\u0c28 \u0c24\u0c46\u0c32\u0c3f\u0c2a\u0c3e\u0c30\u0c41"),
    ("\u0c05\u0c28\u0c3f \u0c06\u0c2e\u0c46 \u0c05\u0c28\u0c4d\u0c28\u0c3e\u0c30\u0c41",
     "\u0c05\u0c28\u0c3f \u0c06\u0c2e\u0c46 \u0c24\u0c46\u0c32\u0c3f\u0c2a\u0c3e\u0c30\u0c41"),
)


def normalize_text(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [SPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    return MULTIBLANK_RE.sub("\n\n", "\n".join(lines)).strip()


def remove_boilerplate(value: str) -> tuple[str, list[str]]:
    kept, removed = [], []
    for line in normalize_text(value).splitlines():
        if any(marker in line.casefold() for marker in BOILERPLATE):
            removed.append(line)
        else:
            kept.append(line)
    return normalize_text("\n".join(kept)), removed


def normalize_punctuation(value: str) -> str:
    text = normalize_text(value)
    text = LIST_PREFIX_RE.sub("", text)
    text = re.sub(r"\s+([,.;:!?।])", r"\1", text)
    text = re.sub(r"([,;:])(?=\S)", r"\1 ", text)
    text = re.sub(r"([.!?।])\1+", r"\1", text)
    text = re.sub(r"[–—]{2,}", "—", text)
    return normalize_text(text)


def rewrite_translationese(value: str) -> tuple[str, list[str]]:
    text = value
    changes: list[str] = []
    for old, new in PHRASE_REWRITES:
        if old in text:
            text = text.replace(old, new)
            changes.append(f"{old} -> {new}")
    return text, changes


def split_long_sentences(value: str, limit: int) -> tuple[str, int]:
    paragraphs, split_count = [], 0
    for paragraph in normalize_text(value).split("\n"):
        if not paragraph:
            paragraphs.append("")
            continue
        sentences = SENTENCE_SPLIT_RE.split(paragraph)
        output: list[str] = []
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) <= limit:
                output.append(sentence)
                continue
            parts = re.split(r"(?<=[,;:])\s+|\s+(?=అయితే|కాగా|అలాగే|అంతేకాక|దీంతో)", sentence)
            current = ""
            for part in parts:
                candidate = f"{current} {part}".strip()
                if current and len(candidate) > limit:
                    output.append(current.rstrip(",;:") + ".")
                    current = part
                    split_count += 1
                else:
                    current = candidate
            if current:
                output.append(current)
        paragraphs.append(" ".join(output))
    return normalize_text("\n".join(paragraphs)), split_count


def telugu_ratio(value: str) -> float:
    letters = [c for c in value if c.isalpha()]
    return 1.0 if not letters else sum(bool(TELUGU_RE.match(c)) for c in letters) / len(letters)


def unwanted_latin_words(value: str, allowed: tuple[str, ...]) -> list[str]:
    scrubbed = URL_RE.sub("", EMAIL_RE.sub("", value))
    allowed_set = {x.casefold() for x in allowed}
    return sorted({
        word for word in LATIN_WORD_RE.findall(scrubbed)
        if word.casefold() not in allowed_set
    })


def latin_word_ratio(value: str) -> float:
    words = re.findall(r"\b[\w\u0C00-\u0C7F'-]+\b", value)
    return 0.0 if not words else len(LATIN_WORD_RE.findall(value)) / len(words)


def duplicate_sentences(value: str) -> list[str]:
    seen, duplicates = set(), []
    for sentence in SENTENCE_SPLIT_RE.split(normalize_text(value)):
        key = re.sub(r"\W+", "", sentence, flags=re.UNICODE).casefold()
        if len(key) < 12:
            continue
        if key in seen:
            duplicates.append(sentence.strip())
        seen.add(key)
    return duplicates


class TeluguEditorialDesk:
    def __init__(self, settings: EditorialSettings | None = None) -> None:
        self.settings = settings or EditorialSettings()

    def _edit_field(self, name: str, value: str) -> tuple[str, list[str]]:
        changes: list[str] = []
        cleaned, removed = remove_boilerplate(value)
        if removed:
            changes.append(f"{name}: removed {len(removed)} boilerplate line(s)")
        punctuated = normalize_punctuation(cleaned)
        if punctuated != cleaned:
            changes.append(f"{name}: normalized punctuation/list formatting")
        rewritten, rewrites = rewrite_translationese(punctuated)
        changes.extend(f"{name}: {item}" for item in rewrites)
        split, count = split_long_sentences(
            rewritten,
            self.settings.max_sentence_chars,
        )
        if count:
            changes.append(f"{name}: split {count} long sentence(s)")
        return split, changes

    def _validate_field(
        self,
        name: str,
        value: str,
        required: bool,
    ) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        if required and not value.strip():
            return [QualityIssue(
                "empty_field", Severity.ERROR, name,
                f"{name} is empty.",
            )]
        if not value.strip():
            return issues

        ratio = telugu_ratio(value)
        if ratio < self.settings.minimum_telugu_ratio:
            issues.append(QualityIssue(
                "low_telugu_ratio", Severity.ERROR, name,
                f"Telugu character ratio {ratio:.1%} is below "
                f"{self.settings.minimum_telugu_ratio:.1%}.",
            ))

        latin = unwanted_latin_words(value, self.settings.allowed_latin_words)
        if latin:
            severity = (
                Severity.ERROR
                if latin_word_ratio(value) > self.settings.maximum_latin_word_ratio
                else Severity.WARNING
            )
            issues.append(QualityIssue(
                "english_leakage", severity, name,
                "Unexpected English words remain.",
                ", ".join(latin[:12]),
            ))

        duplicates = duplicate_sentences(value)
        if duplicates:
            issues.append(QualityIssue(
                "duplicate_sentence", Severity.ERROR, name,
                "Repeated narration sentence detected.",
                duplicates[0][:160],
            ))

        if name == "headline" and len(value) > self.settings.max_headline_chars:
            issues.append(QualityIssue(
                "long_headline", Severity.WARNING, name,
                f"Headline is {len(value)} characters; target is "
                f"{self.settings.max_headline_chars} or fewer.",
            ))
        return issues

    def edit(self, request: EditorialInput) -> EditorialResult:
        values: dict[str, str] = {}
        changes: list[str] = []

        for name in ("headline", "intro", "body", "closing"):
            values[name], field_changes = self._edit_field(
                name, getattr(request, name)
            )
            changes.extend(field_changes)

        issues: list[QualityIssue] = []
        for name, required in (
            ("headline", True), ("intro", False),
            ("body", True), ("closing", False),
        ):
            issues.extend(self._validate_field(name, values[name], required))

        if request.language.casefold() not in {"te", "telugu"}:
            issues.append(QualityIssue(
                "language_mismatch", Severity.ERROR, "language",
                f"Expected Telugu language code; received {request.language!r}.",
            ))

        approved = not any(x.severity == Severity.ERROR for x in issues)
        result = EditorialResult(
            **values,
            language="te",
            approved=approved,
            issues=issues,
            changes=changes,
            metadata={
                **dict(request.metadata),
                "editorial_desk_version": MODULE_VERSION,
                "source_id": request.source_id,
                "quality_gate": "passed" if approved else "failed",
                "change_count": len(changes),
                "issue_count": len(issues),
            },
        )

        if self.settings.strict and not approved:
            details = "; ".join(
                f"{x.field_name}:{x.code}" for x in result.errors
            )
            raise EditorialValidationError(
                f"Telugu editorial quality gate failed: {details}"
            )
        return result


def edit_telugu_bulletin(
    headline: str,
    intro: str,
    body: str,
    closing: str = "",
    *,
    strict: bool = True,
    source_id: str = "",
    metadata: Mapping[str, object] | None = None,
) -> EditorialResult:
    """Convenience API for production integration."""

    desk = TeluguEditorialDesk(EditorialSettings(strict=strict))
    return desk.edit(EditorialInput(
        headline=headline,
        intro=intro,
        body=body,
        closing=closing,
        language="te",
        source_id=source_id,
        metadata=metadata or {},
    ))


def _run_self_test() -> None:
    result = edit_telugu_bulletin(
        headline="ఆంధ్రప్రదేశ్‌లో భారీ వర్షాలు కొనసాగుతున్నాయి",
        intro="పలు జిల్లాల్లో అధికారులు హెచ్చరికలు జారీ చేయబడ్డాయి.",
        body=(
            "భారీ వర్షాల కారణంగా లోతట్టు ప్రాంతాల ప్రజలు అప్రమత్తంగా "
            "ఉండాలని అధికారులు సూచించారు. దర్యాప్తు చేయబడుతోంది."
        ),
        closing="మరిన్ని వార్తల కోసం బాహువు న్యూస్‌ను అనుసరించండి.",
        strict=True,
        source_id="editorial_desk_self_test",
    )

    assert result.approved
    assert "జారీ చేశారు" in result.intro
    assert "దర్యాప్తు కొనసాగుతోంది" in result.body
    assert result.language == "te"
    assert result.metadata["quality_gate"] == "passed"

    rejected = False
    try:
        edit_telugu_bulletin(
            headline="Breaking News Today",
            intro="",
            body="This narration is entirely in English.",
            strict=True,
        )
    except EditorialValidationError:
        rejected = True
    assert rejected

    print("BahuvuNewsAI Telugu editorial desk")
    print(f"Module version       : {MODULE_VERSION}")
    print(f"Approved             : {result.approved}")
    print(f"Changes applied      : {len(result.changes)}")
    print(f"Quality issues       : {len(result.issues)}")
    print(f"Telugu headline      : {result.headline}")
    print(f"Telugu intro         : {result.intro}")
    print("English rejection    : passed")
    print("Telugu editorial desk self-test passed.")


if __name__ == "__main__":
    _run_self_test()