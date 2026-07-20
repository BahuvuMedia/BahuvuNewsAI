"""
BahuvuNewsAI AI Broadcast Director.

This module converts a selected editorial bulletin into one canonical,
validated Telugu broadcast production plan.

Design rules:
* AI performs newsroom rewriting and production direction.
* Deterministic Python protects facts and validates output.
* Display text, anchor narration, and TTS speech text remain separate.
* Downstream voice, scenes, graphics, and video stages consume one plan.
* AI failure never destroys the bulletin; a deterministic fallback is used.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from ai.manager import AIManagerRequest, get_default_ai_manager

MODULE_NAME = "BahuvuNewsAI AI Broadcast Director"
MODULE_VERSION = "1.0.0"

_TELUGU_RE = re.compile(r"[\u0C00-\u0C7F]")
_LATIN_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9.'&/-]*\b")
_NUMBER_RE = re.compile(
    r"(?<!\w)(?:₹|Rs\.?|INR|\$|USD|€|EUR|£|GBP)?\s*"
    r"\d[\d,]*(?:\.\d+)?(?:\s*(?:%|percent|crore|crores|lakh|lakhs|million|billion))?",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b(?:"
    r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|"
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2}(?:,\s*\d{4})?"
    r")\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?।])\s+|\n+")

_ALLOWED_LATIN_TOKENS = {
    "AI", "GDP", "CEO", "CM", "PM", "MP", "MLA", "IAS", "IPS",
    "CBI", "ED", "GST", "UPI", "RBI", "SEBI", "NASA", "ISRO",
    "WHO", "UN", "UNICEF", "IMF", "IT", "TV", "AP", "TS",
}

_TRANSLITERATIONS = {
    "AI": "ఏఐ",
    "GDP": "జీడీపీ",
    "CEO": "సీఈఓ",
    "CM": "సీఎం",
    "PM": "పీఎం",
    "MP": "ఎంపీ",
    "MLA": "ఎమ్మెల్యే",
    "IAS": "ఐఏఎస్",
    "IPS": "ఐపీఎస్",
    "CBI": "సీబీఐ",
    "ED": "ఈడీ",
    "GST": "జీఎస్టీ",
    "UPI": "యూపీఐ",
    "RBI": "ఆర్‌బీఐ",
    "SEBI": "సెబీ",
    "NASA": "నాసా",
    "ISRO": "ఇస్రో",
    "WHO": "డబ్ల్యూహెచ్ఓ",
    "UN": "ఐక్యరాజ్యసమితి",
    "UNICEF": "యూనిసెఫ్",
    "IMF": "ఐఎంఎఫ్",
    "IT": "ఐటీ",
    "TV": "టీవీ",
}

_KNOWN_BOILERPLATE = (
    "subscribe",
    "subscribed",
    "subscription benefits",
    "first day first show",
    "today's cache",
    "todays cache",
    "click here",
    "read more",
    "advertisement",
    "sign in",
    "log in",
    "account subscription",
)

_DEFAULT_INTRO = (
    "నమస్కారం. బహువు న్యూస్‌కు స్వాగతం. "
    "ఇప్పుడు ముఖ్యమైన వార్తలను వివరంగా తెలుసుకుందాం."
)
_DEFAULT_OUTRO = (
    "ఇవీ ఇప్పటి ముఖ్యమైన వార్తలు. మరిన్ని విశ్వసనీయ వార్తల కోసం "
    "బహువు న్యూస్‌ను అనుసరించండి. నమస్కారం."
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}_{stamp}_{uuid4().hex[:8]}"


def clean_text(value: Any) -> str:
    text = str(value or "").replace("\ufeff", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def read_field(value: Any, *names: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return default

    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return default


def primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if hasattr(value, "__dataclass_fields__"):
        return {key: primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [primitive(item) for item in value]
    return value


def telugu_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    telugu = sum(1 for char in letters if _TELUGU_RE.fullmatch(char))
    return telugu / len(letters)


def latin_words(text: str) -> list[str]:
    return _LATIN_WORD_RE.findall(text)


def sentence_parts(text: str) -> list[str]:
    return [
        clean_text(part)
        for part in _SENTENCE_SPLIT_RE.split(clean_text(text))
        if clean_text(part)
    ]


def apply_tts_transliterations(text: str) -> str:
    result = clean_text(text)
    for source, target in sorted(
        _TRANSLITERATIONS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        result = re.sub(
            rf"(?<![A-Za-z0-9]){re.escape(source)}(?![A-Za-z0-9])",
            target,
            result,
            flags=re.IGNORECASE,
        )
    return clean_text(result)


def strip_boilerplate(text: str) -> str:
    kept: list[str] = []
    for sentence in sentence_parts(text):
        lowered = sentence.casefold()
        if any(phrase in lowered for phrase in _KNOWN_BOILERPLATE):
            continue
        kept.append(sentence)
    return " ".join(kept).strip()


class PlanStatus(str, Enum):
    READY = "ready"
    READY_WITH_WARNINGS = "ready_with_warnings"
    BLOCKED = "blocked"


@dataclass(slots=True)
class StoryFactRecord:
    original_headline: str = ""
    original_summary: str = ""
    original_content: str = ""
    source_names: list[str] = field(default_factory=list)
    people_and_organisations: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    quotations: list[str] = field(default_factory=list)
    protected_terms: list[str] = field(default_factory=list)

    def source_text(self) -> str:
        return "\n".join(
            part
            for part in (
                self.original_headline,
                self.original_summary,
                self.original_content,
            )
            if part
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DirectedScene:
    scene_id: str
    story_id: str
    order: int
    narration_segment: str
    display_headline: str
    supporting_text: str = ""
    visual_search_terms: list[str] = field(default_factory=list)
    preferred_visual_type: str = "story_image"
    preferred_visual: str = ""
    fallback_visual_type: str = "branded_headline_card"
    fallback_visual: str = "assets/images/bahuvu_newsroom_background.png"
    estimated_duration_seconds: float = 0.0
    actual_duration_seconds: float = 0.0
    resolved_visual_path: str = ""
    readiness: str = "planned"
    warnings: list[str] = field(default_factory=list)
    blocking_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DirectedStory:
    story_id: str
    rank: int
    category: str
    source_headline: str
    display_headline: str
    display_summary: str
    anchor_narration: str
    speech_text: str
    pronunciation_notes: dict[str, str] = field(default_factory=dict)
    visual_search_terms: list[str] = field(default_factory=list)
    preferred_image_path: str = ""
    preferred_image_url: str = ""
    fact_record: StoryFactRecord = field(default_factory=StoryFactRecord)
    scenes: list[DirectedScene] = field(default_factory=list)
    estimated_duration_seconds: float = 0.0
    actual_audio_duration_seconds: float = 0.0
    audio_path: str = ""
    ai_provider: str = ""
    ai_model: str = ""
    ai_fallback_used: bool = False
    warnings: list[str] = field(default_factory=list)
    blocking_errors: list[str] = field(default_factory=list)

    @property
    def production_ready(self) -> bool:
        return not self.blocking_errors and all(
            not scene.blocking_errors for scene in self.scenes
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["production_ready"] = self.production_ready
        return payload


@dataclass(slots=True)
class BroadcastProductionPlan:
    production_id: str
    bulletin_id: str
    bulletin_title: str
    edition_name: str
    language: str
    opening_narration: str
    opening_speech_text: str
    stories: list[DirectedStory]
    closing_narration: str
    closing_speech_text: str
    created_at: str = field(default_factory=utc_now_iso)
    director_version: str = MODULE_VERSION
    warnings: list[str] = field(default_factory=list)
    blocking_errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> PlanStatus:
        story_blockers = any(not story.production_ready for story in self.stories)
        if self.blocking_errors or story_blockers:
            return PlanStatus.BLOCKED
        story_warnings = any(story.warnings for story in self.stories)
        if self.warnings or story_warnings:
            return PlanStatus.READY_WITH_WARNINGS
        return PlanStatus.READY

    @property
    def production_ready(self) -> bool:
        return self.status is not PlanStatus.BLOCKED

    @property
    def estimated_duration_seconds(self) -> float:
        opening = estimate_speech_duration(self.opening_speech_text)
        closing = estimate_speech_duration(self.closing_speech_text)
        return opening + closing + sum(
            story.estimated_duration_seconds for story in self.stories
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "bulletin_id": self.bulletin_id,
            "bulletin_title": self.bulletin_title,
            "edition_name": self.edition_name,
            "language": self.language,
            "opening_narration": self.opening_narration,
            "opening_speech_text": self.opening_speech_text,
            "stories": [story.to_dict() for story in self.stories],
            "closing_narration": self.closing_narration,
            "closing_speech_text": self.closing_speech_text,
            "created_at": self.created_at,
            "director_version": self.director_version,
            "status": self.status.value,
            "production_ready": self.production_ready,
            "estimated_duration_seconds": round(
                self.estimated_duration_seconds, 3
            ),
            "warnings": list(self.warnings),
            "blocking_errors": list(self.blocking_errors),
            "metadata": primitive(self.metadata),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=indent,
        )

    def save_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(), encoding="utf-8")
        return target


@dataclass(slots=True)
class DirectorConfiguration:
    use_ai: bool = True
    require_ai: bool = False
    min_telugu_ratio: float = 0.72
    max_latin_words: int = 3
    max_story_words: int = 180
    min_story_words: int = 20
    target_words_per_minute: int = 125
    max_scenes_per_story: int = 5
    default_fallback_visual: str = (
        "assets/images/bahuvu_newsroom_background.png"
    )
    preferred_provider: str | None = "gemini"
    preferred_model: str | None = "gemini-flash-latest"
    temperature: float = 0.15
    max_output_tokens: int = 2200

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_telugu_ratio <= 1.0:
            raise ValueError("min_telugu_ratio must be between 0 and 1")
        if self.max_latin_words < 0:
            raise ValueError("max_latin_words cannot be negative")
        if self.max_story_words < self.min_story_words:
            raise ValueError(
                "max_story_words must be greater than min_story_words"
            )
        if self.target_words_per_minute <= 0:
            raise ValueError(
                "target_words_per_minute must be greater than zero"
            )
        if self.max_scenes_per_story <= 0:
            raise ValueError(
                "max_scenes_per_story must be greater than zero"
            )


def estimate_speech_duration(
    text: str,
    words_per_minute: int = 125,
) -> float:
    words = len(clean_text(text).split())
    if not words:
        return 0.0
    return max(1.0, words / max(1, words_per_minute) * 60.0)


class BroadcastDirectorError(RuntimeError):
    """Raised for unrecoverable Broadcast Director failures."""


class BroadcastDirector:
    def __init__(
        self,
        configuration: DirectorConfiguration | None = None,
        *,
        ai_manager: Any | None = None,
    ) -> None:
        self.configuration = configuration or DirectorConfiguration()
        self._ai_manager = ai_manager

    @property
    def ai_manager(self) -> Any:
        if self._ai_manager is None:
            self._ai_manager = get_default_ai_manager()
        return self._ai_manager

    def direct(
        self,
        bulletin: Any,
        *,
        production_id: str | None = None,
    ) -> BroadcastProductionPlan:
        stories = list(read_field(bulletin, "stories", default=[]) or [])
        bulletin_id = clean_text(read_field(bulletin, "id", default=""))
        bulletin_title = clean_text(
            read_field(bulletin, "title", default="")
        ) or "బహువు న్యూస్"
        edition_name = clean_text(
            read_field(bulletin, "edition_name", default="")
        )

        plan = BroadcastProductionPlan(
            production_id=production_id or new_id("bahuvu_broadcast"),
            bulletin_id=bulletin_id,
            bulletin_title=bulletin_title,
            edition_name=edition_name,
            language="te",
            opening_narration=self._opening_text(bulletin),
            opening_speech_text="",
            stories=[],
            closing_narration=self._closing_text(bulletin),
            closing_speech_text="",
            metadata={
                "source_story_count": len(stories),
                "ai_enabled": self.configuration.use_ai,
            },
        )
        plan.opening_speech_text = apply_tts_transliterations(
            plan.opening_narration
        )
        plan.closing_speech_text = apply_tts_transliterations(
            plan.closing_narration
        )

        if not stories:
            plan.blocking_errors.append(
                "The bulletin contains no stories."
            )
            return plan

        for order, story in enumerate(stories, start=1):
            try:
                directed = self._direct_story(story, order)
            except Exception as error:
                directed = self._fallback_story(story, order)
                directed.warnings.append(
                    f"AI direction failed; deterministic fallback used: {error}"
                )
                if self.configuration.require_ai:
                    directed.blocking_errors.append(
                        "AI direction was required but failed."
                    )
            plan.stories.append(directed)

        self._validate_plan(plan)
        return plan

    def _opening_text(self, bulletin: Any) -> str:
        value = strip_boilerplate(
            clean_text(
                read_field(
                    bulletin,
                    "opening_script",
                    "intro",
                    default="",
                )
            )
        )
        if value and telugu_ratio(value) >= 0.55:
            return value
        return _DEFAULT_INTRO

    def _closing_text(self, bulletin: Any) -> str:
        value = strip_boilerplate(
            clean_text(
                read_field(
                    bulletin,
                    "closing_script",
                    "outro",
                    default="",
                )
            )
        )
        if value and telugu_ratio(value) >= 0.55:
            return value
        return _DEFAULT_OUTRO

    def _direct_story(self, story: Any, order: int) -> DirectedStory:
        fallback = self._fallback_story(story, order)

        if not self.configuration.use_ai:
            return fallback

        prompt = self._build_prompt(story, fallback.fact_record, order)
        request = AIManagerRequest(
            request_id=new_id("broadcast_direction"),
            task="editorial_polish",
            prompt=prompt,
            provider=self.configuration.preferred_provider,
            model=self.configuration.preferred_model,
            source_language="en",
            target_language="te",
            temperature=self.configuration.temperature,
            max_output_tokens=self.configuration.max_output_tokens,
            structured_output=True,
            metadata={
                "story_id": fallback.story_id,
                "rank": order,
                "capability": "broadcast_direction",
            },
        )

        result = self.ai_manager.generate_with_details(request)
        if not result.success or not clean_text(result.text):
            raise BroadcastDirectorError(
                "AI manager returned no successful direction."
            )

        payload = self._parse_ai_json(result.text)
        directed = self._story_from_ai(
            story=story,
            order=order,
            fact_record=fallback.fact_record,
            payload=payload,
        )
        directed.ai_provider = clean_text(result.provider)
        directed.ai_model = clean_text(result.model)
        directed.ai_fallback_used = bool(result.used_fallback)
        if directed.ai_fallback_used:
            directed.warnings.append(
                "The AI manager used its provider fallback."
            )
        self._validate_story(directed)
        return directed

    def _build_prompt(
        self,
        story: Any,
        fact_record: StoryFactRecord,
        order: int,
    ) -> str:
        source_payload = {
            "story_id": clean_text(read_field(story, "id", default="")),
            "rank": order,
            "category": clean_text(
                read_field(story, "category", default="")
            ),
            "headline": fact_record.original_headline,
            "summary": fact_record.original_summary,
            "content": fact_record.original_content,
            "key_facts": list(
                read_field(story, "key_facts", default=[]) or []
            ),
            "source_names": fact_record.source_names,
            "protected_numbers": fact_record.numbers,
            "protected_dates": fact_record.dates,
            "protected_terms": fact_record.protected_terms,
        }

        return f"""
