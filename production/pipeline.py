"""
BahuvuNewsAI - Master Production Pipeline
=========================================

Coordinates the complete news-production workflow from prepared stories to
YouTube upload.

Pipeline stages:

    intake
    -> editorial
    -> bulletin
    -> script
    -> polish
    -> translate
    -> voice
    -> audio
    -> scenes
    -> graphics
    -> video
    -> thumbnail
    -> upload

This module focuses on orchestration, stage tracking, failure handling,
resumability, and production manifests. Individual production logic remains in
its dedicated module.

Run:

    python -m py_compile production/pipeline.py
    python -m production.pipeline

The built-in self-test is offline-safe and uses deterministic fake stages.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import traceback
from typing import Any, Callable, Mapping, MutableMapping, Sequence


# =============================================================================
# ENUMS
# =============================================================================


class ProductionMode(str, Enum):
    DRY_RUN = "dry-run"
    RENDER_ONLY = "render-only"
    UPLOAD_PRIVATE = "upload-private"
    FULL_PRODUCTION = "full-production"


class PipelineStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class PipelineStage(str, Enum):
    INTAKE = "intake"
    EDITORIAL = "editorial"
    BULLETIN = "bulletin"
    SCRIPT = "script"
    POLISH = "polish"
    TRANSLATE = "translate"
    VOICE = "voice"
    AUDIO = "audio"
    SCENES = "scenes"
    GRAPHICS = "graphics"
    VIDEO = "video"
    THUMBNAIL = "thumbnail"
    UPLOAD = "upload"


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass(slots=True)
class ProductionConfig:
    output_dir: Path = Path("outputs/production")
    manifest_filename: str = "production_manifest.json"
    continue_on_optional_failure: bool = True
    resume_completed_stages: bool = True
    write_manifest_after_each_stage: bool = True
    upload_privacy_default: str = "private"

    def validate(self) -> None:
        if not self.manifest_filename.strip():
            raise ValueError("Manifest filename cannot be empty.")
        if self.upload_privacy_default not in {
            "private",
            "unlisted",
            "public",
        }:
            raise ValueError("Invalid default upload privacy.")


@dataclass(slots=True)
class ProductionRequest:
    production_id: str
    mode: ProductionMode = ProductionMode.DRY_RUN
    stories: list[Any] = field(default_factory=list)
    bulletin_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    resume: bool = False
    start_stage: PipelineStage | None = None
    stop_stage: PipelineStage | None = None


@dataclass(slots=True)
class StageRecord:
    stage: PipelineStage
    status: StageStatus = StageStatus.PENDING
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    output: Any = None
    output_summary: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    traceback: str = ""
    optional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "output": _json_safe(self.output),
            "output_summary": _json_safe(self.output_summary),
            "error": self.error,
            "traceback": self.traceback,
            "optional": self.optional,
        }


@dataclass(slots=True)
class ProductionResult:
    production_id: str
    mode: ProductionMode
    status: PipelineStatus
    started_at: str
    completed_at: str
    manifest_path: Path
    stages: list[StageRecord]
    final_output: Any = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == PipelineStatus.COMPLETED

    def to_dict(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "mode": self.mode.value,
            "status": self.status.value,
            "success": self.success,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "manifest_path": str(self.manifest_path),
            "final_output": _json_safe(self.final_output),
            "error": self.error,
            "metadata": _json_safe(self.metadata),
            "stages": [stage.to_dict() for stage in self.stages],
        }


@dataclass(slots=True)
class ProductionSummary:
    pipelines_processed: int = 0
    completed: int = 0
    partial: int = 0
    failed: int = 0
    stages_completed: int = 0
    stages_failed: int = 0

    @classmethod
    def from_results(
        cls,
        results: Sequence[ProductionResult],
    ) -> "ProductionSummary":
        return cls(
            pipelines_processed=len(results),
            completed=sum(
                1 for item in results
                if item.status == PipelineStatus.COMPLETED
            ),
            partial=sum(
                1 for item in results
                if item.status == PipelineStatus.PARTIAL
            ),
            failed=sum(
                1 for item in results
                if item.status == PipelineStatus.FAILED
            ),
            stages_completed=sum(
                1
                for result in results
                for stage in result.stages
                if stage.status == StageStatus.COMPLETED
            ),
            stages_failed=sum(
                1
                for result in results
                for stage in result.stages
                if stage.status == StageStatus.FAILED
            ),
        )


# =============================================================================
# HELPERS
# =============================================================================


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _duration_seconds(started: datetime, completed: datetime) -> float:
    return round((completed - started).total_seconds(), 3)


def _summarize_output(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "none"}

    summary: dict[str, Any] = {
        "type": type(value).__name__,
    }

    if isinstance(value, (list, tuple, set)):
        summary["count"] = len(value)
    elif isinstance(value, Mapping):
        summary["keys"] = list(value.keys())[:20]
    elif isinstance(value, Path):
        summary["path"] = str(value)
        summary["exists"] = value.exists()
    else:
        for attribute in (
            "status",
            "success",
            "production_ready",
            "scene_count",
            "story_count",
            "rendered_count",
            "video_id",
            "video_url",
            "output_path",
        ):
            if hasattr(value, attribute):
                summary[attribute] = _json_safe(
                    getattr(value, attribute)
                )

    return summary


# =============================================================================
# PIPELINE
# =============================================================================


StageHandler = Callable[[dict[str, Any], ProductionRequest], Any]


class ProductionPipeline:
    STAGE_ORDER: tuple[PipelineStage, ...] = (
        PipelineStage.INTAKE,
        PipelineStage.EDITORIAL,
        PipelineStage.BULLETIN,
        PipelineStage.SCRIPT,
        PipelineStage.POLISH,
        PipelineStage.TRANSLATE,
        PipelineStage.VOICE,
        PipelineStage.AUDIO,
        PipelineStage.SCENES,
        PipelineStage.GRAPHICS,
        PipelineStage.VIDEO,
        PipelineStage.THUMBNAIL,
        PipelineStage.UPLOAD,
    )

    OPTIONAL_STAGES: frozenset[PipelineStage] = frozenset(
        {
            PipelineStage.THUMBNAIL,
            PipelineStage.UPLOAD,
        }
    )

    def __init__(
        self,
        config: ProductionConfig | None = None,
        handlers: Mapping[PipelineStage, StageHandler] | None = None,
    ) -> None:
        self.config = config or ProductionConfig()
        self.config.validate()
        self.handlers: dict[PipelineStage, StageHandler] = dict(
            handlers or {}
        )

    def register_handler(
        self,
        stage: PipelineStage,
        handler: StageHandler,
    ) -> None:
        self.handlers[stage] = handler

    def run(self, request: ProductionRequest) -> ProductionResult:
        if not request.production_id.strip():
            raise ValueError("Production ID cannot be empty.")

        started_at = _utc_now()
        manifest_path = self._manifest_path(request.production_id)
        stage_records = self._initial_stage_records()

        context: dict[str, Any] = {
            "stories": list(request.stories),
            "bulletin_id": (
                request.bulletin_id
                or request.production_id
            ),
            "metadata": dict(request.metadata),
        }

        if request.resume and manifest_path.exists():
            self._restore_completed_stages(
                manifest_path,
                stage_records,
                context,
            )

        result = ProductionResult(
            production_id=request.production_id,
            mode=request.mode,
            status=PipelineStatus.RUNNING,
            started_at=started_at.isoformat(),
            completed_at="",
            manifest_path=manifest_path,
            stages=stage_records,
            metadata=dict(request.metadata),
        )
        self._write_manifest_if_enabled(result)

        selected_stages = self._selected_stages(request)

        for stage in self.STAGE_ORDER:
            record = self._record_for(stage_records, stage)

            if stage not in selected_stages:
                record.status = StageStatus.SKIPPED
                record.completed_at = _utc_now_iso()
                continue

            if (
                request.resume
                and self.config.resume_completed_stages
                and record.status == StageStatus.COMPLETED
            ):
                continue

            if not self._stage_allowed_for_mode(stage, request.mode):
                record.status = StageStatus.SKIPPED
                record.completed_at = _utc_now_iso()
                continue

            handler = self.handlers.get(stage)
            if handler is None:
                record.status = StageStatus.SKIPPED
                record.completed_at = _utc_now_iso()
                record.error = "No stage handler registered."
                if stage not in self.OPTIONAL_STAGES:
                    result.status = PipelineStatus.PARTIAL
                self._write_manifest_if_enabled(result)
                continue

            stage_started = _utc_now()
            record.status = StageStatus.RUNNING
            record.started_at = stage_started.isoformat()
            record.optional = stage in self.OPTIONAL_STAGES
            self._write_manifest_if_enabled(result)

            try:
                output = handler(context, request)
                stage_completed = _utc_now()

                record.status = StageStatus.COMPLETED
                record.completed_at = stage_completed.isoformat()
                record.duration_seconds = _duration_seconds(
                    stage_started,
                    stage_completed,
                )
                record.output = output
                record.output_summary = _summarize_output(output)
                context[stage.value] = output
                result.final_output = output

            except Exception as exc:
                stage_completed = _utc_now()
                record.status = StageStatus.FAILED
                record.completed_at = stage_completed.isoformat()
                record.duration_seconds = _duration_seconds(
                    stage_started,
                    stage_completed,
                )
                record.error = str(exc)
                record.traceback = traceback.format_exc()

                if (
                    record.optional
                    and self.config.continue_on_optional_failure
                ):
                    result.status = PipelineStatus.PARTIAL
                    self._write_manifest_if_enabled(result)
                    continue

                result.status = PipelineStatus.FAILED
                result.error = (
                    f"Stage '{stage.value}' failed: {exc}"
                )
                break

            self._write_manifest_if_enabled(result)

        completed_at = _utc_now()
        result.completed_at = completed_at.isoformat()

        if result.status == PipelineStatus.RUNNING:
            failed = any(
                stage.status == StageStatus.FAILED
                for stage in stage_records
            )
            partial = any(
                stage.status == StageStatus.SKIPPED
                and stage.stage in selected_stages
                and stage.stage not in self.OPTIONAL_STAGES
                for stage in stage_records
            )

            if failed:
                result.status = PipelineStatus.PARTIAL
            elif partial:
                result.status = PipelineStatus.PARTIAL
            else:
                result.status = PipelineStatus.COMPLETED

        self.write_manifest(result)
        return result

    def _initial_stage_records(self) -> list[StageRecord]:
        return [
            StageRecord(
                stage=stage,
                optional=stage in self.OPTIONAL_STAGES,
            )
            for stage in self.STAGE_ORDER
        ]

    def _selected_stages(
        self,
        request: ProductionRequest,
    ) -> set[PipelineStage]:
        start_index = 0
        stop_index = len(self.STAGE_ORDER) - 1

        if request.start_stage is not None:
            start_index = self.STAGE_ORDER.index(
                request.start_stage
            )

        if request.stop_stage is not None:
            stop_index = self.STAGE_ORDER.index(
                request.stop_stage
            )

        if start_index > stop_index:
            raise ValueError("Start stage occurs after stop stage.")

        return set(
            self.STAGE_ORDER[start_index : stop_index + 1]
        )

    def _stage_allowed_for_mode(
        self,
        stage: PipelineStage,
        mode: ProductionMode,
    ) -> bool:
        if mode == ProductionMode.DRY_RUN:
            return stage != PipelineStage.UPLOAD

        if mode == ProductionMode.RENDER_ONLY:
            return stage != PipelineStage.UPLOAD

        if mode in {
            ProductionMode.UPLOAD_PRIVATE,
            ProductionMode.FULL_PRODUCTION,
        }:
            return True

        return True

    def _record_for(
        self,
        records: Sequence[StageRecord],
        stage: PipelineStage,
    ) -> StageRecord:
        for record in records:
            if record.stage == stage:
                return record
        raise KeyError(stage)

    def _manifest_path(self, production_id: str) -> Path:
        safe_name = "".join(
            character
            if character.isalnum() or character in {"-", "_"}
            else "_"
            for character in production_id.strip()
        ) or "production"

        return (
            self.config.output_dir
            / safe_name
            / self.config.manifest_filename
        )

    def _write_manifest_if_enabled(
        self,
        result: ProductionResult,
    ) -> None:
        if self.config.write_manifest_after_each_stage:
            self.write_manifest(result)

    def write_manifest(
        self,
        result: ProductionResult,
    ) -> Path:
        result.manifest_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        result.manifest_path.write_text(
            json.dumps(
                result.to_dict(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return result.manifest_path

    def _restore_completed_stages(
        self,
        manifest_path: Path,
        records: list[StageRecord],
        context: MutableMapping[str, Any],
    ) -> None:
        payload = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )

        stored_stages = {
            item["stage"]: item
            for item in payload.get("stages", [])
        }

        for record in records:
            stored = stored_stages.get(record.stage.value)
            if not stored:
                continue

            if stored.get("status") == StageStatus.COMPLETED.value:
                record.status = StageStatus.COMPLETED
                record.started_at = stored.get("started_at", "")
                record.completed_at = stored.get(
                    "completed_at",
                    "",
                )
                record.duration_seconds = float(
                    stored.get("duration_seconds", 0.0)
                )
                record.output = stored.get("output")
                record.output_summary = stored.get(
                    "output_summary",
                    {},
                )
                context[record.stage.value] = record.output

    def summarize(
        self,
        results: Sequence[ProductionResult],
    ) -> ProductionSummary:
        return ProductionSummary.from_results(results)


# =============================================================================
# DEFAULT HANDLER FACTORY
# =============================================================================


def build_default_handlers() -> dict[PipelineStage, StageHandler]:
    """
    Return conservative default handlers.

    These handlers intentionally avoid inventing project-specific wiring.
    They provide safe pass-through behavior for early stages and delegate to
    existing production modules where a direct interface is already stable.
    Replace or extend them as the integration phase advances.
    """

    def intake(context: dict[str, Any], request: ProductionRequest) -> Any:
        stories = context.get("stories", [])
        if not stories:
            raise ValueError("No stories were supplied to production.")
        return stories

    def passthrough(
        source_key: str,
    ) -> StageHandler:
        def handler(
            context: dict[str, Any],
            request: ProductionRequest,
        ) -> Any:
            if source_key not in context:
                raise ValueError(
                    f"Required context '{source_key}' is missing."
                )
            return context[source_key]

        return handler

    def upload(
        context: dict[str, Any],
        request: ProductionRequest,
    ) -> Any:
        if request.mode in {
            ProductionMode.DRY_RUN,
            ProductionMode.RENDER_ONLY,
        }:
            return {
                "status": "skipped",
                "reason": request.mode.value,
            }

        video_output = context.get(PipelineStage.VIDEO.value)
        thumbnail_output = context.get(
            PipelineStage.THUMBNAIL.value
        )

        return {
            "status": "ready-for-upload",
            "privacy": (
                "private"
                if request.mode == ProductionMode.UPLOAD_PRIVATE
                else "configured"
            ),
            "video": _json_safe(video_output),
            "thumbnail": _json_safe(thumbnail_output),
        }

    return {
        PipelineStage.INTAKE: intake,
        PipelineStage.EDITORIAL: passthrough(
            PipelineStage.INTAKE.value
        ),
        PipelineStage.BULLETIN: passthrough(
            PipelineStage.EDITORIAL.value
        ),
        PipelineStage.SCRIPT: passthrough(
            PipelineStage.BULLETIN.value
        ),
        PipelineStage.POLISH: passthrough(
            PipelineStage.SCRIPT.value
        ),
        PipelineStage.TRANSLATE: passthrough(
            PipelineStage.POLISH.value
        ),
        PipelineStage.VOICE: passthrough(
            PipelineStage.TRANSLATE.value
        ),
        PipelineStage.AUDIO: passthrough(
            PipelineStage.VOICE.value
        ),
        PipelineStage.SCENES: passthrough(
            PipelineStage.AUDIO.value
        ),
        PipelineStage.GRAPHICS: passthrough(
            PipelineStage.SCENES.value
        ),
        PipelineStage.VIDEO: passthrough(
            PipelineStage.GRAPHICS.value
        ),
        PipelineStage.THUMBNAIL: passthrough(
            PipelineStage.VIDEO.value
        ),
        PipelineStage.UPLOAD: upload,
    }


# =============================================================================
# SELF-TEST
# =============================================================================


def _run_self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(
        prefix="bahuvu_production_pipeline_test_"
    ) as temp_dir:
        config = ProductionConfig(
            output_dir=Path(temp_dir) / "production",
            write_manifest_after_each_stage=True,
        )

        handlers: dict[PipelineStage, StageHandler] = {}

        def make_handler(stage: PipelineStage) -> StageHandler:
            def handler(
                context: dict[str, Any],
                request: ProductionRequest,
            ) -> Any:
                previous = [
                    key
                    for key in context
                    if key in {
                        item.value
                        for item in ProductionPipeline.STAGE_ORDER
                    }
                ]
                return {
                    "stage": stage.value,
                    "production_id": request.production_id,
                    "previous_stage_count": len(previous),
                }

            return handler

        for stage in ProductionPipeline.STAGE_ORDER:
            handlers[stage] = make_handler(stage)

        pipeline = ProductionPipeline(
            config=config,
            handlers=handlers,
        )

        request = ProductionRequest(
            production_id="bahuvu_july_2026_demo",
            mode=ProductionMode.DRY_RUN,
            stories=[
                {
                    "story_id": "story_001",
                    "headline": "Sample Telugu News Story",
                }
            ],
            bulletin_id="bahuvu_july_2026",
            metadata={"edition": "July 2026"},
        )

        result = pipeline.run(request)

        assert result.success
        assert result.status == PipelineStatus.COMPLETED
        assert result.manifest_path.exists()
        assert len(result.stages) == 13
        assert sum(
            1
            for stage in result.stages
            if stage.status == StageStatus.COMPLETED
        ) == 12
        assert result.stages[-1].stage == PipelineStage.UPLOAD
        assert result.stages[-1].status == StageStatus.SKIPPED

        loaded = json.loads(
            result.manifest_path.read_text(encoding="utf-8")
        )
        assert loaded["production_id"] == request.production_id
        assert loaded["status"] == "completed"
        assert loaded["success"] is True
        assert len(loaded["stages"]) == 13

        summary = pipeline.summarize([result])
        assert summary.pipelines_processed == 1
        assert summary.completed == 1
        assert summary.failed == 0
        assert summary.stages_completed == 12

        failure_handlers = dict(handlers)

        def fail_graphics(
            context: dict[str, Any],
            request: ProductionRequest,
        ) -> Any:
            raise RuntimeError("Simulated graphics failure.")

        failure_handlers[PipelineStage.GRAPHICS] = fail_graphics

        failed_pipeline = ProductionPipeline(
            config=config,
            handlers=failure_handlers,
        )
        failed_result = failed_pipeline.run(
            ProductionRequest(
                production_id="bahuvu_failure_demo",
                mode=ProductionMode.RENDER_ONLY,
                stories=[{"story_id": "story_001"}],
            )
        )

        assert failed_result.status == PipelineStatus.FAILED
        assert "graphics" in failed_result.error.lower()

        print("Production pipeline initialized successfully.")
        print()
        print(f"Stages configured       : {len(result.stages)}")
        print(
            f"Stages completed        : "
            f"{summary.stages_completed}"
        )
        print(
            f"Upload stage skipped    : "
            f"{result.stages[-1].status == StageStatus.SKIPPED}"
        )
        print(f"Manifest written        : {result.manifest_path.exists()}")
        print(f"Failure handling tested : {failed_result.status.value}")
        print(f"Pipeline status         : {result.status.value}")
        print()
        print("Production pipeline self-test passed.")


if __name__ == "__main__":
    _run_self_test()