"""
BahuvuNewsAI - Graphics Renderer
================================

Renders canonical scene-timeline entries into broadcast-ready PNG frames.

Pipeline position:

    graphics.scene_builder
        -> graphics.graphics_renderer
        -> video composer

The renderer uses Pillow and is intentionally deterministic. It supports
intro, headline, photo, summary, quote, data, map, transition, and outro
scenes. Every rendered frame is recorded in a graphics manifest.

Run:

    python -m py_compile graphics/graphics_renderer.py
    python -m graphics.graphics_renderer
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

from PIL import Image, ImageDraw, ImageFont, ImageOps

from graphics.scene_builder import (
    LayoutType,
    Scene,
    SceneStatus,
    SceneTimeline,
    SceneType,
    TransitionType,
)


# =============================================================================
# ENUMS
# =============================================================================


class RenderStatus(str, Enum):
    READY = "ready"
    FAILED = "failed"
    SKIPPED = "skipped"


class ImageFit(str, Enum):
    COVER = "cover"
    CONTAIN = "contain"
    STRETCH = "stretch"


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass(slots=True)
class GraphicsTheme:
    width: int = 1280
    height: int = 720
    margin: int = 40
    header_height: int = 72
    footer_height: int = 58
    panel_radius: int = 24
    background_rgb: tuple[int, int, int] = (15, 23, 42)
    secondary_rgb: tuple[int, int, int] = (30, 41, 59)
    panel_rgb: tuple[int, int, int] = (248, 250, 252)
    text_rgb: tuple[int, int, int] = (248, 250, 252)
    dark_text_rgb: tuple[int, int, int] = (15, 23, 42)
    muted_text_rgb: tuple[int, int, int] = (203, 213, 225)
    accent_rgb: tuple[int, int, int] = (220, 38, 38)
    accent_secondary_rgb: tuple[int, int, int] = (245, 158, 11)
    overlay_alpha: int = 145
    brand_name: str = "BAHUVU NEWS"
    footer_text: str = "తెలుగు వార్తలు • విశ్వసనీయ సమాచారం"
    font_regular_path: str = ""
    font_bold_path: str = ""

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Canvas dimensions must be positive.")
        if self.margin < 0:
            raise ValueError("Margin cannot be negative.")
        if self.header_height < 0 or self.footer_height < 0:
            raise ValueError("Header and footer heights cannot be negative.")
        if not 0 <= self.overlay_alpha <= 255:
            raise ValueError("Overlay alpha must be between 0 and 255.")


@dataclass(slots=True)
class GraphicsRendererConfig:
    output_dir: Path = Path("outputs/graphics/scenes")
    manifest_filename: str = "graphics_manifest.json"
    image_format: str = "PNG"
    overwrite: bool = True
    write_manifest: bool = True
    image_fit: ImageFit = ImageFit.COVER
    show_safe_area: bool = False
    fallback_image_path: str = ""
    theme: GraphicsTheme = field(default_factory=GraphicsTheme)

    def validate(self) -> None:
        self.theme.validate()
        if not self.manifest_filename.strip():
            raise ValueError("Manifest filename cannot be empty.")
        if self.image_format.upper() not in {"PNG", "JPEG", "JPG", "WEBP"}:
            raise ValueError("Unsupported output image format.")


@dataclass(slots=True)
class RenderedScene:
    scene_id: str
    scene_order: int
    scene_type: SceneType
    status: RenderStatus
    output_path: Path | None
    width: int
    height: int
    bytes_written: int = 0
    duration_seconds: float = 0.0
    story_id: str = ""
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return (
            self.status == RenderStatus.READY
            and self.output_path is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "scene_order": self.scene_order,
            "scene_type": self.scene_type.value,
            "status": self.status.value,
            "output_path": str(self.output_path) if self.output_path else None,
            "width": self.width,
            "height": self.height,
            "bytes_written": self.bytes_written,
            "duration_seconds": self.duration_seconds,
            "story_id": self.story_id,
            "error": self.error,
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class GraphicsManifest:
    bulletin_id: str
    generated_at: str
    width: int
    height: int
    scene_count: int
    rendered_count: int
    failed_count: int
    skipped_count: int
    total_duration_seconds: float
    manifest_path: Path | None
    scenes: list[RenderedScene]
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def production_ready(self) -> bool:
        return (
            self.scene_count > 0
            and self.rendered_count == self.scene_count
            and self.failed_count == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bulletin_id": self.bulletin_id,
            "generated_at": self.generated_at,
            "width": self.width,
            "height": self.height,
            "scene_count": self.scene_count,
            "rendered_count": self.rendered_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "total_duration_seconds": self.total_duration_seconds,
            "production_ready": self.production_ready,
            "manifest_path": (
                str(self.manifest_path) if self.manifest_path else None
            ),
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
            "scenes": [scene.to_dict() for scene in self.scenes],
        }


@dataclass(slots=True)
class GraphicsRenderSummary:
    manifests_processed: int = 0
    scenes_processed: int = 0
    scenes_rendered: int = 0
    scenes_failed: int = 0
    scenes_skipped: int = 0
    bytes_written: int = 0

    @classmethod
    def from_manifests(
        cls,
        manifests: Sequence[GraphicsManifest],
    ) -> "GraphicsRenderSummary":
        return cls(
            manifests_processed=len(manifests),
            scenes_processed=sum(item.scene_count for item in manifests),
            scenes_rendered=sum(item.rendered_count for item in manifests),
            scenes_failed=sum(item.failed_count for item in manifests),
            scenes_skipped=sum(item.skipped_count for item in manifests),
            bytes_written=sum(
                scene.bytes_written
                for manifest in manifests
                for scene in manifest.scenes
            ),
        )


# =============================================================================
# HELPERS
# =============================================================================


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str, fallback: str = "scene") -> str:
    value = value.strip().lower()
    value = re.sub(r"[^\w\-]+", "_", value, flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or fallback


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _load_font(path: str, size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates: list[str] = []

    if path:
        candidates.append(path)

    if bold:
        candidates.extend(
            [
                "C:/Windows/Fonts/NirmalaB.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                "C:/Windows/Fonts/Nirmala.ttf",
                "C:/Windows/Fonts/arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
        )

    for candidate in candidates:
        try:
            if Path(candidate).exists():
                return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue

    return ImageFont.load_default()


def _text_bbox(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
) -> tuple[int, int, int, int]:
    return draw.textbbox((0, 0), text, font=font)


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int | None = None,
) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []

    words = text.split(" ")
    lines: list[str] = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        width = _text_bbox(draw, candidate, font)[2]

        if current and width > max_width:
            lines.append(current)
            current = word
            if max_lines and len(lines) >= max_lines:
                break
        else:
            current = candidate

    if current and (not max_lines or len(lines) < max_lines):
        lines.append(current)

    if max_lines and len(lines) == max_lines:
        consumed = " ".join(lines)
        if len(consumed) < len(text):
            last = lines[-1]
            while last and _text_bbox(
                draw, last + "…", font
            )[2] > max_width:
                last = last[:-1]
            lines[-1] = last.rstrip() + "…"

    return lines


def _fit_image(
    image: Image.Image,
    size: tuple[int, int],
    fit: ImageFit,
) -> Image.Image:
    if fit == ImageFit.STRETCH:
        return image.resize(size, Image.Resampling.LANCZOS)

    if fit == ImageFit.CONTAIN:
        contained = ImageOps.contain(
            image,
            size,
            method=Image.Resampling.LANCZOS,
        )
        canvas = Image.new("RGB", size, (0, 0, 0))
        x = (size[0] - contained.width) // 2
        y = (size[1] - contained.height) // 2
        canvas.paste(contained, (x, y))
        return canvas

    return ImageOps.fit(
        image,
        size,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


# =============================================================================
# RENDERER
# =============================================================================


class GraphicsRenderer:
    def __init__(
        self,
        config: GraphicsRendererConfig | None = None,
    ) -> None:
        self.config = config or GraphicsRendererConfig()
        self.config.validate()
        self.theme = self.config.theme

        self.font_small = _load_font(
            self.theme.font_regular_path,
            24,
        )
        self.font_medium = _load_font(
            self.theme.font_regular_path,
            34,
        )
        self.font_large = _load_font(
            self.theme.font_bold_path,
            52,
            bold=True,
        )
        self.font_xlarge = _load_font(
            self.theme.font_bold_path,
            68,
            bold=True,
        )
        self.font_brand = _load_font(
            self.theme.font_bold_path,
            38,
            bold=True,
        )

    def render_timeline(
        self,
        timeline: SceneTimeline,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> GraphicsManifest:
        output_root = (
            self.config.output_dir
            / _slugify(timeline.bulletin_id, "bulletin")
        )
        output_root.mkdir(parents=True, exist_ok=True)

        rendered_scenes: list[RenderedScene] = []
        warnings: list[str] = []

        for scene in timeline.scenes:
            result = self.render_scene(
                scene,
                output_dir=output_root,
            )
            rendered_scenes.append(result)
            warnings.extend(result.warnings)

        manifest_path = output_root / self.config.manifest_filename

        manifest = GraphicsManifest(
            bulletin_id=timeline.bulletin_id,
            generated_at=_utc_now_iso(),
            width=self.theme.width,
            height=self.theme.height,
            scene_count=len(rendered_scenes),
            rendered_count=sum(
                1
                for item in rendered_scenes
                if item.status == RenderStatus.READY
            ),
            failed_count=sum(
                1
                for item in rendered_scenes
                if item.status == RenderStatus.FAILED
            ),
            skipped_count=sum(
                1
                for item in rendered_scenes
                if item.status == RenderStatus.SKIPPED
            ),
            total_duration_seconds=timeline.total_duration_seconds,
            manifest_path=(
                manifest_path if self.config.write_manifest else None
            ),
            scenes=rendered_scenes,
            warnings=warnings,
            metadata={
                **timeline.metadata,
                **dict(metadata or {}),
            },
        )

        if self.config.write_manifest:
            self.write_manifest(manifest)

        return manifest

    def render_scene(
        self,
        scene: Scene,
        *,
        output_dir: Path | None = None,
    ) -> RenderedScene:
        output_dir = output_dir or self.config.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        extension = (
            "jpg"
            if self.config.image_format.upper() in {"JPEG", "JPG"}
            else self.config.image_format.lower()
        )
        filename = (
            f"{scene.order:03d}_"
            f"{_slugify(scene.scene_id, 'scene')}.{extension}"
        )
        output_path = output_dir / filename

        if output_path.exists() and not self.config.overwrite:
            return RenderedScene(
                scene_id=scene.scene_id,
                scene_order=scene.order,
                scene_type=scene.scene_type,
                status=RenderStatus.SKIPPED,
                output_path=output_path,
                width=self.theme.width,
                height=self.theme.height,
                bytes_written=output_path.stat().st_size,
                duration_seconds=scene.duration_seconds,
                story_id=scene.story_id,
            )

        try:
            image, warnings = self._render_scene_image(scene)
            image.save(
                output_path,
                format=self.config.image_format,
            )

            if not output_path.exists() or output_path.stat().st_size == 0:
                raise RuntimeError("Rendered image was not created.")

            return RenderedScene(
                scene_id=scene.scene_id,
                scene_order=scene.order,
                scene_type=scene.scene_type,
                status=RenderStatus.READY,
                output_path=output_path,
                width=image.width,
                height=image.height,
                bytes_written=output_path.stat().st_size,
                duration_seconds=scene.duration_seconds,
                story_id=scene.story_id,
                warnings=warnings,
                metadata=dict(scene.metadata),
            )
        except Exception as exc:
            return RenderedScene(
                scene_id=scene.scene_id,
                scene_order=scene.order,
                scene_type=scene.scene_type,
                status=RenderStatus.FAILED,
                output_path=None,
                width=self.theme.width,
                height=self.theme.height,
                duration_seconds=scene.duration_seconds,
                story_id=scene.story_id,
                error=str(exc),
                metadata=dict(scene.metadata),
            )

    def _render_scene_image(
        self,
        scene: Scene,
    ) -> tuple[Image.Image, list[str]]:
        warnings: list[str] = []

        image = Image.new(
            "RGB",
            (self.theme.width, self.theme.height),
            self.theme.background_rgb,
        )

        if scene.scene_type in {
            SceneType.PHOTO,
            SceneType.MAP,
        }:
            image, image_warnings = self._render_visual_scene(
                image,
                scene,
            )
            warnings.extend(image_warnings)
        elif scene.scene_type == SceneType.INTRO:
            self._render_intro(image, scene)
        elif scene.scene_type == SceneType.OUTRO:
            self._render_outro(image, scene)
        elif scene.scene_type == SceneType.HEADLINE:
            self._render_headline(image, scene)
        elif scene.scene_type == SceneType.SUMMARY:
            self._render_summary(image, scene)
        elif scene.scene_type == SceneType.QUOTE:
            self._render_quote(image, scene)
        elif scene.scene_type == SceneType.DATA:
            self._render_data(image, scene)
        elif scene.scene_type == SceneType.TRANSITION:
            self._render_transition(image, scene)
        else:
            self._render_summary(image, scene)

        if scene.scene_type not in {
            SceneType.INTRO,
            SceneType.OUTRO,
            SceneType.TRANSITION,
        }:
            self._draw_header(image, scene)
            self._draw_footer(image)

        if self.config.show_safe_area:
            self._draw_safe_area(image)

        return image, warnings

    # ------------------------------------------------------------------
    # Scene-specific rendering
    # ------------------------------------------------------------------

    def _render_intro(self, image: Image.Image, scene: Scene) -> None:
        draw = ImageDraw.Draw(image)

        draw.rectangle(
            (0, 0, self.theme.width, self.theme.height),
            fill=self.theme.background_rgb,
        )
        draw.rectangle(
            (
                0,
                self.theme.height // 2 - 10,
                self.theme.width,
                self.theme.height // 2 + 10,
            ),
            fill=self.theme.accent_rgb,
        )

        brand = scene.headline.strip() or self.theme.brand_name
        bbox = draw.textbbox((0, 0), brand, font=self.font_xlarge)
        x = (self.theme.width - (bbox[2] - bbox[0])) // 2
        y = self.theme.height // 2 - 120
        draw.text(
            (x, y),
            brand,
            font=self.font_xlarge,
            fill=self.theme.text_rgb,
        )

        subtitle = "తెలుగు వార్తలు"
        bbox = draw.textbbox((0, 0), subtitle, font=self.font_medium)
        x = (self.theme.width - (bbox[2] - bbox[0])) // 2
        draw.text(
            (x, self.theme.height // 2 + 45),
            subtitle,
            font=self.font_medium,
            fill=self.theme.muted_text_rgb,
        )

    def _render_outro(self, image: Image.Image, scene: Scene) -> None:
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            (0, 0, self.theme.width, self.theme.height),
            fill=self.theme.background_rgb,
        )

        brand = scene.headline.strip() or self.theme.brand_name
        bbox = draw.textbbox((0, 0), brand, font=self.font_xlarge)
        x = (self.theme.width - (bbox[2] - bbox[0])) // 2
        draw.text(
            (x, 220),
            brand,
            font=self.font_xlarge,
            fill=self.theme.text_rgb,
        )

        summary = (
            scene.summary.strip()
            or "మరిన్ని వార్తల కోసం బాహువు న్యూస్‌ను అనుసరించండి."
        )
        lines = _wrap_text(
            draw,
            summary,
            self.font_medium,
            self.theme.width - 220,
            max_lines=3,
        )
        y = 360
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=self.font_medium)
            x = (self.theme.width - (bbox[2] - bbox[0])) // 2
            draw.text(
                (x, y),
                line,
                font=self.font_medium,
                fill=self.theme.muted_text_rgb,
            )
            y += 48

    def _render_headline(self, image: Image.Image, scene: Scene) -> None:
        draw = ImageDraw.Draw(image)

        panel = (
            self.theme.margin,
            self.theme.header_height + 55,
            self.theme.width - self.theme.margin,
            self.theme.height - self.theme.footer_height - 55,
        )
        draw.rounded_rectangle(
            panel,
            radius=self.theme.panel_radius,
            fill=self.theme.secondary_rgb,
        )

        badge = scene.category.upper() if scene.category else "NEWS"
        self._draw_category_badge(
            draw,
            badge,
            panel[0] + 40,
            panel[1] + 38,
        )

        lines = _wrap_text(
            draw,
            scene.headline,
            self.font_xlarge,
            panel[2] - panel[0] - 80,
            max_lines=4,
        )
        y = panel[1] + 125
        for line in lines:
            draw.text(
                (panel[0] + 40, y),
                line,
                font=self.font_xlarge,
                fill=self.theme.text_rgb,
            )
            y += 86

    def _render_summary(self, image: Image.Image, scene: Scene) -> None:
        draw = ImageDraw.Draw(image)

        panel = (
            self.theme.margin,
            self.theme.header_height + 35,
            self.theme.width - self.theme.margin,
            self.theme.height - self.theme.footer_height - 35,
        )
        draw.rounded_rectangle(
            panel,
            radius=self.theme.panel_radius,
            fill=self.theme.panel_rgb,
        )

        headline_lines = _wrap_text(
            draw,
            scene.headline,
            self.font_large,
            panel[2] - panel[0] - 80,
            max_lines=2,
        )

        y = panel[1] + 40
        for line in headline_lines:
            draw.text(
                (panel[0] + 40, y),
                line,
                font=self.font_large,
                fill=self.theme.dark_text_rgb,
            )
            y += 66

        draw.rectangle(
            (
                panel[0] + 40,
                y + 10,
                panel[0] + 180,
                y + 16,
            ),
            fill=self.theme.accent_rgb,
        )
        y += 55

        summary_lines = _wrap_text(
            draw,
            scene.summary,
            self.font_medium,
            panel[2] - panel[0] - 80,
            max_lines=7,
        )
        for line in summary_lines:
            draw.text(
                (panel[0] + 40, y),
                line,
                font=self.font_medium,
                fill=self.theme.dark_text_rgb,
            )
            y += 50

    def _render_quote(self, image: Image.Image, scene: Scene) -> None:
        draw = ImageDraw.Draw(image)

        panel = (
            120,
            150,
            self.theme.width - 120,
            self.theme.height - 130,
        )
        draw.rounded_rectangle(
            panel,
            radius=32,
            fill=self.theme.panel_rgb,
        )

        draw.text(
            (panel[0] + 45, panel[1] + 10),
            "“",
            font=self.font_xlarge,
            fill=self.theme.accent_rgb,
        )

        lines = _wrap_text(
            draw,
            scene.summary,
            self.font_large,
            panel[2] - panel[0] - 110,
            max_lines=5,
        )
        y = panel[1] + 115
        for line in lines:
            draw.text(
                (panel[0] + 60, y),
                line,
                font=self.font_large,
                fill=self.theme.dark_text_rgb,
            )
            y += 68

    def _render_data(self, image: Image.Image, scene: Scene) -> None:
        draw = ImageDraw.Draw(image)

        panel = (
            90,
            130,
            self.theme.width - 90,
            self.theme.height - 110,
        )
        draw.rounded_rectangle(
            panel,
            radius=28,
            fill=self.theme.panel_rgb,
        )

        draw.text(
            (panel[0] + 40, panel[1] + 35),
            scene.headline,
            font=self.font_large,
            fill=self.theme.dark_text_rgb,
        )

        data_items = [
            item.strip()
            for item in scene.summary.split("|")
            if item.strip()
        ]

        y = panel[1] + 145
        for item in data_items[:6]:
            draw.ellipse(
                (panel[0] + 48, y + 9, panel[0] + 68, y + 29),
                fill=self.theme.accent_rgb,
            )
            draw.text(
                (panel[0] + 90, y),
                item,
                font=self.font_medium,
                fill=self.theme.dark_text_rgb,
            )
            y += 68

    def _render_transition(self, image: Image.Image, scene: Scene) -> None:
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            (0, 0, self.theme.width, self.theme.height),
            fill=self.theme.background_rgb,
        )
        draw.rectangle(
            (
                0,
                self.theme.height // 2 - 6,
                self.theme.width,
                self.theme.height // 2 + 6,
            ),
            fill=self.theme.accent_rgb,
        )
        bbox = draw.textbbox(
            (0, 0),
            self.theme.brand_name,
            font=self.font_brand,
        )
        x = (self.theme.width - (bbox[2] - bbox[0])) // 2
        draw.text(
            (x, self.theme.height // 2 - 70),
            self.theme.brand_name,
            font=self.font_brand,
            fill=self.theme.text_rgb,
        )

    def _render_visual_scene(
        self,
        base: Image.Image,
        scene: Scene,
    ) -> tuple[Image.Image, list[str]]:
        warnings: list[str] = []
        image_path = Path(scene.image_path) if scene.image_path else None

        if (
            image_path is None
            or not image_path.exists()
            or not image_path.is_file()
        ):
            fallback = (
                Path(self.config.fallback_image_path)
                if self.config.fallback_image_path
                else None
            )
            if fallback and fallback.exists():
                image_path = fallback
                warnings.append(
                    f"{scene.scene_id}: fallback image used."
                )
            else:
                warnings.append(
                    f"{scene.scene_id}: image missing; placeholder rendered."
                )
                self._render_image_placeholder(base, scene)
                return base, warnings

        with Image.open(image_path) as source:
            source = source.convert("RGB")
            fitted = _fit_image(
                source,
                (self.theme.width, self.theme.height),
                self.config.image_fit,
            )

        overlay = Image.new(
            "RGBA",
            fitted.size,
            (0, 0, 0, 0),
        )
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle(
            (
                0,
                self.theme.height * 0.55,
                self.theme.width,
                self.theme.height,
            ),
            fill=(0, 0, 0, self.theme.overlay_alpha),
        )

        composed = Image.alpha_composite(
            fitted.convert("RGBA"),
            overlay,
        ).convert("RGB")

        draw = ImageDraw.Draw(composed)
        self._draw_category_badge(
            draw,
            scene.category.upper() if scene.category else "NEWS",
            self.theme.margin,
            self.theme.height - 235,
        )

        headline_lines = _wrap_text(
            draw,
            scene.headline,
            self.font_large,
            self.theme.width - (self.theme.margin * 2),
            max_lines=2,
        )
        y = self.theme.height - 175
        for line in headline_lines:
            draw.text(
                (self.theme.margin, y),
                line,
                font=self.font_large,
                fill=self.theme.text_rgb,
            )
            y += 62

        return composed, warnings

    def _render_image_placeholder(
        self,
        image: Image.Image,
        scene: Scene,
    ) -> None:
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            (0, 0, self.theme.width, self.theme.height),
            fill=self.theme.secondary_rgb,
        )

        draw.rectangle(
            (
                180,
                150,
                self.theme.width - 180,
                self.theme.height - 150,
            ),
            outline=self.theme.muted_text_rgb,
            width=4,
        )

        placeholder = "IMAGE NOT AVAILABLE"
        bbox = draw.textbbox((0, 0), placeholder, font=self.font_large)
        x = (self.theme.width - (bbox[2] - bbox[0])) // 2
        y = self.theme.height // 2 - 30
        draw.text(
            (x, y),
            placeholder,
            font=self.font_large,
            fill=self.theme.muted_text_rgb,
        )

    # ------------------------------------------------------------------
    # Shared elements
    # ------------------------------------------------------------------

    def _draw_header(self, image: Image.Image, scene: Scene) -> None:
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            (0, 0, self.theme.width, self.theme.header_height),
            fill=self.theme.background_rgb,
        )
        draw.rectangle(
            (0, self.theme.header_height - 5, self.theme.width, self.theme.header_height),
            fill=self.theme.accent_rgb,
        )
        draw.text(
            (self.theme.margin, 15),
            self.theme.brand_name,
            font=self.font_brand,
            fill=self.theme.text_rgb,
        )

        category = scene.category.upper() if scene.category else "NEWS"
        bbox = draw.textbbox((0, 0), category, font=self.font_small)
        draw.text(
            (
                self.theme.width - self.theme.margin - (bbox[2] - bbox[0]),
                23,
            ),
            category,
            font=self.font_small,
            fill=self.theme.muted_text_rgb,
        )

    def _draw_footer(self, image: Image.Image) -> None:
        draw = ImageDraw.Draw(image)
        y = self.theme.height - self.theme.footer_height
        draw.rectangle(
            (0, y, self.theme.width, self.theme.height),
            fill=self.theme.background_rgb,
        )
        draw.rectangle(
            (0, y, 250, y + 5),
            fill=self.theme.accent_secondary_rgb,
        )
        draw.text(
            (self.theme.margin, y + 15),
            self.theme.footer_text,
            font=self.font_small,
            fill=self.theme.muted_text_rgb,
        )

    def _draw_category_badge(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        x: int,
        y: int,
    ) -> None:
        text = text or "NEWS"
        bbox = draw.textbbox((0, 0), text, font=self.font_small)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]

        draw.rounded_rectangle(
            (
                x,
                y,
                x + width + 32,
                y + height + 20,
            ),
            radius=10,
            fill=self.theme.accent_rgb,
        )
        draw.text(
            (x + 16, y + 8),
            text,
            font=self.font_small,
            fill=self.theme.text_rgb,
        )

    def _draw_safe_area(self, image: Image.Image) -> None:
        draw = ImageDraw.Draw(image)
        margin = self.theme.margin
        draw.rectangle(
            (
                margin,
                margin,
                self.theme.width - margin,
                self.theme.height - margin,
            ),
            outline=(255, 255, 0),
            width=2,
        )

    def write_manifest(self, manifest: GraphicsManifest) -> Path:
        if manifest.manifest_path is None:
            raise ValueError("Manifest path is not configured.")

        manifest.manifest_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        manifest.manifest_path.write_text(
            json.dumps(
                manifest.to_dict(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return manifest.manifest_path

    def summarize(
        self,
        manifests: Sequence[GraphicsManifest],
    ) -> GraphicsRenderSummary:
        return GraphicsRenderSummary.from_manifests(manifests)


# =============================================================================
# CONVENIENCE API
# =============================================================================


def render_scene_timeline(
    timeline: SceneTimeline,
    *,
    config: GraphicsRendererConfig | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> GraphicsManifest:
    return GraphicsRenderer(config=config).render_timeline(
        timeline,
        metadata=metadata,
    )


# =============================================================================
# SELF-TEST
# =============================================================================


def _build_test_timeline(temp_root: Path) -> SceneTimeline:
    sample_image = temp_root / "sample.jpg"
    canvas = Image.new("RGB", (900, 600), (70, 100, 140))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((80, 80, 820, 520), fill=(130, 160, 190))
    draw.text((250, 270), "BAHUVU TEST IMAGE", fill=(255, 255, 255))
    canvas.save(sample_image)

    scenes = [
        Scene(
            scene_id="demo_intro",
            story_id="",
            order=1,
            scene_type=SceneType.INTRO,
            status=SceneStatus.READY,
            start_time_seconds=0.0,
            duration_seconds=5.0,
            end_time_seconds=5.0,
            headline="BAHUVU NEWS",
            layout=LayoutType.FULL_FRAME,
            transition_in=TransitionType.FADE,
            transition_out=TransitionType.FADE,
        ),
        Scene(
            scene_id="story_001_headline",
            story_id="story_001",
            order=2,
            scene_type=SceneType.HEADLINE,
            status=SceneStatus.READY,
            start_time_seconds=5.0,
            duration_seconds=4.0,
            end_time_seconds=9.0,
            headline="తీర ప్రాంతాలకు భారీ వర్ష హెచ్చరిక",
            category="weather",
            layout=LayoutType.HEADLINE_FOCUS,
        ),
        Scene(
            scene_id="story_001_photo",
            story_id="story_001",
            order=3,
            scene_type=SceneType.PHOTO,
            status=SceneStatus.READY,
            start_time_seconds=9.0,
            duration_seconds=6.0,
            end_time_seconds=15.0,
            headline="తీర ప్రాంతాలకు భారీ వర్ష హెచ్చరిక",
            summary="పలు జిల్లాలకు ఆరెంజ్ అలర్ట్ జారీ చేసింది.",
            image_path=str(sample_image),
            category="weather",
            layout=LayoutType.IMAGE_FULL,
        ),
        Scene(
            scene_id="story_001_summary",
            story_id="story_001",
            order=4,
            scene_type=SceneType.SUMMARY,
            status=SceneStatus.READY,
            start_time_seconds=15.0,
            duration_seconds=9.0,
            end_time_seconds=24.0,
            headline="తీర ప్రాంతాలకు భారీ వర్ష హెచ్చరిక",
            summary=(
                "భారత వాతావరణ శాఖ పలు తీర ప్రాంత జిల్లాలకు "
                "ఆరెంజ్ అలర్ట్ జారీ చేసింది."
            ),
            category="weather",
            layout=LayoutType.SUMMARY_PANEL,
        ),
        Scene(
            scene_id="demo_outro",
            story_id="",
            order=5,
            scene_type=SceneType.OUTRO,
            status=SceneStatus.READY,
            start_time_seconds=24.0,
            duration_seconds=5.0,
            end_time_seconds=29.0,
            headline="BAHUVU NEWS",
            summary="మరిన్ని వార్తల కోసం బాహువు న్యూస్‌ను అనుసరించండి.",
            layout=LayoutType.FULL_FRAME,
        ),
    ]

    return SceneTimeline(
        bulletin_id="bahuvu_graphics_demo",
        generated_at=_utc_now_iso(),
        total_duration_seconds=29.0,
        scene_count=len(scenes),
        story_count=1,
        scenes=scenes,
        manifest_path=None,
        warnings=[],
        metadata={"edition": "test"},
    )


def _run_self_test() -> None:
    with tempfile.TemporaryDirectory(
        prefix="bahuvu_graphics_renderer_test_"
    ) as temp_dir:
        root = Path(temp_dir)

        config = GraphicsRendererConfig(
            output_dir=root / "rendered",
            write_manifest=True,
            overwrite=True,
            show_safe_area=False,
        )

        renderer = GraphicsRenderer(config=config)
        timeline = _build_test_timeline(root)
        manifest = renderer.render_timeline(timeline)

        assert manifest.scene_count == 5
        assert manifest.rendered_count == 5
        assert manifest.failed_count == 0
        assert manifest.production_ready
        assert manifest.manifest_path is not None
        assert manifest.manifest_path.exists()

        for item in manifest.scenes:
            assert item.ready
            assert item.output_path is not None
            assert item.output_path.exists()
            assert item.output_path.stat().st_size > 0
            with Image.open(item.output_path) as rendered:
                assert rendered.size == (
                    config.theme.width,
                    config.theme.height,
                )

        loaded = json.loads(
            manifest.manifest_path.read_text(encoding="utf-8")
        )
        assert loaded["bulletin_id"] == "bahuvu_graphics_demo"
        assert loaded["rendered_count"] == 5
        assert loaded["production_ready"] is True

        summary = renderer.summarize([manifest])
        assert summary.manifests_processed == 1
        assert summary.scenes_processed == 5
        assert summary.scenes_rendered == 5
        assert summary.scenes_failed == 0
        assert summary.bytes_written > 0

        print("Graphics renderer initialized successfully.")
        print()
        print(f"Scenes processed        : {manifest.scene_count}")
        print(f"Scenes rendered         : {manifest.rendered_count}")
        print(f"Scenes failed           : {manifest.failed_count}")
        print(f"Canvas                  : {manifest.width}x{manifest.height}")
        print(f"Manifest written        : {manifest.manifest_path.exists()}")
        print(f"Production ready        : {manifest.production_ready}")
        print()
        print("Graphics renderer self-test passed.")


if __name__ == "__main__":
    _run_self_test()