You are the senior Telugu television news editor and bulletin director for
BAHUVU NEWS.

Rewrite the supplied factual news story as polished, natural Telugu that a
professional television news anchor can read aloud immediately.

This is newsroom rewriting. It is not literal, word-for-word, or
sentence-by-sentence translation.

EDITORIAL VOICE:
- Write in clear, contemporary, neutral Telugu used in professional television
  news bulletins.
- The narration must sound as though it was originally written in Telugu.
- Use natural Telugu sentence order instead of preserving English syntax.
- Prefer direct, confident newsroom language.
- Keep spoken sentences concise, normally between 8 and 18 words.
- Break long factual sentences into two or more natural sentences.
- Avoid academic, bureaucratic, mechanical, or machine-translated Telugu.
- Avoid unnecessary repetition of names, titles, dates, and background facts.
- Use respectful plural verb forms for people where Telugu newsroom convention
  requires them.
- Use linking expressions only when they fit the meaning. Do not mechanically
  begin every story with phrases such as "????? ?????" or "? ?????????".

LANGUAGE RULES:
- Narration must be predominantly in Telugu script.
- Do not use English words merely because they appeared in the source.
- Preserve official names, organisation names, product names, technical terms,
  and internationally recognised terms when translation would be misleading.
- Transliterate unavoidable acronyms and abbreviations into readable Telugu
  pronunciation in speech_text.
