# news/telugu_translator.py

"""
BahuvuNewsAI - Telugu News Translator
======================================

Translates editorially approved English NewsArticle objects into natural,
broadcast-ready Telugu while preserving facts, names, numbers, dates, quotes,
and newsroom metadata.

Design goals
------------
1. Use the canonical NewsArticle model.
2. Keep translation-provider logic replaceable.
3. Support Google Generative AI when an API key is configured.
4. Provide a deterministic offline backend for testing.
5. Validate every translation before mutating the article.
6. Never silently overwrite usable Telugu unless explicitly requested.
7. Record translation provenance in article.metadata.
8. Provide a deterministic self-test.

Environment variables
---------------------
BAHUVU_TRANSLATION_PROVIDER
    "google" or "deterministic". Default: "google" when
    GOOGLE_API_KEY is available, otherwise "deterministic".

GOOGLE_API_KEY
    Google AI Studio API key.

BAHUVU_TRANSLATION_MODEL
    Optional model name. Default: "gemini-2.0-flash".

Important
---------
The deterministic backend is intended for self-tests and pipeline wiring.
Production news translation should use a capable language-model backend and
must remain subject to editorial review.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable, Mapping, Protocol, Sequence

try:
    from news.models import (
        ArticleStatus,
        LanguageCode,
        NewsArticle,
        normalize_text,
        utc_now,
    )
except ImportError as exc:
    raise ImportError(
        "Unable to import news models. Run this module from the project root "
        "using: python -m news.telugu_translator"
    ) from exc


# ==========================================================
# EXCEPTIONS
# ==========================================================


class TranslationError(RuntimeError):
    """Base error raised by the Telugu translation stage."""


class TranslationConfigurationError(TranslationError):
    """Raised when a translation backend is not configured correctly."""


class TranslationProviderError(TranslationError):
    """Raised when the configured translation provider fails."""


class TranslationValidationError(TranslationError):
    """Raised when translated output fails newsroom validation."""


# ==========================================================
# ENUMERATIONS AND DATA CONTRACTS
# ==========================================================


class TranslationProvider(StrEnum):
    """Supported translation-provider identifiers."""

    GOOGLE = "google"
    DETERMINISTIC = "deterministic"


class TranslationField(StrEnum):
    """Canonical article fields translated by this module."""

    HEADLINE = "headline"
    SUMMARY = "summary"
    SCRIPT = "script"


@dataclass(slots=True, frozen=True)
class TranslationRequest:
    """Input sent to a translation backend."""

    article_id: str
    headline: str
    summary: str
    script: str
    category: str
    publisher: str
    source_name: str
    published_at: str
    keywords: tuple[str, ...] = ()
    style: str = "professional Telugu television news"


@dataclass(slots=True)
class TranslationResult:
    """Validated Telugu output returned by a translation backend."""

    telugu_headline: str
    telugu_summary: str
    telugu_script: str
    provider: str
    model: str
    raw_response: str = ""
    warnings: list[str] = field(default_factory=list)

    def normalized(self) -> "TranslationResult":
        """Return this result after normalizing whitespace."""

        self.telugu_headline = normalize_multiline(self.telugu_headline)
        self.telugu_summary = normalize_multiline(self.telugu_summary)
        self.telugu_script = normalize_multiline(self.telugu_script)
        self.provider = normalize_text(self.provider)
        self.model = normalize_text(self.model)
        self.warnings = [
            normalize_text(item)
            for item in self.warnings
            if normalize_text(item)
        ]
        return self


@dataclass(slots=True, frozen=True)
class TranslationSettings:
    """Runtime settings for the Telugu translator."""

    provider: TranslationProvider
    model: str
    temperature: float = 0.2
    max_output_tokens: int = 4096
    overwrite_existing: bool = False
    require_telugu_script: bool = True
    preserve_numbers: bool = True
    preserve_urls: bool = True

    @classmethod
    def from_environment(cls) -> "TranslationSettings":
        """Build settings from environment variables."""

        api_key_present = bool(os.getenv("GOOGLE_API_KEY", "").strip())
        default_provider = (
            TranslationProvider.GOOGLE.value
            if api_key_present
            else TranslationProvider.DETERMINISTIC.value
        )
        provider_text = os.getenv(
            "BAHUVU_TRANSLATION_PROVIDER",
            default_provider,
        ).strip().lower()

        try:
            provider = TranslationProvider(provider_text)
        except ValueError as exc:
            supported = ", ".join(item.value for item in TranslationProvider)
            raise TranslationConfigurationError(
                f"Unsupported translation provider '{provider_text}'. "
                f"Supported providers: {supported}."
            ) from exc

        model = os.getenv(
            "BAHUVU_TRANSLATION_MODEL",
            "gemini-2.0-flash",
        ).strip()

        if not model:
            raise TranslationConfigurationError(
                "BAHUVU_TRANSLATION_MODEL cannot be empty."
            )

        return cls(provider=provider, model=model)


@dataclass(slots=True)
class ArticleTranslationOutcome:
    """Result of attempting to translate one article."""

    article_id: str
    success: bool
    translated: bool
    skipped: bool
    provider: str = ""
    model: str = ""
    error: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TranslationBatchReport:
    """Summary of a batch translation operation."""

    total: int = 0
    translated: int = 0
    skipped: int = 0
    failed: int = 0
    outcomes: list[ArticleTranslationOutcome] = field(default_factory=list)

    @property
    def successful(self) -> int:
        """Return translated plus intentionally skipped articles."""

        return self.translated + self.skipped


# ==========================================================
# BACKEND PROTOCOL
# ==========================================================


class TeluguTranslationBackend(Protocol):
    """Protocol implemented by translation providers."""

    provider_name: str
    model_name: str

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Translate a canonical request into Telugu."""


