"""
BahuvuNewsAI - Audio and Timing Reliability

Uses assembled bulletin audio as the timing authority, reconciles every scene
to measured narration duration, and blocks final video/audio mismatches.

Run:
    python -m py_compile production/audio_timing.py
    python -m production.audio_timing
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Mapping, Sequence


MODULE_NAME = "BahuvuNewsAI Audio and Timing Reliability"
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


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return list(value)
    return [value]


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _scene_type(scene: Any) -> str:
    value = getattr(scene, "scene_type", "")
    if hasattr(value, "value"):
        value = value.value
    return _safe_text(value).lower()


@dataclass(slots=True)
class TimingPolicy:
    tolerance_seconds: float = 0.15
    minimum_scene_duration_seconds: float = 0.50
    probe_assembled_audio: bool = True
    require_complete_audio: bool = True

    def validate(self) -> None:
        if self.tolerance_seconds < 0:
            raise ValueError("Timing tolerance cannot be negative.")
        if self.minimum_scene_duration_seconds <= 0:
            raise ValueError("Minimum scene duration must be positive.")


@dataclass(slots=True)
class TimingReport:
    bulletin_id: str
    story_audio_seconds: float
    silence_seconds: float
    manifest_audio_seconds: float
    measured_audio_seconds: float
    timeline_seconds: float
    difference_seconds: float
    synchronized: bool
    story_count: int
    scene_count: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AudioTimingError(RuntimeError):
    pass


def probe_media_duration(path: str | Path) -> float:
    media_path = Path(path)
    if not media_path.exists() or media_path.stat().st_size <= 0:
        raise FileNotFoundError(f"Media file is missing or empty: {media_path}")

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError(
            "FFprobe was not found in PATH; measured timing cannot be verified."
        )

    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip()
            or f"Unable to read media duration: {media_path}"
        )

    duration = _safe_float(completed.stdout.strip())
    if duration <= 0:
        raise RuntimeError(f"Invalid measured media duration: {media_path}")
    return round(duration, 3)


def validate_audio_manifest(
    audio_manifest: Any,
    *,
    policy: TimingPolicy | None = None,
) -> tuple[list[Any], float, float, Path]:
    policy = policy or TimingPolicy()
    policy.validate()

    mapping = _mapping(audio_manifest)
    stories = _as_list(
        mapping.get("stories")
        if "stories" in mapping
        else getattr(audio_manifest, "stories", None)
    )
    if not stories:
        raise AudioTimingError("Audio manifest contains no story audio items.")

    ready: list[Any] = []
    failures: list[str] = []
    story_seconds = 0.0

    for item in stories:
        item_mapping = _mapping(item)
        status_value = item_mapping.get("status")
        if hasattr(status_value, "value"):
            status_value = status_value.value
        status = _safe_text(status_value).lower()
        duration = _safe_float(item_mapping.get("duration_seconds"))
        audio_path = item_mapping.get("audio_path")
        story_id = _safe_text(item_mapping.get("story_id") or "unknown")

        if status == "ready" and duration > 0 and audio_path:
            path = Path(str(audio_path))
            if path.exists() and path.stat().st_size > 0:
                ready.append(item)
                story_seconds += duration
                continue

        failures.append(
            f"{story_id}: status={status or 'unknown'}, duration={duration:.3f}"
        )

    if not ready:
        raise AudioTimingError("No usable story audio was produced.")
    if failures and policy.require_complete_audio:
        raise AudioTimingError(
            "Bulletin audio is incomplete: " + " | ".join(failures[:20])
        )

    silence_seconds = _safe_float(
        mapping.get("silence_duration_seconds")
        or getattr(audio_manifest, "silence_duration_seconds", 0.0)
    )
    bulletin_value = (
        mapping.get("bulletin_audio_path")
        or getattr(audio_manifest, "bulletin_audio_path", None)
    )
    if not bulletin_value:
        raise AudioTimingError("Assembled bulletin audio path is missing.")

    bulletin_path = Path(str(bulletin_value))
    if not bulletin_path.exists() or bulletin_path.stat().st_size <= 0:
        raise AudioTimingError(
            f"Assembled bulletin audio is missing or empty: {bulletin_path}"
        )

    return (
        ready,
        round(story_seconds, 3),
        round(silence_seconds, 3),
        bulletin_path,
    )


def _allocate_story_durations(
    scenes: Sequence[Any],
    target_seconds: float,
    minimum_seconds: float,
) -> list[float]:
    if not scenes:
        raise AudioTimingError("Cannot time an empty story scene group.")
    if target_seconds <= 0:
        raise AudioTimingError("Story audio duration must be positive.")
    if len(scenes) == 1:
        return [round(target_seconds, 3)]

    minimum = min(
        minimum_seconds,
        target_seconds / len(scenes) / 2,
    )
    weights: list[float] = []
    for scene in scenes:
        kind = _scene_type(scene)
        if kind == "headline":
            weights.append(0.22)
        elif kind == "photo":
            weights.append(0.30)
        else:
            weights.append(1.0)

    base = minimum * len(scenes)
    distributable = max(0.0, target_seconds - base)
    total_weight = sum(weights)
    durations = [
        minimum + distributable * weight / total_weight
        for weight in weights
    ]
    rounded = [round(value, 3) for value in durations]
    rounded[-1] = round(
        rounded[-1] + target_seconds - sum(rounded),
        3,
    )
    if rounded[-1] <= 0:
        raise AudioTimingError("Unable to allocate positive scene durations.")
    return rounded


def synchronize_timeline(
    *,
    timeline: Any,
    audio_manifest: Any,
    policy: TimingPolicy | None = None,
) -> TimingReport:
    policy = policy or TimingPolicy()
    policy.validate()

    ready, story_seconds, silence_seconds, bulletin_path = (
        validate_audio_manifest(audio_manifest, policy=policy)
    )

    audio_by_story = {
        _safe_text(_mapping(item).get("story_id")): _safe_float(
            _mapping(item).get("duration_seconds")
        )
        for item in ready
    }
    ordered_story_ids = [
        _safe_text(_mapping(item).get("story_id"))
        for item in sorted(
            ready,
            key=lambda item: int(_mapping(item).get("order") or 0),
        )
    ]

    original_scenes = list(getattr(timeline, "scenes", []) or [])
    if not original_scenes:
        raise AudioTimingError("Scene timeline is empty.")

    # Intro and outro currently have no matching sound in the bulletin audio.
    retained = [
        scene
        for scene in original_scenes
        if _scene_type(scene) not in {"intro", "outro"}
    ]

    story_groups: dict[str, list[Any]] = {}
    transitions: list[Any] = []
    for scene in retained:
        kind = _scene_type(scene)
        story_id = _safe_text(getattr(scene, "story_id", ""))
        if kind == "transition":
            transitions.append(scene)
        elif story_id:
            story_groups.setdefault(story_id, []).append(scene)

    missing = [
        story_id for story_id in ordered_story_ids
        if story_id not in story_groups
    ]
    if missing:
        raise AudioTimingError(
            "No scenes were created for audio stories: "
            + ", ".join(missing)
        )

    transition_seconds = (
        silence_seconds / (len(ordered_story_ids) - 1)
        if len(ordered_story_ids) > 1
        else 0.0
    )

    rebuilt: list[Any] = []
    cursor = 0.0
    order = 1

    for story_index, story_id in enumerate(ordered_story_ids):
        group = sorted(
            story_groups[story_id],
            key=lambda scene: int(getattr(scene, "order", 0)),
        )
        durations = _allocate_story_durations(
            group,
            audio_by_story[story_id],
            policy.minimum_scene_duration_seconds,
        )

        for scene, duration in zip(group, durations):
            scene.order = order
            scene.start_time_seconds = round(cursor, 3)
            scene.duration_seconds = round(duration, 3)
            cursor = round(cursor + duration, 3)
            scene.end_time_seconds = round(cursor, 3)
            rebuilt.append(scene)
            order += 1

        if story_index < len(ordered_story_ids) - 1:
            if story_index >= len(transitions):
                raise AudioTimingError(
                    "A transition scene is required for inter-story silence."
                )
            transition = transitions[story_index]
            transition.order = order
            transition.start_time_seconds = round(cursor, 3)
            transition.duration_seconds = round(transition_seconds, 3)
            cursor = round(cursor + transition_seconds, 3)
            transition.end_time_seconds = round(cursor, 3)
            rebuilt.append(transition)
            order += 1

    manifest_seconds = _safe_float(
        _mapping(audio_manifest).get("total_duration_seconds")
        or getattr(audio_manifest, "total_duration_seconds", 0.0)
    )
    measured_seconds = manifest_seconds
    warnings: list[str] = []

    if policy.probe_assembled_audio:
        measured_seconds = probe_media_duration(bulletin_path)
        manifest_gap = abs(measured_seconds - manifest_seconds)
        if manifest_gap > policy.tolerance_seconds:
            warnings.append(
                "Measured assembled audio differs from the manifest by "
                f"{manifest_gap:.3f}s."
            )

    target_seconds = measured_seconds or manifest_seconds
    correction = round(target_seconds - cursor, 3)
    if correction:
        final_scene = rebuilt[-1]
        corrected = round(
            float(final_scene.duration_seconds) + correction,
            3,
        )
        if corrected <= 0:
            raise AudioTimingError(
                "Final timing correction would make the last scene invalid."
            )
        final_scene.duration_seconds = corrected
        final_scene.end_time_seconds = round(target_seconds, 3)
        cursor = round(target_seconds, 3)

    timeline.scenes = rebuilt
    timeline.scene_count = len(rebuilt)
    timeline.story_count = len(ordered_story_ids)
    timeline.total_duration_seconds = round(cursor, 3)

    metadata = dict(getattr(timeline, "metadata", {}) or {})
    metadata["audio_timing"] = {
        "authority": "measured_bulletin_audio",
        "manifest_audio_seconds": round(manifest_seconds, 3),
        "measured_audio_seconds": round(measured_seconds, 3),
        "timeline_seconds": round(cursor, 3),
        "tolerance_seconds": policy.tolerance_seconds,
        "intro_removed": True,
        "outro_removed": True,
        "silence_seconds": round(silence_seconds, 3),
    }
    timeline.metadata = metadata

    difference = round(abs(cursor - target_seconds), 3)
    if difference > policy.tolerance_seconds:
        raise AudioTimingError(
            f"Timeline/audio mismatch remains: {difference:.3f}s"
        )

    return TimingReport(
        bulletin_id=_safe_text(getattr(timeline, "bulletin_id", "")),
        story_audio_seconds=story_seconds,
        silence_seconds=silence_seconds,
        manifest_audio_seconds=round(manifest_seconds, 3),
        measured_audio_seconds=round(measured_seconds, 3),
        timeline_seconds=round(cursor, 3),
        difference_seconds=difference,
        synchronized=True,
        story_count=len(ordered_story_ids),
        scene_count=len(rebuilt),
        warnings=warnings,
    )


def validate_video_audio_sync(
    *,
    video_result: Any,
    audio_manifest: Any,
    policy: TimingPolicy | None = None,
) -> dict[str, Any]:
    policy = policy or TimingPolicy()
    policy.validate()

    result = _mapping(video_result)
    status_value = result.get("status")
    if hasattr(status_value, "value"):
        status_value = status_value.value
    status = _safe_text(status_value).lower()
    if status != "rendered":
        raise AudioTimingError(
            "Video rendering failed: "
            + _safe_text(result.get("error") or status or "unknown")
        )

    output_value = result.get("output_path")
    if not output_value:
        raise AudioTimingError("Rendered video path is missing.")

    video_seconds = probe_media_duration(Path(str(output_value)))
    _, _, _, bulletin_path = validate_audio_manifest(
        audio_manifest,
        policy=policy,
    )
    audio_seconds = probe_media_duration(bulletin_path)
    difference = round(abs(video_seconds - audio_seconds), 3)

    if difference > policy.tolerance_seconds:
        raise AudioTimingError(
            "Final video/audio duration mismatch: "
            f"video={video_seconds:.3f}s, audio={audio_seconds:.3f}s, "
            f"difference={difference:.3f}s"
        )

    return {
        "video_seconds": round(video_seconds, 3),
        "audio_seconds": round(audio_seconds, 3),
        "difference_seconds": difference,
        "tolerance_seconds": policy.tolerance_seconds,
        "synchronized": True,
    }


def _self_test() -> None:
    from dataclasses import dataclass
    from enum import Enum

    class Kind(str, Enum):
        INTRO = "intro"
        HEADLINE = "headline"
        SUMMARY = "summary"
        TRANSITION = "transition"
        OUTRO = "outro"

    @dataclass
    class Scene:
        scene_id: str
        story_id: str
        order: int
        scene_type: Kind
        start_time_seconds: float
        duration_seconds: float
        end_time_seconds: float

    @dataclass
    class Timeline:
        bulletin_id: str
        scenes: list[Scene]
        total_duration_seconds: float
        scene_count: int
        story_count: int
        metadata: dict[str, Any]

    with tempfile.TemporaryDirectory(prefix="bahuvu_timing_test_") as temp:
        root = Path(temp)
        one = root / "one.mp3"
        two = root / "two.mp3"
        bulletin = root / "bulletin.mp3"
        one.write_bytes(b"test")
        two.write_bytes(b"test")
        bulletin.write_bytes(b"test")

        audio_manifest = {
            "stories": [
                {
                    "story_id": "one",
                    "order": 1,
                    "status": "ready",
                    "duration_seconds": 10.0,
                    "audio_path": str(one),
                },
                {
                    "story_id": "two",
                    "order": 2,
                    "status": "ready",
                    "duration_seconds": 8.0,
                    "audio_path": str(two),
                },
            ],
            "silence_duration_seconds": 1.25,
            "total_duration_seconds": 19.25,
            "bulletin_audio_path": str(bulletin),
        }
        timeline = Timeline(
            bulletin_id="timing_test",
            total_duration_seconds=31.0,
            scene_count=7,
            story_count=2,
            metadata={},
            scenes=[
                Scene("intro", "", 1, Kind.INTRO, 0, 5, 5),
                Scene("one_h", "one", 2, Kind.HEADLINE, 5, 4, 9),
                Scene("one_s", "one", 3, Kind.SUMMARY, 9, 6, 15),
                Scene("gap", "one", 4, Kind.TRANSITION, 15, 1, 16),
                Scene("two_h", "two", 5, Kind.HEADLINE, 16, 4, 20),
                Scene("two_s", "two", 6, Kind.SUMMARY, 20, 6, 26),
                Scene("outro", "", 7, Kind.OUTRO, 26, 5, 31),
            ],
        )

        report = synchronize_timeline(
            timeline=timeline,
            audio_manifest=audio_manifest,
            policy=TimingPolicy(probe_assembled_audio=False),
        )

        assert report.synchronized
        assert timeline.total_duration_seconds == 19.25
        assert timeline.scenes[0].start_time_seconds == 0
        assert timeline.scenes[-1].end_time_seconds == 19.25
        assert all(
            _scene_type(scene) not in {"intro", "outro"}
            for scene in timeline.scenes
        )

        print(MODULE_NAME)
        print(f"Module version       : {MODULE_VERSION}")
        print(f"Stories synchronized : {report.story_count}")
        print(f"Scenes synchronized  : {report.scene_count}")
        print(f"Audio duration       : {report.manifest_audio_seconds:.2f}s")
        print(f"Timeline duration    : {report.timeline_seconds:.2f}s")
        print(f"Difference           : {report.difference_seconds:.3f}s")
        print("Audio and Timing Reliability self-test passed.")


if __name__ == "__main__":
    _self_test()