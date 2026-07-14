"""
BahuvuNewsAI deterministic offline AI provider.

This module provides a no-network fallback implementation for the unified
BahuvuNewsAI AI subsystem.

The offline provider is designed for:

* Development and automated testing.
* Pipeline continuity when remote AI services are unavailable.
* Deterministic translation fixtures.
* Basic summarization.
* Rule-based classification.
* Editorial cleanup.
* Template-based broadcast script generation.
* Structured JSON output.
* Health checks without external dependencies.

The provider intentionally does not pretend to be a general-purpose language
model. It performs conservative deterministic transformations and clearly
identifies itself as an offline fallback.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from ai.providers.base import (
    BaseAIProvider,
    ProviderCapability,
    ProviderConfigurationError,
    ProviderExecutionContext,
    ProviderHealth,
    ProviderMetadata,
    ProviderOperationalStatus,
    RateLimitPolicy,
    RetryPolicy,
    read_object_field,
    safe_int,
    utc_now_iso,
)


__all__ = [
    "OfflineTask",
    "OfflineConfiguration",
    "OfflineUsage",
    "OfflineResponse",
    "OfflineProvider",
    "create_offline_provider",
]


MODULE_NAME = "BahuvuNewsAI deterministic offline AI provider"
MODULE_VERSION = "1.0.0"
DEFAULT_MODEL = "bahuvu-offline-rules-v1"


class OfflineTask(str, Enum):
    """Tasks supported by the deterministic offline provider."""

    TEXT_GENERATION = "text_generation"
    TRANSLATION = "translation"
    SUMMARIZATION = "summarization"
    CLASSIFICATION = "classification"
    EDITORIAL_POLISHING = "editorial_polishing"
    SCRIPT_GENERATION = "script_generation"
    STRUCTURED_OUTPUT = "structured_output"


@dataclass(frozen=True, slots=True)
class OfflineConfiguration:
    """Offline provider configuration."""

    model: str = DEFAULT_MODEL
    enabled: bool = True
    maximum_summary_sentences: int = 3
    maximum_script_words: int = 220
    preserve_unknown_translation_text: bool = True

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("Offline model name cannot be empty")

        if self.maximum_summary_sentences < 1:
            raise ValueError(
                "maximum_summary_sentences must be at least 1"
            )

        if self.maximum_script_words < 20:
            raise ValueError(
                "maximum_script_words must be at least 20"
            )


@dataclass(frozen=True, slots=True)
class OfflineUsage:
    """Approximate deterministic token usage."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class OfflineResponse:
    """Normalized response returned by the offline provider."""

    request_id: str
    status: str
    provider: str
    model: str
    task: str
    text: str
    created_at: str
    usage: OfflineUsage = field(default_factory=OfflineUsage)
    structured_data: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.status == "success"

    @property
    def content(self) -> str:
        return self.text

    @property
    def output_text(self) -> str:
        return self.text

    @property
    def token_usage(self) -> OfflineUsage:
        return self.usage


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _split_sentences(text: str) -> list[str]:
    normalized = _normalize_whitespace(text)

    if not normalized:
        return []

    parts = re.split(
        r"(?<=[.!?।])\s+",
        normalized,
    )

    return [part.strip() for part in parts if part.strip()]


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _estimate_tokens(text: str) -> int:
    words = _word_count(text)
    return max(1, round(words * 1.35)) if text.strip() else 0