- Examples for speech_text:
  AI -> ??
  GDP -> ??????
  BJP -> ??????
  MP -> ????
  MLA -> ?????????
  CEO -> ????
- Write BAHUVU NEWS in speech_text as "?????? ??????".
- Do not write phonetic spellings in display_headline or display_summary unless
  that is the standard public Telugu form.

FACTUAL SAFETY ? NON-NEGOTIABLE:
1. Preserve every person, organisation, place, date, number, percentage,
   currency amount, quotation, attribution, and factual relationship.
2. Do not invent causes, motives, reactions, analysis, context, quotations,
   consequences, or conclusions.
3. Do not strengthen uncertain claims into confirmed facts.
4. Preserve distinctions such as alleged, proposed, expected, likely, reported,
   and confirmed.
5. Remove website menus, subscription messages, promotions, advertisements,
   navigation text, unrelated recommendations, and publication boilerplate.
6. Do not add greetings, channel promotions, opinions, slogans, or calls to
   subscribe.

OUTPUT FIELD RULES:
- display_headline:
  Write one accurate, concise Telugu television headline.
  Prefer approximately 5 to 12 words.
  Do not end it with a full sentence explanation.

- display_summary:
  Write one short Telugu supporting line for the screen.
  It must add the most important fact not already clear from the headline.