# ==========================================================
# TEXT HELPERS
# ==========================================================


_TELUGU_RE = re.compile(r"[\u0C00-\u0C7F]")
_NUMBER_RE = re.compile(
    r"(?<![\w])\d+(?:,\d{2,3})*(?:\.\d+)?(?:%|\u00B0[CF])?"
)

_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
    re.IGNORECASE | re.DOTALL,
)


def normalize_multiline(value: str | None) -> str:
    """Normalize line endings and whitespace while preserving paragraphs."""

    if value is None:
        return ""

    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs: list[str] = []

    for block in re.split(r"\n\s*\n", text):
        lines = [
            " ".join(line.strip().split())
            for line in block.split("\n")
            if line.strip()
        ]
        if lines:
            paragraphs.append("\n".join(lines))

    return "\n\n".join(paragraphs)


def contains_telugu(value: str) -> bool:
    """Return True when text contains at least one Telugu character."""

    return bool(_TELUGU_RE.search(value or ""))


def extract_numbers(value: str) -> list[str]:
    """Extract and normalize factual numeric tokens.

    Structural list markers such as ``1.``, ``2.``, or ``3)``
    at the beginning of a line are ignored.

    Unicode decimal digits are converted to ASCII before extraction,
    allowing values such as Telugu digits and Latin digits to compare
    as the same factual number.
    """

    normalized_characters: list[str] = []

    for character in value or "":
        if character.isdecimal():
            normalized_characters.append(
                str(unicodedata.decimal(character))
            )
        else:
            normalized_characters.append(character)

    normalized_value = "".join(normalized_characters)

    cleaned = re.sub(
        r"(?m)^\s*\d{1,2}[.)]\s+",
        "",
        normalized_value,
    )

    return _NUMBER_RE.findall(cleaned)


def extract_urls(value: str) -> list[str]:
    """Extract URL tokens in their original order."""

    return _URL_RE.findall(value or "")


def strip_markdown_code_fence(value: str) -> str:
    """Remove a surrounding Markdown JSON fence when present."""

    match = _JSON_FENCE_RE.match(value or "")
    return match.group(1).strip() if match else (value or "").strip()