class OfflineProvider(BaseAIProvider[Any, OfflineResponse]):
    """
    Deterministic local fallback provider.

    The provider uses fixed rules and templates. It does not make network
    requests and does not require credentials.
    """

    _TELUGU_PHRASES: Mapping[str, str] = {
        "heavy rain": "భారీ వర్షాలు",
        "heavy rainfall": "భారీ వర్షపాతం",
        "officials issued a warning": (
            "అధికారులు హెచ్చరిక జారీ చేశారు"
        ),
        "weather warning": "వాతావరణ హెచ్చరిక",
        "government": "ప్రభుత్వం",
        "police": "పోలీసులు",
        "district": "జిల్లా",
        "districts": "జిల్లాలు",
        "today": "ఈ రోజు",
        "tomorrow": "రేపు",
        "people": "ప్రజలు",
        "news": "వార్తలు",
        "breaking news": "తాజా వార్తలు",
        "chief minister": "ముఖ్యమంత్రి",
        "prime minister": "ప్రధాన మంత్రి",
        "india": "భారతదేశం",
        "andhra pradesh": "ఆంధ్రప్రదేశ్",
        "telangana": "తెలంగాణ",
        "warning": "హెచ్చరిక",
        "alert": "అప్రమత్తత",
        "rain": "వర్షం",
        "continue": "కొనసాగుతుంది",
        "continues": "కొనసాగుతోంది",
        "continuing": "కొనసాగుతున్న",
        "authorities": "అధికారులు",
        "issued": "జారీ చేశారు",
        "schools": "పాఠశాలలు",
        "closed": "మూసివేశారు",
        "rescue operations": "రక్షణ చర్యలు",
        "emergency services": "అత్యవసర సేవలు",
    }

    _CATEGORY_KEYWORDS: Mapping[str, tuple[str, ...]] = {
        "politics": (
            "election",
            "minister",
            "parliament",
            "assembly",
            "government",
            "party",
            "political",
        ),
        "national": (
            "india",
            "national",
            "central government",
            "supreme court",
            "new delhi",
        ),
        "international": (
            "international",
            "global",
            "united nations",
            "foreign",
            "world",
            "war",
        ),
        "business": (
            "market",
            "stock",
            "economy",
            "business",
            "company",
            "revenue",
            "bank",
        ),
        "technology": (
            "technology",
            "software",
            "artificial intelligence",
            "ai ",
            "digital",
            "cyber",
            "startup",
        ),
        "sports": (
            "match",
            "tournament",
            "cricket",
            "football",
            "player",
            "team",
            "score",
        ),
        "weather": (
            "rain",
            "cyclone",
            "weather",
            "storm",
            "temperature",
            "flood",
            "imd",
        ),
        "health": (
            "health",
            "hospital",
            "disease",
            "medical",
            "doctor",
            "vaccine",
        ),
        "education": (
            "school",
            "college",
            "university",
            "student",
            "exam",
            "education",
        ),
        "crime": (
            "police",
            "arrest",
            "crime",
            "murder",
            "theft",
            "investigation",
        ),
        "entertainment": (
            "film",
            "movie",
            "actor",
            "actress",
            "cinema",
            "music",
        ),
    }

    def __init__(
        self,
        configuration: OfflineConfiguration | None = None,
    ) -> None:
        self.configuration = configuration or OfflineConfiguration()

        metadata = ProviderMetadata(
            name="offline",
            display_name="Bahuvu Offline Rules",
            version=MODULE_VERSION,
            provider_type="offline",
            default_model=self.configuration.model,
            capabilities=frozenset(
                {
                    ProviderCapability.TEXT_GENERATION,
                    ProviderCapability.TRANSLATION,
                    ProviderCapability.SUMMARIZATION,
                    ProviderCapability.CLASSIFICATION,
                    ProviderCapability.EDITORIAL_POLISHING,
                    ProviderCapability.SCRIPT_GENERATION,
                    ProviderCapability.STRUCTURED_OUTPUT,
                    ProviderCapability.OFFLINE,
                }
            ),
            description=(
                "Deterministic no-network fallback provider for "
                "BahuvuNewsAI"
            ),
        )

        super().__init__(
            metadata,
            enabled=self.configuration.enabled,
            timeout_seconds=10.0,
            retry_policy=RetryPolicy(
                max_attempts=1,
                initial_delay_seconds=0.0,
                maximum_delay_seconds=0.0,
                jitter_seconds=0.0,
            ),
            rate_limit_policy=RateLimitPolicy(
                requests_per_window=1000,
                window_seconds=1.0,
                enabled=False,
            ),
        )

    def validate_request(self, request: Any) -> None:
        super().validate_request(request)

        prompt = self._request_prompt(request)

        if not prompt.strip():
            raise ProviderConfigurationError(
                "Offline request prompt cannot be empty",
                provider=self.name,
                request_id=self._request_id(request),
            )

    def _request_task(self, request: Any) -> str:
        value = read_object_field(
            request,
            "task",
            "task_type",
            "operation",
            default=OfflineTask.TEXT_GENERATION.value,
        )

        value = _enum_value(value)
        normalized = str(value).strip().lower()

        aliases = {
            "polish": OfflineTask.EDITORIAL_POLISHING.value,
            "editorial": OfflineTask.EDITORIAL_POLISHING.value,
            "summary": OfflineTask.SUMMARIZATION.value,
            "classify": OfflineTask.CLASSIFICATION.value,
            "script": OfflineTask.SCRIPT_GENERATION.value,
            "json": OfflineTask.STRUCTURED_OUTPUT.value,
        }

        return aliases.get(
            normalized,
            normalized or OfflineTask.TEXT_GENERATION.value,
        )

    def _request_prompt(self, request: Any) -> str:
        value = read_object_field(
            request,
            "prompt",
            "input_text",
            "text",
            "content",
            "source_text",
            default="",
        )

        if isinstance(value, str):
            return value

        if isinstance(value, Sequence) and not isinstance(
            value,
            (bytes, bytearray),
        ):
            return "\n".join(str(item) for item in value)

        return str(value or "")

    def _request_model_name(self, request: Any) -> str:
        value = read_object_field(
            request,
            "model",
            "model_name",
            default=self.configuration.model,
        )

        return str(_enum_value(value) or self.configuration.model)

    def _request_target_language(self, request: Any) -> str:
        value = read_object_field(
            request,
            "target_language",
            "output_language",
            "language",
            default="te",
        )

        return str(_enum_value(value) or "te").lower()

    def _request_categories(self, request: Any) -> tuple[str, ...]:
        categories = read_object_field(
            request,
            "categories",
            "labels",
            default=None,
        )

        if categories is None:
            return tuple(self._CATEGORY_KEYWORDS.keys())

        if isinstance(categories, str):
            return (categories,)

        return tuple(str(item) for item in categories)

    def _expects_structured_output(self, request: Any) -> bool:
        explicit = read_object_field(
            request,
            "structured_output",
            "json_output",
            "expect_json",
            default=None,
        )

        if explicit is not None:
            return bool(explicit)

        response_format = read_object_field(
            request,
            "response_format",
            "output_format",
            default="",
        )

        normalized = str(_enum_value(response_format)).lower()

        return normalized in {
            "json",
            "application/json",
            "structured",
            "structured_output",
        }

    def _translate_to_telugu(self, text: str) -> str:
        normalized = _normalize_whitespace(text)
        lowered = normalized.lower()

        exact_translations = {
            (
                "officials issued a warning over continuing "
                "heavy rainfall."
            ): (
                "కొనసాగుతున్న భారీ వర్షపాతంపై అధికారులు "
                "హెచ్చరిక జారీ చేశారు."
            ),
            "heavy rain continues in andhra pradesh.": (
                "ఆంధ్రప్రదేశ్‌లో భారీ వర్షాలు కొనసాగుతున్నాయి."
            ),
            "schools were closed due to heavy rain.": (
                "భారీ వర్షాల కారణంగా పాఠశాలలను మూసివేశారు."
            ),
            "rescue operations are continuing.": (
                "రక్షణ చర్యలు కొనసాగుతున్నాయి."
            ),
        }

        if lowered in exact_translations:
            return exact_translations[lowered]

        translated = lowered

        for phrase in sorted(
            self._TELUGU_PHRASES,
            key=len,
            reverse=True,
        ):
            translated = re.sub(
                rf"\b{re.escape(phrase)}\b",
                self._TELUGU_PHRASES[phrase],
                translated,
                flags=re.IGNORECASE,
            )

        translated = translated.strip()

        if re.search(r"[అ-హ]", translated):
            translated = translated.rstrip(".")
            return f"{translated}."

        if self.configuration.preserve_unknown_translation_text:
            return (
                "[ఆఫ్‌లైన్ అనువాదం అందుబాటులో లేదు] "
                f"{normalized}"
            )

        return "ఆఫ్‌లైన్ అనువాదం అందుబాటులో లేదు."

    def _translate(self, request: Any, text: str) -> str:
        target_language = self._request_target_language(request)

        if target_language in {"te", "telugu", "te-in"}:
            return self._translate_to_telugu(text)

        if target_language in {"en", "english", "en-in", "en-us"}:
            return _normalize_whitespace(text)

        return (
            f"[Offline translation unavailable for "
            f"{target_language}] {_normalize_whitespace(text)}"
        )

    def _summarize(self, text: str) -> str:
        sentences = _split_sentences(text)

        if not sentences:
            return ""

        selected = sentences[
            : self.configuration.maximum_summary_sentences
        ]

        return " ".join(selected)

    def _classify(
        self,
        request: Any,
        text: str,
    ) -> tuple[str, dict[str, int]]:
        lowered = f" {text.lower()} "
        requested_categories = self._request_categories(request)
        scores: dict[str, int] = {}

        for category in requested_categories:
            keywords = self._CATEGORY_KEYWORDS.get(
                category.lower(),
                (),
            )

            score = sum(
                1
                for keyword in keywords
                if keyword.lower() in lowered
            )

            scores[category] = score

        ranked = sorted(
            scores.items(),
            key=lambda item: (-item[1], item[0]),
        )

        if not ranked or ranked[0][1] == 0:
            return "general", scores

        return ranked[0][0], scores

    def _polish(self, text: str) -> str:
        polished = text.strip()

        replacements = (
            (r"\s+", " "),
            (r"\s+([,.;:!?])", r"\1"),
            (r"([,.;:!?])([^\s])", r"\1 \2"),
            (r"\bvery very\b", "very"),
            (r"\bin order to\b", "to"),
            (r"\bdue to the fact that\b", "because"),
            (r"\bat this point in time\b", "now"),
            (r"\bhas been announced by\b", "was announced by"),
        )

        for pattern, replacement in replacements:
            polished = re.sub(
                pattern,
                replacement,
                polished,
                flags=re.IGNORECASE,
            )

        sentences = _split_sentences(polished)
        normalized_sentences: list[str] = []

        for sentence in sentences:
            sentence = sentence.strip()

            if not sentence:
                continue

            sentence = sentence[0].upper() + sentence[1:]

            if sentence[-1] not in ".!?।":
                sentence += "."

            normalized_sentences.append(sentence)

        return " ".join(normalized_sentences)

    def _script(self, text: str) -> str:
        summary = self._summarize(text)
        polished = self._polish(summary)

        script = (
            "నమస్కారం. బహువు న్యూస్‌కు స్వాగతం. "
            f"{polished} "
            "ఈ వార్తకు సంబంధించిన మరిన్ని వివరాలు అందుబాటులోకి "
            "వచ్చిన వెంటనే తెలియజేస్తాము."
        )

        words = script.split()

        if len(words) > self.configuration.maximum_script_words:
            script = " ".join(
                words[: self.configuration.maximum_script_words]
            )
            script = script.rstrip(" ,.;:") + "."

        return script

    def _structured_output(
        self,
        request: Any,
        text: str,
    ) -> tuple[str, Mapping[str, Any]]:
        task = self._request_task(request)

        if task == OfflineTask.CLASSIFICATION.value:
            category, scores = self._classify(request, text)
            data: Mapping[str, Any] = {
                "category": category,
                "scores": scores,
                "provider": self.name,
                "deterministic": True,
            }

        elif task == OfflineTask.SUMMARIZATION.value:
            summary = self._summarize(text)
            data = {
                "summary": summary,
                "sentence_count": len(_split_sentences(summary)),
                "provider": self.name,
                "deterministic": True,
            }

        elif task == OfflineTask.TRANSLATION.value:
            translation = self._translate(request, text)
            data = {
                "translation": translation,
                "target_language": (
                    self._request_target_language(request)
                ),
                "provider": self.name,
                "deterministic": True,
            }

        else:
            data = {
                "text": _normalize_whitespace(text),
                "task": task,
                "provider": self.name,
                "deterministic": True,
            }

        return (
            json.dumps(
                data,
                ensure_ascii=False,
                sort_keys=True,
            ),
            data,
        )

    def _generate_once(
        self,
        request: Any,
        context: ProviderExecutionContext,
    ) -> OfflineResponse:
        task = self._request_task(request)
        prompt = self._request_prompt(request)
        model = self._request_model_name(request)
        structured_data: Any = None

        if task == OfflineTask.TRANSLATION.value:
            output = self._translate(request, prompt)

        elif task == OfflineTask.SUMMARIZATION.value:
            output = self._summarize(prompt)

        elif task == OfflineTask.CLASSIFICATION.value:
            category, scores = self._classify(request, prompt)
            output = category
            structured_data = {
                "category": category,
                "scores": scores,
            }

        elif task == OfflineTask.EDITORIAL_POLISHING.value:
            output = self._polish(prompt)

        elif task == OfflineTask.SCRIPT_GENERATION.value:
            output = self._script(prompt)

        elif task == OfflineTask.STRUCTURED_OUTPUT.value:
            output, structured_data = self._structured_output(
                request,
                prompt,
            )

        elif task == OfflineTask.TEXT_GENERATION.value:
            output = self._polish(prompt)

        else:
            raise ProviderConfigurationError(
                f"Unsupported offline task: {task}",
                provider=self.name,
                request_id=context.request_id,
            )

        if self._expects_structured_output(request):
            output, structured_data = self._structured_output(
                request,
                prompt,
            )

        input_tokens = _estimate_tokens(prompt)
        output_tokens = _estimate_tokens(output)

        return OfflineResponse(
            request_id=context.request_id,
            status="success",
            provider=self.name,
            model=model,
            task=task,
            text=output,
            created_at=utc_now_iso(),
            usage=OfflineUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
            structured_data=structured_data,
            metadata={
                "offline": True,
                "deterministic": True,
                "network_used": False,
                "fallback_quality": "rule_based",
            },
        )

    def extract_usage(
        self,
        response: OfflineResponse,
    ) -> tuple[int, int, int]:
        return (
            response.usage.input_tokens,
            response.usage.output_tokens,
            response.usage.total_tokens,
        )

    def _perform_health_check(
        self,
    ) -> tuple[bool, str, dict[str, Any]]:
        self.validate_configuration()

        return (
            True,
            "Offline deterministic provider is ready",
            {
                "model": self.configuration.model,
                "network_required": False,
                "credentials_required": False,
                "deterministic": True,
            },
        )

    def health_check(self) -> ProviderHealth:
        return super().health_check()


