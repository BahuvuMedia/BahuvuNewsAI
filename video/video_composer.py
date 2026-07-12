"""
BahuvuNewsAI - Video Composer

Combines rendered scene images, timeline durations, and optional bulletin audio
into a final MP4 using MoviePy.

Run:
    python -m py_compile video/video_composer.py
    python -m video.video_composer
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image, ImageDraw


class VideoStatus(str, Enum):
    RENDERED = "rendered"
    FAILED = "failed"
    SKIPPED = "skipped"


class AudioMode(str, Enum):
    NONE = "none"
    BULLETIN = "bulletin"


class VideoCodec(str, Enum):
    H264 = "libx264"
    H265 = "libx265"


@dataclass(slots=True)
class VideoComposerConfig:
    output_dir: Path = Path("outputs/video")
    output_filename: str = "bahuvu_bulletin.mp4"
    manifest_filename: str = "video_manifest.json"
    width: int = 1280
    height: int = 720
    fps: int = 24
    codec: VideoCodec = VideoCodec.H264
    audio_codec: str = "aac"
    preset: str = "medium"
    bitrate: str = "4000k"
    pixel_format: str = "yuv420p"
    threads: int | None = None
    overwrite: bool = True
    write_manifest: bool = True
    include_audio: bool = True
    audio_mode: AudioMode = AudioMode.BULLETIN
    trim_audio_to_video: bool = True
    logger: str | None = None

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Video dimensions must be positive.")
        if self.fps <= 0:
            raise ValueError("FPS must be positive.")
        if not self.output_filename.strip():
            raise ValueError("Output filename cannot be empty.")
        if not self.manifest_filename.strip():
            raise ValueError("Manifest filename cannot be empty.")
        if self.threads is not None and self.threads <= 0:
            raise ValueError("Threads must be positive.")


@dataclass(slots=True)
class VideoSceneInput:
    scene_id: str
    order: int
    image_path: Path
    duration_seconds: float
    start_time_seconds: float = 0.0
    end_time_seconds: float = 0.0
    audio_path: Path | None = None
    scene_type: str = ""
    story_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VideoRenderResult:
    status: VideoStatus
    bulletin_id: str
    output_path: Path | None
    manifest_path: Path | None
    scene_count: int
    duration_seconds: float
    width: int
    height: int
    fps: int
    file_size_bytes: int = 0
    audio_included: bool = False
    started_at: str = ""
    completed_at: str = ""
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == VideoStatus.RENDERED and self.output_path is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "bulletin_id": self.bulletin_id,
            "output_path": str(self.output_path) if self.output_path else None,
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "scene_count": self.scene_count,
            "duration_seconds": self.duration_seconds,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "file_size_bytes": self.file_size_bytes,
            "audio_included": self.audio_included,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
            "success": self.success,
        }


@dataclass(slots=True)
class VideoComposerSummary:
    renders_processed: int
    renders_succeeded: int
    renders_failed: int
    total_duration_seconds: float
    total_bytes: int

    @classmethod
    def from_results(cls, results: Sequence[VideoRenderResult]) -> "VideoComposerSummary":
        return cls(
            renders_processed=len(results),
            renders_succeeded=sum(1 for item in results if item.success),
            renders_failed=sum(1 for item in results if item.status == VideoStatus.FAILED),
            total_duration_seconds=round(sum(item.duration_seconds for item in results), 2),
            total_bytes=sum(item.file_size_bytes for item in results),
        )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str, fallback: str = "bulletin") -> str:
    value = re.sub(r"[^\w\-]+", "_", value.strip().lower(), flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or fallback


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def coerce_video_scene_input(value: Any, fallback_order: int = 1) -> VideoSceneInput:
    if isinstance(value, VideoSceneInput):
        return value

    data = _mapping(value)
    if not data:
        raise TypeError("Video scene input must be a mapping, dataclass, or object.")

    image_path = data.get("image_path") or data.get("output_path") or data.get("frame_path")
    if not image_path:
        raise ValueError("Scene image path is required.")

    order_value = data.get("order") or data.get("scene_order") or fallback_order
    try:
        order = int(order_value)
    except (TypeError, ValueError):
        order = fallback_order

    scene_type = data.get("scene_type") or ""
    if isinstance(scene_type, Enum):
        scene_type = scene_type.value

    audio_path = data.get("audio_path")
    metadata = data.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        metadata = {}

    return VideoSceneInput(
        scene_id=str(data.get("scene_id") or f"scene_{order:03d}"),
        order=order,
        image_path=Path(str(image_path)),
        duration_seconds=_float(data.get("duration_seconds") or data.get("duration")),
        start_time_seconds=_float(data.get("start_time_seconds")),
        end_time_seconds=_float(data.get("end_time_seconds")),
        audio_path=Path(str(audio_path)) if audio_path else None,
        scene_type=str(scene_type),
        story_id=str(data.get("story_id") or ""),
        metadata=dict(metadata),
    )


def coerce_scene_list(values: Iterable[Any]) -> list[VideoSceneInput]:
    scenes = [
        coerce_video_scene_input(value, index)
        for index, value in enumerate(values, start=1)
    ]
    scenes.sort(key=lambda item: (item.order, item.scene_id))
    return scenes


class VideoComposer:
    def __init__(self, config: VideoComposerConfig | None = None) -> None:
        self.config = config or VideoComposerConfig()
        self.config.validate()

    def moviepy_available(self) -> bool:
        try:
            import moviepy  # noqa: F401
            return True
        except ImportError:
            return False

    def build_scene_inputs(self, *, timeline: Any, graphics_manifest: Any) -> list[VideoSceneInput]:
        rendered_by_id = {
            item.scene_id: item
            for item in graphics_manifest.scenes
            if getattr(item, "output_path", None) is not None
        }
        inputs: list[VideoSceneInput] = []

        for scene in timeline.scenes:
            rendered = rendered_by_id.get(scene.scene_id)
            if rendered is None or rendered.output_path is None:
                raise ValueError(f"No rendered image found for scene {scene.scene_id}.")

            inputs.append(
                VideoSceneInput(
                    scene_id=scene.scene_id,
                    order=scene.order,
                    image_path=Path(rendered.output_path),
                    duration_seconds=float(scene.duration_seconds),
                    start_time_seconds=float(scene.start_time_seconds),
                    end_time_seconds=float(scene.end_time_seconds),
                    audio_path=Path(scene.audio_path) if scene.audio_path else None,
                    scene_type=scene.scene_type.value,
                    story_id=scene.story_id,
                    metadata={**scene.metadata, **rendered.metadata},
                )
            )
        return inputs

    def compose(
        self,
        *,
        bulletin_id: str,
        scenes: Iterable[Any],
        bulletin_audio_path: str | Path | None = None,
        output_path: str | Path | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> VideoRenderResult:
        started_at = _utc_now_iso()
        scene_inputs = coerce_scene_list(scenes)
        warnings: list[str] = []

        try:
            self._validate_scenes(scene_inputs)
            target = self._output_path(bulletin_id, output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            manifest_path = target.parent / self.config.manifest_filename if self.config.write_manifest else None

            if target.exists() and not self.config.overwrite:
                result = VideoRenderResult(
                    status=VideoStatus.SKIPPED,
                    bulletin_id=bulletin_id,
                    output_path=target,
                    manifest_path=manifest_path,
                    scene_count=len(scene_inputs),
                    duration_seconds=round(sum(x.duration_seconds for x in scene_inputs), 2),
                    width=self.config.width,
                    height=self.config.height,
                    fps=self.config.fps,
                    file_size_bytes=target.stat().st_size,
                    started_at=started_at,
                    completed_at=_utc_now_iso(),
                    warnings=["Existing output was preserved."],
                    metadata=dict(metadata or {}),
                )
                if manifest_path:
                    self.write_manifest(result)
                return result

            if not self.moviepy_available():
                raise RuntimeError("MoviePy is not installed. Run: pip install moviepy")

            audio_path = Path(bulletin_audio_path) if bulletin_audio_path else None
            if self.config.include_audio and audio_path and not audio_path.exists():
                warnings.append("Bulletin audio was not found; rendering silent video.")
                audio_path = None

            duration = self._render_moviepy(scene_inputs, target, audio_path)

            if not target.exists() or target.stat().st_size == 0:
                raise RuntimeError("Video output was not created correctly.")

            result = VideoRenderResult(
                status=VideoStatus.RENDERED,
                bulletin_id=bulletin_id,
                output_path=target,
                manifest_path=manifest_path,
                scene_count=len(scene_inputs),
                duration_seconds=duration,
                width=self.config.width,
                height=self.config.height,
                fps=self.config.fps,
                file_size_bytes=target.stat().st_size,
                audio_included=audio_path is not None,
                started_at=started_at,
                completed_at=_utc_now_iso(),
                warnings=warnings,
                metadata=dict(metadata or {}),
            )
            if manifest_path:
                self.write_manifest(result)
            return result

        except Exception as exc:
            return VideoRenderResult(
                status=VideoStatus.FAILED,
                bulletin_id=bulletin_id,
                output_path=None,
                manifest_path=None,
                scene_count=len(scene_inputs),
                duration_seconds=round(sum(x.duration_seconds for x in scene_inputs), 2),
                width=self.config.width,
                height=self.config.height,
                fps=self.config.fps,
                started_at=started_at,
                completed_at=_utc_now_iso(),
                error=str(exc),
                warnings=warnings,
                metadata=dict(metadata or {}),
            )

    def compose_from_manifests(
        self,
        *,
        timeline: Any,
        graphics_manifest: Any,
        bulletin_audio_path: str | Path | None = None,
        output_path: str | Path | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> VideoRenderResult:
        return self.compose(
            bulletin_id=timeline.bulletin_id,
            scenes=self.build_scene_inputs(
                timeline=timeline,
                graphics_manifest=graphics_manifest,
            ),
            bulletin_audio_path=bulletin_audio_path,
            output_path=output_path,
            metadata={
                **getattr(timeline, "metadata", {}),
                **getattr(graphics_manifest, "metadata", {}),
                **dict(metadata or {}),
            },
        )

    def _render_moviepy(
        self,
        scenes: Sequence[VideoSceneInput],
        target: Path,
        audio_path: Path | None,
    ) -> float:
        try:
            from moviepy import AudioFileClip, ImageClip, concatenate_videoclips
        except ImportError:
            from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips

        clips = []
        audio_clip = None
        final_clip = None

        try:
            for scene in scenes:
                clip = ImageClip(str(scene.image_path))
                clip = (
                    clip.with_duration(scene.duration_seconds)
                    if hasattr(clip, "with_duration")
                    else clip.set_duration(scene.duration_seconds)
                )

                current_size = tuple(clip.size)
                target_size = (self.config.width, self.config.height)
                if current_size != target_size:
                    clip = (
                        clip.resized(new_size=target_size)
                        if hasattr(clip, "resized")
                        else clip.resize(newsize=target_size)
                    )
                clips.append(clip)

            final_clip = concatenate_videoclips(clips, method="compose")
            total_duration = float(final_clip.duration)

            if audio_path is not None and self.config.audio_mode == AudioMode.BULLETIN:
                audio_clip = AudioFileClip(str(audio_path))
                if self.config.trim_audio_to_video and audio_clip.duration > total_duration:
                    audio_clip = (
                        audio_clip.subclipped(0, total_duration)
                        if hasattr(audio_clip, "subclipped")
                        else audio_clip.subclip(0, total_duration)
                    )
                final_clip = (
                    final_clip.with_audio(audio_clip)
                    if hasattr(final_clip, "with_audio")
                    else final_clip.set_audio(audio_clip)
                )

            kwargs = {
                "fps": self.config.fps,
                "codec": self.config.codec.value,
                "audio_codec": self.config.audio_codec,
                "preset": self.config.preset,
                "bitrate": self.config.bitrate,
                "logger": self.config.logger,
                "ffmpeg_params": ["-pix_fmt", self.config.pixel_format],
            }
            if self.config.threads is not None:
                kwargs["threads"] = self.config.threads
            if audio_path is None:
                kwargs["audio"] = False

            final_clip.write_videofile(str(target), **kwargs)
            return round(total_duration, 2)
        finally:
            if final_clip is not None:
                final_clip.close()
            if audio_clip is not None:
                audio_clip.close()
            for clip in clips:
                clip.close()

    def _validate_scenes(self, scenes: Sequence[VideoSceneInput]) -> None:
        if not scenes:
            raise ValueError("No scenes were provided.")
        previous_order = 0
        for scene in scenes:
            if scene.order <= previous_order:
                raise ValueError("Scene order must be strictly increasing.")
            if scene.duration_seconds <= 0:
                raise ValueError(f"Invalid duration for scene {scene.scene_id}.")
            if not scene.image_path.exists():
                raise FileNotFoundError(f"Scene image not found: {scene.image_path}")
            previous_order = scene.order

    def _output_path(self, bulletin_id: str, output_path: str | Path | None) -> Path:
        if output_path:
            path = Path(output_path)
            return path if path.suffix else path.with_suffix(".mp4")
        return (
            self.config.output_dir
            / _slugify(bulletin_id)
            / self.config.output_filename
        )

    def write_manifest(self, result: VideoRenderResult) -> Path:
        if result.manifest_path is None:
            raise ValueError("Manifest path is not configured.")
        result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        result.manifest_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result.manifest_path

    def summarize(self, results: Sequence[VideoRenderResult]) -> VideoComposerSummary:
        return VideoComposerSummary.from_results(results)


def compose_video(
    *,
    bulletin_id: str,
    scenes: Iterable[Any],
    bulletin_audio_path: str | Path | None = None,
    output_path: str | Path | None = None,
    config: VideoComposerConfig | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> VideoRenderResult:
    return VideoComposer(config).compose(
        bulletin_id=bulletin_id,
        scenes=scenes,
        bulletin_audio_path=bulletin_audio_path,
        output_path=output_path,
        metadata=metadata,
    )


def _make_frame(path: Path, text: str, background: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (640, 360), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 620, 340), outline=(255, 255, 255), width=4)
    draw.text((220, 165), text, fill=(255, 255, 255))
    image.save(path)


def _run_self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="bahuvu_video_test_") as temp_dir:
        root = Path(temp_dir)
        frame_one = root / "001.png"
        frame_two = root / "002.png"
        _make_frame(frame_one, "INTRO", (20, 40, 80))
        _make_frame(frame_two, "STORY", (90, 30, 30))

        composer = VideoComposer(
            VideoComposerConfig(
                output_dir=root / "video",
                output_filename="self_test.mp4",
                width=640,
                height=360,
                fps=12,
                bitrate="800k",
                preset="ultrafast",
                include_audio=False,
                audio_mode=AudioMode.NONE,
                logger=None,
            )
        )

        scenes = [
            VideoSceneInput("intro", 1, frame_one, 0.5, 0.0, 0.5, scene_type="intro"),
            VideoSceneInput("story", 2, frame_two, 0.5, 0.5, 1.0, scene_type="headline"),
        ]

        result = composer.compose(
            bulletin_id="bahuvu_video_demo",
            scenes=scenes,
            metadata={"edition": "self-test"},
        )

        assert result.success, result.error
        assert result.output_path and result.output_path.exists()
        assert result.output_path.stat().st_size > 0
        assert result.manifest_path and result.manifest_path.exists()
        assert result.scene_count == 2
        assert result.duration_seconds >= 1.0
        assert result.width == 640 and result.height == 360
        assert result.fps == 12
        assert not result.audio_included

        loaded = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        assert loaded["status"] == "rendered"
        assert loaded["success"] is True

        summary = composer.summarize([result])
        assert summary.renders_succeeded == 1
        assert summary.total_bytes > 0

        print("Video composer initialized successfully.")
        print()
        print(f"Scenes composed         : {result.scene_count}")
        print(f"Video duration          : {result.duration_seconds:.2f} seconds")
        print(f"Resolution              : {result.width}x{result.height}")
        print(f"Frame rate              : {result.fps} FPS")
        print(f"Audio included          : {result.audio_included}")
        print(f"Manifest written        : {result.manifest_path.exists()}")
        print(f"Output created          : {result.output_path.exists()}")
        print()
        print("Video composer self-test passed.")


if __name__ == "__main__":
    _run_self_test()