def safe_iso_datetime(value: datetime | None) -> str:
    """Serialize a datetime for provider context."""

    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def best_summary(article: NewsArticle) -> str:
    """Return the best available concise English summary."""

    return (
        normalize_multiline(article.summary)
        or normalize_multiline(article.description)
        or normalize_multiline(article.effective_text)
    )


def best_script(article: NewsArticle) -> str:
    """Return the best available English script or narration."""

    return (
        normalize_multiline(article.script)
        or best_summary(article)
    )


# ==========================================================
# PROMPT BUILDER AND RESPONSE PARSER
# ==========================================================


_SYSTEM_INSTRUCTION = """
You are the senior Telugu-language broadcast editor for BAHUVU NEWS.

Translate English news copy into natural, professional Telugu suitable for a
television news anchor. Accuracy is more important than flourish.

Mandatory rules:
1. Preserve every factual claim. Do not add, infer, exaggerate, or omit facts.
2. Preserve names, places, institutions, numbers, dates, times, percentages,
   currencies, measurements, quotations, and attribution.
3. Use clear contemporary Telugu understood across Andhra Pradesh and
   Telangana.
4. Avoid literal word-for-word translation, slang, sensationalism, propaganda,
   and unnecessary English.
5. Keep unavoidable proper nouns readable through accepted Telugu
   transliteration.
6. Headline: concise and broadcast-friendly.
7. Summary: compact factual overview.
8. Script: smooth anchor narration with the same paragraph order and meaning.
9. Return only valid JSON. Do not use Markdown.
""".strip()


def build_translation_prompt(request: TranslationRequest) -> str:
    """Build a provider-neutral translation prompt."""

    payload = {
        "article_id": request.article_id,
        "category": request.category,
        "publisher": request.publisher,
        "source_name": request.source_name,
        "published_at": request.published_at,
        "keywords": list(request.keywords),
        "style": request.style,
        "english": {
            "headline": request.headline,
            "summary": request.summary,
            "script": request.script,
        },
        "required_json_schema": {
            "telugu_headline": "string",
            "telugu_summary": "string",
            "telugu_script": "string",
            "warnings": ["string"],
        },
    }

    return (
        f"{_SYSTEM_INSTRUCTION}\n\n"
        "Translate the following article and return the required JSON object:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def parse_translation_response(
    raw_response: str,
    *,
    provider: str,
    model: str,
) -> TranslationResult:
    """Parse a provider response into a TranslationResult."""

    cleaned = strip_markdown_code_fence(raw_response)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise TranslationProviderError(
            "Translation provider returned invalid JSON."
        ) from exc

    if not isinstance(data, Mapping):
        raise TranslationProviderError(
            "Translation provider response must be a JSON object."
        )

    warnings_value = data.get("warnings", [])
    if isinstance(warnings_value, str):
        warnings = [warnings_value]
    elif isinstance(warnings_value, Sequence):
        warnings = [str(item) for item in warnings_value]
    else:
        warnings = []

    return TranslationResult(
        telugu_headline=str(data.get("telugu_headline", "")),
        telugu_summary=str(data.get("telugu_summary", "")),
        telugu_script=str(data.get("telugu_script", "")),
        provider=provider,
        model=model,
        raw_response=raw_response,
        warnings=warnings,
    ).normalized()


# ==========================================================
# GOOGLE GENERATIVE AI BACKEND
# ==========================================================


