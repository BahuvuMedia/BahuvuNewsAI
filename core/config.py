"""
BahuvuNewsAI
core/config.py

Central project configuration.

This module provides:
- Stable project paths
- Environment-variable loading
- Runtime settings
- Directory creation
- Configuration validation
- A reusable singleton settings object
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from core.exceptions import ConfigurationError


# ------------------------------------------------------------------
# Project Root
# ------------------------------------------------------------------

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------
# Environment Helpers
# ------------------------------------------------------------------

def _load_dotenv() -> None:
    """
    Load variables from the project's .env file when python-dotenv
    is installed.

    The project can still run without a .env file.
    """

    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    load_dotenv(PROJECT_ROOT / ".env")


def _get_bool(name: str, default: bool) -> bool:
    """
    Read a boolean environment variable.
    """

    value = os.getenv(name)

    if value is None:
        return default

    normalized = value.strip().lower()

    if normalized in {"1", "true", "yes", "on"}:
        return True

    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ConfigurationError(
        f"Environment variable {name} must be a boolean value."
    )


def _get_int(name: str, default: int) -> int:
    """
    Read an integer environment variable.
    """

    value = os.getenv(name)

    if value is None:
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(
            f"Environment variable {name} must be an integer."
        ) from exc


def _get_float(name: str, default: float) -> float:
    """
    Read a floating-point environment variable.
    """

    value = os.getenv(name)

    if value is None:
        return default

    try:
        return float(value)
    except ValueError as exc:
        raise ConfigurationError(
            f"Environment variable {name} must be a number."
        ) from exc


_load_dotenv()


# ------------------------------------------------------------------
# Application Settings
# ------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    """
    Immutable central configuration for BahuvuNewsAI.

    Environment variables may override selected defaults.
    """

    # --------------------------------------------------------------
    # Application
    # --------------------------------------------------------------

    app_name: str = "BahuvuNewsAI"
    environment: str = field(
        default_factory=lambda: os.getenv(
            "BAHUVU_ENVIRONMENT",
            "development",
        ).strip().lower()
    )

    debug: bool = field(
        default_factory=lambda: _get_bool(
            "BAHUVU_DEBUG",
            False,
        )
    )

    # --------------------------------------------------------------
    # Branding
    # --------------------------------------------------------------

    channel_name: str = field(
        default_factory=lambda: os.getenv(
            "BAHUVU_CHANNEL_NAME",
            "BAHUVU NEWS",
        ).strip()
    )

    default_language: str = field(
        default_factory=lambda: os.getenv(
            "BAHUVU_DEFAULT_LANGUAGE",
            "en",
        ).strip().lower()
    )

    target_language: str = field(
        default_factory=lambda: os.getenv(
            "BAHUVU_TARGET_LANGUAGE",
            "te",
        ).strip().lower()
    )

    # --------------------------------------------------------------
    # Project Paths
    # --------------------------------------------------------------

    project_root: Path = PROJECT_ROOT

    agents_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "agents"
    )

    assets_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "assets"
    )

    outputs_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "outputs"
    )

    logs_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "logs"
    )

    temp_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "temp"
    )

    data_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "data"
    )

    graphics_output_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "outputs" / "graphics"
    )

    audio_output_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "outputs" / "audio"
    )

    video_output_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "outputs" / "video"
    )

    thumbnail_output_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "outputs" / "thumbnails"
    )

    final_output_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "outputs" / "final"
    )

    # --------------------------------------------------------------
    # Editorial Quality Thresholds
    # --------------------------------------------------------------

    minimum_quality_score: float = field(
        default_factory=lambda: _get_float(
            "BAHUVU_MINIMUM_QUALITY_SCORE",
            70.0,
        )
    )

    minimum_source_count: int = field(
        default_factory=lambda: _get_int(
            "BAHUVU_MINIMUM_SOURCE_COUNT",
            2,
        )
    )

    require_fact_check: bool = field(
        default_factory=lambda: _get_bool(
            "BAHUVU_REQUIRE_FACT_CHECK",
            True,
        )
    )

    require_editorial_approval: bool = field(
        default_factory=lambda: _get_bool(
            "BAHUVU_REQUIRE_EDITORIAL_APPROVAL",
            True,
        )
    )

    # --------------------------------------------------------------
    # Media Settings
    # --------------------------------------------------------------

    video_width: int = field(
        default_factory=lambda: _get_int(
            "BAHUVU_VIDEO_WIDTH",
            1280,
        )
    )

    video_height: int = field(
        default_factory=lambda: _get_int(
            "BAHUVU_VIDEO_HEIGHT",
            720,
        )
    )

    video_fps: int = field(
        default_factory=lambda: _get_int(
            "BAHUVU_VIDEO_FPS",
            24,
        )
    )

    # --------------------------------------------------------------
    # Pipeline Settings
    # --------------------------------------------------------------

    stop_on_error: bool = field(
        default_factory=lambda: _get_bool(
            "BAHUVU_STOP_ON_ERROR",
            True,
        )
    )

    continue_on_warning: bool = field(
        default_factory=lambda: _get_bool(
            "BAHUVU_CONTINUE_ON_WARNING",
            True,
        )
    )

    max_pipeline_retries: int = field(
        default_factory=lambda: _get_int(
            "BAHUVU_MAX_PIPELINE_RETRIES",
            2,
        )
    )

    # --------------------------------------------------------------
    # Methods
    # --------------------------------------------------------------

    def create_directories(self) -> None:
        """
        Create all standard runtime directories.
        """

        directories = (
            self.assets_dir,
            self.outputs_dir,
            self.logs_dir,
            self.temp_dir,
            self.data_dir,
            self.graphics_output_dir,
            self.audio_output_dir,
            self.video_output_dir,
            self.thumbnail_output_dir,
            self.final_output_dir,
        )

        for directory in directories:
            directory.mkdir(
                parents=True,
                exist_ok=True,
            )

    def validate(self) -> None:
        """
        Validate configuration values.

        Raises:
            ConfigurationError:
                If an invalid setting is found.
        """

        valid_environments = {
            "development",
            "testing",
            "production",
        }

        if self.environment not in valid_environments:
            raise ConfigurationError(
                "BAHUVU_ENVIRONMENT must be one of: "
                "development, testing, production."
            )

        if not self.channel_name:
            raise ConfigurationError(
                "Channel name cannot be empty."
            )

        if not self.default_language:
            raise ConfigurationError(
                "Default language cannot be empty."
            )

        if not self.target_language:
            raise ConfigurationError(
                "Target language cannot be empty."
            )

        if not 0.0 <= self.minimum_quality_score <= 100.0:
            raise ConfigurationError(
                "Minimum quality score must be between 0 and 100."
            )

        if self.minimum_source_count < 1:
            raise ConfigurationError(
                "Minimum source count must be at least 1."
            )

        if self.video_width <= 0 or self.video_height <= 0:
            raise ConfigurationError(
                "Video dimensions must be greater than zero."
            )

        if self.video_fps <= 0:
            raise ConfigurationError(
                "Video FPS must be greater than zero."
            )

        if self.max_pipeline_retries < 0:
            raise ConfigurationError(
                "Maximum pipeline retries cannot be negative."
            )

    def initialize(self) -> None:
        """
        Validate settings and prepare runtime directories.
        """

        self.validate()
        self.create_directories()


# ------------------------------------------------------------------
# Shared Settings Instance
# ------------------------------------------------------------------

settings = Settings()


def get_settings() -> Settings:
    """
    Return the shared immutable settings object.
    """

    return settings


# ------------------------------------------------------------------
# Self Test
# ------------------------------------------------------------------

if __name__ == "__main__":
    settings.initialize()

    print("Configuration initialized successfully.")
    print(f"Application: {settings.app_name}")
    print(f"Environment: {settings.environment}")
    print(f"Project root: {settings.project_root}")
    print(f"Outputs directory: {settings.outputs_dir}")
    print(
        "Video format: "
        f"{settings.video_width}x{settings.video_height} "
        f"at {settings.video_fps} FPS"
    )
    print(
        "Editorial threshold: "
        f"{settings.minimum_quality_score}"
    )