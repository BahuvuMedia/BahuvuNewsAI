"""
BahuvuNewsAI - Editorial Polisher
=================================

A deterministic, production-oriented editorial polishing engine for English
broadcast-news scripts.

The module improves grammar, clarity, sentence flow, neutrality, punctuation,
broadcast readability, and consistency without intentionally changing facts.

Typical pipeline position:

    script_generator
        -> editorial_polisher
        -> telugu_translator
        -> voice generation

Run:

    python -m py_compile news/editorial_polisher.py
    python -m news.editorial_polisher

The module is deliberately self-contained and uses only the Python standard
library. It can accept:

* PolishedScriptInput
* dictionaries
* dataclass-like objects
* script objects exposing headline / intro / body / closing attributes
* plain strings

The output is always a PolishingResult.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from enum import Enum
import copy
import math
import re
import statistics
import unicodedata
from typing import Any, Iterable, Mapping, MutableMapping, Sequence


# =============================================================================
# ENUMERATIONS
# =============================================================================


class EditorialTone(str, Enum):
    """Supported editorial tones."""

    NEUTRAL = "neutral"
    FORMAL = "formal"
    CONVERSATIONAL = "conversational"
    BREAKING = "breaking"
    EXPLAINER = "explainer"


class EditorialSeverity(str, Enum):
    """Severity assigned to an editorial issue."""

    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class ChangeCategory(str, Enum):
    """Categories used for the editorial change log."""

    NORMALIZATION = "normalization"
    GRAMMAR = "grammar"
    PUNCTUATION = "punctuation"
    CAPITALIZATION = "capitalization"
    CLARITY = "clarity"
    FLOW = "flow"
    TONE = "tone"
    REPETITION = "repetition"
    BROADCAST_STYLE = "broadcast_style"
    SAFETY = "safety"


class ScriptSection(str, Enum):
    """Canonical script sections."""

    HEADLINE = "headline"
    INTRO = "intro"
    BODY = "body"
    CLOSING = "closing"


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass(slots=True)
class EditorialStyle:
    """
    Editorial style configuration.

    The defaults are suitable for professional neutral English news scripts
    that will later be translated into Telugu.
    """

    tone: EditorialTone = EditorialTone.NEUTRAL
    target_words_per_sentence: int = 18
    maximum_words_per_sentence: int = 32
    minimum_words_per_sentence: int = 4
    maximum_paragraph_words: int = 90
    minimum_quality_score: float = 80.0
    preserve_quotes: bool = True
    preserve_numbers: bool = True
    preserve_proper_names: bool = True
    use_active_voice_preference: bool = True
    normalize_whitespace: bool = True
    normalize_unicode: bool = True
    normalize_punctuation: bool = True
    simplify_parentheses: bool = True
    remove_repeated_sentences: bool = True
    remove_repeated_phrases: bool = True
    remove_sensational_language: bool = True
    require_complete_sentences: bool = True
    allow_headline_without_period: bool = True


@dataclass(slots=True)
class PolishedScriptInput:
    """Canonical input accepted by the editorial polisher."""

    headline: str = ""
    intro: str = ""
    body: str = ""
    closing: str = ""
    language: str = "en"
    source_script_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def combined_text(self) -> str:
        """Return all non-empty sections as one readable string."""

        parts = [
            self.headline.strip(),
            self.intro.strip(),
            self.body.strip(),
            self.closing.strip(),
        ]
        return "\n\n".join(part for part in parts if part)


@dataclass(slots=True)
class EditorialChange:
    """A single recorded editorial change."""

    section: ScriptSection
    category: ChangeCategory
    before: str
    after: str
    reason: str

    @property
    def changed(self) -> bool:
        return self.before != self.after


@dataclass(slots=True)
class EditorialIssue:
    """An issue detected before or after polishing."""

    section: ScriptSection
    severity: EditorialSeverity
    code: str
    message: str
    excerpt: str = ""


@dataclass(slots=True)
class SectionMetrics:
    """Metrics calculated for one script section."""

    words: int = 0
    sentences: int = 0
    paragraphs: int = 0
    average_words_per_sentence: float = 0.0
    longest_sentence_words: int = 0
    repeated_sentence_count: int = 0
    sensational_term_count: int = 0
    incomplete_sentence_count: int = 0


@dataclass(slots=True)
class PolishedScript:
    """Final polished script."""

    headline: str
    intro: str
    body: str
    closing: str
    language: str = "en"
    source_script_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def combined_text(self) -> str:
        parts = [
            self.headline.strip(),
            self.intro.strip(),
            self.body.strip(),
            self.closing.strip(),
        ]
        return "\n\n".join(part for part in parts if part)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PolishingResult:
    """Complete result returned by EditorialPolisher."""

    script: PolishedScript
    quality_score: float
    production_ready: bool
    changes: list[EditorialChange] = field(default_factory=list)
    issues: list[EditorialIssue] = field(default_factory=list)
    metrics: dict[str, SectionMetrics] = field(default_factory=dict)
    editorial_notes: list[str] = field(default_factory=list)

    @property
    def changes_applied(self) -> int:
        return sum(1 for change in self.changes if change.changed)

    @property
    def blocking_issues(self) -> int:
        return sum(
            1 for issue in self.issues
            if issue.severity == EditorialSeverity.BLOCKING
        )

    @property
    def warning_issues(self) -> int:
        return sum(
            1 for issue in self.issues
            if issue.severity == EditorialSeverity.WARNING
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "script": self.script.to_dict(),
            "quality_score": self.quality_score,
            "production_ready": self.production_ready,
            "changes_applied": self.changes_applied,
            "changes": [asdict(item) for item in self.changes],
            "issues": [asdict(item) for item in self.issues],
            "metrics": {
                name: asdict(metric)
                for name, metric in self.metrics.items()
            },
            "editorial_notes": list(self.editorial_notes),
        }


@dataclass(slots=True)
class PolishingSummary:
    """Aggregate statistics for a batch."""

    scripts_processed: int = 0
    scripts_ready: int = 0
    scripts_not_ready: int = 0
    total_changes: int = 0
    grammar_improvements: int = 0
    punctuation_improvements: int = 0
    style_improvements: int = 0
    tone_adjustments: int = 0
    repetition_removals: int = 0
    average_quality_score: float = 0.0

    @classmethod
    def from_results(
        cls,
        results: Sequence[PolishingResult],
    ) -> "PolishingSummary":
        scores = [result.quality_score for result in results]
        categories = [
            change.category
            for result in results
            for change in result.changes
            if change.changed
        ]

        ready = sum(1 for result in results if result.production_ready)

        return cls(
            scripts_processed=len(results),
            scripts_ready=ready,
            scripts_not_ready=len(results) - ready,
            total_changes=sum(result.changes_applied for result in results),
            grammar_improvements=categories.count(ChangeCategory.GRAMMAR),
            punctuation_improvements=categories.count(
                ChangeCategory.PUNCTUATION
            ),
            style_improvements=sum(
                1
                for category in categories
                if category
                in {
                    ChangeCategory.CLARITY,
                    ChangeCategory.FLOW,
                    ChangeCategory.BROADCAST_STYLE,
                    ChangeCategory.CAPITALIZATION,
                    ChangeCategory.NORMALIZATION,
                }
            ),
            tone_adjustments=categories.count(ChangeCategory.TONE),
            repetition_removals=categories.count(
                ChangeCategory.REPETITION
            ),
            average_quality_score=round(
                statistics.fmean(scores), 2
            ) if scores else 0.0,
        )


# =============================================================================
# CONSTANTS
# =============================================================================


_SECTION_NAMES: tuple[ScriptSection, ...] = (
    ScriptSection.HEADLINE,
    ScriptSection.INTRO,
    ScriptSection.BODY,
    ScriptSection.CLOSING,
)

_SENTENCE_END_RE = re.compile(r'(?<=[.!?])(?:["\']?)(?=\s+|$)')
_WORD_RE = re.compile(r"\b[\w’'-]+\b", re.UNICODE)
_MULTI_SPACE_RE = re.compile(r"[ \t]+")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")
_MISSING_SPACE_AFTER_PUNCT_RE = re.compile(
    r"([,.;:!?])(?=[A-Za-z])"
)
_REPEAT_PUNCT_RE = re.compile(r"([!?.,])\1+")
_DUPLICATE_WORD_RE = re.compile(
    r"\b([A-Za-z][A-Za-z'-]*)\s+\1\b",
    re.IGNORECASE,
)
_LEADING_CONNECTOR_RE = re.compile(
    r"^(and|but|so|also|then)\s*,?\s+",
    re.IGNORECASE,
)
_ALL_CAPS_WORD_RE = re.compile(r"\b[A-Z]{5,}\b")
_NUMBER_RE = re.compile(
    r"(?<!\w)(?:₹|\$|€|£)?\d[\d,]*(?:\.\d+)?%?(?!\w)"
)
_QUOTED_TEXT_RE = re.compile(r'(["“]).*?(["”])', re.DOTALL)
_ABBREVIATION_RE = re.compile(
    r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|No|vs|etc)\.$",
    re.IGNORECASE,
)

_SENSATIONAL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bshocking\b", "significant"),
    (r"\bstunning\b", "notable"),
    (r"\bexplosive\b", "major"),
    (r"\bmassive\b", "large"),
    (r"\bhuge\b", "large"),
    (r"\bunbelievable\b", "unexpected"),
    (r"\bterrifying\b", "serious"),
    (r"\bhorrific\b", "severe"),
    (r"\bdevastating\b", "severe"),
    (r"\bchaos\b", "disruption"),
    (r"\bbombshell\b", "major development"),
    (r"\bslams\b", "criticizes"),
    (r"\bblasts\b", "criticizes"),
    (r"\bdestroys\b", "strongly challenges"),
    (r"\bcrushes\b", "defeats"),
    (r"\bmiracle\b", "unexpected outcome"),
    (r"\bgame[- ]changer\b", "major change"),
)

_GRAMMAR_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\baccording to the reports\b", "according to reports"),
    (r"\bas per the reports\b", "according to reports"),
    (r"\bin regards to\b", "regarding"),
    (r"\bwith regards to\b", "regarding"),
    (r"\bdue to the fact that\b", "because"),
    (r"\bat this point in time\b", "now"),
    (r"\bin order to\b", "to"),
    (r"\bhas been announced by\b", "was announced by"),
    (r"\bthere is a possibility that\b", "may"),
    (r"\bit is being reported that\b", "reports indicate that"),
    (r"\bthe reason is because\b", "the reason is that"),
    (r"\bmore better\b", "better"),
    (r"\bmost important priority\b", "top priority"),
    (r"\bnew innovation\b", "innovation"),
    (r"\bpast history\b", "history"),
    (r"\bfuture plans\b", "plans"),
    (r"\bfinal outcome\b", "outcome"),
    (r"\bclose proximity\b", "proximity"),
)

_BROADCAST_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\butilize\b", "use"),
    (r"\bapproximately\b", "about"),
    (r"\bcommence\b", "begin"),
    (r"\bterminate\b", "end"),
    (r"\bsubsequent to\b", "after"),
    (r"\bprior to\b", "before"),
    (r"\bwith the exception of\b", "except"),
    (r"\ba large number of\b", "many"),
    (r"\ba majority of\b", "most"),
    (r"\bhas the ability to\b", "can"),
    (r"\bis able to\b", "can"),
    (r"\bmake a decision\b", "decide"),
    (r"\bconduct an investigation\b", "investigate"),
    (r"\bprovide assistance\b", "assist"),
)

_WEAK_OPENINGS: tuple[str, ...] = (
    "it is important to note that ",
    "it should be noted that ",
    "we would like to inform you that ",
    "as we know, ",
    "as everyone knows, ",
)

_INCOMPLETE_STARTERS: tuple[str, ...] = (
    "because ",
    "although ",
    "while ",
    "despite ",
    "unless ",
    "since ",
)

_ALLOWED_UPPERCASE: frozenset[str] = frozenset(
    {
        "AI",
        "AP",
        "BBC",
        "CBI",
        "CEO",
        "CM",
        "COVID",
        "DNA",
        "EU",
        "FIR",
        "GDP",
        "GST",
        "IMD",
        "IPS",
        "IAS",
        "ISRO",
        "IT",
        "MLA",
        "MP",
        "NASA",
        "NATO",
        "NGO",
        "PM",
        "RBI",
        "SIT",
        "UK",
        "UN",
        "UPI",
        "US",
        "USA",
        "WHO",
    }
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _safe_string(value: Any) -> str:
    """Convert a value to a safe string."""

    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _split_paragraphs(text: str) -> list[str]:
    return [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", text.strip())
        if paragraph.strip()
    ]


def _split_sentences(text: str) -> list[str]:
    """
    Split text into sentences without external NLP dependencies.

    The implementation is intentionally conservative so initials, decimals,
    and common abbreviations are less likely to be split incorrectly.
    """

    normalized = _MULTI_SPACE_RE.sub(" ", text.strip())
    if not normalized:
        return []

    sentences: list[str] = []
    buffer: list[str] = []

    for index, char in enumerate(normalized):
        buffer.append(char)

        if char not in ".!?":
            continue

        current = "".join(buffer).strip()
        next_char = (
            normalized[index + 1]
            if index + 1 < len(normalized)
            else ""
        )

        if char == ".":
            if (
                index > 0
                and index + 1 < len(normalized)
                and normalized[index - 1].isdigit()
                and normalized[index + 1].isdigit()
            ):
                continue
            if _ABBREVIATION_RE.search(current):
                continue

        if not next_char or next_char.isspace() or next_char in "\"'”’":
            sentences.append(current)
            buffer = []

    remainder = "".join(buffer).strip()
    if remainder:
        sentences.append(remainder)

    return sentences


def _sentence_key(sentence: str) -> str:
    key = unicodedata.normalize("NFKC", sentence).casefold()
    key = re.sub(r"[^\w\s]", "", key)
    key = _MULTI_SPACE_RE.sub(" ", key).strip()
    return key


def _preserved_tokens(text: str) -> dict[str, list[str]]:
    """Capture tokens that should not be accidentally changed."""

    return {
        "numbers": _NUMBER_RE.findall(text),
        "quotes": [
            match.group(0)
            for match in _QUOTED_TEXT_RE.finditer(text)
        ],
    }


def _token_preservation_issues(
    before: str,
    after: str,
    style: EditorialStyle,
) -> list[str]:
    """Return descriptions of potentially changed factual tokens."""

    issues: list[str] = []
    before_tokens = _preserved_tokens(before)
    after_tokens = _preserved_tokens(after)

    if (
        style.preserve_numbers
        and before_tokens["numbers"] != after_tokens["numbers"]
    ):
        issues.append("Numeric content changed during polishing.")

    if (
        style.preserve_quotes
        and before_tokens["quotes"] != after_tokens["quotes"]
    ):
        issues.append("Quoted content changed during polishing.")

    return issues


def _coerce_mapping(value: Any) -> dict[str, Any]:
    """
    Convert an input object to a shallow mapping.

    This supports dictionaries, dataclasses, and ordinary objects.
    """

    if isinstance(value, Mapping):
        return dict(value)

    if is_dataclass(value):
        return asdict(value)

    if hasattr(value, "__dict__"):
        return dict(vars(value))

    return {}


def _extract_first(
    mapping: Mapping[str, Any],
    names: Sequence[str],
    default: Any = "",
) -> Any:
    for name in names:
        if name in mapping and mapping[name] is not None:
            return mapping[name]
    return default


def _normalize_body_value(value: Any) -> str:
    """Normalize body values that may be strings or lists of paragraphs."""

    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence) and not isinstance(
        value,
        (bytes, bytearray, str),
    ):
        return "\n\n".join(
            _safe_string(item).strip()
            for item in value
            if _safe_string(item).strip()
        )
    return _safe_string(value)


def coerce_script_input(value: Any) -> PolishedScriptInput:
    """
    Convert supported inputs into PolishedScriptInput.

    Accepted aliases include:
      headline/title
      intro/lead/opening
      body/content/script/narration
      closing/outro/signoff
    """

    if isinstance(value, PolishedScriptInput):
        return copy.deepcopy(value)

    if isinstance(value, PolishedScript):
        return PolishedScriptInput(
            headline=value.headline,
            intro=value.intro,
            body=value.body,
            closing=value.closing,
            language=value.language,
            source_script_id=value.source_script_id,
            metadata=copy.deepcopy(value.metadata),
        )

    if isinstance(value, str):
        return PolishedScriptInput(body=value)

    mapping = _coerce_mapping(value)
    if not mapping:
        raise TypeError(
            "Unsupported script input. Provide a string, mapping, dataclass, "
            "or object with script attributes."
        )

    headline = _safe_string(
        _extract_first(mapping, ("headline", "title", "news_headline"))
    )
    intro = _safe_string(
        _extract_first(mapping, ("intro", "lead", "opening", "anchor_intro"))
    )
    body = _normalize_body_value(
        _extract_first(
            mapping,
            (
                "body",
                "content",
                "script",
                "narration",
                "main_text",
                "story_text",
            ),
        )
    )
    closing = _safe_string(
        _extract_first(
            mapping,
            ("closing", "outro", "signoff", "anchor_closing"),
        )
    )

    language = _safe_string(
        _extract_first(mapping, ("language", "language_code"), "en")
    )
    source_script_id = _safe_string(
        _extract_first(
            mapping,
            ("source_script_id", "script_id", "id"),
            "",
        )
    )

    metadata_value = _extract_first(mapping, ("metadata", "meta"), {})
    metadata = (
        copy.deepcopy(dict(metadata_value))
        if isinstance(metadata_value, Mapping)
        else {}
    )

    return PolishedScriptInput(
        headline=headline,
        intro=intro,
        body=body,
        closing=closing,
        language=language or "en",
        source_script_id=source_script_id,
        metadata=metadata,
    )


# =============================================================================
# EDITORIAL POLISHER
# =============================================================================


class EditorialPolisher:
    """
    Deterministic editorial polishing engine.

    The engine makes conservative, transparent changes and records each
    transformation. It does not call an external language model.
    """

    def __init__(self, style: EditorialStyle | None = None) -> None:
        self.style = style or EditorialStyle()

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def polish(self, script: Any) -> PolishingResult:
        """Polish one script and return a complete result."""

        source = coerce_script_input(script)

        section_values: dict[ScriptSection, str] = {
            ScriptSection.HEADLINE: source.headline,
            ScriptSection.INTRO: source.intro,
            ScriptSection.BODY: source.body,
            ScriptSection.CLOSING: source.closing,
        }

        changes: list[EditorialChange] = []
        issues: list[EditorialIssue] = []
        polished_values: dict[ScriptSection, str] = {}

        for section, original in section_values.items():
            polished, section_changes, section_issues = self._polish_section(
                section,
                original,
            )
            polished_values[section] = polished
            changes.extend(section_changes)
            issues.extend(section_issues)

        script_output = PolishedScript(
            headline=polished_values[ScriptSection.HEADLINE],
            intro=polished_values[ScriptSection.INTRO],
            body=polished_values[ScriptSection.BODY],
            closing=polished_values[ScriptSection.CLOSING],
            language=source.language,
            source_script_id=source.source_script_id,
            metadata=copy.deepcopy(source.metadata),
        )

        metrics = {
            section.value: self._measure_section(
                polished_values[section],
                section,
            )
            for section in _SECTION_NAMES
        }

        issues.extend(
            self._validate_complete_script(
                script_output,
                metrics,
            )
        )

        quality_score = self._calculate_quality_score(
            script_output,
            metrics,
            issues,
        )
        production_ready = (
            quality_score >= self.style.minimum_quality_score
            and not any(
                issue.severity == EditorialSeverity.BLOCKING
                for issue in issues
            )
        )

        notes = self._build_editorial_notes(
            changes,
            issues,
            quality_score,
            production_ready,
        )

        return PolishingResult(
            script=script_output,
            quality_score=quality_score,
            production_ready=production_ready,
            changes=changes,
            issues=issues,
            metrics=metrics,
            editorial_notes=notes,
        )

    def polish_many(
        self,
        scripts: Iterable[Any],
    ) -> list[PolishingResult]:
        """Polish multiple scripts in their original order."""

        return [self.polish(script) for script in scripts]

    def summarize(
        self,
        results: Sequence[PolishingResult],
    ) -> PolishingSummary:
        """Return aggregate statistics for polishing results."""

        return PolishingSummary.from_results(results)

    # ---------------------------------------------------------------------
    # Section processing
    # ---------------------------------------------------------------------

    def _polish_section(
        self,
        section: ScriptSection,
        original: str,
    ) -> tuple[str, list[EditorialChange], list[EditorialIssue]]:
        changes: list[EditorialChange] = []
        issues: list[EditorialIssue] = []

        current = _safe_string(original)
        preserved_before = current

        steps = (
            (
                ChangeCategory.NORMALIZATION,
                "Normalized Unicode and whitespace.",
                self._normalize_text,
            ),
            (
                ChangeCategory.PUNCTUATION,
                "Standardized punctuation and spacing.",
                self._normalize_punctuation,
            ),
            (
                ChangeCategory.GRAMMAR,
                "Corrected common grammar and wording problems.",
                self._apply_grammar_rules,
            ),
            (
                ChangeCategory.BROADCAST_STYLE,
                "Simplified wording for broadcast delivery.",
                self._apply_broadcast_rules,
            ),
            (
                ChangeCategory.TONE,
                "Replaced sensational wording with neutral language.",
                self._neutralize_tone,
            ),
            (
                ChangeCategory.CLARITY,
                "Removed weak openings and duplicated words.",
                self._improve_clarity,
            ),
            (
                ChangeCategory.REPETITION,
                "Removed repeated sentences or phrases.",
                self._remove_repetition,
            ),
            (
                ChangeCategory.FLOW,
                "Improved sentence and paragraph flow.",
                lambda text: self._improve_flow(section, text),
            ),
            (
                ChangeCategory.CAPITALIZATION,
                "Standardized sentence capitalization.",
                lambda text: self._normalize_capitalization(section, text),
            ),
            (
                ChangeCategory.PUNCTUATION,
                "Completed sentence-ending punctuation.",
                lambda text: self._complete_punctuation(section, text),
            ),
        )

        for category, reason, operation in steps:
            before = current
            current = operation(current)
            if before != current:
                changes.append(
                    EditorialChange(
                        section=section,
                        category=category,
                        before=before,
                        after=current,
                        reason=reason,
                    )
                )

        for preservation_issue in _token_preservation_issues(
            preserved_before,
            current,
            self.style,
        ):
            issues.append(
                EditorialIssue(
                    section=section,
                    severity=EditorialSeverity.BLOCKING,
                    code="fact_token_changed",
                    message=preservation_issue,
                    excerpt=current[:160],
                )
            )

        return current.strip(), changes, issues

    # ---------------------------------------------------------------------
    # Text transformation passes
    # ---------------------------------------------------------------------

    def _normalize_text(self, text: str) -> str:
        if not text:
            return ""

        value = text

        if self.style.normalize_unicode:
            value = unicodedata.normalize("NFKC", value)
            value = (
                value.replace("\u00a0", " ")
                .replace("\u200b", "")
                .replace("\ufeff", "")
            )

        value = value.replace("\r\n", "\n").replace("\r", "\n")

        if self.style.normalize_whitespace:
            lines = [
                _MULTI_SPACE_RE.sub(" ", line).strip()
                for line in value.split("\n")
            ]
            value = "\n".join(lines)
            value = _MULTI_BLANK_RE.sub("\n\n", value)
            value = value.strip()

        return value

    def _normalize_punctuation(self, text: str) -> str:
        if not text or not self.style.normalize_punctuation:
            return text

        value = text
        value = value.replace("...", "…")
        value = _REPEAT_PUNCT_RE.sub(r"\1", value)
        value = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", value)
        value = _MISSING_SPACE_AFTER_PUNCT_RE.sub(r"\1 ", value)
        value = re.sub(r"\s*—\s*", " — ", value)
        value = re.sub(r"\s*–\s*", " – ", value)
        value = re.sub(r"\(\s+", "(", value)
        value = re.sub(r"\s+\)", ")", value)
        value = re.sub(r'"\s+', '"', value)
        value = re.sub(r'\s+"', '"', value)
        value = _MULTI_SPACE_RE.sub(" ", value)

        # Restore paragraph boundaries that may have been flattened.
        value = value.replace(" \n", "\n").replace("\n ", "\n")
        return value.strip()

    def _apply_grammar_rules(self, text: str) -> str:
        value = text
        for pattern, replacement in _GRAMMAR_REPLACEMENTS:
            value = re.sub(
                pattern,
                replacement,
                value,
                flags=re.IGNORECASE,
            )

        value = _DUPLICATE_WORD_RE.sub(r"\1", value)
        value = re.sub(r"\bcan not\b", "cannot", value, flags=re.IGNORECASE)
        value = re.sub(
            r"\bdoes not has\b",
            "does not have",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"\bdid not went\b",
            "did not go",
            value,
            flags=re.IGNORECASE,
        )
        return value

    def _apply_broadcast_rules(self, text: str) -> str:
        value = text
        for pattern, replacement in _BROADCAST_REPLACEMENTS:
            value = re.sub(
                pattern,
                replacement,
                value,
                flags=re.IGNORECASE,
            )
        return value

    def _neutralize_tone(self, text: str) -> str:
        if not self.style.remove_sensational_language:
            return text

        value = text
        for pattern, replacement in _SENSATIONAL_REPLACEMENTS:
            value = re.sub(
                pattern,
                replacement,
                value,
                flags=re.IGNORECASE,
            )
        return value

    def _improve_clarity(self, text: str) -> str:
        value = text

        for opening in _WEAK_OPENINGS:
            value = re.sub(
                rf"(?i)(^|(?<=[.!?])\s+){re.escape(opening)}",
                r"\1",
                value,
            )

        value = _DUPLICATE_WORD_RE.sub(r"\1", value)

        if self.style.simplify_parentheses:
            value = re.sub(
                r"\((according to [^)]+)\)",
                r", \1,",
                value,
                flags=re.IGNORECASE,
            )
            value = re.sub(r",\s*,", ",", value)

        value = _MULTI_SPACE_RE.sub(" ", value)
        return value.strip()

    def _remove_repetition(self, text: str) -> str:
        if not text:
            return text

        paragraphs = _split_paragraphs(text)
        output_paragraphs: list[str] = []
        seen_sentences: set[str] = set()

        for paragraph in paragraphs:
            sentences = _split_sentences(paragraph)
            kept: list[str] = []

            for sentence in sentences:
                key = _sentence_key(sentence)
                if (
                    self.style.remove_repeated_sentences
                    and key
                    and key in seen_sentences
                ):
                    continue

                if key:
                    seen_sentences.add(key)

                if (
                    self.style.remove_repeated_phrases
                    and kept
                    and self._is_near_duplicate(kept[-1], sentence)
                ):
                    continue

                kept.append(sentence.strip())

            if kept:
                output_paragraphs.append(" ".join(kept))

        return "\n\n".join(output_paragraphs)

    def _improve_flow(
        self,
        section: ScriptSection,
        text: str,
    ) -> str:
        if not text:
            return text

        paragraphs = _split_paragraphs(text)
        improved_paragraphs: list[str] = []

        for paragraph in paragraphs:
            sentences = _split_sentences(paragraph)
            improved_sentences: list[str] = []

            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue

                if section != ScriptSection.HEADLINE:
                    sentence = _LEADING_CONNECTOR_RE.sub("", sentence)

                sentence = self._soften_overlong_sentence(sentence)
                improved_sentences.append(sentence.strip())

            paragraph_text = " ".join(improved_sentences).strip()

            if (
                section == ScriptSection.BODY
                and _word_count(paragraph_text)
                > self.style.maximum_paragraph_words
            ):
                improved_paragraphs.extend(
                    self._split_long_paragraph(paragraph_text)
                )
            elif paragraph_text:
                improved_paragraphs.append(paragraph_text)

        return "\n\n".join(improved_paragraphs)

    def _normalize_capitalization(
        self,
        section: ScriptSection,
        text: str,
    ) -> str:
        if not text:
            return text

        if section == ScriptSection.HEADLINE:
            text = self._sentence_case_headline(text)

        sentences = _split_sentences(text)
        normalized: list[str] = []

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            first_alpha = next(
                (
                    index
                    for index, char in enumerate(sentence)
                    if char.isalpha()
                ),
                None,
            )
            if first_alpha is not None:
                sentence = (
                    sentence[:first_alpha]
                    + sentence[first_alpha].upper()
                    + sentence[first_alpha + 1 :]
                )

            normalized.append(sentence)

        result = " ".join(normalized)

        # Preserve original paragraph breaks where possible by reprocessing each.
        if "\n\n" in text:
            result_paragraphs = [
                self._normalize_capitalization(section, paragraph)
                for paragraph in _split_paragraphs(text)
            ]
            return "\n\n".join(result_paragraphs)

        return result

    def _complete_punctuation(
        self,
        section: ScriptSection,
        text: str,
    ) -> str:
        if not text:
            return text

        if (
            section == ScriptSection.HEADLINE
            and self.style.allow_headline_without_period
        ):
            return text.rstrip(".")

        paragraphs = _split_paragraphs(text)
        completed: list[str] = []

        for paragraph in paragraphs:
            stripped = paragraph.rstrip()
            if stripped and stripped[-1] not in ".!?…\"”'’":
                stripped += "."
            completed.append(stripped)

        return "\n\n".join(completed)

    # ---------------------------------------------------------------------
    # Transformation helpers
    # ---------------------------------------------------------------------

    def _sentence_case_headline(self, headline: str) -> str:
        words = headline.split()
        if not words:
            return headline

        uppercase_words = [
            word.strip(".,:;!?()[]{}\"'")
            for word in words
            if word.strip(".,:;!?()[]{}\"'").isupper()
            and len(word.strip(".,:;!?()[]{}\"'")) >= 4
        ]

        if len(uppercase_words) < max(2, math.ceil(len(words) * 0.6)):
            return headline

        lowered = headline.lower()
        first_alpha = next(
            (
                index
                for index, char in enumerate(lowered)
                if char.isalpha()
            ),
            None,
        )
        if first_alpha is not None:
            lowered = (
                lowered[:first_alpha]
                + lowered[first_alpha].upper()
                + lowered[first_alpha + 1 :]
            )

        for acronym in _ALLOWED_UPPERCASE:
            lowered = re.sub(
                rf"\b{re.escape(acronym)}\b",
                acronym,
                lowered,
                flags=re.IGNORECASE,
            )

        return lowered

    def _soften_overlong_sentence(self, sentence: str) -> str:
        word_total = _word_count(sentence)
        if word_total <= self.style.maximum_words_per_sentence:
            return sentence

        # Conservative split only at semicolon or a strong conjunction after
        # the target midpoint. This avoids modifying facts or numbers.
        target = self.style.target_words_per_sentence
        words_seen = 0

        for index, char in enumerate(sentence):
            if char.isspace():
                words_seen += 1

            if words_seen < target:
                continue

            if char == ";":
                return (
                    sentence[:index].rstrip() + ". "
                    + sentence[index + 1 :].lstrip().capitalize()
                )

            remainder = sentence[index:]
            match = re.match(
                r"\s+(and|but|while|however)\s+",
                remainder,
                flags=re.IGNORECASE,
            )
            if match:
                split_index = index + match.end()
                connector = match.group(1).lower()
                second = sentence[split_index:].strip()
                if connector == "however":
                    second = "However, " + second
                return (
                    sentence[:index].rstrip(", ") + ". "
                    + second[:1].upper() + second[1:]
                )

        return sentence

    def _split_long_paragraph(self, paragraph: str) -> list[str]:
        sentences = _split_sentences(paragraph)
        if len(sentences) <= 1:
            return [paragraph]

        target = max(40, self.style.maximum_paragraph_words // 2)
        paragraphs: list[str] = []
        current: list[str] = []
        current_words = 0

        for sentence in sentences:
            sentence_words = _word_count(sentence)
            if current and current_words + sentence_words > target:
                paragraphs.append(" ".join(current))
                current = []
                current_words = 0
            current.append(sentence)
            current_words += sentence_words

        if current:
            paragraphs.append(" ".join(current))

        return paragraphs

    def _is_near_duplicate(self, first: str, second: str) -> bool:
        first_words = set(_sentence_key(first).split())
        second_words = set(_sentence_key(second).split())

        if not first_words or not second_words:
            return False

        overlap = len(first_words & second_words)
        union = len(first_words | second_words)
        similarity = overlap / union if union else 0.0

        return similarity >= 0.88

    # ---------------------------------------------------------------------
    # Validation and metrics
    # ---------------------------------------------------------------------

    def _measure_section(
        self,
        text: str,
        section: ScriptSection,
    ) -> SectionMetrics:
        if not text:
            return SectionMetrics()

        sentences = _split_sentences(text)
        paragraphs = _split_paragraphs(text)
        sentence_lengths = [_word_count(item) for item in sentences]
        keys = [_sentence_key(item) for item in sentences]
        unique_keys = {key for key in keys if key}

        sensational_count = 0
        for pattern, _ in _SENSATIONAL_REPLACEMENTS:
            sensational_count += len(
                re.findall(pattern, text, flags=re.IGNORECASE)
            )

        incomplete = 0
        if self.style.require_complete_sentences:
            for sentence in sentences:
                lowered = sentence.strip().lower()
                if lowered.startswith(_INCOMPLETE_STARTERS):
                    incomplete += 1

        return SectionMetrics(
            words=_word_count(text),
            sentences=len(sentences),
            paragraphs=len(paragraphs),
            average_words_per_sentence=round(
                statistics.fmean(sentence_lengths), 2
            ) if sentence_lengths else 0.0,
            longest_sentence_words=max(sentence_lengths, default=0),
            repeated_sentence_count=max(
                0,
                len([key for key in keys if key]) - len(unique_keys),
            ),
            sensational_term_count=sensational_count,
            incomplete_sentence_count=incomplete,
        )

    def _validate_complete_script(
        self,
        script: PolishedScript,
        metrics: Mapping[str, SectionMetrics],
    ) -> list[EditorialIssue]:
        issues: list[EditorialIssue] = []

        if not script.headline.strip():
            issues.append(
                EditorialIssue(
                    section=ScriptSection.HEADLINE,
                    severity=EditorialSeverity.BLOCKING,
                    code="missing_headline",
                    message="The script does not contain a headline.",
                )
            )

        if not script.body.strip():
            issues.append(
                EditorialIssue(
                    section=ScriptSection.BODY,
                    severity=EditorialSeverity.BLOCKING,
                    code="missing_body",
                    message="The script does not contain a body.",
                )
            )

        for section in _SECTION_NAMES:
            metric = metrics[section.value]
            text = getattr(script, section.value)

            if not text:
                continue

            if (
                metric.longest_sentence_words
                > self.style.maximum_words_per_sentence
            ):
                issues.append(
                    EditorialIssue(
                        section=section,
                        severity=EditorialSeverity.WARNING,
                        code="long_sentence",
                        message=(
                            "At least one sentence is longer than the "
                            f"{self.style.maximum_words_per_sentence}-word "
                            "broadcast target."
                        ),
                        excerpt=self._longest_sentence(text)[:180],
                    )
                )

            if metric.repeated_sentence_count:
                issues.append(
                    EditorialIssue(
                        section=section,
                        severity=EditorialSeverity.WARNING,
                        code="repeated_sentence",
                        message="The section contains repeated sentences.",
                    )
                )

            if metric.sensational_term_count:
                issues.append(
                    EditorialIssue(
                        section=section,
                        severity=EditorialSeverity.WARNING,
                        code="sensational_language",
                        message=(
                            "The section still contains potentially "
                            "sensational language."
                        ),
                    )
                )

            if metric.incomplete_sentence_count:
                issues.append(
                    EditorialIssue(
                        section=section,
                        severity=EditorialSeverity.WARNING,
                        code="incomplete_sentence",
                        message=(
                            "The section may contain an incomplete sentence."
                        ),
                    )
                )

            all_caps = [
                token
                for token in _ALL_CAPS_WORD_RE.findall(text)
                if token not in _ALLOWED_UPPERCASE
            ]
            if len(all_caps) >= 3:
                issues.append(
                    EditorialIssue(
                        section=section,
                        severity=EditorialSeverity.WARNING,
                        code="excessive_capitals",
                        message=(
                            "The section contains excessive all-capital words."
                        ),
                        excerpt=", ".join(all_caps[:6]),
                    )
                )

        if script.language.lower() not in {"en", "eng", "english"}:
            issues.append(
                EditorialIssue(
                    section=ScriptSection.BODY,
                    severity=EditorialSeverity.INFO,
                    code="non_english_input",
                    message=(
                        "The deterministic rule set is optimized for English."
                    ),
                )
            )

        return issues

    def _longest_sentence(self, text: str) -> str:
        sentences = _split_sentences(text)
        return max(sentences, key=_word_count, default="")

    def _calculate_quality_score(
        self,
        script: PolishedScript,
        metrics: Mapping[str, SectionMetrics],
        issues: Sequence[EditorialIssue],
    ) -> float:
        score = 100.0

        for issue in issues:
            if issue.severity == EditorialSeverity.BLOCKING:
                score -= 30.0
            elif issue.severity == EditorialSeverity.WARNING:
                score -= 6.0
            else:
                score -= 1.0

        body_metric = metrics[ScriptSection.BODY.value]
        intro_metric = metrics[ScriptSection.INTRO.value]
        closing_metric = metrics[ScriptSection.CLOSING.value]
        headline_metric = metrics[ScriptSection.HEADLINE.value]

        if headline_metric.words > 18:
            score -= min(10.0, (headline_metric.words - 18) * 0.75)

        if body_metric.words and body_metric.words < 25:
            score -= 8.0

        for metric in (intro_metric, body_metric, closing_metric):
            if not metric.sentences:
                continue

            distance = abs(
                metric.average_words_per_sentence
                - self.style.target_words_per_sentence
            )
            if distance > 10:
                score -= min(6.0, distance * 0.25)

        if script.intro and script.body:
            intro_key = _sentence_key(script.intro)
            body_start = _sentence_key(
                _split_sentences(script.body)[0]
                if _split_sentences(script.body)
                else ""
            )
            if intro_key and intro_key == body_start:
                score -= 5.0

        return round(max(0.0, min(100.0, score)), 2)

    def _build_editorial_notes(
        self,
        changes: Sequence[EditorialChange],
        issues: Sequence[EditorialIssue],
        quality_score: float,
        production_ready: bool,
    ) -> list[str]:
        notes: list[str] = []

        changed_categories = {
            change.category
            for change in changes
            if change.changed
        }

        if changed_categories:
            notes.append(
                "Applied: "
                + ", ".join(
                    category.value.replace("_", " ")
                    for category in sorted(
                        changed_categories,
                        key=lambda item: item.value,
                    )
                )
                + "."
            )
        else:
            notes.append("No editorial changes were required.")

        blocking = sum(
            1
            for issue in issues
            if issue.severity == EditorialSeverity.BLOCKING
        )
        warnings = sum(
            1
            for issue in issues
            if issue.severity == EditorialSeverity.WARNING
        )

        notes.append(
            f"Quality score: {quality_score:.2f}/100; "
            f"blocking issues: {blocking}; warnings: {warnings}."
        )

        notes.append(
            "Production ready."
            if production_ready
            else "Editorial review is required before production."
        )

        return notes


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def polish_script(
    script: Any,
    style: EditorialStyle | None = None,
) -> PolishingResult:
    """Convenience function for polishing one script."""

    return EditorialPolisher(style=style).polish(script)


def polish_scripts(
    scripts: Iterable[Any],
    style: EditorialStyle | None = None,
) -> list[PolishingResult]:
    """Convenience function for polishing multiple scripts."""

    return EditorialPolisher(style=style).polish_many(scripts)


# =============================================================================
# SELF-TEST
# =============================================================================


def _self_test_scripts() -> list[PolishedScriptInput]:
    return [
        PolishedScriptInput(
            headline=(
                "IMD ISSUES MASSIVE RAIN ALERT FOR COASTAL "
                "ANDHRA PRADESH"
            ),
            intro=(
                "It is important to note that the weather department "
                "has issued a shocking warning for several districts."
            ),
            body=(
                "According to the reports, the India Meteorological "
                "Department has issued an orange alert for parts of "
                "coastal Andhra Pradesh. The alert is valid on July 13 "
                "and July 14, 2026. Officials said heavy rain may affect "
                "low-lying areas and road traffic.\n\n"
                "Residents residents have been advised to avoid flooded "
                "roads and follow instructions from district authorities. "
                "The alert is valid on July 13 and July 14, 2026."
            ),
            closing=(
                "Further updates will be provided as official information "
                "becomes available"
            ),
            source_script_id="weather_demo",
        ),
        PolishedScriptInput(
            headline="State cabinet approves new education programme",
            intro=(
                "The state cabinet has made a decision to approve a new "
                "education programme."
            ),
            body=(
                "The programme will commence in selected government schools "
                "and approximately 50,000 students are expected to benefit. "
                "Officials said the initiative will provide assistance to "
                "teachers and improve digital learning facilities."
            ),
            closing="More details are expected after the formal notification",
            source_script_id="governance_demo",
        ),
        PolishedScriptInput(
            headline="Technology company announces new AI research centre",
            intro=(
                "A technology company announced a new AI research centre "
                "in Hyderabad."
            ),
            body=(
                "The company said the centre will focus on language "
                "technology, safety research and public-interest tools. "
                "The project is expected to create 1,200 jobs over three "
                "years. The company did not disclose the total investment."
            ),
            closing=(
                "Recruitment information will be released by the company"
            ),
            source_script_id="technology_demo",
        ),
    ]


def run_self_test() -> None:
    """Run deterministic module checks and print a concise report."""

    polisher = EditorialPolisher()
    inputs = _self_test_scripts()
    results = polisher.polish_many(inputs)
    summary = polisher.summarize(results)

    assert len(results) == 3
    assert all(result.script.headline for result in results)
    assert all(result.script.body for result in results)
    assert all(0.0 <= result.quality_score <= 100.0 for result in results)
    assert all(
        result.script.source_script_id
        == inputs[index].source_script_id
        for index, result in enumerate(results)
    )

    first = results[0]
    assert "shocking" not in first.script.intro.lower()
    assert "residents residents" not in first.script.body.lower()
    assert (
        first.script.body.count(
            "The alert is valid on July 13 and July 14, 2026."
        )
        == 1
    )
    assert "July 13" in first.script.body
    assert "July 14" in first.script.body

    print("Editorial polisher initialized successfully.")
    print()
    print(f"Scripts processed       : {summary.scripts_processed}")
    print(f"Total changes applied   : {summary.total_changes}")
    print(f"Grammar improvements    : {summary.grammar_improvements}")
    print(f"Punctuation improvements: {summary.punctuation_improvements}")
    print(f"Style improvements      : {summary.style_improvements}")
    print(f"Tone adjustments        : {summary.tone_adjustments}")
    print(f"Repetition removals     : {summary.repetition_removals}")
    print(f"Average quality         : {summary.average_quality_score:.2f}")
    print(f"Production ready        : {summary.scripts_ready}")
    print()
    print("Editorial polisher self-test passed.")


if __name__ == "__main__":
    run_self_test()