"""
BahuvuNewsAI - YouTube Thumbnail Generator
==========================================

Creates branded YouTube thumbnails from a lead story image, Telugu headline,
category, and Bahuvu News branding.

Pipeline position:

    bulletin / lead story
        -> thumbnail.thumbnail_generator
        -> youtube uploader

Run:

    python -m py_compile thumbnail/thumbnail_generator.py
    python -m thumbnail.thumbnail_generator
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


class ThumbnailStatus(str, Enum):
    GENERATED = "generated"
    FAILED = "failed"
    SKIPPED = "skipped"


class ThumbnailFit(str, Enum):
    COVER = "cover"
    CONTAIN = "contain"


@dataclass(slots=True)
class ThumbnailTheme:
    width: int = 1280
    height: int = 720
    margin: int = 48
    brand_name: str = "BAHUVU NEWS"
    brand_rgb: tuple[int, int, int] = (220, 38, 38)
    accent_rgb: tuple[int, int, int] = (245, 158, 11)
    text_rgb: tuple[int, int, int] = (255, 255, 255)
    shadow_rgb: tuple[int, int, int] = (0, 0, 0)
    badge_text_rgb: tuple[int, int, int] = (255, 255, 255)
    overlay_alpha: int = 175
    font_regular_path: str = ""
    font_bold_path: str = ""

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Thumbnail dimensions must be positive.")
        if self.margin < 0:
            raise ValueError("Thumbnail margin cannot be negative.")
        if not 0 <= self.overlay_alpha <= 255:
            raise ValueError("Overlay alpha must be between 0 and 255.")
        if not self.brand_name.strip():
            raise ValueError("Brand name cannot be empty.")


@dataclass(slots=True)
class ThumbnailConfig:
    output_dir: Path = Path("outputs/thumbnails")
    output_filename: str = "bulletin_thumbnail.png"
    manifest_filename: str = "thumbnail_manifest.json"
    image_format: str = "PNG"
    overwrite: bool = True
    write_manifest: bool = True
    image_fit: ThumbnailFit = ThumbnailFit.COVER
    fallback_image_path: str = ""
    contrast_factor: float = 1.12
    sharpness_factor: float = 1.08
    theme: ThumbnailTheme = field(default_factory=ThumbnailTheme)

    def validate(self) -> None:
        self.theme.validate()
        if not self.output_filename.strip():
            raise ValueError("Output filename cannot be empty.")
        if not self.manifest_filename.strip():
            raise ValueError("Manifest filename cannot be empty.")
        if self.image_format.upper() not in {"PNG", "JPEG", "JPG", "WEBP"}:
            raise ValueError("Unsupported thumbnail image format.")
        if self.contrast_factor <= 0:
            raise ValueError("Contrast factor must be positive.")
        if self.sharpness_factor <= 0:
            raise ValueError("Sharpness factor must be positive.")


@dataclass(slots=True)
class ThumbnailInput:
    headline: str
    category: str = "NEWS"
    image_path: str = ""
    bulletin_id: str = ""
    story_id: str = ""
    subheadline: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ThumbnailResult:
    status: ThumbnailStatus
    input: ThumbnailInput
    output_path: Path | None
    manifest_path: Path | None
    width: int
    height: int
    bytes_written: int = 0
    image_used: str = ""
    placeholder_used: bool = False
    quality_score: float = 0.0
    generated_at: str = ""
    error: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return (
            self.status == ThumbnailStatus.GENERATED
            and self.output_path is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "input": asdict(self.input),
            "output_path": str(self.output_path) if self.output_path else None,
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "width": self.width,
            "height": self.height,
            "bytes_written": self.bytes_written,
            "image_used": self.image_used,
            "placeholder_used": self.placeholder_used,
            "quality_score": self.quality_score,
            "generated_at": self.generated_at,
            "error": self.error,
            "warnings": list(self.warnings),
            "success": self.success,
        }


@dataclass(slots=True)
class ThumbnailSummary:
    processed: int = 0
    generated: int = 0
    failed: int = 0
    skipped: int = 0
    total_bytes: int = 0
    average_quality_score: float = 0.0

    @classmethod
    def from_results(
        cls,
        results: Sequence[ThumbnailResult],
    ) -> "ThumbnailSummary":
        scores = [item.quality_score for item in results]
        return cls(
            processed=len(results),
            generated=sum(1 for item in results if item.status == ThumbnailStatus.GENERATED),
            failed=sum(1 for item in results if item.status == ThumbnailStatus.FAILED),
            skipped=sum(1 for item in results if item.status == ThumbnailStatus.SKIPPED),
            total_bytes=sum(item.bytes_written for item in results),
            average_quality_score=round(
                sum(scores) / len(scores),
                2,
            ) if scores else 0.0,
        )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _slugify(value: str, fallback: str = "thumbnail") -> str:
    value = re.sub(r"[^\w\-]+", "_", value.strip().lower(), flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or fallback


def coerce_thumbnail_input(value: Any) -> ThumbnailInput:
    if isinstance(value, ThumbnailInput):
        return value

    mapping = _coerce_mapping(value)
    if not mapping:
        raise TypeError(
            "Thumbnail input must be a mapping, dataclass, or object."
        )

    metadata = mapping.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        metadata = {}

    return ThumbnailInput(
        headline=_safe_text(
            mapping.get("headline")
            or mapping.get("translated_headline")
            or mapping.get("title")
            or ""
        ),
        category=_safe_text(mapping.get("category") or "NEWS"),
        image_path=_safe_text(
            mapping.get("image_path")
            or mapping.get("image_url")
            or mapping.get("photo_path")
            or ""
        ),
        bulletin_id=_safe_text(mapping.get("bulletin_id") or ""),
        story_id=_safe_text(
            mapping.get("story_id")
            or mapping.get("article_id")
            or mapping.get("id")
            or ""
        ),
        subheadline=_safe_text(
            mapping.get("subheadline")
            or mapping.get("summary")
            or ""
        ),
        metadata=dict(metadata),
    )


def _load_font(
    explicit_path: str,
    size: int,
    *,
    bold: bool = False,
) -> ImageFont.ImageFont:
    candidates: list[str] = []

    if explicit_path:
        candidates.append(explicit_path)

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


def _text_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []

    words = text.split(" ")
    lines: list[str] = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()

        if current and _text_width(draw, candidate, font) > max_width:
            lines.append(current)
            current = word

            if len(lines) >= max_lines:
                break
        else:
            current = candidate

    if current and len(lines) < max_lines:
        lines.append(current)

    if len(lines) == max_lines:
        joined = " ".join(lines)
        if len(joined) < len(text):
            last = lines[-1]
            while (
                last
                and _text_width(draw, last + "…", font) > max_width
            ):
                last = last[:-1]
            lines[-1] = last.rstrip() + "…"

    return lines


class ThumbnailGenerator:
    def __init__(self, config: ThumbnailConfig | None = None) -> None:
        self.config = config or ThumbnailConfig()
        self.config.validate()
        self.theme = self.config.theme

        self.font_brand = _load_font(
            self.theme.font_bold_path,
            36,
            bold=True,
        )
        self.font_badge = _load_font(
            self.theme.font_bold_path,
            28,
            bold=True,
        )
        self.font_headline = _load_font(
            self.theme.font_bold_path,
            68,
            bold=True,
        )
        self.font_subheadline = _load_font(
            self.theme.font_regular_path,
            30,
        )

    def generate(
        self,
        value: Any,
        *,
        output_path: str | Path | None = None,
    ) -> ThumbnailResult:
        thumbnail_input = coerce_thumbnail_input(value)
        generated_at = _utc_now_iso()
        warnings: list[str] = []

        try:
            if not thumbnail_input.headline.strip():
                raise ValueError("Thumbnail headline cannot be empty.")

            target = self._build_output_path(
                thumbnail_input,
                output_path,
            )
            target.parent.mkdir(parents=True, exist_ok=True)

            manifest_path = (
                target.parent / self.config.manifest_filename
                if self.config.write_manifest
                else None
            )

            if target.exists() and not self.config.overwrite:
                result = ThumbnailResult(
                    status=ThumbnailStatus.SKIPPED,
                    input=thumbnail_input,
                    output_path=target,
                    manifest_path=manifest_path,
                    width=self.theme.width,
                    height=self.theme.height,
                    bytes_written=target.stat().st_size,
                    generated_at=generated_at,
                    warnings=["Existing thumbnail was preserved."],
                )
                if manifest_path:
                    self.write_manifest(result)
                return result

            base, image_used, placeholder_used, image_warnings = (
                self._prepare_background(thumbnail_input)
            )
            warnings.extend(image_warnings)

            rendered = self._render_thumbnail(
                base,
                thumbnail_input,
            )
            rendered.save(
                target,
                format=self.config.image_format,
            )

            if not target.exists() or target.stat().st_size == 0:
                raise RuntimeError("Thumbnail output was not created.")

            quality_score = self._calculate_quality_score(
                thumbnail_input,
                placeholder_used,
                warnings,
            )

            result = ThumbnailResult(
                status=ThumbnailStatus.GENERATED,
                input=thumbnail_input,
                output_path=target,
                manifest_path=manifest_path,
                width=rendered.width,
                height=rendered.height,
                bytes_written=target.stat().st_size,
                image_used=image_used,
                placeholder_used=placeholder_used,
                quality_score=quality_score,
                generated_at=generated_at,
                warnings=warnings,
            )

            if manifest_path:
                self.write_manifest(result)

            return result

        except Exception as exc:
            return ThumbnailResult(
                status=ThumbnailStatus.FAILED,
                input=thumbnail_input,
                output_path=None,
                manifest_path=None,
                width=self.theme.width,
                height=self.theme.height,
                generated_at=generated_at,
                error=str(exc),
                warnings=warnings,
            )

    def _build_output_path(
        self,
        thumbnail_input: ThumbnailInput,
        output_path: str | Path | None,
    ) -> Path:
        if output_path is not None:
            path = Path(output_path)
            if not path.suffix:
                path = path.with_suffix(".png")
            return path

        bulletin_name = _slugify(
            thumbnail_input.bulletin_id
            or thumbnail_input.story_id
            or "bulletin"
        )
        return (
            self.config.output_dir
            / bulletin_name
            / self.config.output_filename
        )

    def _prepare_background(
        self,
        thumbnail_input: ThumbnailInput,
    ) -> tuple[Image.Image, str, bool, list[str]]:
        warnings: list[str] = []
        image_path = (
            Path(thumbnail_input.image_path)
            if thumbnail_input.image_path
            else None
        )

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
                warnings.append("Fallback image used.")
            else:
                warnings.append("Story image missing; branded placeholder used.")
                return (
                    self._create_placeholder_background(),
                    "",
                    True,
                    warnings,
                )

        with Image.open(image_path) as source:
            source = source.convert("RGB")

            if self.config.image_fit == ThumbnailFit.CONTAIN:
                fitted = ImageOps.contain(
                    source,
                    (self.theme.width, self.theme.height),
                    method=Image.Resampling.LANCZOS,
                )
                canvas = Image.new(
                    "RGB",
                    (self.theme.width, self.theme.height),
                    (0, 0, 0),
                )
                x = (self.theme.width - fitted.width) // 2
                y = (self.theme.height - fitted.height) // 2
                canvas.paste(fitted, (x, y))
                fitted = canvas
            else:
                fitted = ImageOps.fit(
                    source,
                    (self.theme.width, self.theme.height),
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.45),
                )

        fitted = ImageEnhance.Contrast(fitted).enhance(
            self.config.contrast_factor
        )
        fitted = ImageEnhance.Sharpness(fitted).enhance(
            self.config.sharpness_factor
        )

        return fitted, str(image_path), False, warnings

    def _create_placeholder_background(self) -> Image.Image:
        image = Image.new(
            "RGB",
            (self.theme.width, self.theme.height),
            (20, 30, 50),
        )
        draw = ImageDraw.Draw(image)

        for y in range(self.theme.height):
            ratio = y / max(1, self.theme.height - 1)
            red = int(20 + (75 - 20) * ratio)
            green = int(30 + (15 - 30) * ratio)
            blue = int(50 + (25 - 50) * ratio)
            draw.line(
                (0, y, self.theme.width, y),
                fill=(red, green, blue),
            )

        draw.ellipse(
            (760, 70, 1320, 630),
            fill=(115, 20, 30),
        )
        draw.rectangle(
            (0, 590, self.theme.width, self.theme.height),
            fill=(10, 15, 28),
        )
        return image

    def _render_thumbnail(
        self,
        base: Image.Image,
        thumbnail_input: ThumbnailInput,
    ) -> Image.Image:
        image = base.convert("RGBA")

        overlay = Image.new(
            "RGBA",
            image.size,
            (0, 0, 0, 0),
        )
        overlay_draw = ImageDraw.Draw(overlay)

        for x in range(self.theme.width):
            ratio = 1.0 - (x / max(1, self.theme.width - 1))
            alpha = int(self.theme.overlay_alpha * ratio)
            overlay_draw.line(
                (x, 0, x, self.theme.height),
                fill=(0, 0, 0, alpha),
            )

        overlay_draw.rectangle(
            (
                0,
                self.theme.height - 150,
                self.theme.width,
                self.theme.height,
            ),
            fill=(0, 0, 0, 120),
        )

        image = Image.alpha_composite(image, overlay)
        draw = ImageDraw.Draw(image)

        self._draw_brand(draw)
        self._draw_category(draw, thumbnail_input.category)
        self._draw_headline(draw, thumbnail_input.headline)

        if thumbnail_input.subheadline.strip():
            self._draw_subheadline(
                draw,
                thumbnail_input.subheadline,
            )

        self._draw_accent_bar(draw)

        return image.convert("RGB")

    def _draw_brand(self, draw: ImageDraw.ImageDraw) -> None:
        x = self.theme.width - self.theme.margin
        y = self.theme.margin

        box = draw.textbbox(
            (0, 0),
            self.theme.brand_name,
            font=self.font_brand,
        )
        text_width = box[2] - box[0]

        draw.rounded_rectangle(
            (
                x - text_width - 34,
                y,
                x,
                y + 58,
            ),
            radius=12,
            fill=self.theme.brand_rgb,
        )
        draw.text(
            (
                x - text_width - 17,
                y + 9,
            ),
            self.theme.brand_name,
            font=self.font_brand,
            fill=self.theme.text_rgb,
        )

    def _draw_category(
        self,
        draw: ImageDraw.ImageDraw,
        category: str,
    ) -> None:
        text = category.strip().upper() or "NEWS"
        x = self.theme.margin
        y = 96

        box = draw.textbbox((0, 0), text, font=self.font_badge)
        width = box[2] - box[0]
        height = box[3] - box[1]

        draw.rounded_rectangle(
            (
                x,
                y,
                x + width + 34,
                y + height + 22,
            ),
            radius=12,
            fill=self.theme.brand_rgb,
        )
        draw.text(
            (x + 17, y + 8),
            text,
            font=self.font_badge,
            fill=self.theme.badge_text_rgb,
        )

    def _draw_headline(
        self,
        draw: ImageDraw.ImageDraw,
        headline: str,
    ) -> None:
        max_width = int(self.theme.width * 0.62)
        lines = _wrap_text(
            draw,
            headline,
            self.font_headline,
            max_width,
            max_lines=4,
        )

        x = self.theme.margin
        y = 190

        for line in lines:
            draw.text(
                (x + 4, y + 4),
                line,
                font=self.font_headline,
                fill=(*self.theme.shadow_rgb, 210),
            )
            draw.text(
                (x, y),
                line,
                font=self.font_headline,
                fill=self.theme.text_rgb,
            )
            y += 84

    def _draw_subheadline(
        self,
        draw: ImageDraw.ImageDraw,
        subheadline: str,
    ) -> None:
        max_width = int(self.theme.width * 0.66)
        lines = _wrap_text(
            draw,
            subheadline,
            self.font_subheadline,
            max_width,
            max_lines=2,
        )

        y = self.theme.height - 130
        for line in lines:
            draw.text(
                (self.theme.margin, y),
                line,
                font=self.font_subheadline,
                fill=(225, 231, 239),
            )
            y += 42

    def _draw_accent_bar(self, draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle(
            (
                0,
                self.theme.height - 14,
                self.theme.width,
                self.theme.height,
            ),
            fill=self.theme.brand_rgb,
        )
        draw.rectangle(
            (
                0,
                self.theme.height - 14,
                280,
                self.theme.height,
            ),
            fill=self.theme.accent_rgb,
        )

    def _calculate_quality_score(
        self,
        thumbnail_input: ThumbnailInput,
        placeholder_used: bool,
        warnings: Sequence[str],
    ) -> float:
        score = 100.0

        headline_length = len(thumbnail_input.headline.strip())

        if headline_length < 8:
            score -= 12.0
        elif headline_length > 110:
            score -= 10.0

        if placeholder_used:
            score -= 15.0

        if not thumbnail_input.category.strip():
            score -= 4.0

        score -= min(10.0, len(warnings) * 2.0)

        return round(max(0.0, min(100.0, score)), 2)

    def write_manifest(self, result: ThumbnailResult) -> Path:
        if result.manifest_path is None:
            raise ValueError("Thumbnail manifest path is not configured.")

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

    def summarize(
        self,
        results: Sequence[ThumbnailResult],
    ) -> ThumbnailSummary:
        return ThumbnailSummary.from_results(results)


def generate_thumbnail(
    value: Any,
    *,
    output_path: str | Path | None = None,
    config: ThumbnailConfig | None = None,
) -> ThumbnailResult:
    return ThumbnailGenerator(config=config).generate(
        value,
        output_path=output_path,
    )


def _create_test_image(path: Path) -> None:
    image = Image.new("RGB", (1000, 700), (40, 80, 120))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 920, 620), fill=(70, 130, 170))
    draw.ellipse((550, 110, 930, 490), fill=(220, 170, 80))
    draw.text((170, 320), "BAHUVU TEST IMAGE", fill=(255, 255, 255))
    image.save(path)


def _run_self_test() -> None:
    with tempfile.TemporaryDirectory(
        prefix="bahuvu_thumbnail_test_"
    ) as temp_dir:
        root = Path(temp_dir)
        sample_image = root / "lead_story.jpg"
        _create_test_image(sample_image)

        config = ThumbnailConfig(
            output_dir=root / "thumbnails",
            write_manifest=True,
            overwrite=True,
        )

        generator = ThumbnailGenerator(config=config)

        result = generator.generate(
            ThumbnailInput(
                headline="తీర ప్రాంతాలకు భారీ వర్ష హెచ్చరిక",
                category="WEATHER",
                image_path=str(sample_image),
                bulletin_id="bahuvu_july_demo",
                story_id="story_weather",
                subheadline="పలు జిల్లాలకు ఆరెంజ్ అలర్ట్ జారీ",
            )
        )

        assert result.success, result.error
        assert result.output_path is not None
        assert result.output_path.exists()
        assert result.output_path.stat().st_size > 0
        assert result.manifest_path is not None
        assert result.manifest_path.exists()
        assert result.width == 1280
        assert result.height == 720
        assert result.placeholder_used is False
        assert result.quality_score >= 80.0

        with Image.open(result.output_path) as rendered:
            assert rendered.size == (1280, 720)

        loaded = json.loads(
            result.manifest_path.read_text(encoding="utf-8")
        )
        assert loaded["status"] == "generated"
        assert loaded["success"] is True
        assert loaded["input"]["category"] == "WEATHER"

        placeholder_result = generator.generate(
            ThumbnailInput(
                headline="కొత్త విద్యా కార్యక్రమానికి ఆమోదం",
                category="EDUCATION",
                image_path=str(root / "missing.jpg"),
                bulletin_id="bahuvu_placeholder_demo",
            )
        )

        assert placeholder_result.success
        assert placeholder_result.placeholder_used is True
        assert placeholder_result.output_path is not None
        assert placeholder_result.output_path.exists()

        summary = generator.summarize(
            [result, placeholder_result]
        )
        assert summary.processed == 2
        assert summary.generated == 2
        assert summary.failed == 0
        assert summary.total_bytes > 0

        print("Thumbnail generator initialized successfully.")
        print()
        print(f"Thumbnails generated    : {summary.generated}")
        print(f"Primary dimensions      : {result.width}x{result.height}")
        print(f"Primary quality score   : {result.quality_score:.2f}")
        print(f"Placeholder fallback    : {placeholder_result.placeholder_used}")
        print(f"Manifest written        : {result.manifest_path.exists()}")
        print(f"Output created          : {result.output_path.exists()}")
        print()
        print("Thumbnail generator self-test passed.")


if __name__ == "__main__":
    _run_self_test()