class GoogleGenerativeAIBackend:
    """Google AI Studio backend loaded lazily at runtime."""

    provider_name = TranslationProvider.GOOGLE.value

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        temperature: float = 0.2,
        max_output_tokens: int = 4096,
    ) -> None:
        if not api_key.strip():
            raise TranslationConfigurationError(
                "GOOGLE_API_KEY is required for the Google translation backend."
            )
        if not model_name.strip():
            raise TranslationConfigurationError(
                "A Google model name is required."
            )

        self.api_key = api_key.strip()
        self.model_name = model_name.strip()
        self.temperature = float(temperature)
        self.max_output_tokens = int(max_output_tokens)

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Translate one request using Google Generative AI."""

        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise TranslationConfigurationError(
                "google-generativeai is not installed. Install project "
                "requirements before using the Google backend."
            ) from exc

        try:
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(
                model_name=self.model_name,
                generation_config={
                    "temperature": self.temperature,
                    "max_output_tokens": self.max_output_tokens,
                    "response_mime_type": "application/json",
                },
            )
            response = model.generate_content(
                build_translation_prompt(request)
            )
            raw_text = getattr(response, "text", "") or ""
        except Exception as exc:
            raise TranslationProviderError(
                f"Google translation request failed: {exc}"
            ) from exc

        if not raw_text.strip():
            raise TranslationProviderError(
                "Google translation provider returned an empty response."
            )

        return parse_translation_response(
            raw_text,
            provider=self.provider_name,
            model=self.model_name,
        )


# ==========================================================
# DETERMINISTIC OFFLINE BACKEND
# ==========================================================


class DeterministicTeluguBackend:
    """
    Predictable backend used for self-tests and pipeline integration.

    It deliberately supports a small fixed vocabulary. It must not be treated
    as a general-purpose production translator.
    """

    provider_name = TranslationProvider.DETERMINISTIC.value
    model_name = "offline-self-test-v1"

    _EXACT_TRANSLATIONS: dict[str, str] = {
        "Heavy rain continues across Andhra Pradesh":
            "ఆంధ్రప్రదేశ్‌లో భారీ వర్షాలు కొనసాగుతున్నాయి",
        "Officials issued alerts as heavy rainfall continued across several districts.":
            "పలు జిల్లాల్లో భారీ వర్షాలు కొనసాగుతుండటంతో అధికారులు హెచ్చరికలు జారీ చేశారు.",
        "Heavy rain continues across Andhra Pradesh. Officials issued alerts as heavy rainfall continued across several districts.":
            "ఆంధ్రప్రదేశ్‌లో భారీ వర్షాలు కొనసాగుతున్నాయి. పలు జిల్లాల్లో భారీ వర్షాలు కొనసాగుతుండటంతో అధికారులు హెచ్చరికలు జారీ చేశారు.",
    }

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Return deterministic Telugu for known self-test copy."""

        def convert(text: str) -> str:
            normalized = normalize_multiline(text)
            if not normalized:
                return ""
            translated = self._EXACT_TRANSLATIONS.get(normalized)
            if translated:
                return translated
            return f"తెలుగు అనువాదం: {normalized}"

        return TranslationResult(
            telugu_headline=convert(request.headline),
            telugu_summary=convert(request.summary),
            telugu_script=convert(request.script),
            provider=self.provider_name,
            model=self.model_name,
            warnings=[
                "Deterministic backend used; production editorial review required."
            ],
        ).normalized()


# ==========================================================
# VALIDATION
# ==========================================================