- anchor_narration:
  Write the complete natural Telugu newsroom narration.
  Begin directly with the news.
  Use short connected sentences and smooth spoken rhythm.
  Include only facts supported by the supplied source.
  Do not include production instructions or labels.

- speech_text:
  Preserve the meaning and facts of anchor_narration.
  Make only pronunciation and pacing changes required for Telugu TTS.
  Expand or transliterate acronyms where needed.
  Use commas and full stops to create natural pauses.
  Do not add facts or commentary.

- pronunciation_notes:
  Include only terms that genuinely require special Telugu pronunciation.
  Map the original source term to the Telugu pronunciation used in speech_text.

- scenes:
  Create between 1 and {self.configuration.max_scenes_per_story} scenes.
  Divide the complete narration into meaningful consecutive segments.
  Every narration_segment must appear in the same order as anchor_narration.
  Every scene must include a useful visual concept and a branded fallback.
  Do not create empty, decorative, or narration-free scenes.

QUALITY CHECK BEFORE RESPONDING:
- Read the anchor_narration mentally as a Telugu television anchor.
- Rewrite any sentence that sounds translated from English.
- Confirm that speech_text sounds natural when read aloud.
- Confirm that protected numbers, dates, names, and factual claims are intact.
- Confirm that the response contains valid JSON only.

