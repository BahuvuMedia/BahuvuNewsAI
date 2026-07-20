"""
BahuvuNewsAI - Telugu Broadcast Editor
======================================

Converts an approved Telugu PolishedScript into the bulletin-shaped, story-level
input required by production.broadcast_director.

Pipeline position:

    English editorial polish
        -> Telugu translation
        -> Telugu Editorial Desk
        -> Broadcast Editor
        -> Broadcast Director

The editor is deterministic and fact-conservative. It does not invent facts,
translate English, or replace the Broadcast Director.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import re
from typing import Any, Mapping, Sequence

from news.telugu_broadcast_style import TeluguBroadcastStyle


MODULE_VERSION = "1.0.0"

_TELUGU_RE = re.compile(r"[\u0C00-\u0C7F]")
_LATIN_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9.'-]*\b")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")
_SECTION_LABEL_RE = re.compile(
    r"^\s*(?:TOP\s+HEADLINES|HEADLINES|NEWS|SECTION)\s*:?\s*$",
    re.IGNORECASE,
)
_NUMBER_PREFIX_RE = re.compile(r"^\s*\d{1,3}[.)\-:]\s*")
_SPACE_RE = re.compile(r"[ \t]+")
_PARAGRAPH_BREAK_RE = re.compile(r"\n\s*\n+")

_TRANSITIONS = (
    "ఇక తదుపరి వార్తకు వస్తే,",
    "మరో ముఖ్యమైన పరిణామంలో,",
    "ఇదిలా ఉండగా,",
    "ఇక మరో వార్తలో,",
)

_TRANSITION_PREFIXES = (
    "ఇక ",
    "మరో ",
    "ఇదిలా ",
    "ఈ క్రమంలో",
    "తాజాగా",
    "అలాగే",
)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        converted = value.to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _first(mapping: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        value = mapping.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def _clean(value: str) -> str:
    text = value.replace("\u00A0", " ").replace("\ufeff", "")
    text = _SPACE_RE.sub(" ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text.strip()


def _telugu_ratio(value: str) -> float:
    letters = [character for character in value if character.isalpha()]
    if not letters:
        return 0.0
    telugu = sum(
        1 for character in letters
        if "\u0C00" <= character <= "\u0C7F"
    )
    return telugu / len(letters)


def _sentences(value: str) -> list[str]:
    normalized = _clean(value)
    if not normalized:
        return []
    return [
        sentence.strip()
        for sentence in _SENTENCE_END_RE.split(normalized)
        if sentence.strip()
    ]


def _paragraphs(value: str) -> list[str]:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    parts = [
        _clean(_NUMBER_PREFIX_RE.sub("", part))
        for part in _PARAGRAPH_BREAK_RE.split(normalized)
    ]
    return [
        part
        for part in parts
        if part
        and not _SECTION_LABEL_RE.match(part)
        and _TELUGU_RE.search(part)
    ]


def _balanced_chunks(value: str, target_count: int) -> list[str]:
    paragraphs = _paragraphs(value)

    if target_count <= 1:
        return [_clean(value)] if _clean(value) else []

    if len(paragraphs) == target_count:
        return paragraphs

    sentences = _sentences(value)
    if not sentences:
        return paragraphs

    chunks = [[] for _ in range(target_count)]
    word_totals = [0 for _ in range(target_count)]

    for sentence in sentences:
        slot = min(range(target_count), key=word_totals.__getitem__)
        chunks[slot].append(sentence)
        word_totals[slot] += len(sentence.split())

    return [
        " ".join(chunk).strip()
        for chunk in chunks
        if chunk
    ]


@dataclass(slots=True)
class BroadcastEditorConfiguration:
    minimum_telugu_ratio: float = 0.55
    maximum_latin_words: int = 8
    maximum_latin_ratio: float = 0.12
    add_story_transitions: bool = True
    minimum_story_words: int = 8

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_telugu_ratio <= 1.0:
            raise ValueError("minimum_telugu_ratio must be between 0 and 1")
        if self.maximum_latin_words < 0:
            raise ValueError("maximum_latin_words cannot be negative")
        if not 0.0 <= self.maximum_latin_ratio <= 1.0:
            raise ValueError("maximum_latin_ratio must be between 0 and 1")
        if self.minimum_story_words < 1:
            raise ValueError("minimum_story_words must be positive")


@dataclass(slots=True)
class BroadcastEditorResult:
    bulletin: dict[str, Any]
    story_count: int
    telugu_ratio: float
    latin_word_count: int
    warnings: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    editor_version: str = MODULE_VERSION

    @property
    def production_ready(self) -> bool:
        return bool(self.bulletin.get("stories")) and not any(
            warning.startswith("BLOCKING:")
            for warning in self.warnings
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["production_ready"] = self.production_ready
        return payload


class BroadcastEditor:
    def __init__(
        self,
        configuration: BroadcastEditorConfiguration | None = None,
    ) -> None:
        self.configuration = configuration or BroadcastEditorConfiguration()
        self.style = TeluguBroadcastStyle()

    def edit(
        self,
        translated_script: Any,
        *,
        source_bulletin: Any | None = None,
        production_id: str = "",
    ) -> BroadcastEditorResult:
        script = _mapping(translated_script)
        if "script" in script and _mapping(script["script"]):
            script = _mapping(script["script"])

        headline = _clean(_text(script.get("headline")))
        intro = _clean(_text(script.get("intro")))
        body = _clean(_text(script.get("body")))
        closing = _clean(_text(script.get("closing")))
        source_script_id = _clean(_text(script.get("source_script_id")))
        metadata = dict(script.get("metadata") or {})

        if not headline:
            raise ValueError("Broadcast Editor received an empty Telugu headline.")
        if not body:
            raise ValueError("Broadcast Editor received an empty Telugu body.")

        combined = "\n\n".join(
            part for part in (headline, intro, body, closing) if part
        )
        ratio = _telugu_ratio(combined)
        latin_words = _LATIN_WORD_RE.findall(combined)
        all_words = [
            token
            for token in re.findall(
                r"[\u0C00-\u0C7F]+|[A-Za-z][A-Za-z0-9.'-]*",
                combined,
            )
            if token
        ]
        latin_ratio = (
            len(latin_words) / len(all_words)
            if all_words
            else 0.0
        )

        warnings: list[str] = []
        changes: list[str] = []

        if ratio < self.configuration.minimum_telugu_ratio:
            warnings.append(
                "BLOCKING: approved script does not contain enough Telugu "
                f"content ({ratio:.2%})."
            )
        if (
            len(latin_words) > self.configuration.maximum_latin_words
            and latin_ratio > self.configuration.maximum_latin_ratio
        ):
            preview = ", ".join(latin_words[:20])
            warnings.append(
                "BLOCKING: approved Telugu script contains excessive Latin "
                f"content ({len(latin_words)} words, "
                f"{latin_ratio:.2%} of detected words). "
                f"Examples: {preview}"
            )
        elif len(latin_words) > self.configuration.maximum_latin_words:
            warnings.append(
                "NON-BLOCKING: Telugu bulletin contains Latin names or "
                f"acronyms ({len(latin_words)} words, "
                f"{latin_ratio:.2%} of detected words)."
            )

        source = _mapping(source_bulletin)
        original_stories = list(
            source.get("stories")
            or source.get("selected_stories")
            or []
        )
        target_count = max(1, len(original_stories))
        story_chunks = _balanced_chunks(body, target_count)

        if not story_chunks:
            raise ValueError("Broadcast Editor could not create story narration.")

        edited_stories: list[dict[str, Any]] = []

        for index, chunk in enumerate(story_chunks, start=1):
            source_story = (
                _mapping(original_stories[index - 1])
                if index <= len(original_stories)
                else {}
            )

            chunk = self._apply_transition(chunk, index)
            style_result = self.style.normalize(chunk)

            if len(style_result.display_text.split()) < (
                self.configuration.minimum_story_words
            ):
                warnings.append(
                    f"Story {index} is unusually short for broadcast."
                )

            source_headline = _clean(
                _text(
                    _first(
                        source_story,
                        (
                            "telugu_headline",
                            "translated_headline",
                            "headline",
                            "title",
                        ),
                    )
                    or ""
                )
            )
            display_headline = headline if index == 1 else source_headline
            if not display_headline or not _TELUGU_RE.search(display_headline):
                first_sentence = _sentences(style_result.display_text)
                display_headline = (
                    first_sentence[0][:120].rstrip(" .!?")
                    if first_sentence
                    else headline
                )

            story_id = _clean(
                _text(
                    _first(
                        source_story,
                        ("story_id", "article_id", "id"),
                    )
                    or f"{source_script_id or production_id or 'bulletin'}_"
                    f"{index:03d}"
                )
            )

            story_metadata = dict(source_story.get("metadata") or {})
            story_metadata["broadcast_editor"] = {
                "editor_version": MODULE_VERSION,
                "source_script_id": source_script_id,
                "segment_index": index,
                "display_replacements": list(style_result.replacements),
                "style_warnings": list(style_result.warnings),
            }

            edited_stories.append(
                {
                    **source_story,
                    "id": story_id,
                    "story_id": story_id,
                    "article_id": story_id,
                    "rank": index,
                    "order": index,
                    "headline": display_headline,
                    "title": display_headline,
                    "summary": style_result.display_text,
                    "body": style_result.display_text,
                    "text": style_result.display_text,
                    "translated_text": style_result.display_text,
                    "speech_text": style_result.speech_text,
                    "language": "te",
                    "metadata": story_metadata,
                }
            )

        changes.extend(
            (
                f"Converted approved Telugu bulletin into "
                f"{len(edited_stories)} story-level broadcast units.",
                "Preserved source story metadata and visual references.",
                "Generated separate display and speech text.",
            )
        )

        bulletin_id = (
            _clean(
                _text(
                    _first(
                        source,
                        ("bulletin_id", "id", "script_id"),
                    )
                    or source_script_id
                    or production_id
                )
            )
            or "bahuvu_bulletin"
        )

        bulletin = {
            **source,
            "id": bulletin_id,
            "bulletin_id": bulletin_id,
            "title": headline,
            "headline": headline,
            "language": "te",
            "opening_script": intro,
            "intro": intro,
            "closing_script": closing,
            "outro": closing,
            "stories": edited_stories,
            "metadata": {
                **dict(source.get("metadata") or {}),
                **metadata,
                "broadcast_editor": {
                    "editor_version": MODULE_VERSION,
                    "story_count": len(edited_stories),
                    "telugu_ratio": ratio,
                    "latin_word_count": len(latin_words),
                    "warnings": list(warnings),
                    "changes": list(changes),
                },
            },
        }

        result = BroadcastEditorResult(
            bulletin=bulletin,
            story_count=len(edited_stories),
            telugu_ratio=ratio,
            latin_word_count=len(latin_words),
            warnings=warnings,
            changes=changes,
        )

        if not result.production_ready:
            raise ValueError(
                "Broadcast Editor blocked production: "
                + " | ".join(result.warnings)
            )

        return result

    def _apply_transition(self, text: str, index: int) -> str:
        normalized = _clean(text)
        if (
            index <= 1
            or not self.configuration.add_story_transitions
            or normalized.startswith(_TRANSITION_PREFIXES)
        ):
            return normalized

        transition = _TRANSITIONS[(index - 2) % len(_TRANSITIONS)]
        return f"{transition} {normalized}"


def edit_telugu_broadcast(
    translated_script: Any,
    *,
    source_bulletin: Any | None = None,
    production_id: str = "",
    configuration: BroadcastEditorConfiguration | None = None,
) -> BroadcastEditorResult:
    return BroadcastEditor(configuration).edit(
        translated_script,
        source_bulletin=source_bulletin,
        production_id=production_id,
    )


def _self_test() -> None:
    translated = {
        "headline": "ఆంధ్రప్రదేశ్‌లో భారీ వర్షాలు",
        "intro": "బహువు న్యూస్‌కు స్వాగతం.",
        "body": (
            "ఆంధ్రప్రదేశ్‌లో భారీ వర్షాలు కొనసాగుతున్నాయి. "
            "పలు జిల్లాలకు అధికారులు హెచ్చరికలు జారీ చేశారు.\n\n"
            "వర్షాల ప్రభావంతో రహదారులపై రాకపోకలకు అంతరాయం ఏర్పడింది. "
            "ప్రజలు అప్రమత్తంగా ఉండాలని అధికారులు సూచించారు."
        ),
        "closing": "ఇవి ఈరోజు ప్రధాన వార్తలు.",
        "language": "te",
        "source_script_id": "broadcast_editor_test",
    }
    source = {
        "id": "broadcast_editor_test",
        "stories": [
            {
                "id": "story_001",
                "headline": "Heavy rain continues",
                "category": "weather",
                "image_url": "https://example.org/rain.jpg",
            },
            {
                "id": "story_002",
                "headline": "Traffic affected",
                "category": "weather",
                "image_path": "assets/images/sample.jpg",
            },
        ],
    }

    result = BroadcastEditor(
        BroadcastEditorConfiguration(maximum_latin_words=10)
    ).edit(
        translated,
        source_bulletin=source,
        production_id="broadcast_editor_test",
    )

    assert result.production_ready
    assert result.story_count == 2
    assert result.bulletin["language"] == "te"
    assert result.bulletin["stories"][0]["image_url"]
    assert result.bulletin["stories"][1]["image_path"]
    assert result.bulletin["stories"][0]["speech_text"]
    assert result.bulletin["stories"][1]["text"].startswith(_TRANSITIONS)

    print("BahuvuNewsAI Telugu Broadcast Editor")
    print(f"Module version      : {MODULE_VERSION}")
    print(f"Stories prepared    : {result.story_count}")
    print(f"Telugu ratio        : {result.telugu_ratio:.2%}")
    print(f"Latin words         : {result.latin_word_count}")
    print(f"Production ready    : {result.production_ready}")
    print("Broadcast Editor self-test passed.")


if __name__ == "__main__":
    _self_test()