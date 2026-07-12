"""
BahuvuNewsAI - Bulletin Audio Manager
=====================================

Coordinates story-level Telugu narration into a bulletin-ready audio package.

Pipeline position:

    news.telugu_translator
        -> voice.tts_generator
        -> voice.audio_manager
        -> graphics / video renderer

Responsibilities
----------------
* Preserve bulletin story order.
* Generate one narration file per story.
* Support title, intro, body, and closing narration.
* Track duration, file size, failures, and skipped items.
* Insert configurable silence between stories when assembling a bulletin.
* Produce a JSON audio manifest for the video renderer.
* Keep TTS generation separate from bulletin orchestration.
* Provide an offline-safe self-test.

Run:

    python -m py_compile voice/audio_manager.py
    python -m voice.audio_manager

Real audio generation requires edge-tts through voice.tts_generator.
Audio assembly requires FFmpeg to be available in PATH.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from voice.tts_generator import (
    AudioArtifact,
    AudioFormat,
    NarrationInput,
    TTSConfig,
    TTSResult,
    TTSStatus,
    TeluguTTSGenerator,
    VoiceGender,
)


# =============================================================================
# ENUMS
# =============================================================================


class AudioItemStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    SKIPPED = "skipped"
    FAILED = "failed"


class BulletinAudioStatus(str, Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    READY = "ready"
    FAILED = "failed"


class NarrationSection(str, Enum):
    HEADLINE = "headline"
    INTRO = "intro"
    BODY = "body"
    CLOSING = "closing"


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass(slots=True)
class AudioManagerConfig:
    output_dir: Path = Path("outputs/audio")
    story_audio_dirname: str = "stories"
    manifest_filename: str = "bulletin_audio_manifest.json"
    bulletin_filename: str = "bulletin_te.mp3"
    silence_between_stories_seconds: float = 1.25
    silence_after_headline_seconds: float = 0.35
    include_headline: bool = True
    include_intro: bool = True
    include_body: bool = True
    include_closing: bool = True
    continue_on_error: bool = True
    assemble_bulletin_audio: bool = True
    overwrite: bool = True
    write_manifest: bool = True
    ffmpeg_binary: str = "ffmpeg"
    audio_format: AudioFormat = AudioFormat.MP3

    def validate(self) -> None:
        if self.silence_between_stories_seconds < 0:
            raise ValueError("Silence between stories cannot be negative.")
        if self.silence_after_headline_seconds < 0:
            raise ValueError("Silence after headline cannot be negative.")
        if not self.story_audio_dirname.strip():
            raise ValueError("Story audio directory name cannot be empty.")
        if not self.manifest_filename.strip():
            raise ValueError("Manifest filename cannot be empty.")
        if not self.bulletin_filename.strip():
            raise ValueError("Bulletin filename cannot be empty.")


@dataclass(slots=True)
class BulletinStoryAudioInput:
    story_id: str
    order: int
    headline: str = ""
    intro: str = ""
    body: str = ""
    closing: str = ""
    language: str = "te"
    category: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def combined_text(
        self,
        config: AudioManagerConfig,
    ) -> str:
        sections: list[str] = []

        if config.include_headline and self.headline.strip():
            sections.append(self.headline.strip())

        if config.include_intro and self.intro.strip():
            sections.append(self.intro.strip())

        if config.include_body and self.body.strip():
            sections.append(self.body.strip())

        if config.include_closing and self.closing.strip():
            sections.append(self.closing.strip())

        return "\n\n".join(sections)


@dataclass(slots=True)
class StoryAudioItem:
    story_id: str
    order: int
    title: str
    status: AudioItemStatus
    narration_text: str
    audio_path: Path | None = None
    bytes_written: int = 0
    duration_seconds: float = 0.0
    attempts: int = 0
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return (
            self.status == AudioItemStatus.READY
            and self.audio_path is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "story_id": self.story_id,
            "order": self.order,
            "title": self.title,
            "status": self.status.value,
            "narration_text": self.narration_text,
            "audio_path": str(self.audio_path) if self.audio_path else None,
            "bytes_written": self.bytes_written,
            "duration_seconds": self.duration_seconds,
            "attempts": self.attempts,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class BulletinAudioManifest:
    bulletin_id: str
    status: BulletinAudioStatus
    generated_at: str
    language: str
    story_count: int
    ready_story_count: int
    failed_story_count: int
    skipped_story_count: int
    total_duration_seconds: float
    silence_duration_seconds: float
    bulletin_audio_path: Path | None
    manifest_path: Path | None
    stories: list[StoryAudioItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def production_ready(self) -> bool:
        return (
            self.status == BulletinAudioStatus.READY
            and self.ready_story_count > 0
            and self.failed_story_count == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bulletin_id": self.bulletin_id,
            "status": self.status.value,
            "generated_at": self.generated_at,
            "language": self.language,
            "story_count": self.story_count,
            "ready_story_count": self.ready_story_count,
            "failed_story_count": self.failed_story_count,
            "skipped_story_count": self.skipped_story_count,
            "total_duration_seconds": self.total_duration_seconds,
            "silence_duration_seconds": self.silence_duration_seconds,
            "bulletin_audio_path": (
                str(self.bulletin_audio_path)
                if self.bulletin_audio_path
                else None
            ),
            "manifest_path": (
                str(self.manifest_path)
                if self.manifest_path
                else None
            ),
            "production_ready": self.production_ready,
            "stories": [story.to_dict() for story in self.stories],
            "errors": list(self.errors),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class AudioManagerSummary:
    bulletins_processed: int = 0
    stories_processed: int = 0
    stories_ready: int = 0
    stories_failed: int = 0
    stories_skipped: int = 0
    total_duration_seconds: float = 0.0

    @classmethod
    def from_manifests(
        cls,
        manifests: Sequence[BulletinAudioManifest],
    ) -> "AudioManagerSummary":
        return cls(
            bulletins_processed=len(manifests),
            stories_processed=sum(item.story_count for item in manifests),
            stories_ready=sum(
                item.ready_story_count for item in manifests
            ),
            stories_failed=sum(
                item.failed_story_count for item in manifests
            ),
            stories_skipped=sum(
                item.skipped_story_count for item in manifests
            ),
            total_duration_seconds=round(
                sum(item.total_duration_seconds for item in manifests),
                2,
            ),
        )


# =============================================================================
# HELPERS
# =============================================================================


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _slugify(value: str, fallback: str = "story") -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^\w\-]+", "_", normalized, flags=re.UNICODE)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or fallback


def coerce_story_audio_input(
    value: Any,
    *,
    fallback_order: int = 1,
) -> BulletinStoryAudioInput:
    if isinstance(value, BulletinStoryAudioInput):
        return value

    mapping = _coerce_mapping(value)
    if not mapping:
        raise TypeError(
            "Story audio input must be a mapping, dataclass, or object."
        )

    story_id = _safe_text(
        mapping.get("story_id")
        or mapping.get("article_id")
        or mapping.get("id")
        or f"story_{fallback_order:03d}"
    )

    order_value = (
        mapping.get("order")
        or mapping.get("position")
        or mapping.get("rank")
        or fallback_order
    )

    try:
        order = int(order_value)
    except (TypeError, ValueError):
        order = fallback_order

    body_value = (
        mapping.get("body")
        or mapping.get("translated_body")
        or mapping.get("telugu_body")
        or mapping.get("content")
        or mapping.get("text")
        or mapping.get("translated_text")
        or ""
    )

    if isinstance(body_value, Sequence) and not isinstance(
        body_value,
        (str, bytes, bytearray),
    ):
        body = "\n\n".join(
            _safe_text(item).strip()
            for item in body_value
            if _safe_text(item).strip()
        )
    else:
        body = _safe_text(body_value)

    metadata = mapping.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        metadata = {}

    return BulletinStoryAudioInput(
        story_id=story_id,
        order=order,
        headline=_safe_text(
            mapping.get("headline")
            or mapping.get("translated_headline")
            or mapping.get("telugu_headline")
            or mapping.get("title")
            or ""
        ),
        intro=_safe_text(
            mapping.get("intro")
            or mapping.get("translated_intro")
            or mapping.get("telugu_intro")
            or ""
        ),
        body=body,
        closing=_safe_text(
            mapping.get("closing")
            or mapping.get("translated_closing")
            or mapping.get("telugu_closing")
            or mapping.get("outro")
            or ""
        ),
        language=_safe_text(
            mapping.get("language")
            or mapping.get("language_code")
            or "te"
        ),
        category=_safe_text(mapping.get("category") or ""),
        metadata=dict(metadata),
    )


def coerce_story_list(values: Iterable[Any]) -> list[BulletinStoryAudioInput]:
    stories = [
        coerce_story_audio_input(value, fallback_order=index)
        for index, value in enumerate(values, start=1)
    ]

    stories.sort(key=lambda item: (item.order, item.story_id))
    return stories


# =============================================================================
# AUDIO MANAGER
# =============================================================================


class BulletinAudioManager:
    def __init__(
        self,
        config: AudioManagerConfig | None = None,
        tts_generator: TeluguTTSGenerator | None = None,
    ) -> None:
        self.config = config or AudioManagerConfig()
        self.config.validate()

        if tts_generator is None:
            tts_config = TTSConfig(
                output_dir=(
                    self.config.output_dir
                    / self.config.story_audio_dirname
                ),
                audio_format=self.config.audio_format,
                overwrite=self.config.overwrite,
            )
            tts_generator = TeluguTTSGenerator(config=tts_config)

        self.tts_generator = tts_generator

    def prepare_directories(self) -> None:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        (
            self.config.output_dir
            / self.config.story_audio_dirname
        ).mkdir(parents=True, exist_ok=True)

    def build_story_audio_path(
        self,
        bulletin_id: str,
        story: BulletinStoryAudioInput,
    ) -> Path:
        safe_bulletin = _slugify(bulletin_id, "bulletin")
        safe_story = _slugify(
            story.story_id or story.headline,
            f"story_{story.order:03d}",
        )
        filename = (
            f"{story.order:03d}_{safe_story}."
            f"{self.config.audio_format.value}"
        )
        return (
            self.config.output_dir
            / self.config.story_audio_dirname
            / safe_bulletin
            / filename
        )

    def build_bulletin_audio_path(self, bulletin_id: str) -> Path:
        safe_bulletin = _slugify(bulletin_id, "bulletin")
        filename = Path(self.config.bulletin_filename)
        return (
            self.config.output_dir
            / safe_bulletin
            / filename.name
        )

    def build_manifest_path(self, bulletin_id: str) -> Path:
        safe_bulletin = _slugify(bulletin_id, "bulletin")
        return (
            self.config.output_dir
            / safe_bulletin
            / self.config.manifest_filename
        )

    def generate_bulletin(
        self,
        *,
        bulletin_id: str,
        stories: Iterable[Any],
        gender: VoiceGender | str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> BulletinAudioManifest:
        self.prepare_directories()
        story_inputs = coerce_story_list(stories)

        story_items: list[StoryAudioItem] = []
        errors: list[str] = []

        for story in story_inputs:
            narration_text = story.combined_text(self.config)

            if not narration_text.strip():
                item = StoryAudioItem(
                    story_id=story.story_id,
                    order=story.order,
                    title=story.headline,
                    status=AudioItemStatus.SKIPPED,
                    narration_text="",
                    error="Story contains no narration text.",
                    metadata=dict(story.metadata),
                )
                story_items.append(item)
                continue

            target_path = self.build_story_audio_path(
                bulletin_id,
                story,
            )

            narration = NarrationInput(
                text=narration_text,
                story_id=story.story_id,
                title=story.headline,
                language=story.language,
                filename_stem=target_path.stem,
                metadata={
                    **story.metadata,
                    "order": story.order,
                    "category": story.category,
                    "bulletin_id": bulletin_id,
                },
            )

            result = self.tts_generator.generate(
                narration,
                output_path=target_path,
                gender=gender,
            )

            item = self._story_item_from_tts_result(
                story=story,
                narration_text=narration_text,
                result=result,
            )
            story_items.append(item)

            if item.status == AudioItemStatus.FAILED:
                errors.append(
                    f"{story.story_id}: {item.error or 'TTS failed'}"
                )
                if not self.config.continue_on_error:
                    break

        ready_items = [
            item for item in story_items if item.ready
        ]

        bulletin_audio_path: Path | None = None

        if self.config.assemble_bulletin_audio and ready_items:
            try:
                bulletin_audio_path = self.build_bulletin_audio_path(
                    bulletin_id
                )
                self.assemble_bulletin_audio(
                    ready_items,
                    bulletin_audio_path,
                )
            except Exception as exc:
                errors.append(f"Bulletin assembly failed: {exc}")

        status = self._derive_status(
            story_items=story_items,
            bulletin_audio_path=bulletin_audio_path,
            errors=errors,
        )

        silence_duration = self._calculate_silence_duration(
            ready_story_count=len(ready_items)
        )

        total_duration = round(
            sum(item.duration_seconds for item in ready_items)
            + silence_duration,
            2,
        )

        manifest_path = self.build_manifest_path(bulletin_id)

        manifest = BulletinAudioManifest(
            bulletin_id=bulletin_id,
            status=status,
            generated_at=_utc_now_iso(),
            language="te",
            story_count=len(story_items),
            ready_story_count=sum(
                1
                for item in story_items
                if item.status == AudioItemStatus.READY
            ),
            failed_story_count=sum(
                1
                for item in story_items
                if item.status == AudioItemStatus.FAILED
            ),
            skipped_story_count=sum(
                1
                for item in story_items
                if item.status == AudioItemStatus.SKIPPED
            ),
            total_duration_seconds=total_duration,
            silence_duration_seconds=silence_duration,
            bulletin_audio_path=bulletin_audio_path,
            manifest_path=manifest_path if self.config.write_manifest else None,
            stories=story_items,
            errors=errors,
            metadata=dict(metadata or {}),
        )

        if self.config.write_manifest:
            self.write_manifest(manifest)

        return manifest

    def _story_item_from_tts_result(
        self,
        *,
        story: BulletinStoryAudioInput,
        narration_text: str,
        result: TTSResult,
    ) -> StoryAudioItem:
        if result.status == TTSStatus.GENERATED and result.artifact:
            return StoryAudioItem(
                story_id=story.story_id,
                order=story.order,
                title=story.headline,
                status=AudioItemStatus.READY,
                narration_text=narration_text,
                audio_path=result.artifact.path,
                bytes_written=result.artifact.bytes_written,
                duration_seconds=(
                    result.artifact.duration_seconds or 0.0
                ),
                attempts=result.attempts,
                metadata=dict(story.metadata),
            )

        if result.status == TTSStatus.SKIPPED:
            return StoryAudioItem(
                story_id=story.story_id,
                order=story.order,
                title=story.headline,
                status=AudioItemStatus.SKIPPED,
                narration_text=narration_text,
                audio_path=(
                    result.artifact.path
                    if result.artifact
                    else None
                ),
                bytes_written=(
                    result.artifact.bytes_written
                    if result.artifact
                    else 0
                ),
                duration_seconds=(
                    result.artifact.duration_seconds or 0.0
                    if result.artifact
                    else 0.0
                ),
                attempts=result.attempts,
                error=result.error,
                metadata=dict(story.metadata),
            )

        return StoryAudioItem(
            story_id=story.story_id,
            order=story.order,
            title=story.headline,
            status=AudioItemStatus.FAILED,
            narration_text=narration_text,
            attempts=result.attempts,
            error=result.error or "TTS generation failed.",
            metadata=dict(story.metadata),
        )

    def assemble_bulletin_audio(
        self,
        items: Sequence[StoryAudioItem],
        output_path: Path,
    ) -> Path:
        ready_items = [item for item in items if item.ready]

        if not ready_items:
            raise ValueError("No ready story audio files to assemble.")

        ffmpeg = shutil.which(self.config.ffmpeg_binary)
        if not ffmpeg:
            raise RuntimeError(
                "FFmpeg was not found in PATH. Bulletin audio assembly "
                "cannot continue."
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(
            prefix="bahuvu_audio_manager_"
        ) as temp_dir:
            temp_path = Path(temp_dir)
            concat_entries: list[str] = []

            silence_path: Path | None = None
            if (
                self.config.silence_between_stories_seconds > 0
                and len(ready_items) > 1
            ):
                silence_path = temp_path / "silence.mp3"
                self._create_silence_file(
                    ffmpeg=ffmpeg,
                    duration_seconds=(
                        self.config.silence_between_stories_seconds
                    ),
                    output_path=silence_path,
                )

            for index, item in enumerate(ready_items):
                assert item.audio_path is not None
                concat_entries.append(
                    f"file '{item.audio_path.resolve().as_posix()}'"
                )

                if (
                    silence_path is not None
                    and index < len(ready_items) - 1
                ):
                    concat_entries.append(
                        f"file '{silence_path.resolve().as_posix()}'"
                    )

            concat_file = temp_path / "concat.txt"
            concat_file.write_text(
                "\n".join(concat_entries),
                encoding="utf-8",
            )

            command = [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c",
                "copy",
                str(output_path),
            ]

            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
            )

            if completed.returncode != 0:
                raise RuntimeError(
                    completed.stderr.strip()
                    or "FFmpeg audio assembly failed."
                )

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(
                "Bulletin audio output was not created correctly."
            )

        return output_path

    def _create_silence_file(
        self,
        *,
        ffmpeg: str,
        duration_seconds: float,
        output_path: Path,
    ) -> None:
        command = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-t",
            f"{duration_seconds:.3f}",
            "-q:a",
            "9",
            "-acodec",
            "libmp3lame",
            str(output_path),
        ]

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )

        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr.strip()
                or "Unable to create silence audio."
            )

    def _calculate_silence_duration(
        self,
        *,
        ready_story_count: int,
    ) -> float:
        if ready_story_count <= 1:
            return 0.0

        return round(
            (ready_story_count - 1)
            * self.config.silence_between_stories_seconds,
            2,
        )

    def _derive_status(
        self,
        *,
        story_items: Sequence[StoryAudioItem],
        bulletin_audio_path: Path | None,
        errors: Sequence[str],
    ) -> BulletinAudioStatus:
        ready = sum(
            1 for item in story_items if item.status == AudioItemStatus.READY
        )
        failed = sum(
            1 for item in story_items if item.status == AudioItemStatus.FAILED
        )

        if ready == 0:
            return BulletinAudioStatus.FAILED

        if failed > 0 or errors:
            return BulletinAudioStatus.PARTIAL

        if (
            self.config.assemble_bulletin_audio
            and bulletin_audio_path is None
        ):
            return BulletinAudioStatus.PARTIAL

        return BulletinAudioStatus.READY

    def write_manifest(
        self,
        manifest: BulletinAudioManifest,
    ) -> Path:
        path = manifest.manifest_path or self.build_manifest_path(
            manifest.bulletin_id
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                manifest.to_dict(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    def summarize(
        self,
        manifests: Sequence[BulletinAudioManifest],
    ) -> AudioManagerSummary:
        return AudioManagerSummary.from_manifests(manifests)


# =============================================================================
# OFFLINE TEST SUPPORT
# =============================================================================


class FakeTTSGenerator:
    """
    Offline fake used only by the self-test.

    It creates deterministic placeholder files so the audio manager can be
    tested without contacting edge-tts.
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def generate(
        self,
        value: Any,
        *,
        output_path: str | Path | None = None,
        gender: VoiceGender | str | None = None,
    ) -> TTSResult:
        narration = (
            value
            if isinstance(value, NarrationInput)
            else NarrationInput(text=_safe_text(value))
        )

        target = Path(output_path or self.output_dir / "fake.mp3")
        target.parent.mkdir(parents=True, exist_ok=True)

        if "FAIL_TEST" in narration.text:
            return TTSResult(
                status=TTSStatus.FAILED,
                input=narration,
                profile=TTSConfig().default_profile,
                error="Simulated TTS failure.",
                attempts=1,
                started_at=_utc_now_iso(),
                completed_at=_utc_now_iso(),
            )

        payload = (
            b"ID3"
            + narration.text.encode("utf-8", errors="ignore")
        )
        target.write_bytes(payload)

        artifact = AudioArtifact(
            path=target,
            format=AudioFormat.MP3,
            bytes_written=target.stat().st_size,
            duration_seconds=round(
                max(1.0, len(narration.text.split()) * 0.45),
                2,
            ),
            chunk_count=1,
        )

        return TTSResult(
            status=TTSStatus.GENERATED,
            input=narration,
            profile=TTSConfig().default_profile,
            artifact=artifact,
            attempts=1,
            started_at=_utc_now_iso(),
            completed_at=_utc_now_iso(),
        )


