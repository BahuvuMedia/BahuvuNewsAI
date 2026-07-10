"""
BahuvuNewsAI
core/context.py

Central runtime context shared by every agent.

Every pipeline stage receives a NewsContext object,
reads the fields it needs, updates the fields it owns,
and passes the same object to the next stage.

This file intentionally contains no business logic.
It only defines the shared state model.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class NewsContext:
    """
    Shared runtime context for a single news story.
    """

    # ---------------------------------------------------------
    # Pipeline Metadata
    # ---------------------------------------------------------

    story_id: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    pipeline_status: str = "initialized"

    # ---------------------------------------------------------
    # Source Information
    # ---------------------------------------------------------

    source_name: str = ""
    source_url: str = ""

    category: str = ""
    language: str = "en"

    # ---------------------------------------------------------
    # Raw Content
    # ---------------------------------------------------------

    original_title: str = ""
    original_summary: str = ""
    original_article: str = ""

    # ---------------------------------------------------------
    # Editorial
    # ---------------------------------------------------------

    headline: str = ""
    summary: str = ""
    article: str = ""

    # ---------------------------------------------------------
    # Telugu Content
    # ---------------------------------------------------------

    telugu_headline: str = ""
    telugu_summary: str = ""
    telugu_article: str = ""

    # ---------------------------------------------------------
    # Quality
    # ---------------------------------------------------------

    quality_score: float = 0.0

    fact_checked: bool = False
    duplicate: bool = False
    bias_checked: bool = False
    approved: bool = False

    # ---------------------------------------------------------
    # Media
    # ---------------------------------------------------------

    image_url: str = ""
    local_image: str = ""

    graphic_path: str = ""
    voice_path: str = ""
    video_path: str = ""
    thumbnail_path: str = ""

    # ---------------------------------------------------------
    # Publishing
    # ---------------------------------------------------------

    youtube_title: str = ""
    youtube_description: str = ""
    youtube_tags: list[str] = field(default_factory=list)

    # ---------------------------------------------------------
    # Diagnostics
    # ---------------------------------------------------------

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------
    # Utility Methods
    # ---------------------------------------------------------

    def touch(self) -> None:
        """
        Update modification timestamp.
        """
        self.updated_at = datetime.utcnow()

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.touch()

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)
        self.touch()

    def set_status(self, status: str) -> None:
        self.pipeline_status = status
        self.touch()

    def output_directory(self) -> Path:
        """
        Return output directory for this story.
        """
        directory = Path("outputs") / self.story_id

        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        return directory