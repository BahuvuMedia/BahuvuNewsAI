"""
BahuvuNewsAI - Telugu TTS Generator
===================================

Production-oriented Telugu text-to-speech generation using edge-tts.

Pipeline position:

    news.telugu_translator
        -> voice.tts_generator
        -> video assembly

Run:

    python -m py_compile voice/tts_generator.py
    python -m voice.tts_generator

Notes
-----
* The built-in self-test is offline-safe and does not contact any TTS service.
* Real audio generation requires:
      pip install edge-tts
* Default voice:
      te-IN-ShrutiNeural
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence


# =============================================================================
# ENUMS
# =============================================================================


class VoiceGender(str, Enum):
    FEMALE = "female"
    MALE = "male"


class AudioFormat(str, Enum):
    MP3 = "mp3"
    WAV = "wav"


class TTSStatus(str, Enum):
    PENDING = "pending"
    GENERATED = "generated"
    SKIPPED = "skipped"
    FAILED = "failed"


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass(slots=True)
class VoiceProfile:
    name: str
    locale: str = "te-IN"
    gender: VoiceGender = VoiceGender.FEMALE
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("Voice name cannot be empty.")
        if not re.fullmatch(r"[+-]\d+%", self.rate):
            raise ValueError("Rate must look like +0% or -10%.")
        if not re.fullmatch(r"[+-]\d+Hz", self.pitch):
            raise ValueError("Pitch must look like +0Hz or -2Hz.")
        if not re.fullmatch(r"[+-]\d+%", self.volume):
            raise ValueError("Volume must look like +0% or -5%.")


@dataclass(slots=True)
class TTSConfig:
    output_dir: Path = Path("outputs/audio")
    default_profile: VoiceProfile = field(
        default_factory=lambda: VoiceProfile(
            name="te-IN-ShrutiNeural",
            locale="te-IN",
            gender=VoiceGender.FEMALE,
            rate="-2%",
            pitch="+0Hz",
            volume="+0%",
        )
    )
    male_profile: VoiceProfile = field(
        default_factory=lambda: VoiceProfile(
            name="te-IN-MohanNeural",
            locale="te-IN",
            gender=VoiceGender.MALE,
            rate="-2%",
            pitch="+0Hz",
            volume="+0%",
        )
    )
    audio_format: AudioFormat = AudioFormat.MP3
    overwrite: bool = True
    retries: int = 3
    retry_delay_seconds: float = 1.5
    minimum_text_length: int = 2
    maximum_text_length: int = 20000
    split_long_text: bool = True
    chunk_character_limit: int = 3000
    write_metadata: bool = True
    ffmpeg_binary: str = "ffmpeg"

    def validate(self) -> None:
        self.default_profile.validate()
        self.male_profile.validate()

        if self.retries < 1:
            raise ValueError("Retries must be at least 1.")
        if self.retry_delay_seconds < 0:
            raise ValueError("Retry delay cannot be negative.")
        if self.minimum_text_length < 1:
            raise ValueError("Minimum text length must be positive.")
        if self.maximum_text_length < self.minimum_text_length:
            raise ValueError("Maximum text length is invalid.")
        if self.chunk_character_limit < 100:
            raise ValueError("Chunk character limit is too small.")


@dataclass(slots=True)
class NarrationInput:
    text: str
    story_id: str = ""
    title: str = ""
    language: str = "te"
    filename_stem: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AudioArtifact:
    path: Path
    format: AudioFormat
    bytes_written: int = 0
    duration_seconds: float | None = None
    chunk_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "format": self.format.value,
            "bytes_written": self.bytes_written,
            "duration_seconds": self.duration_seconds,
            "chunk_count": self.chunk_count,
        }


@dataclass(slots=True)
class TTSResult:
    status: TTSStatus
    input: NarrationInput
    profile: VoiceProfile
    artifact: AudioArtifact | None = None
    error: str = ""
    attempts: int = 0
    started_at: str = ""
    completed_at: str = ""

    @property
    def success(self) -> bool:
        return self.status == TTSStatus.GENERATED and self.artifact is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "input": asdict(self.input),
            "profile": asdict(self.profile),
            "artifact": self.artifact.to_dict() if self.artifact else None,
            "error": self.error,
            "attempts": self.attempts,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "success": self.success,
        }


@dataclass(slots=True)
class TTSSummary:
    processed: int = 0
    generated: int = 0
    skipped: int = 0
    failed: int = 0
    total_bytes: int = 0
    total_duration_seconds: float = 0.0

    @classmethod
    def from_results(cls, results: Sequence[TTSResult]) -> "TTSSummary":
        durations = [
            result.artifact.duration_seconds or 0.0
            for result in results
            if result.artifact
        ]
        return cls(
            processed=len(results),
            generated=sum(1 for result in results if result.status == TTSStatus.GENERATED),
            skipped=sum(1 for result in results if result.status == TTSStatus.SKIPPED),
            failed=sum(1 for result in results if result.status == TTSStatus.FAILED),
            total_bytes=sum(
                result.artifact.bytes_written
                for result in results
                if result.artifact
            ),
            total_duration_seconds=round(sum(durations), 2),
        )


# =============================================================================
# HELPERS
# =============================================================================


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _slugify(value: str, fallback: str = "narration") -> str:
    value = value.strip().lower()
    value = re.sub(r"[^\w\-]+", "_", value, flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or fallback


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def coerce_narration_input(value: Any) -> NarrationInput:
    if isinstance(value, NarrationInput):
        return value

    if isinstance(value, str):
        return NarrationInput(text=value)

    mapping = _coerce_mapping(value)
    if not mapping:
        raise TypeError(
            "Unsupported narration input. Provide a string, mapping, dataclass, "
            "or object containing text."
        )

    text = ""
    for key in (
        "text",
        "telugu_text",
        "translated_text",
        "script",
        "body",
        "content",
        "narration",
    ):
        if key in mapping and mapping[key] is not None:
            text = _safe_text(mapping[key])
            break

    story_id = _safe_text(
        mapping.get("story_id")
        or mapping.get("article_id")
        or mapping.get("id")
        or ""
    )
    title = _safe_text(
        mapping.get("title")
        or mapping.get("headline")
        or ""
    )
    language = _safe_text(
        mapping.get("language")
        or mapping.get("language_code")
        or "te"
    )
    filename_stem = _safe_text(mapping.get("filename_stem") or "")

    metadata = mapping.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        metadata = {}

    return NarrationInput(
        text=text,
        story_id=story_id,
        title=title,
        language=language,
        filename_stem=filename_stem,
        metadata=dict(metadata),
    )


def normalize_text(text: str) -> str:
    value = text.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u200b", "").replace("\ufeff", "")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def split_text(text: str, max_chars: int) -> list[str]:
    text = normalize_text(text)
    if len(text) <= max_chars:
        return [text] if text else []

    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", text)
        if paragraph.strip()
    ]

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(paragraph) <= max_chars:
            current = paragraph
            continue

        sentences = re.split(r"(?<=[.!?।])\s+", paragraph)
        sentence_buffer = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            candidate = (
                f"{sentence_buffer} {sentence}".strip()
                if sentence_buffer
                else sentence
            )

            if len(candidate) <= max_chars:
                sentence_buffer = candidate
            else:
                if sentence_buffer:
                    chunks.append(sentence_buffer)
                if len(sentence) <= max_chars:
                    sentence_buffer = sentence
                else:
                    for start in range(0, len(sentence), max_chars):
                        chunks.append(sentence[start : start + max_chars].strip())
                    sentence_buffer = ""

        if sentence_buffer:
            current = sentence_buffer

    if current:
        chunks.append(current)

    return [chunk for chunk in chunks if chunk]


def estimate_duration_seconds(text: str, words_per_minute: float = 125.0) -> float:
    word_count = len(re.findall(r"\S+", normalize_text(text)))
    if not word_count:
        return 0.0
    return round((word_count / words_per_minute) * 60.0, 2)


# =============================================================================
# ENGINE
# =============================================================================


class TeluguTTSGenerator:
    def __init__(self, config: TTSConfig | None = None) -> None:
        self.config = config or TTSConfig()
        self.config.validate()

    def is_edge_tts_available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            return False

    def select_profile(
        self,
        gender: VoiceGender | str | None = None,
    ) -> VoiceProfile:
        if gender is None:
            return self.config.default_profile

        normalized = (
            gender.value
            if isinstance(gender, VoiceGender)
            else str(gender).strip().lower()
        )

        if normalized == VoiceGender.MALE.value:
            return self.config.male_profile
        return self.config.default_profile

    def validate_input(self, narration: NarrationInput) -> None:
        narration.text = normalize_text(narration.text)

        if len(narration.text) < self.config.minimum_text_length:
            raise ValueError("Narration text is empty or too short.")

        if len(narration.text) > self.config.maximum_text_length:
            raise ValueError(
                "Narration text exceeds the configured maximum length."
            )

        if narration.language.lower() not in {"te", "te-in", "telugu"}:
            raise ValueError(
                "Telugu TTS generator expects Telugu language input."
            )

    def build_output_path(
        self,
        narration: NarrationInput,
        output_path: str | Path | None = None,
    ) -> Path:
        if output_path is not None:
            path = Path(output_path)
            if not path.suffix:
                path = path.with_suffix(f".{self.config.audio_format.value}")
            return path

        stem = narration.filename_stem.strip()

        if not stem:
            stem = (
                narration.story_id.strip()
                or narration.title.strip()
                or "telugu_narration"
            )

        stem = _slugify(stem)
        return self.config.output_dir / f"{stem}.{self.config.audio_format.value}"

    async def generate_async(
        self,
        value: Any,
        *,
        output_path: str | Path | None = None,
        gender: VoiceGender | str | None = None,
    ) -> TTSResult:
        narration = coerce_narration_input(value)
        profile = self.select_profile(gender)
        started_at = _utc_now_iso()

        try:
            self.validate_input(narration)
        except Exception as exc:
            return TTSResult(
                status=TTSStatus.FAILED,
                input=narration,
                profile=profile,
                error=str(exc),
                attempts=0,
                started_at=started_at,
                completed_at=_utc_now_iso(),
            )

        target_path = self.build_output_path(narration, output_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if target_path.exists() and not self.config.overwrite:
            artifact = AudioArtifact(
                path=target_path,
                format=self.config.audio_format,
                bytes_written=target_path.stat().st_size,
                duration_seconds=estimate_duration_seconds(narration.text),
            )
            return TTSResult(
                status=TTSStatus.SKIPPED,
                input=narration,
                profile=profile,
                artifact=artifact,
                attempts=0,
                started_at=started_at,
                completed_at=_utc_now_iso(),
            )

        if not self.is_edge_tts_available():
            return TTSResult(
                status=TTSStatus.FAILED,
                input=narration,
                profile=profile,
                error=(
                    "edge-tts is not installed. Run: pip install edge-tts"
                ),
                attempts=0,
                started_at=started_at,
                completed_at=_utc_now_iso(),
            )

        chunks = (
            split_text(narration.text, self.config.chunk_character_limit)
            if self.config.split_long_text
            else [narration.text]
        )

        attempts = 0
        last_error = ""

        for attempt in range(1, self.config.retries + 1):
            attempts = attempt
            try:
                artifact = await self._generate_chunks(
                    chunks=chunks,
                    target_path=target_path,
                    profile=profile,
                    narration=narration,
                )
                result = TTSResult(
                    status=TTSStatus.GENERATED,
                    input=narration,
                    profile=profile,
                    artifact=artifact,
                    attempts=attempts,
                    started_at=started_at,
                    completed_at=_utc_now_iso(),
                )

                if self.config.write_metadata:
                    self._write_metadata(result)

                return result
            except Exception as exc:
                last_error = str(exc)
                if attempt < self.config.retries:
                    await asyncio.sleep(self.config.retry_delay_seconds)

        return TTSResult(
            status=TTSStatus.FAILED,
            input=narration,
            profile=profile,
            error=last_error or "Unknown TTS generation failure.",
            attempts=attempts,
            started_at=started_at,
            completed_at=_utc_now_iso(),
        )

    def generate(
        self,
        value: Any,
        *,
        output_path: str | Path | None = None,
        gender: VoiceGender | str | None = None,
    ) -> TTSResult:
        return asyncio.run(
            self.generate_async(
                value,
                output_path=output_path,
                gender=gender,
            )
        )

    async def generate_many_async(
        self,
        values: Iterable[Any],
        *,
        gender: VoiceGender | str | None = None,
    ) -> list[TTSResult]:
        results: list[TTSResult] = []
        for value in values:
            results.append(
                await self.generate_async(value, gender=gender)
            )
        return results

    def generate_many(
        self,
        values: Iterable[Any],
        *,
        gender: VoiceGender | str | None = None,
    ) -> list[TTSResult]:
        return asyncio.run(
            self.generate_many_async(values, gender=gender)
        )

    async def _generate_chunks(
        self,
        *,
        chunks: Sequence[str],
        target_path: Path,
        profile: VoiceProfile,
        narration: NarrationInput,
    ) -> AudioArtifact:
        import edge_tts

        if not chunks:
            raise ValueError("No narration chunks were produced.")

        if len(chunks) == 1:
            communicate = edge_tts.Communicate(
                chunks[0],
                profile.name,
                rate=profile.rate,
                volume=profile.volume,
                pitch=profile.pitch,
            )
            await communicate.save(str(target_path))
        else:
            await self._generate_and_merge_chunks(
                edge_tts_module=edge_tts,
                chunks=chunks,
                target_path=target_path,
                profile=profile,
            )

        if not target_path.exists() or target_path.stat().st_size == 0:
            raise RuntimeError("TTS service did not produce a valid audio file.")

        return AudioArtifact(
            path=target_path,
            format=self.config.audio_format,
            bytes_written=target_path.stat().st_size,
            duration_seconds=estimate_duration_seconds(narration.text),
            chunk_count=len(chunks),
        )

    async def _generate_and_merge_chunks(
        self,
        *,
        edge_tts_module: Any,
        chunks: Sequence[str],
        target_path: Path,
        profile: VoiceProfile,
    ) -> None:
        ffmpeg = shutil.which(self.config.ffmpeg_binary)
        if not ffmpeg:
            raise RuntimeError(
                "Long narration requires FFmpeg for audio merging, but "
                "FFmpeg was not found in PATH."
            )

        with tempfile.TemporaryDirectory(prefix="bahuvu_tts_") as temp_dir:
            temp_path = Path(temp_dir)
            chunk_files: list[Path] = []

            for index, chunk in enumerate(chunks, start=1):
                chunk_file = temp_path / f"chunk_{index:04d}.mp3"
                communicate = edge_tts_module.Communicate(
                    chunk,
                    profile.name,
                    rate=profile.rate,
                    volume=profile.volume,
                    pitch=profile.pitch,
                )
                await communicate.save(str(chunk_file))
                chunk_files.append(chunk_file)

            concat_file = temp_path / "concat.txt"
            concat_file.write_text(
                "\n".join(
                    f"file '{path.as_posix()}'"
                    for path in chunk_files
                ),
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
                str(target_path),
            ]

            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
            )

            if completed.returncode != 0:
                raise RuntimeError(
                    "FFmpeg failed to merge TTS chunks: "
                    + completed.stderr.strip()
                )

    def _write_metadata(self, result: TTSResult) -> None:
        if not result.artifact:
            return

        metadata_path = result.artifact.path.with_suffix(
            result.artifact.path.suffix + ".json"
        )
        metadata_path.write_text(
            json.dumps(
                result.to_dict(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def summarize(
        self,
        results: Sequence[TTSResult],
    ) -> TTSSummary:
        return TTSSummary.from_results(results)


# =============================================================================
# CONVENIENCE API
# =============================================================================


def generate_telugu_audio(
    value: Any,
    *,
    output_path: str | Path | None = None,
    gender: VoiceGender | str | None = None,
    config: TTSConfig | None = None,
) -> TTSResult:
    return TeluguTTSGenerator(config=config).generate(
        value,
        output_path=output_path,
        gender=gender,
    )


# =============================================================================
# OFFLINE-SAFE SELF-TEST
# =============================================================================


def _run_self_test() -> None:
    config = TTSConfig(
        output_dir=Path("outputs/audio"),
        overwrite=True,
        retries=2,
        split_long_text=True,
        chunk_character_limit=120,
    )

    generator = TeluguTTSGenerator(config=config)

    sample = NarrationInput(
        text=(
            "ఆంధ్రప్రదేశ్ తీర ప్రాంతాల్లో భారీ వర్షాలు కురిసే అవకాశం ఉందని "
            "భారత వాతావరణ శాఖ తెలిపింది. ప్రజలు అప్రమత్తంగా ఉండాలని అధికారులు "
            "సూచించారు."
        ),
        story_id="weather_demo",
        title="ఆంధ్రప్రదేశ్‌లో భారీ వర్షాల హెచ్చరిక",
        language="te",
    )

    generator.validate_input(sample)

    female = generator.select_profile(VoiceGender.FEMALE)
    male = generator.select_profile(VoiceGender.MALE)

    assert female.name == "te-IN-ShrutiNeural"
    assert male.name == "te-IN-MohanNeural"

    output_path = generator.build_output_path(sample)
    assert output_path.as_posix().endswith(
        "outputs/audio/weather_demo.mp3"
    )

    normalized = normalize_text("  ఇది   పరీక్ష.\n\n\nఇది రెండో వాక్యం.  ")
    assert normalized == "ఇది పరీక్ష.\n\nఇది రెండో వాక్యం."

    long_text = (
        "ఇది మొదటి వాక్యం. ఇది రెండో వాక్యం. ఇది మూడో వాక్యం. "
        "ఇది నాలుగో వాక్యం. ఇది ఐదో వాక్యం."
    )
    chunks = split_text(long_text, 40)
    assert len(chunks) >= 2
    assert all(chunk.strip() for chunk in chunks)

    duration = estimate_duration_seconds(sample.text)
    assert duration > 0

    mapped = coerce_narration_input(
        {
            "translated_text": sample.text,
            "article_id": "article_001",
            "headline": sample.title,
            "language_code": "te",
        }
    )
    assert mapped.story_id == "article_001"
    assert mapped.text == sample.text

    fake_artifact = AudioArtifact(
        path=Path("outputs/audio/test.mp3"),
        format=AudioFormat.MP3,
        bytes_written=1024,
        duration_seconds=12.5,
        chunk_count=2,
    )

    fake_result = TTSResult(
        status=TTSStatus.GENERATED,
        input=sample,
        profile=female,
        artifact=fake_artifact,
        attempts=1,
        started_at=_utc_now_iso(),
        completed_at=_utc_now_iso(),
    )

    summary = generator.summarize([fake_result])
    assert summary.processed == 1
    assert summary.generated == 1
    assert summary.total_bytes == 1024

    print("Telugu TTS generator initialized successfully.")
    print()
    print(f"Default voice          : {female.name}")
    print(f"Alternative voice      : {male.name}")
    print(f"Sample text characters : {len(sample.text)}")
    print(f"Generated text chunks  : {len(chunks)}")
    print(f"Estimated duration     : {duration:.2f} seconds")
    print(f"Output path            : {output_path}")
    print(f"edge-tts available     : {generator.is_edge_tts_available()}")
    print()
    print("Telugu TTS generator self-test passed.")


if __name__ == "__main__":
    _run_self_test()