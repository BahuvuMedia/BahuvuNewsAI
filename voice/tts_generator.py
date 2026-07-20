"""
BahuvuNewsAI - Telugu TTS Generator v2.0
========================================

Provider-aware Telugu speech synthesis.

Primary production path:
    BAHUVU_VOICE_PROVIDER=azure
    -> Microsoft Azure Speech SDK
    -> SSML-controlled Telugu neural speech

Fallback path:
    BAHUVU_VOICE_PROVIDER=edge
    -> edge-tts

The public API remains compatible with production.integrations:
    TeluguTTSGenerator().generate_many(...)
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from html import escape
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence

from voice.telugu_speech_normalizer import normalize_for_speech


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


@dataclass(slots=True)
class VoiceProfile:
    name: str
    locale: str = "te-IN"
    gender: VoiceGender = VoiceGender.FEMALE
    rate: str = "-4%"
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
            name=os.getenv("AZURE_SPEECH_VOICE", "te-IN-ShrutiNeural"),
            locale="te-IN",
            gender=VoiceGender.FEMALE,
            rate=os.getenv("BAHUVU_SPEECH_RATE", "-4%"),
            pitch=os.getenv("BAHUVU_SPEECH_PITCH", "+0Hz"),
            volume=os.getenv("BAHUVU_SPEECH_VOLUME", "+0%"),
        )
    )
    male_profile: VoiceProfile = field(
        default_factory=lambda: VoiceProfile(
            name=os.getenv("AZURE_SPEECH_MALE_VOICE", "te-IN-MohanNeural"),
            locale="te-IN",
            gender=VoiceGender.MALE,
            rate=os.getenv("BAHUVU_SPEECH_RATE", "-4%"),
            pitch=os.getenv("BAHUVU_SPEECH_PITCH", "+0Hz"),
            volume=os.getenv("BAHUVU_SPEECH_VOLUME", "+0%"),
        )
    )
    audio_format: AudioFormat = AudioFormat.MP3
    overwrite: bool = True
    retries: int = 3
    retry_delay_seconds: float = 1.5
    minimum_text_length: int = 2
    maximum_text_length: int = 20000
    split_long_text: bool = True
    chunk_character_limit: int = 2800
    write_metadata: bool = True
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    sentence_pause_ms: int = 280
    paragraph_pause_ms: int = 500
    allow_edge_fallback: bool = field(
        default_factory=lambda: os.getenv(
            "BAHUVU_ALLOW_VOICE_FALLBACK", "false"
        ).strip().lower() in {"1", "true", "yes", "on"}
    )

    def validate(self) -> None:
        self.default_profile.validate()
        self.male_profile.validate()
        if self.retries < 1:
            raise ValueError("Retries must be at least 1.")
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
    provider: str = ""
    voice_name: str = ""
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "format": self.format.value,
            "bytes_written": self.bytes_written,
            "duration_seconds": self.duration_seconds,
            "chunk_count": self.chunk_count,
            "provider": self.provider,
            "voice_name": self.voice_name,
            "fallback_used": self.fallback_used,
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
        return cls(
            processed=len(results),
            generated=sum(r.status == TTSStatus.GENERATED for r in results),
            skipped=sum(r.status == TTSStatus.SKIPPED for r in results),
            failed=sum(r.status == TTSStatus.FAILED for r in results),
            total_bytes=sum(r.artifact.bytes_written for r in results if r.artifact),
            total_duration_seconds=round(
                sum((r.artifact.duration_seconds or 0.0) for r in results if r.artifact),
                2,
            ),
        )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    return "" if value is None else (value if isinstance(value, str) else str(value))


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        env_path = Path(".env")
        if not env_path.exists():
            return
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


def _slugify(value: str, fallback: str = "narration") -> str:
    value = re.sub(r"[^\w\-]+", "_", value.strip().lower(), flags=re.UNICODE)
    return re.sub(r"_+", "_", value).strip("_") or fallback


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
        raise TypeError("Narration input must contain text.")

    text = next(
        (
            _safe_text(mapping[key])
            for key in (
                "text", "speech_text", "telugu_text", "translated_text",
                "script", "body", "content", "narration",
            )
            if mapping.get(key) is not None
        ),
        "",
    )
    metadata = mapping.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        metadata = {}

    return NarrationInput(
        text=text,
        story_id=_safe_text(
            mapping.get("story_id") or mapping.get("article_id") or mapping.get("id") or ""
        ),
        title=_safe_text(mapping.get("title") or mapping.get("headline") or ""),
        language=_safe_text(mapping.get("language") or mapping.get("language_code") or "te"),
        filename_stem=_safe_text(mapping.get("filename_stem") or ""),
        metadata=dict(metadata),
    )


def normalize_text(text: str) -> str:
    value = text.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u200b", "").replace("\ufeff", "")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()



def prepare_telugu_speech_text(text: str) -> str:
    """
    Convert display text into Azure-friendly spoken Telugu.

    This function is used only for speech synthesis. It must never be used
    for captions, graphics, stored article text or translated display text.
    """

    value = normalize_text(text)

    # Brand pronunciation: BAHUVU must always be spoken as BAAHUVU.
    value = re.sub(
        r"\bBAHUVU\s+NEWS\b",
        "బాహువు న్యూస్",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\bBAHUVU\b",
        "బాహువు",
        value,
        flags=re.IGNORECASE,
    )

    # Keep the channel brand as "బాహువు న్యూస్", but translate
    # ordinary NEWS references into natural Telugu speech.
    value = re.sub(
        r"\bNEWS\b",
        "వార్తలు",
        value,
        flags=re.IGNORECASE,
    )

    value = value.replace(
        "మరిన్ని వార్తలు వివరాలు",
        "మరిన్ని వార్తా వివరాలు",
    )

    # Correct common Telugu spelling variants before synthesis.
    telugu_replacements = {
        "బహువు న్యూస్": "బాహువు న్యూస్",
        "బహువు": "బాహువు",
        "బాహువు నుయూస్": "బాహువు న్యూస్",
        "బాహువు నుయుస్": "బాహువు న్యూస్",
        "నుయూస్": "న్యూస్",
        "నుయుస్": "న్యూస్",
        "మంతిరి": "మంత్రి",
        "మంత్రీ": "మంత్రి",
    }

    for source, target in telugu_replacements.items():
        value = value.replace(source, target)

    # Give the channel name a clean broadcast pause.
    value = re.sub(
        r"బాహువు న్యూస్\s*[-–—:]?\s*",
        "బాహువు న్యూస్. ",
        value,
    )

    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\.{2,}", ".", value)
    value = re.sub(r"\s+([,.;!?])", r"\1", value)

    return value.strip()


def split_text(text: str, max_chars: int) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
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

        sentences = re.split(r"(?<=[.!?।])\s+", paragraph)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                if len(sentence) <= max_chars:
                    current = sentence
                else:
                    chunks.extend(
                        sentence[i:i + max_chars].strip()
                        for i in range(0, len(sentence), max_chars)
                        if sentence[i:i + max_chars].strip()
                    )
                    current = ""
    if current:
        chunks.append(current)
    return chunks


def estimate_duration_seconds(text: str, words_per_minute: float = 125.0) -> float:
    words = len(re.findall(r"\S+", normalize_text(text)))
    return round((words / words_per_minute) * 60.0, 2) if words else 0.0


class TeluguTTSGenerator:
    def __init__(self, config: TTSConfig | None = None) -> None:
        _load_dotenv_if_available()
        self.config = config or TTSConfig()
        self.config.validate()
        self.provider = os.getenv("BAHUVU_VOICE_PROVIDER", "azure").strip().lower()
        if self.provider not in {"azure", "edge"}:
            raise ValueError(
                "BAHUVU_VOICE_PROVIDER must be 'azure' or 'edge', "
                f"not {self.provider!r}."
            )

    def is_edge_tts_available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            return False

    def is_azure_available(self) -> bool:
        try:
            import azure.cognitiveservices.speech  # noqa: F401
            return True
        except ImportError:
            return False

    def select_profile(self, gender: VoiceGender | str | None = None) -> VoiceProfile:
        normalized = (
            gender.value if isinstance(gender, VoiceGender)
            else str(gender or "").strip().lower()
        )
        return self.config.male_profile if normalized == "male" else self.config.default_profile

    def validate_input(self, narration: NarrationInput) -> None:
        narration.text = normalize_text(narration.text)
        if len(narration.text) < self.config.minimum_text_length:
            raise ValueError("Narration text is empty or too short.")
        if len(narration.text) > self.config.maximum_text_length:
            raise ValueError("Narration text exceeds the configured maximum length.")
        if narration.language.lower() not in {"te", "te-in", "telugu"}:
            raise ValueError("Telugu TTS generator expects Telugu input.")

    def build_output_path(
        self,
        narration: NarrationInput,
        output_path: str | Path | None = None,
    ) -> Path:
        if output_path is not None:
            path = Path(output_path)
            return path if path.suffix else path.with_suffix(".mp3")
        stem = narration.filename_stem.strip() or narration.story_id.strip() \
            or narration.title.strip() or "telugu_narration"
        return self.config.output_dir / f"{_slugify(stem)}.mp3"

    def _duration(self, path: Path, text: str) -> float:
        ffprobe = shutil.which(self.config.ffprobe_binary)
        if ffprobe:
            completed = subprocess.run(
                [
                    ffprobe, "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(path),
                ],
                capture_output=True,
                text=True,
            )
            if completed.returncode == 0:
                try:
                    return round(float(completed.stdout.strip()), 3)
                except ValueError:
                    pass
        return estimate_duration_seconds(text)

    def _build_ssml(self, text: str, profile: VoiceProfile) -> str:
        speech_text = prepare_telugu_speech_text(text)
        paragraphs = [
            p.strip()
            for p in re.split(r"\n\s*\n", speech_text)
            if p.strip()
        ]
        rendered: list[str] = []
        for paragraph in paragraphs:
            sentences = [
                s.strip()
                for s in re.split(r"(?<=[.!?।])\s+", paragraph)
                if s.strip()
            ]
            body = (
                f'<break time="{self.config.sentence_pause_ms}ms"/>'.join(
                    escape(sentence) for sentence in sentences
                )
            )
            rendered.append(f"<p>{body}</p>")
        paragraph_break = f'<break time="{self.config.paragraph_pause_ms}ms"/>'
        content = paragraph_break.join(rendered)
        return (
            '<speak version="1.0" '
            'xmlns="http://www.w3.org/2001/10/synthesis" '
            'xml:lang="te-IN">'
            f'<voice name="{escape(profile.name)}">'
            f'<prosody rate="{profile.rate}" pitch="{profile.pitch}" '
            f'volume="{profile.volume}">{content}</prosody>'
            "</voice></speak>"
        )

    def _azure_credentials(self) -> tuple[str, str]:
        key = os.getenv("AZURE_SPEECH_KEY", "").strip()
        region = os.getenv("AZURE_SPEECH_REGION", "").strip()
        if not key or not region:
            raise RuntimeError(
                "Azure Speech credentials are missing. Set AZURE_SPEECH_KEY "
                "and AZURE_SPEECH_REGION in .env."
            )
        return key, region

    def _generate_azure_chunk(
        self,
        text: str,
        target_path: Path,
        profile: VoiceProfile,
    ) -> None:
        if not self.is_azure_available():
            raise RuntimeError(
                "Azure Speech SDK is not installed. Run: "
                "python -m pip install azure-cognitiveservices-speech"
            )

        import azure.cognitiveservices.speech as speechsdk

        key, region = self._azure_credentials()
        speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        speech_config.speech_synthesis_voice_name = profile.name
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3
        )
        audio_config = speechsdk.audio.AudioOutputConfig(filename=str(target_path))
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )
        result = synthesizer.speak_ssml_async(
            self._build_ssml(text, profile)
        ).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            return

        if result.reason == speechsdk.ResultReason.Canceled:
            details = speechsdk.SpeechSynthesisCancellationDetails.from_result(result)
            raise RuntimeError(
                "Azure synthesis canceled: "
                f"reason={details.reason}; "
                f"error_code={details.error_code}; "
                f"details={details.error_details}"
            )

        raise RuntimeError(f"Azure synthesis failed: {result.reason}")

    async def _generate_edge_chunk(
        self,
        text: str,
        target_path: Path,
        profile: VoiceProfile,
    ) -> None:
        if not self.is_edge_tts_available():
            raise RuntimeError("edge-tts is not installed. Run: pip install edge-tts")
        import edge_tts
        communicate = edge_tts.Communicate(
            text,
            profile.name,
            rate=profile.rate,
            volume=profile.volume,
            pitch=profile.pitch,
        )
        await communicate.save(str(target_path))

    def _merge_chunks(self, chunk_files: Sequence[Path], target_path: Path) -> None:
        ffmpeg = shutil.which(self.config.ffmpeg_binary)
        if not ffmpeg:
            raise RuntimeError("FFmpeg is required to merge narration chunks.")
        with tempfile.TemporaryDirectory(prefix="bahuvu_concat_") as temp_dir:
            concat_file = Path(temp_dir) / "concat.txt"
            concat_file.write_text(
                "\n".join(f"file '{path.resolve().as_posix()}'" for path in chunk_files),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    ffmpeg, "-y", "-f", "concat", "-safe", "0",
                    "-i", str(concat_file), "-c", "copy", str(target_path),
                ],
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    "FFmpeg failed to merge TTS chunks: " + completed.stderr.strip()
                )

    async def _generate_with_provider(
        self,
        *,
        provider: str,
        chunks: Sequence[str],
        target_path: Path,
        profile: VoiceProfile,
        narration: NarrationInput,
        fallback_used: bool,
    ) -> AudioArtifact:
        if not chunks:
            raise ValueError("No narration chunks were produced.")

        if len(chunks) == 1:
            if provider == "azure":
                await asyncio.to_thread(
                    self._generate_azure_chunk, chunks[0], target_path, profile
                )
            else:
                await self._generate_edge_chunk(chunks[0], target_path, profile)
        else:
            with tempfile.TemporaryDirectory(prefix=f"bahuvu_{provider}_") as temp_dir:
                temp_path = Path(temp_dir)
                chunk_files: list[Path] = []
                for index, chunk in enumerate(chunks, start=1):
                    chunk_file = temp_path / f"chunk_{index:04d}.mp3"
                    if provider == "azure":
                        await asyncio.to_thread(
                            self._generate_azure_chunk, chunk, chunk_file, profile
                        )
                    else:
                        await self._generate_edge_chunk(chunk, chunk_file, profile)
                    chunk_files.append(chunk_file)
                self._merge_chunks(chunk_files, target_path)

        if not target_path.exists() or target_path.stat().st_size < 1000:
            raise RuntimeError("TTS provider did not produce a valid audio file.")

        return AudioArtifact(
            path=target_path,
            format=AudioFormat.MP3,
            bytes_written=target_path.stat().st_size,
            duration_seconds=self._duration(target_path, narration.text),
            chunk_count=len(chunks),
            provider=provider,
            voice_name=profile.name,
            fallback_used=fallback_used,
        )

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
                started_at=started_at,
                completed_at=_utc_now_iso(),
            )

        target_path = self.build_output_path(narration, output_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if target_path.exists() and not self.config.overwrite:
            artifact = AudioArtifact(
                path=target_path,
                format=AudioFormat.MP3,
                bytes_written=target_path.stat().st_size,
                duration_seconds=self._duration(target_path, narration.text),
                provider=self.provider,
                voice_name=profile.name,
            )
            return TTSResult(
                status=TTSStatus.SKIPPED,
                input=narration,
                profile=profile,
                artifact=artifact,
                started_at=started_at,
                completed_at=_utc_now_iso(),
            )

        speech_text = normalize_for_speech(narration.text)
        chunks = split_text(
            speech_text,
            self.config.chunk_character_limit,
        )
        attempts = 0
        last_error = ""

        for attempt in range(1, self.config.retries + 1):
            attempts = attempt
            try:
                artifact = await self._generate_with_provider(
                    provider=self.provider,
                    chunks=chunks,
                    target_path=target_path,
                    profile=profile,
                    narration=narration,
                    fallback_used=False,
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
                target_path.unlink(missing_ok=True)
                if attempt < self.config.retries:
                    await asyncio.sleep(self.config.retry_delay_seconds)

        if self.provider == "azure" and self.config.allow_edge_fallback:
            try:
                artifact = await self._generate_with_provider(
                    provider="edge",
                    chunks=chunks,
                    target_path=target_path,
                    profile=profile,
                    narration=narration,
                    fallback_used=True,
                )
                result = TTSResult(
                    status=TTSStatus.GENERATED,
                    input=narration,
                    profile=profile,
                    artifact=artifact,
                    error=f"Azure failed; Edge fallback used: {last_error}",
                    attempts=attempts,
                    started_at=started_at,
                    completed_at=_utc_now_iso(),
                )
                if self.config.write_metadata:
                    self._write_metadata(result)
                return result
            except Exception as fallback_exc:
                last_error += f" | Edge fallback failed: {fallback_exc}"

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
            self.generate_async(value, output_path=output_path, gender=gender)
        )

    async def generate_many_async(
        self,
        values: Iterable[Any],
        *,
        gender: VoiceGender | str | None = None,
    ) -> list[TTSResult]:
        results: list[TTSResult] = []
        for value in values:
            results.append(await self.generate_async(value, gender=gender))
        return results

    def generate_many(
        self,
        values: Iterable[Any],
        *,
        gender: VoiceGender | str | None = None,
    ) -> list[TTSResult]:
        return asyncio.run(self.generate_many_async(values, gender=gender))

    def _write_metadata(self, result: TTSResult) -> None:
        if not result.artifact:
            return
        path = result.artifact.path.with_suffix(result.artifact.path.suffix + ".json")
        path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def summarize(self, results: Sequence[TTSResult]) -> TTSSummary:
        return TTSSummary.from_results(results)


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


def _run_self_test() -> None:
    generator = TeluguTTSGenerator()
    profile = generator.select_profile()
    sample = NarrationInput(
        text=(
            "నమస్కారం. ఇది బాహువు న్యూస్‌ Azure తెలుగు స్వర పరీక్ష. "
            "ఆంధ్రప్రదేశ్‌లో భారీ వర్షాలు కురిసే అవకాశం ఉందని "
            "వాతావరణ శాఖ తెలిపింది. ప్రజలు అప్రమత్తంగా ఉండాలని అధికారులు సూచించారు."
        ),
        story_id="azure_telugu_final_test",
        title="Azure తెలుగు స్వర పరీక్ష",
        language="te",
    )

    print("BahuvuNewsAI Telugu TTS v2.0")
    print(f"Voice provider : {generator.provider}")
    print(f"Voice name     : {profile.name}")
    print(f"SSML           : enabled for Azure")
    print(f"Azure SDK      : {generator.is_azure_available()}")
    print(f"Edge fallback  : {generator.config.allow_edge_fallback}")
    print()

    result = generator.generate(sample)
    if not result.success:
        raise RuntimeError(result.error)

    assert result.artifact is not None
    print("Synthesis      : SUCCESS")
    print(f"Provider used  : {result.artifact.provider}")
    print(f"Fallback used  : {result.artifact.fallback_used}")
    print(f"Output         : {result.artifact.path}")
    print(f"Bytes          : {result.artifact.bytes_written}")
    print(f"Duration       : {result.artifact.duration_seconds:.3f}s")


if __name__ == "__main__":
    _run_self_test()