# =============================================================================
# SELF-TEST
# =============================================================================


def _run_self_test() -> None:
    with tempfile.TemporaryDirectory(
        prefix="bahuvu_audio_manager_test_"
    ) as temp_dir:
        root = Path(temp_dir)

        config = AudioManagerConfig(
            output_dir=root / "audio",
            silence_between_stories_seconds=1.25,
            assemble_bulletin_audio=False,
            write_manifest=True,
        )

        manager = BulletinAudioManager(
            config=config,
            tts_generator=FakeTTSGenerator(root / "fake_tts"),
        )

        stories = [
            {
                "story_id": "story_weather",
                "order": 2,
                "headline": "తీర ప్రాంతాలకు భారీ వర్ష సూచన",
                "body": (
                    "భారత వాతావరణ శాఖ తీర ప్రాంత జిల్లాలకు "
                    "భారీ వర్ష హెచ్చరిక జారీ చేసింది."
                ),
                "language": "te",
                "category": "weather",
            },
            {
                "story_id": "story_governance",
                "order": 1,
                "headline": "కొత్త విద్యా కార్యక్రమానికి ఆమోదం",
                "body": (
                    "రాష్ట్ర మంత్రివర్గం కొత్త విద్యా కార్యక్రమానికి "
                    "ఆమోదం తెలిపింది."
                ),
                "language": "te",
                "category": "governance",
            },
            {
                "story_id": "story_empty",
                "order": 3,
                "headline": "",
                "body": "",
                "language": "te",
            },
        ]

        manifest = manager.generate_bulletin(
            bulletin_id="bahuvu_july_demo",
            stories=stories,
            metadata={"edition": "July 2026"},
        )

        assert manifest.story_count == 3
        assert manifest.ready_story_count == 2
        assert manifest.failed_story_count == 0
        assert manifest.skipped_story_count == 1
        assert manifest.stories[0].story_id == "story_governance"
        assert manifest.stories[1].story_id == "story_weather"
        assert manifest.total_duration_seconds > 0
        assert manifest.silence_duration_seconds == 1.25
        assert manifest.manifest_path is not None
        assert manifest.manifest_path.exists()

        loaded = json.loads(
            manifest.manifest_path.read_text(encoding="utf-8")
        )
        assert loaded["bulletin_id"] == "bahuvu_july_demo"
        assert loaded["ready_story_count"] == 2
        assert len(loaded["stories"]) == 3

        summary = manager.summarize([manifest])
        assert summary.bulletins_processed == 1
        assert summary.stories_processed == 3
        assert summary.stories_ready == 2
        assert summary.stories_skipped == 1

        expected_path = manager.build_story_audio_path(
            "bahuvu_july_demo",
            coerce_story_audio_input(stories[0]),
        )
        assert expected_path.name.startswith("002_")
        assert expected_path.suffix == ".mp3"

        print("Bulletin audio manager initialized successfully.")
        print()
        print(f"Stories processed       : {manifest.story_count}")
        print(f"Stories ready           : {manifest.ready_story_count}")
        print(f"Stories skipped         : {manifest.skipped_story_count}")
        print(f"Stories failed          : {manifest.failed_story_count}")
        print(
            f"Narration duration      : "
            f"{manifest.total_duration_seconds:.2f} seconds"
        )
        print(
            f"Inter-story silence     : "
            f"{manifest.silence_duration_seconds:.2f} seconds"
        )
        print(f"Manifest written        : {manifest.manifest_path.exists()}")
        print(f"Bulletin status         : {manifest.status.value}")
        print()
        print("Bulletin audio manager self-test passed.")


if __name__ == "__main__":
    _run_self_test()