@dataclass(slots=True)
class TranslationValidator:
    """Validate translated copy before applying it to an article."""

    require_telugu_script: bool = True
    preserve_numbers: bool = True
    preserve_urls: bool = True
    minimum_headline_characters: int = 6

    def validate(
        self,
        request: TranslationRequest,
        result: TranslationResult,
    ) -> list[str]:
        """Return non-blocking warnings or raise for blocking failures."""

        result.normalized()
        errors: list[str] = []
        warnings: list[str] = list(result.warnings)

        required_fields = {
            TranslationField.HEADLINE.value: result.telugu_headline,
            TranslationField.SUMMARY.value: result.telugu_summary,
        }
        if self.require_telugu_script:
            required_fields[TranslationField.SCRIPT.value] = (
                result.telugu_script
            )

        for field_name, translated_text in required_fields.items():
            if not translated_text:
                errors.append(f"{field_name} translation is empty.")
            elif not contains_telugu(translated_text):
                errors.append(
                    f"{field_name} translation contains no Telugu characters."
                )

        if (
            result.telugu_headline
            and len(result.telugu_headline)
            < self.minimum_headline_characters
        ):
            errors.append("Telugu headline is unexpectedly short.")

        if self.preserve_numbers:
            self._validate_token_preservation(
                label="numbers",
                source="\n".join(
                    [request.headline, request.summary, request.script]
                ),
                translated="\n".join(
                    [
                        result.telugu_headline,
                        result.telugu_summary,
                        result.telugu_script,
                    ]
                ),
                extractor=extract_numbers,
                errors=errors,
            )

        if self.preserve_urls:
            self._validate_token_preservation(
                label="URLs",
                source="\n".join(
                    [request.headline, request.summary, request.script]
                ),
                translated="\n".join(
                    [
                        result.telugu_headline,
                        result.telugu_summary,
                        result.telugu_script,
                    ]
                ),
                extractor=extract_urls,
                errors=errors,
            )

        if result.telugu_headline.endswith((".", "।")):
            warnings.append(
                "Telugu headline ends with sentence punctuation."
            )

        if errors:
            raise TranslationValidationError(
                "Translation validation failed: " + " ".join(errors)
            )

        return deduplicate_strings(warnings)

    @staticmethod
    def _validate_token_preservation(
        *,
        label: str,
        source: str,
        translated: str,
        extractor: Any,
        errors: list[str],
    ) -> None:
        source_tokens = extractor(source)
        translated_tokens = extractor(translated)

        missing: list[str] = []
        remaining = list(translated_tokens)

        for token in source_tokens:
            if token in remaining:
                remaining.remove(token)
            else:
                missing.append(token)

        if missing:
            errors.append(
                f"Missing {label} in Telugu output: {', '.join(missing)}."
            )


