"""
BahuvuNewsAI - Visual and Video Reliability

Guarantees every scene has a usable visual, validates Telugu text layout,
detects blank or nearly blank rendered frames, and samples the final video
before release.

Run:
    python -m py_compile production/visual_quality.py
    python -m production.visual_quality
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Mapping, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat


MODULE_NAME = "BahuvuNewsAI Visual and Video Reliability"
MODULE_VERSION = "1.0.0"


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


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value)


def _scene_type(scene: Any) -> str:
    value = getattr(scene, "scene_type", "")
    if hasattr(value, "value"):
        value = value.value
    return _safe_text(value).lower()


def _status_value(value: Any) -> str:
    if hasattr(value, "value"):
        value = value.value
    return _safe_text(value).lower()


def _load_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        [
            "C:/Windows/Fonts/NirmalaB.ttf",
            "C:/Windows/Fonts/gautamib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ]
        if bold
        else [
            "C:/Windows/Fonts/Nirmala.ttf",
            "C:/Windows/Fonts/gautami.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _telugu_ratio(text: str) -> float:
    letters = [character for character in text if character.isalpha()]
    if not letters:
        return 1.0
    telugu = sum(1 for character in letters if "\u0C00" <= character <= "\u0C7F")
    return telugu / len(letters)


@dataclass(slots=True)
class VisualQualityPolicy:
    width: int = 1280
    height: int = 720
    fallback_dir: Path = Path("assets/generated")
    fallback_filename: str = "bahuvu_newsroom_fallback.png"
    minimum_file_bytes: int = 1500
    minimum_luminance_stddev: float = 3.0
    maximum_single_tone_ratio: float = 0.985
    minimum_telugu_ratio: float = 0.55
    headline_max_lines: int = 4
    summary_max_lines: int = 7
    final_video_sample_count: int = 9
    frame_blank_tolerance: int = 0

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Visual dimensions must be positive.")
        if self.minimum_file_bytes <= 0:
            raise ValueError("Minimum file size must be positive.")
        if not 0 <= self.maximum_single_tone_ratio <= 1:
            raise ValueError("Single-tone ratio must be between zero and one.")
        if self.final_video_sample_count < 3:
            raise ValueError("At least three final-video samples are required.")


@dataclass(slots=True)
class FrameInspection:
    path: str
    width: int
    height: int
    file_size_bytes: int
    luminance_stddev: float
    single_tone_ratio: float
    blank: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class VisualQualityReport:
    bulletin_id: str
    scene_count: int
    fallback_assignments: int
    frames_checked: int
    blank_frames: int
    text_warnings: list[str] = field(default_factory=list)
    frame_warnings: list[str] = field(default_factory=list)
    production_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VisualQualityError(RuntimeError):
    pass


def ensure_brand_fallback(
    policy: VisualQualityPolicy | None = None,
) -> Path:
    policy = policy or VisualQualityPolicy()
    policy.validate()

    target = policy.fallback_dir / policy.fallback_filename
    if target.exists() and target.stat().st_size >= policy.minimum_file_bytes:
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (policy.width, policy.height), (15, 23, 42))
    draw = ImageDraw.Draw(image)

    # Layered newsroom background; deliberately non-uniform so it can never
    # be mistaken for a blank frame.
    draw.rectangle((0, 0, policy.width, 84), fill=(9, 14, 28))
    draw.rectangle(
        (0, policy.height - 72, policy.width, policy.height),
        fill=(9, 14, 28),
    )
    draw.rectangle((0, 84, 18, policy.height - 72), fill=(220, 38, 38))
    draw.rectangle(
        (policy.width - 18, 84, policy.width, policy.height - 72),
        fill=(220, 38, 38),
    )

    for offset in range(-policy.height, policy.width, 160):
        draw.polygon(
            [
                (offset, policy.height),
                (offset + 90, policy.height),
                (offset + policy.height + 90, 84),
                (offset + policy.height, 84),
            ],
            fill=(21, 31, 52),
        )

    panel = (110, 160, policy.width - 110, policy.height - 150)
    draw.rounded_rectangle(
        panel,
        radius=34,
        fill=(30, 41, 59),
        outline=(71, 85, 105),
        width=3,
    )

    brand_font = _load_font(72, bold=True)
    telugu_font = _load_font(38, bold=True)
    small_font = _load_font(26)

    brand = "BAHUVU NEWS"
    bbox = draw.textbbox((0, 0), brand, font=brand_font)
    brand_x = (policy.width - (bbox[2] - bbox[0])) // 2
    draw.text((brand_x, 242), brand, font=brand_font, fill=(248, 250, 252))

    draw.rectangle(
        (policy.width // 2 - 170, 345, policy.width // 2 + 170, 357),
        fill=(220, 38, 38),
    )

    telugu = "బాహువు న్యూస్"
    bbox = draw.textbbox((0, 0), telugu, font=telugu_font)
    telugu_x = (policy.width - (bbox[2] - bbox[0])) // 2
    draw.text((telugu_x, 390), telugu, font=telugu_font, fill=(248, 250, 252))

    footer = "విశ్వసనీయ సమాచారం • తెలుగు వార్తలు"
    bbox = draw.textbbox((0, 0), footer, font=small_font)
    footer_x = (policy.width - (bbox[2] - bbox[0])) // 2
    draw.text((footer_x, 500), footer, font=small_font, fill=(203, 213, 225))

    image.save(target, format="PNG")
    if not target.exists() or target.stat().st_size < policy.minimum_file_bytes:
        raise VisualQualityError("Unable to create branded fallback visual.")
    return target


def _text_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _wrap_count(
    text: str,
    *,
    font: ImageFont.ImageFont,
    max_width: int,
) -> int:
    clean = re.sub(r"\s+", " ", text.strip())
    if not clean:
        return 0
    canvas = Image.new("RGB", (32, 32))
    draw = ImageDraw.Draw(canvas)
    lines = 1
    current = ""
    for word in clean.split(" "):
        candidate = f"{current} {word}".strip()
        if current and _text_width(draw, candidate, font) > max_width:
            lines += 1
            current = word
        else:
            current = candidate
    return lines


def prepare_timeline_visuals(
    timeline: Any,
    *,
    policy: VisualQualityPolicy | None = None,
) -> VisualQualityReport:
    policy = policy or VisualQualityPolicy()
    policy.validate()
    fallback = ensure_brand_fallback(policy)

    scenes = list(getattr(timeline, "scenes", []) or [])
    if not scenes:
        raise VisualQualityError("Scene timeline is empty.")

    fallback_assignments = 0
    text_warnings: list[str] = []
    headline_font = _load_font(68, bold=True)
    summary_font = _load_font(34)

    for scene in scenes:
        kind = _scene_type(scene)
        headline = _safe_text(getattr(scene, "headline", "")).strip()
        summary = _safe_text(getattr(scene, "summary", "")).strip()
        metadata = dict(getattr(scene, "metadata", {}) or {})

        if kind in {"photo", "map"}:
            current = _safe_text(getattr(scene, "image_path", "")).strip()
            current_path = Path(current) if current else None
            if (
                current_path is None
                or not current_path.exists()
                or not current_path.is_file()
                or current_path.stat().st_size <= 0
            ):
                directed_fallback = _safe_text(
                    metadata.get("fallback_visual") or ""
                ).strip()
                directed_path = (
                    Path(directed_fallback) if directed_fallback else None
                )
                if (
                    directed_path is not None
                    and directed_path.exists()
                    and directed_path.is_file()
                    and directed_path.stat().st_size > 0
                ):
                    resolved = directed_path
                    source = "directed_fallback"
                else:
                    resolved = fallback
                    source = "brand_fallback"

                scene.image_path = str(resolved)
                metadata["visual_fallback_used"] = True
                metadata["visual_fallback_source"] = source
                fallback_assignments += 1

        if headline:
            headline_lines = _wrap_count(
                headline,
                font=headline_font,
                max_width=policy.width - 160,
            )
            if headline_lines > policy.headline_max_lines:
                text_warnings.append(
                    f"{getattr(scene, 'scene_id', 'scene')}: "
                    f"headline requires {headline_lines} lines"
                )
            if _telugu_ratio(headline) < policy.minimum_telugu_ratio:
                text_warnings.append(
                    f"{getattr(scene, 'scene_id', 'scene')}: "
                    "headline contains excessive non-Telugu text"
                )

        if summary:
            summary_lines = _wrap_count(
                summary,
                font=summary_font,
                max_width=policy.width - 160,
            )
            if summary_lines > policy.summary_max_lines:
                text_warnings.append(
                    f"{getattr(scene, 'scene_id', 'scene')}: "
                    f"summary requires {summary_lines} lines"
                )

        metadata["visual_quality_prepared"] = True
        metadata["visual_quality_fallback"] = str(fallback)
        scene.metadata = metadata

    timeline_metadata = dict(getattr(timeline, "metadata", {}) or {})
    timeline_metadata["visual_quality"] = {
        "fallback_path": str(fallback),
        "fallback_assignments": fallback_assignments,
        "text_warnings": list(text_warnings),
    }
    timeline.metadata = timeline_metadata

    return VisualQualityReport(
        bulletin_id=_safe_text(getattr(timeline, "bulletin_id", "")),
        scene_count=len(scenes),
        fallback_assignments=fallback_assignments,
        frames_checked=0,
        blank_frames=0,
        text_warnings=text_warnings,
        production_ready=not text_warnings,
    )


def inspect_frame(
    path: str | Path,
    *,
    policy: VisualQualityPolicy | None = None,
) -> FrameInspection:
    policy = policy or VisualQualityPolicy()
    policy.validate()
    frame_path = Path(path)

    reasons: list[str] = []
    if not frame_path.exists():
        return FrameInspection(
            path=str(frame_path),
            width=0,
            height=0,
            file_size_bytes=0,
            luminance_stddev=0.0,
            single_tone_ratio=1.0,
            blank=True,
            reasons=["file is missing"],
        )

    size = frame_path.stat().st_size
    if size < policy.minimum_file_bytes:
        reasons.append("file is unusually small")

    with Image.open(frame_path) as source:
        image = source.convert("RGB")
        width, height = image.size
        if (width, height) != (policy.width, policy.height):
            reasons.append(
                f"unexpected dimensions {width}x{height}"
            )

        grayscale = image.convert("L")
        stat = ImageStat.Stat(grayscale)
        stddev = float(stat.stddev[0])

        reduced = image.resize((64, 36), Image.Resampling.BILINEAR)
        colors = reduced.getcolors(maxcolors=64 * 36)
        if colors:
            dominant = max(count for count, _ in colors)
            single_tone_ratio = dominant / (64 * 36)
        else:
            single_tone_ratio = 0.0

        if stddev < policy.minimum_luminance_stddev:
            reasons.append("frame has almost no visual variation")
        if single_tone_ratio > policy.maximum_single_tone_ratio:
            reasons.append("frame is dominated by one flat tone")

    return FrameInspection(
        path=str(frame_path),
        width=width,
        height=height,
        file_size_bytes=size,
        luminance_stddev=round(stddev, 3),
        single_tone_ratio=round(single_tone_ratio, 5),
        blank=bool(reasons),
        reasons=reasons,
    )


def validate_graphics_manifest(
    graphics_manifest: Any,
    *,
    timeline: Any | None = None,
    policy: VisualQualityPolicy | None = None,
) -> VisualQualityReport:
    policy = policy or VisualQualityPolicy()
    policy.validate()

    manifest = _mapping(graphics_manifest)
    status_ready = bool(
        manifest.get("production_ready")
        if "production_ready" in manifest
        else getattr(graphics_manifest, "production_ready", False)
    )
    scenes = (
        list(getattr(graphics_manifest, "scenes", []) or [])
        if hasattr(graphics_manifest, "scenes")
        else list(manifest.get("scenes") or [])
    )
    if not scenes:
        raise VisualQualityError("Graphics manifest contains no scenes.")

    failures: list[str] = []
    inspections: list[FrameInspection] = []

    for item in scenes:
        data = _mapping(item)
        status = _status_value(data.get("status"))
        output = data.get("output_path")
        scene_id = _safe_text(data.get("scene_id") or "scene")

        if status not in {"ready", "skipped"} or not output:
            failures.append(
                f"{scene_id}: graphics status is {status or 'unknown'}"
            )
            continue

        inspection = inspect_frame(output, policy=policy)
        inspections.append(inspection)
        if inspection.blank:
            failures.append(
                f"{scene_id}: " + ", ".join(inspection.reasons)
            )

    expected_count = (
        len(getattr(timeline, "scenes", []) or [])
        if timeline is not None
        else int(manifest.get("scene_count") or len(scenes))
    )
    if len(scenes) != expected_count:
        failures.append(
            f"graphics count {len(scenes)} does not match timeline "
            f"count {expected_count}"
        )

    if not status_ready:
        failures.append("graphics manifest is not production-ready")

    if failures:
        raise VisualQualityError(
            "Visual quality gate failed: " + " | ".join(failures[:20])
        )

    previous = (
        _mapping(getattr(timeline, "metadata", {}))
        .get("visual_quality", {})
        if timeline is not None
        else {}
    )
    text_warnings = list(previous.get("text_warnings") or [])

    return VisualQualityReport(
        bulletin_id=_safe_text(
            manifest.get("bulletin_id")
            or getattr(graphics_manifest, "bulletin_id", "")
        ),
        scene_count=expected_count,
        fallback_assignments=int(
            previous.get("fallback_assignments") or 0
        ),
        frames_checked=len(inspections),
        blank_frames=0,
        text_warnings=text_warnings,
        production_ready=True,
    )


def _probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise VisualQualityError("FFprobe is required for final video QA.")

    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise VisualQualityError(
            completed.stderr.strip() or "Unable to probe final video."
        )
    try:
        duration = float(completed.stdout.strip())
    except ValueError as exc:
        raise VisualQualityError("Invalid final video duration.") from exc
    if duration <= 0:
        raise VisualQualityError("Final video duration is not positive.")
    return duration


def validate_final_video_frames(
    video_result: Any,
    *,
    policy: VisualQualityPolicy | None = None,
) -> dict[str, Any]:
    policy = policy or VisualQualityPolicy()
    policy.validate()

    result = _mapping(video_result)
    status = _status_value(result.get("status"))
    output = result.get("output_path")
    if status != "rendered" or not output:
        raise VisualQualityError(
            "Final video was not rendered successfully."
        )

    video_path = Path(str(output))
    if not video_path.exists() or video_path.stat().st_size <= 0:
        raise VisualQualityError("Final video file is missing or empty.")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VisualQualityError("FFmpeg is required for final frame QA.")

    duration = _probe_duration(video_path)
    sample_count = policy.final_video_sample_count
    # Avoid exact first/last frame because encoder fades can legitimately be dark.
    timestamps = [
        duration * (index + 1) / (sample_count + 1)
        for index in range(sample_count)
    ]

    inspections: list[FrameInspection] = []
    with tempfile.TemporaryDirectory(
        prefix="bahuvu_video_frames_"
    ) as temp_dir:
        root = Path(temp_dir)
        for index, timestamp in enumerate(timestamps, start=1):
            target = root / f"sample_{index:03d}.png"
            completed = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale={policy.width}:{policy.height}",
                    str(target),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0 or not target.exists():
                raise VisualQualityError(
                    f"Unable to sample final video at {timestamp:.3f}s."
                )
            inspections.append(inspect_frame(target, policy=policy))

    blank = [
        inspection
        for inspection in inspections
        if inspection.blank
    ]
    if len(blank) > policy.frame_blank_tolerance:
        details = [
            f"{Path(item.path).name}: {', '.join(item.reasons)}"
            for item in blank
        ]
        raise VisualQualityError(
            "Final video contains blank or unusable sampled frames: "
            + " | ".join(details[:10])
        )

    return {
        "video_path": str(video_path),
        "duration_seconds": round(duration, 3),
        "samples_checked": len(inspections),
        "blank_samples": len(blank),
        "production_ready": True,
    }


def _self_test() -> None:
    from dataclasses import dataclass
    from enum import Enum

    class Kind(str, Enum):
        HEADLINE = "headline"
        PHOTO = "photo"
        SUMMARY = "summary"

    @dataclass
    class Scene:
        scene_id: str
        scene_type: Kind
        image_path: str
        headline: str
        summary: str
        metadata: dict[str, Any]

    @dataclass
    class Timeline:
        bulletin_id: str
        scenes: list[Scene]
        metadata: dict[str, Any]

    with tempfile.TemporaryDirectory(
        prefix="bahuvu_visual_test_"
    ) as temp_dir:
        root = Path(temp_dir)
        policy = VisualQualityPolicy(
            fallback_dir=root / "assets",
            minimum_file_bytes=500,
        )
        timeline = Timeline(
            bulletin_id="visual_test",
            metadata={},
            scenes=[
                Scene(
                    scene_id="headline",
                    scene_type=Kind.HEADLINE,
                    image_path="",
                    headline="ఆంధ్రప్రదేశ్‌లో భారీ వర్షాల హెచ్చరిక",
                    summary="",
                    metadata={},
                ),
                Scene(
                    scene_id="photo",
                    scene_type=Kind.PHOTO,
                    image_path=str(root / "missing.jpg"),
                    headline="ఆంధ్రప్రదేశ్‌లో భారీ వర్షాల హెచ్చరిక",
                    summary="పలు జిల్లాల్లో అధికారులు అప్రమత్తమయ్యారు.",
                    metadata={},
                ),
                Scene(
                    scene_id="summary",
                    scene_type=Kind.SUMMARY,
                    image_path="",
                    headline="ఆంధ్రప్రదేశ్‌లో భారీ వర్షాల హెచ్చరిక",
                    summary="పలు జిల్లాల్లో అధికారులు అప్రమత్తమయ్యారు.",
                    metadata={},
                ),
            ],
        )

        report = prepare_timeline_visuals(
            timeline,
            policy=policy,
        )
        assert report.fallback_assignments == 1
        fallback = Path(timeline.scenes[1].image_path)
        assert fallback.exists()

        inspection = inspect_frame(fallback, policy=policy)
        assert not inspection.blank
        assert inspection.width == 1280
        assert inspection.height == 720

        print(MODULE_NAME)
        print(f"Module version       : {MODULE_VERSION}")
        print(f"Scenes prepared      : {report.scene_count}")
        print(f"Fallback assignments : {report.fallback_assignments}")
        print(f"Fallback frame blank : {inspection.blank}")
        print(f"Fallback dimensions  : {inspection.width}x{inspection.height}")
        print("Visual and Video Reliability self-test passed.")


if __name__ == "__main__":
    _self_test()