OUTPUT ONLY THIS JSON OBJECT:
{{
  "display_headline": "concise Telugu television headline",
  "display_summary": "one concise Telugu supporting line",
  "anchor_narration": "complete natural Telugu newsroom narration",
  "speech_text": "Telugu TTS-safe version of the same narration",
  "pronunciation_notes": {{
    "original source term": "Telugu pronunciation used in speech_text"
  }},
  "visual_search_terms": [
    "specific person, place, organisation, event, or subject"
  ],
  "scenes": [
    {{
      "narration_segment": "consecutive portion of the narration",
      "supporting_text": "short Telugu screen line",
      "visual_search_terms": ["specific visual search term"],
      "preferred_visual_type": "story_image|location|organisation|map|headline_card",
      "preferred_visual": "specific factual visual description",
      "fallback_visual_type": "branded_headline_card"
    }}
  ]
}}

FACTUAL SOURCE:
{json.dumps(source_payload, ensure_ascii=False, indent=2)}
""".strip()

    @staticmethod
    def _parse_ai_json(text: str) -> dict[str, Any]:
        candidate = clean_text(text)
        candidate = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            candidate,
            flags=re.IGNORECASE,
        ).strip()

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start < 0 or end <= start:
                raise BroadcastDirectorError(
                    "AI response did not contain a JSON object."
                )
            try:
                parsed = json.loads(candidate[start : end + 1])
            except json.JSONDecodeError as error:
                raise BroadcastDirectorError(
                    f"AI response contained invalid JSON: {error}"
                ) from error

        if not isinstance(parsed, dict):
            raise BroadcastDirectorError(
                "AI response JSON must be an object."
            )
        return parsed

    def _story_from_ai(
        self,
        *,
        story: Any,
        order: int,
        fact_record: StoryFactRecord,
        payload: Mapping[str, Any],
    ) -> DirectedStory:
        story_id = clean_text(read_field(story, "id", default="")) or new_id(
            "story"
        )
        headline = strip_boilerplate(
            clean_text(payload.get("display_headline"))
        )
        summary = strip_boilerplate(
            clean_text(payload.get("display_summary"))
        )
        narration = strip_boilerplate(
            clean_text(payload.get("anchor_narration"))
        )
        speech = strip_boilerplate(
            clean_text(payload.get("speech_text"))
        )
        if not speech:
            speech = apply_tts_transliterations(narration)
        else:
            speech = apply_tts_transliterations(speech)

        directed = DirectedStory(
            story_id=story_id,
            rank=order,
            category=clean_text(
                read_field(story, "category", default="")
            ),
            source_headline=fact_record.original_headline,
            display_headline=headline,
            display_summary=summary,
            anchor_narration=narration,
            speech_text=speech,
            pronunciation_notes={
                clean_text(key): clean_text(value)
                for key, value in dict(
                    payload.get("pronunciation_notes") or {}
                ).items()
                if clean_text(key) and clean_text(value)
            },
            visual_search_terms=self._string_list(
                payload.get("visual_search_terms")
            ),
            preferred_image_path=clean_text(
                read_field(story, "image_path", default="")
            ),
            preferred_image_url=clean_text(
                read_field(story, "image_url", default="")
            ),
            fact_record=fact_record,
        )

        raw_scenes = payload.get("scenes")
        if not isinstance(raw_scenes, Sequence) or isinstance(
            raw_scenes, (str, bytes)
        ):
            raw_scenes = []

        for scene_order, raw_scene in enumerate(
            list(raw_scenes)[: self.configuration.max_scenes_per_story],
            start=1,
        ):
            if not isinstance(raw_scene, Mapping):
                continue
            narration_segment = strip_boilerplate(
                clean_text(raw_scene.get("narration_segment"))
            )
            if not narration_segment:
                continue
            directed.scenes.append(
                DirectedScene(
                    scene_id=f"{story_id}_scene_{scene_order:02d}",
                    story_id=story_id,
                    order=scene_order,
                    narration_segment=narration_segment,
                    display_headline=headline,
                    supporting_text=strip_boilerplate(
                        clean_text(raw_scene.get("supporting_text"))
                    ),
                    visual_search_terms=self._string_list(
                        raw_scene.get("visual_search_terms")
                    ),
                    preferred_visual_type=clean_text(
                        raw_scene.get("preferred_visual_type")
                    ) or "story_image",
                    preferred_visual=clean_text(
                        raw_scene.get("preferred_visual")
                    ),
                    fallback_visual_type=clean_text(
                        raw_scene.get("fallback_visual_type")
                    ) or "branded_headline_card",
                    fallback_visual=self.configuration.default_fallback_visual,
                )
            )

        if not directed.scenes:
            directed.scenes = self._fallback_scenes(directed)

        self._assign_estimated_durations(directed)
        return directed

    def _fallback_story(self, story: Any, order: int) -> DirectedStory:
        fact_record = self._extract_facts(story)
        story_id = clean_text(read_field(story, "id", default="")) or new_id(
            "story"
        )

        script = self._existing_telugu_script(story)
        source_headline = fact_record.original_headline
        source_summary = (
            fact_record.original_summary
            or fact_record.original_content
        )

        display_headline = clean_text(
            read_field(story, "editorial_headline", default="")
        )
        if telugu_ratio(display_headline) < 0.45:
            display_headline = source_headline

        narration = script or source_summary or source_headline
        narration = strip_boilerplate(narration)
        speech = apply_tts_transliterations(narration)

        directed = DirectedStory(
            story_id=story_id,
            rank=order,
            category=clean_text(
                read_field(story, "category", default="")
            ),
            source_headline=source_headline,
            display_headline=display_headline,
            display_summary=clean_text(
                read_field(story, "editorial_summary", default="")
            ) or fact_record.original_summary,
            anchor_narration=narration,
            speech_text=speech,
            visual_search_terms=self._string_list(
                read_field(story, "keywords", default=[])
            ),
            preferred_image_path=clean_text(
                read_field(story, "image_path", default="")
            ),
            preferred_image_url=clean_text(
                read_field(story, "image_url", default="")
            ),
            fact_record=fact_record,
        )
        directed.scenes = self._fallback_scenes(directed)
        self._assign_estimated_durations(directed)
        self._validate_story(directed)
        return directed

    def _existing_telugu_script(self, story: Any) -> str:
        scripts = read_field(story, "scripts", default={}) or {}
        script = None

        if isinstance(scripts, Mapping):
            script = scripts.get("te") or scripts.get("telugu")
        if script is None and hasattr(story, "get_script"):
            try:
                script = story.get_script("te")
            except Exception:
                script = None

        if script is None:
            return ""

        full_text = read_field(script, "full_text", default="")
        if callable(full_text):
            full_text = full_text()
        if clean_text(full_text):
            return clean_text(full_text)

        return "\n\n".join(
            part
            for part in (
                clean_text(read_field(script, "intro", default="")),
                clean_text(read_field(script, "body", default="")),
                clean_text(read_field(script, "outro", default="")),
            )
            if part
        )

    def _extract_facts(self, story: Any) -> StoryFactRecord:
        headline = clean_text(
            read_field(
                story,
                "original_title",
                "editorial_headline",
                "headline",
                "title",
                default="",
            )
        )
        summary = clean_text(
            read_field(
                story,
                "original_summary",
                "editorial_summary",
                "summary",
                default="",
            )
        )
        content = clean_text(
            read_field(
                story,
                "original_content",
                "content",
                "body",
                default="",
            )
        )
        source_text = "\n".join(
            part for part in (headline, summary, content) if part
        )

        source_names: list[str] = []
        for source in list(
            read_field(story, "sources", default=[]) or []
        ):
            name = clean_text(
                read_field(source, "name", "publisher", default="")
            )
            if name and name not in source_names:
                source_names.append(name)

        quoted = re.findall(r'["“]([^"”]{3,200})["”]', source_text)
        protected = self._string_list(
            read_field(story, "key_facts", default=[])
        )
        protected.extend(
            self._string_list(
                read_field(story, "keywords", default=[])
            )
        )

        return StoryFactRecord(
            original_headline=headline,
            original_summary=summary,
            original_content=content,
            source_names=source_names,
            dates=self._unique(_DATE_RE.findall(source_text)),
            numbers=self._unique(
                clean_text(match.group(0))
                for match in _NUMBER_RE.finditer(source_text)
            ),
            quotations=self._unique(quoted),
            protected_terms=self._unique(protected),
        )

    def _fallback_scenes(
        self,
        story: DirectedStory,
    ) -> list[DirectedScene]:
        parts = sentence_parts(story.anchor_narration)
        if not parts and story.anchor_narration:
            parts = [story.anchor_narration]

        max_scenes = self.configuration.max_scenes_per_story
        if len(parts) > max_scenes:
            chunk_size = max(1, (len(parts) + max_scenes - 1) // max_scenes)
            parts = [
                " ".join(parts[index : index + chunk_size])
                for index in range(0, len(parts), chunk_size)
            ][:max_scenes]

        return [
            DirectedScene(
                scene_id=f"{story.story_id}_scene_{index:02d}",
                story_id=story.story_id,
                order=index,
                narration_segment=part,
                display_headline=story.display_headline,
                supporting_text=(
                    story.display_summary if index == 1 else ""
                ),
                visual_search_terms=list(story.visual_search_terms),
                preferred_visual_type=(
                    "story_image"
                    if story.preferred_image_path
                    or story.preferred_image_url
                    else "headline_card"
                ),
                preferred_visual=(
                    story.preferred_image_path
                    or story.preferred_image_url
                ),
                fallback_visual_type="branded_headline_card",
                fallback_visual=self.configuration.default_fallback_visual,
            )
            for index, part in enumerate(parts, start=1)
        ]

    def _assign_estimated_durations(
        self,
        story: DirectedStory,
    ) -> None:
        total = estimate_speech_duration(
            story.speech_text,
            self.configuration.target_words_per_minute,
        )
        weights = [
            max(1, len(scene.narration_segment.split()))
            for scene in story.scenes
        ]
        weight_total = sum(weights) or 1

        assigned = 0.0
        for index, (scene, weight) in enumerate(
            zip(story.scenes, weights),
            start=1,
        ):
            if index == len(story.scenes):
                duration = max(0.1, total - assigned)
            else:
                duration = max(0.1, total * weight / weight_total)
                assigned += duration
            scene.estimated_duration_seconds = round(duration, 3)

        story.estimated_duration_seconds = round(
            sum(
                scene.estimated_duration_seconds
                for scene in story.scenes
            ),
            3,
        )

    def _validate_story(self, story: DirectedStory) -> None:
        story.warnings.clear()
        story.blocking_errors.clear()

        if not story.display_headline:
            story.blocking_errors.append("Display headline is empty.")
        if not story.anchor_narration:
            story.blocking_errors.append("Anchor narration is empty.")
        if not story.speech_text:
            story.blocking_errors.append("Speech text is empty.")
        if not story.scenes:
            story.blocking_errors.append("No scenes were created.")

        word_count = len(story.anchor_narration.split())
        if word_count < self.configuration.min_story_words:
            story.warnings.append(
                f"Narration is short ({word_count} words)."
            )
        if word_count > self.configuration.max_story_words:
            story.warnings.append(
                f"Narration is long ({word_count} words)."
            )

        ratio = telugu_ratio(story.speech_text)
        if ratio < self.configuration.min_telugu_ratio:
            story.blocking_errors.append(
                "Telugu-script ratio is below the production threshold "
                f"({ratio:.1%} < "
                f"{self.configuration.min_telugu_ratio:.1%})."
            )

        remaining_latin = [
            word
            for word in latin_words(story.speech_text)
            if word.upper() not in _ALLOWED_LATIN_TOKENS
        ]
        if len(remaining_latin) > self.configuration.max_latin_words:
            story.blocking_errors.append(
                "Excessive Latin-script leakage remains in speech text: "
                + ", ".join(remaining_latin[:12])
            )
        elif remaining_latin:
            story.warnings.append(
                "Latin-script words remain: "
                + ", ".join(remaining_latin)
            )

        lowered = story.anchor_narration.casefold()
        boilerplate = [
            phrase
            for phrase in _KNOWN_BOILERPLATE
            if phrase in lowered
        ]
        if boilerplate:
            story.blocking_errors.append(
                "Website boilerplate remains: "
                + ", ".join(boilerplate)
            )

        self._validate_protected_facts(story)

        for scene in story.scenes:
            scene.blocking_errors.clear()
            scene.warnings.clear()
            if not scene.narration_segment:
                scene.blocking_errors.append(
                    "Scene narration is empty."
                )
            if scene.estimated_duration_seconds <= 0:
                scene.blocking_errors.append(
                    "Scene duration is not positive."
                )
            if not (
                scene.preferred_visual
                or scene.fallback_visual
                or scene.fallback_visual_type
            ):
                scene.blocking_errors.append(
                    "Scene has no preferred or fallback visual."
                )

    def _validate_protected_facts(
        self,
        story: DirectedStory,
    ) -> None:
        source = story.fact_record
        output = (
            story.display_headline
            + "\n"
            + story.anchor_narration
        ).casefold()

        missing_numbers = [
            value
            for value in source.numbers
            if self._normalize_fact(value) not in self._normalize_fact(output)
        ]
        if missing_numbers:
            story.warnings.append(
                "Review protected numbers not found verbatim after Telugu "
                "rewriting: " + ", ".join(missing_numbers[:10])
            )

        missing_dates = [
            value
            for value in source.dates
            if self._normalize_fact(value) not in self._normalize_fact(output)
        ]
        if missing_dates:
            story.warnings.append(
                "Review protected dates not found verbatim after Telugu "
                "rewriting: " + ", ".join(missing_dates[:10])
            )

    def _validate_plan(
        self,
        plan: BroadcastProductionPlan,
    ) -> None:
        if not plan.bulletin_id:
            plan.warnings.append("Source bulletin ID is empty.")
        if not plan.bulletin_title:
            plan.blocking_errors.append("Bulletin title is empty.")
        if not plan.opening_speech_text:
            plan.blocking_errors.append("Opening speech text is empty.")
        if not plan.closing_speech_text:
            plan.blocking_errors.append("Closing speech text is empty.")
        if not plan.stories:
            plan.blocking_errors.append(
                "Production plan contains no stories."
            )

        story_ids: set[str] = set()
        for story in plan.stories:
            if story.story_id in story_ids:
                plan.blocking_errors.append(
                    f"Duplicate directed story ID: {story.story_id}"
                )
            story_ids.add(story.story_id)
            self._validate_story(story)

    @staticmethod
    def _normalize_fact(value: str) -> str:
        return re.sub(r"[\s,₹$€£.%/-]+", "", clean_text(value).casefold())

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            items: Iterable[Any] = re.split(r"[,;\n]+", value)
        elif isinstance(value, Iterable):
            items = value
        else:
            items = [value]
        return BroadcastDirector._unique(
            clean_text(item) for item in items if clean_text(item)
        )

    @staticmethod
    def _unique(values: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = clean_text(value)
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                result.append(cleaned)
        return result


def direct_bulletin(
    bulletin: Any,
    *,
    production_id: str | None = None,
    configuration: DirectorConfiguration | None = None,
    ai_manager: Any | None = None,
) -> BroadcastProductionPlan:
    director = BroadcastDirector(
        configuration=configuration,
        ai_manager=ai_manager,
    )
    return director.direct(
        bulletin,
        production_id=production_id,
    )


def _self_test() -> None:
    sample = {
        "id": "bulletin_broadcast_director_test",
        "title": "బహువు న్యూస్ పరీక్షా బులెటిన్",
        "edition_name": "సాయంత్రం వార్తలు",
        "stories": [
            {
                "id": "story_001",
                "category": "weather",
                "original_title": (
                    "ఆంధ్రప్రదేశ్‌లో భారీ వర్షాలు కొనసాగుతున్నాయి"
                ),
                "original_summary": (
                    "పలు జిల్లాల్లో భారీ వర్షాలు కొనసాగుతుండటంతో "
                    "అధికారులు ప్రజలను అప్రమత్తంగా ఉండాలని సూచించారు."
                ),
                "editorial_headline": (
                    "ఆంధ్రప్రదేశ్‌లో భారీ వర్షాలు"
                ),
                "editorial_summary": (
                    "పలు జిల్లాలకు అధికారుల హెచ్చరిక"
                ),
                "scripts": {
                    "te": {
                        "body": (
                            "ఆంధ్రప్రదేశ్‌లో పలు జిల్లాల్లో భారీ వర్షాలు "
                            "కొనసాగుతున్నాయి. లోతట్టు ప్రాంతాల ప్రజలు "
                            "అప్రమత్తంగా ఉండాలని అధికారులు సూచించారు."
                        )
                    }
                },
                "keywords": [
                    "ఆంధ్రప్రదేశ్",
                    "భారీ వర్షాలు",
                    "వాతావరణం",
                ],
            }
        ],
    }

    class OfflineTestDirector(BroadcastDirector):
        def _existing_telugu_script(self, story: Any) -> str:
            scripts = read_field(story, "scripts", default={}) or {}
            script = scripts.get("te", {}) if isinstance(scripts, Mapping) else {}
            return clean_text(read_field(script, "body", default=""))

    director = OfflineTestDirector(
        DirectorConfiguration(
            use_ai=False,
            min_story_words=8,
            max_latin_words=0,
        )
    )
    plan = director.direct(sample, production_id="broadcast_test")

    assert plan.production_id == "broadcast_test"
    assert len(plan.stories) == 1
    assert plan.stories[0].story_id == "story_001"
    assert plan.stories[0].scenes
    assert plan.stories[0].speech_text
    assert plan.status in {
        PlanStatus.READY,
        PlanStatus.READY_WITH_WARNINGS,
    }

    output = Path("outputs/production/broadcast_director_self_test.json")
    plan.save_json(output)

    print(MODULE_NAME)
    print(f"Module version  : {MODULE_VERSION}")
    print(f"Production ID  : {plan.production_id}")
    print(f"Stories        : {len(plan.stories)}")
    print(f"Scenes         : {len(plan.stories[0].scenes)}")
    print(f"Status         : {plan.status.value}")
    print(f"Output         : {output}")
    print("Broadcast Director self-test passed.")


if __name__ == "__main__":
    _self_test()