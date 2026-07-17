"""
BahuvuNewsAI Telugu broadcast-language normalization.

This module separates:

1. display_text
   Text shown in captions, graphics and thumbnails.

2. speech_text
   Text passed to Telugu TTS, with pronunciation guidance only where required.

Important architectural rule:
This module must never translate, summarize, expand, shorten, or alter facts.
It only normalizes already-approved Telugu newsroom copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable, Mapping, Sequence


MODULE_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class BroadcastTerm:
    """One approved modern Telugu broadcast-language term."""

    canonical: str
    speech: str
    aliases: tuple[str, ...] = ()
    preserve_display: bool = True


@dataclass(frozen=True, slots=True)
class BroadcastText:
    """Final text representations consumed by downstream production stages."""

    original_text: str
    display_text: str
    speech_text: str
    warnings: tuple[str, ...] = ()
    replacements: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BroadcastValidation:
    valid: bool
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


DEFAULT_TERMS: tuple[BroadcastTerm, ...] = (
    BroadcastTerm("GDP", "జీడీపీ", ("G.D.P.", "gdp")),
    BroadcastTerm("AI", "ఏఐ", ("A.I.", "ai")),
    BroadcastTerm("IT", "ఐటీ", ("I.T.", "it")),
    BroadcastTerm("IPL", "ఐపీఎల్", ("I.P.L.", "ipl")),
    BroadcastTerm("ISRO", "ఇస్రో", ("isro",)),
    BroadcastTerm("NASA", "నాసా", ("nasa",)),
    BroadcastTerm("GST", "జీఎస్టీ", ("G.S.T.", "gst")),
    BroadcastTerm("UPI", "యూపీఐ", ("upi",)),
    BroadcastTerm("ATM", "ఏటీఎం", ("atm",)),
    BroadcastTerm("CEO", "సీఈఓ", ("C.E.O.", "ceo")),
    BroadcastTerm("CM", "సీఎం", ("C.M.", "cm")),
    BroadcastTerm("PM", "పీఎం", ("P.M.", "pm")),
    BroadcastTerm("MLA", "ఎమ్మెల్యే", ("M.L.A.", "mla")),
    BroadcastTerm("MP", "ఎంపీ", ("M.P.", "mp")),
    BroadcastTerm("5G", "ఫైవ్ జీ", ("5g",)),
    BroadcastTerm("YouTube", "యూట్యూబ్", ("youtube",)),
    BroadcastTerm("WhatsApp", "వాట్సాప్", ("whatsapp",)),
    BroadcastTerm("Google", "గూగుల్", ("google",)),
    BroadcastTerm("Microsoft", "మైక్రోసాఫ్ట్", ("microsoft",)),
    BroadcastTerm("Facebook", "ఫేస్‌బుక్", ("facebook",)),
)


_ALLOWED_ENGLISH_WORDS = {
    "app",
    "apps",
    "bank",
    "budget",
    "business",
    "cabinet",
    "camera",
    "CEO",
    "CM",
    "college",
    "company",
    "data",
    "digital",
    "dollar",
    "GDP",
    "Google",
    "GST",
    "hospital",
    "AI",
    "IT",
    "IPL",
    "ISRO",
    "loan",
    "market",
    "Microsoft",
    "NASA",
    "online",
    "phone",
    "PM",
    "project",
    "report",
    "software",
    "smartphone",
    "social",
    "technology",
    "TV",
    "UPI",
    "video",
    "WhatsApp",
    "YouTube",
}


_TELUGU_RE = re.compile(r"[\u0C00-\u0C7F]")
_ENGLISH_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9.+&'-]*\b")
_NUMBER_EXPRESSION_RE = re.compile(
    r"""
    (?:
        ₹\s?\d[\d,]*(?:\.\d+)?
        |
        \$\s?\d[\d,]*(?:\.\d+)?
        |
        \d[\d,]*(?:\.\d+)?%
        |
        \d+(?:\.\d+)?[A-Za-z]+
        |
        \d[\d,]*(?:\.\d+)?
    )
    """,
    re.VERBOSE,
)


def _normalize_spaces(text: str) -> str:
    text = text.replace("\u00A0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_punctuation(text: str) -> str:
    replacements = {
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "…": "...",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def _replace_term(
    text: str,
    source: str,
    replacement: str,
) -> tuple[str, int]:
    pattern = re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(source)}(?![A-Za-z0-9])",
        flags=re.IGNORECASE,
    )
    return pattern.subn(replacement, text)


def _build_term_index(
    terms: Sequence[BroadcastTerm],
) -> Mapping[str, BroadcastTerm]:
    index: dict[str, BroadcastTerm] = {}

    for term in terms:
        for value in (term.canonical, *term.aliases):
            normalized = value.casefold()
            if normalized in index and index[normalized] != term:
                raise ValueError(f"Duplicate broadcast alias: {value}")
            index[normalized] = term

    return index


def _normalize_telugu_suffix_joining(text: str) -> str:
    """
    Insert ZWNJ between a final Telugu consonant and common suffixes.

    Example:
        ?????????? -> ???????????
    """

    virama = chr(0x0C4D)
    zwnj = chr(0x200C)

    suffixes = (
        chr(0x0C32) + chr(0x0C4B),  # ??
        chr(0x0C15) + chr(0x0C41),  # ??
        chr(0x0C15) + chr(0x0C3F),  # ??
        chr(0x0C24) + chr(0x0C4B),  # ??
        chr(0x0C2A) + chr(0x0C48),  # ??
        chr(0x0C17) + chr(0x0C3E),  # ??
    )

    for suffix in suffixes:
        text = text.replace(
            virama + suffix,
            virama + zwnj + suffix,
        )

    return text


class TeluguBroadcastStyle:
    """
    Convert approved Telugu editorial copy into display and speech variants.

    Numbers, percentages, currencies, dates and measurements remain unchanged.
    This is deliberate: their actual TTS pronunciation must be tested before
    any engine-specific spoken-number conversion is introduced.
    """

    def __init__(
        self,
        terms: Iterable[BroadcastTerm] = DEFAULT_TERMS,
        allowed_english_words: Iterable[str] = _ALLOWED_ENGLISH_WORDS,
    ) -> None:
        self.terms = tuple(terms)
        self.allowed_english_words = {
            word.casefold() for word in allowed_english_words
        }
        self._term_index = _build_term_index(self.terms)

    def normalize(self, text: str) -> BroadcastText:
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        original = text
        display = _normalize_spaces(_normalize_punctuation(text))

        if not display:
            return BroadcastText(
                original_text=original,
                display_text="",
                speech_text="",
                warnings=("Broadcast text is empty.",),
            )

        speech = display
        replacements: list[str] = []

        # Longest terms first so that shorter aliases cannot interfere.
        ordered_sources: list[tuple[str, BroadcastTerm]] = []

        for term in self.terms:
            ordered_sources.append((term.canonical, term))
            ordered_sources.extend((alias, term) for alias in term.aliases)

        ordered_sources.sort(key=lambda item: len(item[0]), reverse=True)

        display_seen: set[str] = set()
        speech_seen: set[str] = set()

        for source, term in ordered_sources:
            source_key = source.casefold()

            if source_key not in display_seen:
                display_replacement = (
                    term.canonical if term.preserve_display else term.speech
                )
                display, display_count = _replace_term(
                    display,
                    source,
                    display_replacement,
                )

                if display_count:
                    display_seen.add(source_key)

            if source_key not in speech_seen:
                speech, speech_count = _replace_term(
                    speech,
                    source,
                    term.speech,
                )

                if speech_count:
                    replacements.append(
                        f"{source} -> {term.speech} ({speech_count})"
                    )
                    speech_seen.add(source_key)

        display = _normalize_telugu_suffix_joining(
            _normalize_spaces(display)
        )
        speech = _normalize_telugu_suffix_joining(
            _normalize_spaces(speech)
        )

        validation = self.validate(display)

        return BroadcastText(
            original_text=original,
            display_text=display,
            speech_text=speech,
            warnings=validation.warnings + validation.errors,
            replacements=tuple(replacements),
        )

    def validate(self, text: str) -> BroadcastValidation:
        errors: list[str] = []
        warnings: list[str] = []

        normalized = _normalize_spaces(text)

        if not normalized:
            errors.append("Text is empty.")
            return BroadcastValidation(
                valid=False,
                warnings=tuple(warnings),
                errors=tuple(errors),
            )

        if not _TELUGU_RE.search(normalized):
            errors.append("Text does not contain Telugu script.")

        english_words = _ENGLISH_WORD_RE.findall(normalized)
        unexpected_english: list[str] = []

        for word in english_words:
            key = word.casefold()

            if key in self.allowed_english_words:
                continue

            if key in self._term_index:
                continue

            # Proper names and acronyms are allowed but reported for review.
            if word.isupper() or word[:1].isupper():
                continue

            unexpected_english.append(word)

        if unexpected_english:
            unique_words = sorted(
                set(unexpected_english),
                key=str.casefold,
            )
            warnings.append(
                "Review unexpected English words: "
                + ", ".join(unique_words)
            )

        number_expressions = _NUMBER_EXPRESSION_RE.findall(normalized)

        if number_expressions:
            warnings.append(
                "Numeric expressions preserved exactly: "
                + ", ".join(number_expressions)
            )

        if re.search(r"\b\d+\s*దశాంశ\s*\d+\b", normalized):
            warnings.append(
                "Written-out decimal detected; prefer figures such as 12.5 "
                "when that matches Telugu broadcast style."
            )

        return BroadcastValidation(
            valid=not errors,
            warnings=tuple(warnings),
            errors=tuple(errors),
        )


def normalize_telugu_broadcast_text(text: str) -> BroadcastText:
    """Convenience function using the default Bahuvu News rules."""

    return TeluguBroadcastStyle().normalize(text)


def _self_test() -> None:
    engine = TeluguBroadcastStyle()

    examples = (
        (
            "2026లో GDP 12.5% పెరిగింది.",
            "2026లో GDP 12.5% పెరిగింది.",
            "2026లో జీడీపీ 12.5% పెరిగింది.",
        ),
        (
            "AI రంగంలో కొత్త పెట్టుబడులు వచ్చాయి.",
            "AI రంగంలో కొత్త పెట్టుబడులు వచ్చాయి.",
            "ఏఐ రంగంలో కొత్త పెట్టుబడులు వచ్చాయి.",
        ),
        (
            "ISRO కొత్త ప్రయోగానికి సిద్ధమైంది.",
            "ISRO కొత్త ప్రయోగానికి సిద్ధమైంది.",
            "ఇస్రో కొత్త ప్రయోగానికి సిద్ధమైంది.",
        ),
        (
            "YouTubeలో వీడియో విడుదలైంది.",
            "YouTubeలో వీడియో విడుదలైంది.",
            "యూట్యూబ్‌లో వీడియో విడుదలైంది.",
        ),
        (
            "UPI లావాదేవీలు 18.2% పెరిగాయి.",
            "UPI లావాదేవీలు 18.2% పెరిగాయి.",
            "యూపీఐ లావాదేవీలు 18.2% పెరిగాయి.",
        ),
    )

    for source, expected_display, expected_speech in examples:
        result = engine.normalize(source)

        assert result.display_text == expected_display, (
            source,
            result.display_text,
            expected_display,
        )
        assert result.speech_text == expected_speech, (
            source,
            result.speech_text,
            expected_speech,
        )

    sample = engine.normalize(
        "2026లో GDP 12.5% పెరిగింది. AI రంగంలో పెట్టుబడులు పెరిగాయి."
    )

    print("BahuvuNewsAI Telugu broadcast style")
    print(f"Module version : {MODULE_VERSION}")
    print(f"Display text   : {sample.display_text}")
    print(f"Speech text    : {sample.speech_text}")
    print(f"Replacements   : {len(sample.replacements)}")
    print(f"Warnings       : {len(sample.warnings)}")

    for warning in sample.warnings:
        print(f"  - {warning}")

    print("Telugu broadcast-style self-test passed.")


if __name__ == "__main__":
    _self_test()