def deduplicate_strings(values: Iterable[str]) -> list[str]:
    """Normalize and deduplicate strings while preserving order."""

    output: list[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = normalize_text(value)
        if not normalized:
            continue
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            output.append(normalized)

    return output


# ==========================================================
# TRANSLATOR SERVICE
# ==========================================================


class TeluguTranslator:
    """Translate canonical NewsArticle objects safely."""

    def __init__(
        self,
        backend: TeluguTranslationBackend,
        *,
        settings: TranslationSettings,
    ) -> None:
        self.backend = backend
        self.settings = settings
        self.validator = TranslationValidator(
            require_telugu_script=settings.require_telugu_script,
            preserve_numbers=settings.preserve_numbers,
            preserve_urls=settings.preserve_urls,
        )

    @classmethod
    def from_environment(cls) -> "TeluguTranslator":
        """Create a translator using environment configuration."""

        settings = TranslationSettings.from_environment()

        if settings.provider == TranslationProvider.GOOGLE:
            backend: TeluguTranslationBackend = GoogleGenerativeAIBackend(
                api_key=os.getenv("GOOGLE_API_KEY", ""),
                model_name=settings.model,
                temperature=settings.temperature,
                max_output_tokens=settings.max_output_tokens,
            )
        else:
            backend = DeterministicTeluguBackend()

        return cls(backend, settings=settings)

    def translate_article(
        self,
        article: NewsArticle,
        *,
        overwrite: bool | None = None,
    ) -> ArticleTranslationOutcome:
        """Translate one article and update it only after validation."""

        should_overwrite = (
            self.settings.overwrite_existing
            if overwrite is None
            else bool(overwrite)
        )

        self._validate_article_eligibility(article)

        if self._already_translated(article) and not should_overwrite:
            return ArticleTranslationOutcome(
                article_id=article.article_id,
                success=True,
                translated=False,
                skipped=True,
                provider=getattr(self.backend, "provider_name", ""),
                model=getattr(self.backend, "model_name", ""),
                warnings=["Existing Telugu translation preserved."],
            )

        request = self._build_request(article)

        try:
            result = self.backend.translate(request).normalized()
            warnings = self.validator.validate(request, result)
            self._apply_result(article, result, warnings)
        except TranslationError as exc:
            self._record_failure(article, str(exc))
            return ArticleTranslationOutcome(
                article_id=article.article_id,
                success=False,
                translated=False,
                skipped=False,
                provider=getattr(self.backend, "provider_name", ""),
                model=getattr(self.backend, "model_name", ""),
                error=str(exc),
            )
        except Exception as exc:
            message = f"Unexpected translation failure: {exc}"
            self._record_failure(article, message)
            return ArticleTranslationOutcome(
                article_id=article.article_id,
                success=False,
                translated=False,
                skipped=False,
                provider=getattr(self.backend, "provider_name", ""),
                model=getattr(self.backend, "model_name", ""),
                error=message,
            )

        return ArticleTranslationOutcome(
            article_id=article.article_id,
            success=True,
            translated=True,
            skipped=False,
            provider=result.provider,
            model=result.model,
            warnings=warnings,
        )

    def translate_articles(
        self,
        articles: Iterable[NewsArticle],
        *,
        overwrite: bool | None = None,
        continue_on_error: bool = True,
    ) -> TranslationBatchReport:
        """Translate a batch and return an auditable report."""

        report = TranslationBatchReport()

        for article in articles:
            report.total += 1

            try:
                outcome = self.translate_article(
                    article,
                    overwrite=overwrite,
                )
            except Exception as exc:
                if not continue_on_error:
                    raise
                outcome = ArticleTranslationOutcome(
                    article_id=getattr(article, "article_id", ""),
                    success=False,
                    translated=False,
                    skipped=False,
                    error=str(exc),
                )

            report.outcomes.append(outcome)

            if outcome.translated:
                report.translated += 1
            elif outcome.skipped:
                report.skipped += 1
            else:
                report.failed += 1

            if not outcome.success and not continue_on_error:
                raise TranslationError(outcome.error)

        return report

    @staticmethod
    def _validate_article_eligibility(article: NewsArticle) -> None:
        if not isinstance(article, NewsArticle):
            raise TypeError(
                "TeluguTranslator expects a canonical NewsArticle instance."
            )

        blocked_statuses = {
            ArticleStatus.REJECTED,
            ArticleStatus.DUPLICATE,
            ArticleStatus.FAILED,
        }
        if article.status in blocked_statuses:
            raise TranslationValidationError(
                f"Article status '{article.status.value}' is not translatable."
            )

        if not article.effective_headline:
            raise TranslationValidationError(
                "Article has no English headline to translate."
            )

        if not best_script(article):
            raise TranslationValidationError(
                "Article has no English summary or script to translate."
            )

    @staticmethod
    def _already_translated(article: NewsArticle) -> bool:
        return bool(
            article.telugu_headline
            and article.telugu_summary
            and article.telugu_script
        )

    @staticmethod
    def _build_request(article: NewsArticle) -> TranslationRequest:
        return TranslationRequest(
            article_id=article.article_id,
            headline=normalize_multiline(article.effective_headline),
            summary=best_summary(article),
            script=best_script(article),
            category=article.category.value,
            publisher=article.publisher,
            source_name=article.source_name,
            published_at=safe_iso_datetime(article.published_at),
            keywords=tuple(article.keywords),
        )

    @staticmethod
    def _apply_result(
        article: NewsArticle,
        result: TranslationResult,
        warnings: Sequence[str],
    ) -> None:
        translated_at = utc_now()

        article.telugu_headline = result.telugu_headline
        article.telugu_summary = result.telugu_summary
        article.telugu_script = result.telugu_script
        article.language = LanguageCode.TELUGU
        article.status = ArticleStatus.TRANSLATED
        article.updated_at = translated_at

        translation_metadata = {
            "provider": result.provider,
            "model": result.model,
            "translated_at": translated_at.isoformat(),
            "warnings": list(warnings),
            "source_language": LanguageCode.ENGLISH.value,
            "target_language": LanguageCode.TELUGU.value,
        }

        article.metadata = dict(article.metadata or {})
        article.metadata["translation"] = translation_metadata
        article.validate()

    @staticmethod
    def _record_failure(article: NewsArticle, error: str) -> None:
        failed_at = utc_now()
        article.metadata = dict(article.metadata or {})
        article.metadata["translation_failure"] = {
            "error": normalize_text(error),
            "failed_at": failed_at.isoformat(),
        }
        article.updated_at = failed_at


# ==========================================================
# PUBLIC CONVENIENCE FUNCTIONS
# ==========================================================


def translate_article_to_telugu(
    article: NewsArticle,
    *,
    translator: TeluguTranslator | None = None,
    overwrite: bool | None = None,
) -> ArticleTranslationOutcome:
    """Translate one canonical article using a supplied or configured service."""

    service = translator or TeluguTranslator.from_environment()
    return service.translate_article(article, overwrite=overwrite)


def translate_articles_to_telugu(
    articles: Iterable[NewsArticle],
    *,
    translator: TeluguTranslator | None = None,
    overwrite: bool | None = None,
    continue_on_error: bool = True,
) -> TranslationBatchReport:
    """Translate multiple canonical articles."""

    service = translator or TeluguTranslator.from_environment()
    return service.translate_articles(
        articles,
        overwrite=overwrite,
        continue_on_error=continue_on_error,
    )


# ==========================================================
# MODULE SELF-TEST
# ==========================================================


def _make_self_test_article() -> NewsArticle:
    """Create a canonical article for deterministic testing."""

    return NewsArticle(
        article_id="article_telugu_translation_test",
        title="Heavy rain continues across Andhra Pradesh",
        generated_headline="Heavy rain continues across Andhra Pradesh",
        url="https://example.com/news/heavy-rain",
        source_id="source_bahuvu_test",
        source_name="Bahuvu Test Feed",
        publisher="Example News",
        description=(
            "Officials issued alerts as heavy rainfall continued "
            "across several districts."
        ),
        summary=(
            "Officials issued alerts as heavy rainfall continued "
            "across several districts."
        ),
        script=(
            "Heavy rain continues across Andhra Pradesh. "
            "Officials issued alerts as heavy rainfall continued "
            "across several districts."
        ),
        status=ArticleStatus.SCRIPTED,
        language=LanguageCode.ENGLISH,
        reliability_score=90.0,
        relevance_score=88.0,
        importance_score=85.0,
        editorial_score=89.0,
        keywords=["Andhra Pradesh", "heavy rain", "alerts"],
    )


def _run_self_test() -> None:
    """Run deterministic translation, validation, and overwrite tests."""

    settings = TranslationSettings(
        provider=TranslationProvider.DETERMINISTIC,
        model=DeterministicTeluguBackend.model_name,
    )
    translator = TeluguTranslator(
        DeterministicTeluguBackend(),
        settings=settings,
    )
    article = _make_self_test_article()

    outcome = translator.translate_article(article)

    assert outcome.success
    assert outcome.translated
    assert not outcome.skipped
    assert article.status == ArticleStatus.TRANSLATED
    assert article.language == LanguageCode.TELUGU
    assert contains_telugu(article.telugu_headline)
    assert contains_telugu(article.telugu_summary)
    assert contains_telugu(article.telugu_script)
    assert article.metadata["translation"]["provider"] == "deterministic"

    second_outcome = translator.translate_article(article)
    assert second_outcome.success
    assert second_outcome.skipped
    assert not second_outcome.translated

    report = translator.translate_articles(
        [_make_self_test_article(), _make_self_test_article()]
    )
    assert report.total == 2
    assert report.translated == 2
    assert report.failed == 0

    print("Telugu translator initialized successfully.")
    print(f"Article ID       : {article.article_id}")
    print(f"Provider         : {outcome.provider}")
    print(f"Model            : {outcome.model}")
    print(f"Status           : {article.status.value}")
    print(f"Language         : {article.language.value}")
    print(f"Telugu headline  : {article.telugu_headline}")
    print(f"Telugu summary   : {article.telugu_summary}")
    print(f"Batch translated : {report.translated}")
    print(f"Batch failed     : {report.failed}")
    print("Telugu translator self-test passed.")


if __name__ == "__main__":
    _run_self_test()