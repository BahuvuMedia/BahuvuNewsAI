"""
BahuvuNewsAI - Controlled End-to-End Render Test
================================================

Runs one prepared Telugu story through the real media-production stages:

    prepared Telugu story
        -> audio
        -> scene timeline
        -> graphics
        -> final MP4
        -> thumbnail
        -> production manifest

YouTube upload is always disabled.

Default behaviour attempts real Telugu Edge TTS. If the TTS service is
unavailable, the test automatically creates a short local fallback WAV so the
graphics/video integration can still be verified.

Run:

    python -m py_compile production/render_test.py
    python -m production.render_test

Force offline mode:

    python -m production.render_test --offline

Open the generated video:

    start outputs\\production\\bahuvu_render_test\\bahuvu_render_test.mp4
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import struct
import sys
import wave
from typing import Any

from graphics.graphics_renderer import GraphicsRenderer, GraphicsRendererConfig
from graphics.scene_builder import SceneBuilder, SceneBuilderConfig
from production.pipeline import (
    PipelineStage,
    ProductionConfig,
    ProductionMode,
    ProductionPipeline,
    ProductionRequest,
)
from thumbnail.thumbnail_generator import (
    ThumbnailConfig,
    ThumbnailGenerator,
    ThumbnailInput,
)
from video.video_composer import (
    AudioMode,
    VideoComposer,
    VideoComposerConfig,
)
from voice.tts_generator import (
    NarrationInput,
    TeluguTTSGenerator,
    TTSConfig,
    TTSStatus,
)


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass(slots=True)
class RenderTestPaths:
    root: Path
    audio: Path
    scenes: Path
    graphics: Path
    video: Path
    thumbnail: Path
    manifest: Path

    @classmethod
    def build(
        cls,
        root: Path = Path("outputs/production/bahuvu_render_test"),
    ) -> "RenderTestPaths":
        return cls(
            root=root,
            audio=root / "audio",
            scenes=root / "scenes",
            graphics=root / "graphics",
            video=root / "bahuvu_render_test.mp4",
            thumbnail=root / "bahuvu_render_test_thumbnail.png",
            manifest=root / "production_manifest.json",
        )

    def create(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.audio.mkdir(parents=True, exist_ok=True)
        self.scenes.mkdir(parents=True, exist_ok=True)
        self.graphics.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class RenderTestAudio:
    bulletin_audio_path: Path
    story_id: str
    duration_seconds: float
    bytes_written: int
    real_tts: bool
    warning: str = ""
    stories: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bulletin_audio_path": str(self.bulletin_audio_path),
            "story_id": self.story_id,
            "duration_seconds": self.duration_seconds,
            "bytes_written": self.bytes_written,
            "real_tts": self.real_tts,
            "warning": self.warning,
            "stories": list(self.stories),
        }


# =============================================================================
# SAMPLE STORY
# =============================================================================


def prepared_telugu_story() -> dict[str, Any]:
    return {
        "story_id": "render_test_weather",
        "order": 1,
        "headline": "ఆంధ్రప్రదేశ్ తీర ప్రాంతాలకు భారీ వర్ష హెచ్చరిక",
        "summary": (
            "భారత వాతావరణ శాఖ ఆంధ్రప్రదేశ్ తీర ప్రాంత జిల్లాలకు "
            "భారీ వర్ష సూచన జారీ చేసింది. లోతట్టు ప్రాంతాల ప్రజలు "
            "అప్రమత్తంగా ఉండాలని అధికారులు సూచించారు."
        ),
        "body": (
            "భారత వాతావరణ శాఖ ఆంధ్రప్రదేశ్ తీర ప్రాంత జిల్లాలకు "
            "భారీ వర్ష సూచన జారీ చేసింది. రాబోయే ఇరవై నాలుగు గంటల్లో "
            "కొన్ని ప్రాంతాల్లో భారీ నుంచి అతి భారీ వర్షాలు కురిసే "
            "అవకాశం ఉందని తెలిపింది. లోతట్టు ప్రాంతాల ప్రజలు అప్రమత్తంగా "
            "ఉండాలని, వరద నీరు ఉన్న రహదారులపై ప్రయాణించవద్దని అధికారులు "
            "సూచించారు."
        ),
        "closing": (
            "అధికారిక సమాచారం అందిన వెంటనే బాహువు న్యూస్ మరిన్ని "
            "వివరాలను అందిస్తుంది."
        ),
        "category": "WEATHER",
        "language": "te",
        "image_path": "assets/images/sample.jpg",
        "metadata": {
            "source": "controlled render test",
            "production_safe": True,
        },
    }


# =============================================================================
# AUDIO HELPERS
# =============================================================================


def _create_fallback_wav(
    output_path: Path,
    duration_seconds: float = 8.0,
    sample_rate: int = 24000,
) -> Path:
    """
    Create a quiet test tone using only the Python standard library.

    It is deliberately low-volume and exists only to validate audio/video
    synchronization when network TTS is unavailable.
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = int(duration_seconds * sample_rate)
    frequency = 220.0
    amplitude = 750

    with wave.open(str(output_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)

        frames = bytearray()
        for index in range(frame_count):
            envelope = min(
                1.0,
                index / max(1, sample_rate // 4),
                (frame_count - index) / max(1, sample_rate // 4),
            )
            sample = int(
                amplitude
                * max(0.0, envelope)
                * math.sin(
                    2.0
                    * math.pi
                    * frequency
                    * index
                    / sample_rate
                )
            )
            frames.extend(struct.pack("<h", sample))

        audio.writeframes(bytes(frames))

    return output_path


def _generate_audio(
    story: dict[str, Any],
    paths: RenderTestPaths,
    *,
    force_offline: bool,
) -> RenderTestAudio:
    narration_text = "\n\n".join(
        [
            story["headline"],
            story["body"],
            story["closing"],
        ]
    )

    if not force_offline:
        tts = TeluguTTSGenerator(
            TTSConfig(
                output_dir=paths.audio,
                overwrite=True,
                retries=2,
                retry_delay_seconds=1.0,
                split_long_text=True,
            )
        )

        result = tts.generate(
            NarrationInput(
                text=narration_text,
                story_id=story["story_id"],
                title=story["headline"],
                language="te",
                filename_stem="render_test_telugu_narration",
            ),
            output_path=paths.audio / "render_test_telugu_narration.mp3",
        )

        if (
            result.status == TTSStatus.GENERATED
            and result.artifact is not None
            and result.artifact.path.exists()
        ):
            duration = result.artifact.duration_seconds or 20.0
            story_item = {
                "story_id": story["story_id"],
                "order": story["order"],
                "title": story["headline"],
                "status": "ready",
                "audio_path": str(result.artifact.path),
                "duration_seconds": duration,
                "bytes_written": result.artifact.bytes_written,
            }
            return RenderTestAudio(
                bulletin_audio_path=result.artifact.path,
                story_id=story["story_id"],
                duration_seconds=duration,
                bytes_written=result.artifact.bytes_written,
                real_tts=True,
                stories=[story_item],
            )

        warning = (
            result.error
            or "Real Telugu TTS was unavailable; local fallback audio used."
        )
    else:
        warning = "Offline mode requested; local fallback audio used."

    fallback_path = _create_fallback_wav(
        paths.audio / "render_test_fallback.wav",
        duration_seconds=10.0,
    )
    story_item = {
        "story_id": story["story_id"],
        "order": story["order"],
        "title": story["headline"],
        "status": "ready",
        "audio_path": str(fallback_path),
        "duration_seconds": 10.0,
        "bytes_written": fallback_path.stat().st_size,
    }

    return RenderTestAudio(
        bulletin_audio_path=fallback_path,
        story_id=story["story_id"],
        duration_seconds=10.0,
        bytes_written=fallback_path.stat().st_size,
        real_tts=False,
        warning=warning,
        stories=[story_item],
    )


# =============================================================================
# PIPELINE HANDLERS
# =============================================================================


def build_render_test_handlers(
    paths: RenderTestPaths,
    *,
    force_offline: bool,
) -> dict[PipelineStage, Any]:
    def intake(
        context: dict[str, Any],
        request: ProductionRequest,
    ) -> list[dict[str, Any]]:
        stories = list(request.stories)
        if not stories:
            raise ValueError("Controlled render test requires one story.")
        return stories

    def pass_previous(stage: PipelineStage):
        previous_order = list(ProductionPipeline.STAGE_ORDER)
        index = previous_order.index(stage)
        previous_stage = previous_order[index - 1]

        def handler(
            context: dict[str, Any],
            request: ProductionRequest,
        ) -> Any:
            return context[previous_stage.value]

        return handler

    def audio(
        context: dict[str, Any],
        request: ProductionRequest,
    ) -> RenderTestAudio:
        story = context[PipelineStage.TRANSLATE.value][0]
        return _generate_audio(
            story,
            paths,
            force_offline=force_offline,
        )

    def scenes(
        context: dict[str, Any],
        request: ProductionRequest,
    ) -> Any:
        story = dict(context[PipelineStage.TRANSLATE.value][0])
        audio_result: RenderTestAudio = context[
            PipelineStage.AUDIO.value
        ]

        story["audio_path"] = str(audio_result.bulletin_audio_path)
        story["audio_duration_seconds"] = (
            audio_result.duration_seconds
        )

        builder = SceneBuilder(
            SceneBuilderConfig(
                output_dir=paths.scenes,
                write_manifest=True,
                intro_duration_seconds=3.0,
                outro_duration_seconds=3.0,
                headline_duration_seconds=4.0,
                photo_duration_seconds=5.0,
                summary_minimum_duration_seconds=6.0,
                transition_duration_seconds=0.75,
            )
        )
        return builder.build_timeline(
            bulletin_id=request.bulletin_id,
            stories=[story],
            metadata=dict(request.metadata),
        )

    def graphics(
        context: dict[str, Any],
        request: ProductionRequest,
    ) -> Any:
        timeline = context[PipelineStage.SCENES.value]
        renderer = GraphicsRenderer(
            GraphicsRendererConfig(
                output_dir=paths.graphics,
                overwrite=True,
                write_manifest=True,
                fallback_image_path="assets/images/sample.jpg",
            )
        )
        return renderer.render_timeline(timeline)

    def video(
        context: dict[str, Any],
        request: ProductionRequest,
    ) -> Any:
        timeline = context[PipelineStage.SCENES.value]
        graphics_manifest = context[
            PipelineStage.GRAPHICS.value
        ]
        audio_result: RenderTestAudio = context[
            PipelineStage.AUDIO.value
        ]

        composer = VideoComposer(
            VideoComposerConfig(
                output_dir=paths.root,
                output_filename=paths.video.name,
                manifest_filename="video_manifest.json",
                width=1280,
                height=720,
                fps=24,
                include_audio=True,
                audio_mode=AudioMode.BULLETIN,
                overwrite=True,
                write_manifest=True,
                preset="ultrafast",
                bitrate="2500k",
                logger=None,
            )
        )

        return composer.compose_from_manifests(
            timeline=timeline,
            graphics_manifest=graphics_manifest,
            bulletin_audio_path=audio_result.bulletin_audio_path,
            output_path=paths.video,
            metadata=dict(request.metadata),
        )

    def thumbnail(
        context: dict[str, Any],
        request: ProductionRequest,
    ) -> Any:
        story = context[PipelineStage.TRANSLATE.value][0]
        generator = ThumbnailGenerator(
            ThumbnailConfig(
                output_dir=paths.root,
                output_filename=paths.thumbnail.name,
                manifest_filename="thumbnail_manifest.json",
                overwrite=True,
                write_manifest=True,
                fallback_image_path="assets/images/sample.jpg",
            )
        )

        return generator.generate(
            ThumbnailInput(
                headline=story["headline"],
                category=story["category"],
                image_path=story["image_path"],
                bulletin_id=request.bulletin_id,
                story_id=story["story_id"],
                subheadline=story["summary"],
                metadata=dict(request.metadata),
            ),
            output_path=paths.thumbnail,
        )

    return {
        PipelineStage.INTAKE: intake,
        PipelineStage.EDITORIAL: pass_previous(
            PipelineStage.EDITORIAL
        ),
        PipelineStage.BULLETIN: pass_previous(
            PipelineStage.BULLETIN
        ),
        PipelineStage.SCRIPT: pass_previous(
            PipelineStage.SCRIPT
        ),
        PipelineStage.POLISH: pass_previous(
            PipelineStage.POLISH
        ),
        PipelineStage.TRANSLATE: pass_previous(
            PipelineStage.TRANSLATE
        ),
        PipelineStage.VOICE: pass_previous(
            PipelineStage.VOICE
        ),
        PipelineStage.AUDIO: audio,
        PipelineStage.SCENES: scenes,
        PipelineStage.GRAPHICS: graphics,
        PipelineStage.VIDEO: video,
        PipelineStage.THUMBNAIL: thumbnail,
    }


# =============================================================================
# RUNNER
# =============================================================================


def run_render_test(
    *,
    force_offline: bool = False,
    output_root: Path | None = None,
) -> Any:
    paths = RenderTestPaths.build(
        output_root
        or Path("outputs/production/bahuvu_render_test")
    )
    paths.create()

    request = ProductionRequest(
        production_id="bahuvu_render_test",
        bulletin_id="bahuvu_render_test",
        mode=ProductionMode.RENDER_ONLY,
        stories=[prepared_telugu_story()],
        metadata={
            "edition": "Controlled Render Test",
            "youtube_upload": False,
        },
        stop_stage=PipelineStage.THUMBNAIL,
    )

    pipeline = ProductionPipeline(
        config=ProductionConfig(
            output_dir=paths.root.parent,
            manifest_filename=paths.manifest.name,
            continue_on_optional_failure=False,
            resume_completed_stages=False,
            write_manifest_after_each_stage=True,
        ),
        handlers=build_render_test_handlers(
            paths,
            force_offline=force_offline,
        ),
    )

    result = pipeline.run(request)

    # Ensure the expected final artifacts exist.
    video_record = next(
        item
        for item in result.stages
        if item.stage == PipelineStage.VIDEO
    )
    thumbnail_record = next(
        item
        for item in result.stages
        if item.stage == PipelineStage.THUMBNAIL
    )

    if video_record.status.value != "completed":
        raise RuntimeError(
            "Render test video stage failed: "
            f"{video_record.error}"
        )

    if thumbnail_record.status.value != "completed":
        raise RuntimeError(
            "Render test thumbnail stage failed: "
            f"{thumbnail_record.error}"
        )

    if not paths.video.exists():
        raise RuntimeError(
            f"Expected video was not created: {paths.video}"
        )

    if not paths.thumbnail.exists():
        raise RuntimeError(
            f"Expected thumbnail was not created: {paths.thumbnail}"
        )

    return result, paths


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the BahuvuNewsAI controlled render test."
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip Edge TTS and use local fallback audio.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Optional custom render-test output directory.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = _parse_arguments()
    result, paths = run_render_test(
        force_offline=arguments.offline,
        output_root=arguments.output_root,
    )

    audio_record = next(
        item
        for item in result.stages
        if item.stage == PipelineStage.AUDIO
    )
    audio_output = audio_record.output
    audio_mapping = (
        audio_output.to_dict()
        if hasattr(audio_output, "to_dict")
        else asdict(audio_output)
    )

    print("Controlled render test completed successfully.")
    print()
    print(f"Pipeline status         : {result.status.value}")
    print(f"Real Telugu TTS         : {audio_mapping['real_tts']}")
    if audio_mapping.get("warning"):
        print(f"Audio note              : {audio_mapping['warning']}")
    print(f"Audio file              : {audio_mapping['bulletin_audio_path']}")
    print(f"Scene output            : {paths.scenes}")
    print(f"Graphics output         : {paths.graphics}")
    print(f"Final video             : {paths.video}")
    print(f"Thumbnail               : {paths.thumbnail}")
    print(f"Production manifest     : {result.manifest_path}")
    print()
    print("BahuvuNewsAI controlled render test passed.")


if __name__ == "__main__":
    main()