def create_offline_provider(
    *,
    model: str = DEFAULT_MODEL,
    enabled: bool = True,
    maximum_summary_sentences: int = 3,
    maximum_script_words: int = 220,
    preserve_unknown_translation_text: bool = True,
) -> OfflineProvider:
    """Create a deterministic offline provider."""

    return OfflineProvider(
        OfflineConfiguration(
            model=model,
            enabled=enabled,
            maximum_summary_sentences=(
                maximum_summary_sentences
            ),
            maximum_script_words=maximum_script_words,
            preserve_unknown_translation_text=(
                preserve_unknown_translation_text
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class _SelfTestRequest:
    request_id: str
    task: str
    prompt: str
    model: str = DEFAULT_MODEL
    source_language: str = "en"
    target_language: str = "te"
    structured_output: bool = False
    categories: tuple[str, ...] = ()


def _run_self_test() -> None:
    provider = create_offline_provider()

    translation_request = _SelfTestRequest(
        request_id="offline_translation_0001",
        task="translation",
        prompt=(
            "Officials issued a warning over continuing heavy rainfall."
        ),
    )

    summary_request = _SelfTestRequest(
        request_id="offline_summary_0001",
        task="summarization",
        prompt=(
            "Heavy rain continued across several districts. "
            "Officials issued a weather warning. "
            "Emergency teams were deployed. "
            "Residents were advised to remain cautious."
        ),
    )

    classification_request = _SelfTestRequest(
        request_id="offline_classification_0001",
        task="classification",
        prompt=(
            "The cricket team won the final match of the tournament."
        ),
        categories=("sports", "politics", "business"),
        structured_output=True,
    )

    polish_request = _SelfTestRequest(
        request_id="offline_polish_0001",
        task="editorial_polishing",
        prompt=(
            "officials  said that  heavy rain will continue"
        ),
    )

    translation_response = provider.generate(
        translation_request
    )
    summary_response = provider.generate(summary_request)
    classification_response = provider.generate(
        classification_request
    )
    polish_response = provider.generate(polish_request)

    health = provider.health_check()
    metrics = provider.get_metrics()

    assert translation_response.status == "success"
    assert translation_response.provider == "offline"
    assert "హెచ్చరిక" in translation_response.text

    assert summary_response.status == "success"
    assert len(_split_sentences(summary_response.text)) == 3

    assert classification_response.status == "success"
    assert classification_response.structured_data is not None
    assert (
        classification_response.structured_data["category"]
        == "sports"
    )

    assert polish_response.status == "success"
    assert polish_response.text.startswith("Officials")
    assert polish_response.text.endswith(".")

    assert health.status is ProviderOperationalStatus.HEALTHY
    assert metrics.total_requests == 4
    assert metrics.successful_requests == 4
    assert metrics.failed_requests == 0
    assert metrics.success_rate == 100.0

    assert provider.supports(ProviderCapability.OFFLINE)
    assert provider.supports(ProviderCapability.TRANSLATION)
    assert provider.supports(
        ProviderCapability.STRUCTURED_OUTPUT
    )

    print(MODULE_NAME)
    print(f"Module version : {MODULE_VERSION}")
    print(f"Provider       : {provider.name}")
    print(f"Model          : {provider.default_model}")
    print(f"Translation    : {translation_response.text}")
    print(f"Summary        : {summary_response.text}")
    print(
        "Classification : "
        f"{classification_response.structured_data['category']}"
    )
    print(f"Polished text  : {polish_response.text}")
    print(f"Requests       : {metrics.total_requests}")
    print(f"Success rate   : {metrics.success_rate:.2f}%")
    print(f"Health status  : {health.status.value}")
    print("Offline AI provider self-test passed.")


if __name__ == "__main__":
    _run_self_test()