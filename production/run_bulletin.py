"""
BahuvuNewsAI - Live Bulletin Runner
===================================

Collects live RSS news and sends the resulting NewsArticle objects through
the existing BahuvuNewsAI production pipeline.

This file does not replace or redesign any existing module. It only connects:

    NewsSource
        -> FetchScheduler
        -> ProductionRequest
        -> ProductionPipeline
        -> Integrated production handlers

Examples:

    Collect live news only:
        python -m production.run_bulletin --collect-only

    Test collection and editorial selection:
        python -m production.run_bulletin --mode dry-run

    Render video and thumbnail without YouTube upload:
        python -m production.run_bulletin --mode render-only

    Render and upload privately:
        python -m production.run_bulletin --mode upload-private

    Run all production stages:
        python -m production.run_bulletin --mode full-production
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

import requests
from bs4 import BeautifulSoup

from news.fetch_scheduler import FetchScheduler, FetchSchedulerConfig
from news.models import (
    LanguageCode,
    NewsCategory,
    NewsSource,
    SourceType,
)
from production.integrations import build_integrated_handlers
from production.pipeline import (
    PipelineStage,
    ProductionConfig,
    ProductionMode,
    ProductionPipeline,
    ProductionRequest,
)


# =============================================================================
# DEFAULT LIVE SOURCES
# =============================================================================


BBC_INDIA_RSS = (
    "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml"
)

THE_HINDU_HOME_RSS = (
    "https://www.thehindu.com/feeder/default.rss"
)

DEFAULT_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "application/rss+xml, application/xml, text/xml, "
        "text/html;q=0.9, */*;q=0.8"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Cache-Control": "no-cache",
}


def build_default_sources() -> list[NewsSource]:
    """
    Return the initial live production source list.

    PIB is temporarily excluded because its server currently returns HTTP 403
    to automated RSS requests. It can be restored after source-specific access
    handling is added.
    """

    return [
        NewsSource(
            name="BBC News India",
            source_type=SourceType.RSS,
            url=BBC_INDIA_RSS,
            language=LanguageCode.ENGLISH,
            default_category=NewsCategory.NATIONAL,
            reliability_score=88.0,
            priority=90,
            fetch_interval_minutes=15,
            request_timeout_seconds=30,
            country="India",
            region="National",
            publisher="BBC News",
            headers=dict(DEFAULT_BROWSER_HEADERS),
            metadata={
                "production_source": True,
                "source_group": "news_media",
            },
        ),
        NewsSource(
            name="The Hindu",
            source_type=SourceType.RSS,
            url=THE_HINDU_HOME_RSS,
            language=LanguageCode.ENGLISH,
            default_category=NewsCategory.NATIONAL,
            reliability_score=90.0,
            priority=92,
            fetch_interval_minutes=15,
            request_timeout_seconds=30,
            country="India",
            region="National",
            publisher="The Hindu",
            headers=dict(DEFAULT_BROWSER_HEADERS),
            metadata={
                "production_source": True,
                "source_group": "news_media",
            },
        ),
    ]

# =============================================================================
# GENERIC HELPERS
# =============================================================================


def to_mapping(value: Any) -> dict[str, Any]:
    """Convert supported objects into a regular dictionary."""

    if value is None:
        return {}

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


def text_value(value: Any) -> str:
    """Return a clean printable string."""

    if value is None:
        return ""

    return str(value).strip()


def article_title(article: Any) -> str:
    """Return an article title without depending on one exact model shape."""

    mapping = to_mapping(article)

    for key in ("title", "headline", "name"):
        value = mapping.get(key)
        if value:
            return text_value(value)

    return "(untitled article)"


def article_publisher(article: Any) -> str:
    """Return an article publisher/source name."""

    mapping = to_mapping(article)

    for key in ("publisher", "source_name", "source"):
        value = mapping.get(key)
        if value:
            return text_value(value)

    return "(unknown publisher)"


def article_category(article: Any) -> str:
    """Return a printable category."""

    mapping = to_mapping(article)
    value = mapping.get("category")

    if hasattr(value, "value"):
        return text_value(value.value)

    return text_value(value) or "other"


def parse_mode(value: str) -> ProductionMode:
    """Convert a command-line mode into ProductionMode."""

    normalized = value.strip().lower()

    mapping = {
        ProductionMode.DRY_RUN.value: ProductionMode.DRY_RUN,
        ProductionMode.RENDER_ONLY.value: ProductionMode.RENDER_ONLY,
        ProductionMode.UPLOAD_PRIVATE.value: ProductionMode.UPLOAD_PRIVATE,
        ProductionMode.FULL_PRODUCTION.value: ProductionMode.FULL_PRODUCTION,
    }

    try:
        return mapping[normalized]
    except KeyError as exc:
        supported = ", ".join(mapping)
        raise ValueError(
            f"Unsupported production mode '{value}'. "
            f"Supported modes: {supported}"
        ) from exc


def default_stop_stage(mode: ProductionMode) -> PipelineStage | None:
    """
    Select the safest default stopping point.

    Dry-run first proves live collection and editorial processing.
    Rendering modes continue through thumbnail generation.
    Upload modes continue through the upload stage.
    """

    if mode == ProductionMode.DRY_RUN:
        return PipelineStage.EDITORIAL

    if mode == ProductionMode.RENDER_ONLY:
        return PipelineStage.THUMBNAIL

    return PipelineStage.UPLOAD


def build_production_id() -> str:
    """Create a filesystem-safe production identifier."""

    return datetime.now().strftime("bahuvu_live_%Y%m%d_%H%M%S")


def ensure_directory(path: Path) -> Path:
    """Create an output directory and return it."""

    path.mkdir(parents=True, exist_ok=True)
    return path

# =============================================================================
# ARTICLE ENRICHMENT
# =============================================================================


def get_article_url(article: Any) -> str:
    """Return the best available article URL."""

    mapping = to_mapping(article)

    for key in (
        "article_url",
        "canonical_url",
        "url",
        "link",
    ):
        value = mapping.get(key)
        if value:
            return text_value(value)

    return ""


def existing_article_body(article: Any) -> str:
    """Return existing body text when the collector already supplied it."""

    mapping = to_mapping(article)

    for key in (
        "cleaned_text",
        "raw_text",
        "description",
        "content",
        "body",
        "article_text",
        "text",
    ):
        value = mapping.get(key)
        if value and len(text_value(value)) >= 250:
            return text_value(value)

    return ""


def extract_page_text(
    url: str,
    *,
    timeout_seconds: int = 30,
) -> tuple[str, str]:
    """
    Download an article page and extract its description and body.

    This is intentionally generic and conservative. It prefers paragraphs
    inside the HTML article element and falls back to substantial page
    paragraphs when an article element is unavailable.
    """

    response = requests.get(
        url,
        headers=dict(DEFAULT_BROWSER_HEADERS),
        timeout=timeout_seconds,
        allow_redirects=True,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for element in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "form",
            "nav",
            "footer",
            "aside",
        ]
    ):
        element.decompose()

    description = ""

    description_element = soup.find(
        "meta",
        attrs={"name": "description"},
    )

    if description_element is None:
        description_element = soup.find(
            "meta",
            attrs={"property": "og:description"},
        )

    if description_element is not None:
        description = text_value(
            description_element.get("content", "")
        )

    article_element = soup.find("article")

    if article_element is not None:
        paragraph_elements = article_element.find_all("p")
    else:
        paragraph_elements = soup.find_all("p")

    paragraphs: list[str] = []
    seen: set[str] = set()

    for paragraph_element in paragraph_elements:
        paragraph = " ".join(
            paragraph_element.get_text(
                " ",
                strip=True,
            ).split()
        )

        if len(paragraph) < 45:
            continue

        normalized = paragraph.casefold()

        if normalized in seen:
            continue

        seen.add(normalized)
        paragraphs.append(paragraph)

    body = "\n\n".join(paragraphs)

    # Prevent menus, related links and other page material from producing
    # excessively large article records.
    if len(body) > 12000:
        body = body[:12000].rsplit(" ", 1)[0]

    if not description and body:
        description = body[:500].rsplit(" ", 1)[0]

    return description, body


def enrich_article(article: Any) -> bool:
    """Populate summary and content by reading the linked article page."""

    if existing_article_body(article):
        return True

    url = get_article_url(article)

    if not url:
        return False

    try:
        description, body = extract_page_text(url)
    except requests.RequestException as exc:
        print(
            "Article enrichment failed "
            f"| title={article_title(article)} "
            f"| error={type(exc).__name__}: {exc}"
        )
        return False
    except Exception as exc:
        print(
            "Article parsing failed "
            f"| title={article_title(article)} "
            f"| error={type(exc).__name__}: {exc}"
        )
        return False

    if len(body) < 250:
        print(
            "Article enrichment returned insufficient text "
            f"| title={article_title(article)} "
            f"| characters={len(body)}"
        )
        return False

    from news.content_cleaner import (
        assert_clean_content,
        clean_publisher_content,
    )

    cleaned_body = clean_publisher_content(body)

    if len(cleaned_body) < 250:
        print(
            "Article enrichment produced insufficient newsroom-safe text "
            f"| title={article_title(article)} "
            f"| raw_characters={len(body)} "
            f"| cleaned_characters={len(cleaned_body)}"
        )
        return False

    assert_clean_content(cleaned_body)

    if hasattr(article, "raw_text"):
        article.raw_text = body

    if hasattr(article, "cleaned_text"):
        article.cleaned_text = cleaned_body

    if hasattr(article, "description"):
        current_description = text_value(
            getattr(article, "description", "")
        )

        if not current_description:
            article.description = description or cleaned_body[:500]

    if hasattr(article, "summary"):
        current_summary = text_value(
            getattr(article, "summary", "")
        )

        if not current_summary:
            article.summary = description or cleaned_body[:500]

    if hasattr(article, "metadata"):
        metadata = dict(
            getattr(article, "metadata", {}) or {}
        )
        metadata.update(
            {
                "page_enriched": True,
                "enriched_url": url,
                "enriched_body_characters": len(body),
                "cleaned_body_characters": len(cleaned_body),
                "publisher_boilerplate_removed": len(cleaned_body) < len(body),
            }
        )
        article.metadata = metadata

    return True


def enrich_articles(
    articles: Iterable[Any],
) -> tuple[list[Any], int]:
    """Enrich live RSS articles and retain only usable records."""

    enriched: list[Any] = []
    failed = 0

    for index, article in enumerate(articles, start=1):
        print(
            f"Enriching article {index}: "
            f"{article_title(article)}"
        )

        if enrich_article(article):
            enriched.append(article)
        else:
            failed += 1

    return enriched, failed

# =============================================================================
# LIVE COLLECTION
# =============================================================================


def collect_live_articles(
    sources: Iterable[NewsSource],
    *,
    force: bool = True,
    concurrent: bool = True,
) -> tuple[Any, list[Any]]:
    """Collect live articles through the existing FetchScheduler."""

    scheduler = FetchScheduler(
        config=FetchSchedulerConfig(
            max_workers=4,
            max_retries=2,
            retry_backoff_seconds=1.0,
            retry_backoff_multiplier=2.0,
            maximum_retry_delay_seconds=10.0,
            perform_health_checks=False,
            skip_unhealthy_sources=False,
            respect_fetch_intervals=not force,
            concurrent=concurrent,
        ),
        register_default_collectors=True,
    )

    result = scheduler.run(
        list(sources),
        force=force,
        concurrent=concurrent,
    )

    articles = list(result.articles)

    return result, articles


def print_collection_report(fetch_result: Any, articles: list[Any]) -> None:
    """Print a readable live-news collection report."""

    summary = fetch_result.summary()

    print()
    print("=" * 72)
    print("BAHUVU NEWS - LIVE COLLECTION REPORT")
    print("=" * 72)
    print(f"Run ID               : {summary.get('run_id', fetch_result.run_id)}")
    print(f"Sources considered   : {fetch_result.total_sources}")
    print(f"Sources processed    : {fetch_result.processed_sources}")
    print(f"Sources successful   : {fetch_result.successful_sources}")
    print(f"Sources failed       : {fetch_result.failed_sources}")
    print(f"Sources skipped      : {fetch_result.skipped_sources}")
    print(f"Sources retried      : {fetch_result.retried_sources}")
    print(f"Raw items            : {fetch_result.raw_items_count}")
    print(f"Rejected feed items  : {fetch_result.rejected_items_count}")
    print(f"Articles collected   : {len(articles)}")
    print(f"Collection success   : {fetch_result.success}")
    print("-" * 72)

    preview_limit = min(10, len(articles))

    if preview_limit:
        print("Collected article preview:")

        for index, article in enumerate(
            articles[:preview_limit],
            start=1,
        ):
            print(
                f"{index}. {article_title(article)} "
                f"| {article_publisher(article)} "
                f"| {article_category(article)}"
            )
    else:
        print("No articles were collected.")

    print("=" * 72)


def save_collection_snapshot(
    output_directory: Path,
    fetch_result: Any,
) -> Path:
    """Save the collection result for diagnosis and audit."""

    snapshot_path = output_directory / "live_collection.json"

    payload = fetch_result.to_dict(include_articles=True)

    snapshot_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    return snapshot_path


# =============================================================================
# PRODUCTION PIPELINE
# =============================================================================


def build_request(
    *,
    production_id: str,
    mode: ProductionMode,
    articles: list[Any],
    stop_stage: PipelineStage | None,
) -> ProductionRequest:
    """Build the canonical request consumed by ProductionPipeline."""

    date_label = datetime.now().strftime("%d %B %Y")
    title = f"BAHUVU NEWS | Telugu News Bulletin | {date_label}"

    description = (
        "BAHUVU NEWS automated Telugu news bulletin.\n\n"
        "News was collected, editorially processed, scripted, translated, "
        "rendered and prepared through the BahuvuNewsAI production pipeline."
    )

    return ProductionRequest(
        production_id=production_id,
        bulletin_id=production_id,
        mode=mode,
        stories=articles,
        metadata={
            "edition": "Bahuvu Live News Bulletin",
            "edition_date": date_label,
            "language": "te",
            "default_language": "te",
            "default_audio_language": "te",
            "country": "India",
            "youtube_upload": mode
            in {
                ProductionMode.UPLOAD_PRIVATE,
                ProductionMode.FULL_PRODUCTION,
            },
            "youtube_title": title,
            "title": title,
            "youtube_description": description,
            "description": description,
            "youtube_tags": [
                "Bahuvu News",
                "Telugu News",
                "India News",
                "Latest News",
                "BahuvuNewsAI",
            ],
            "tags": [
                "Bahuvu News",
                "Telugu News",
                "India News",
                "Latest News",
                "BahuvuNewsAI",
            ],
            "category_id": "25",
            "privacy_status": "private",
            "made_for_kids": False,
            "embeddable": True,
            "live_news": True,
            "source_count": 2,
            "article_count": len(articles),
        },
        resume=False,
        start_stage=None,
        stop_stage=stop_stage,
    )


def run_production(
    request: ProductionRequest,
    *,
    output_root: Path,
) -> Any:
    """Run the existing integrated production pipeline."""

    pipeline = ProductionPipeline(
        config=ProductionConfig(
            output_dir=output_root,
            manifest_filename="production_manifest.json",
            continue_on_optional_failure=False,
            resume_completed_stages=False,
            write_manifest_after_each_stage=True,
            upload_privacy_default="private",
        ),
        handlers=build_integrated_handlers(),
    )

    return pipeline.run(request)


def print_production_report(result: Any) -> None:
    """Print one line for every executed production stage."""

    print()
    print("=" * 72)
    print("BAHUVU NEWS - PRODUCTION REPORT")
    print("=" * 72)
    print(f"Production ID  : {result.production_id}")
    print(f"Mode           : {result.mode.value}")
    print(f"Status         : {result.status.value}")
    print(f"Manifest       : {result.manifest_path}")
    print("-" * 72)

    for record in result.stages:
        duration = f"{record.duration_seconds:.2f}s"

        print(
            f"{record.stage.value:<12} "
            f"{record.status.value:<10} "
            f"{duration:>10}"
        )

        if record.error:
            print(f"  Error: {record.error}")

    print("-" * 72)

    if result.error:
        print(f"Pipeline error : {result.error}")

    print("=" * 72)


# =============================================================================
# COMMAND-LINE INTERFACE
# =============================================================================


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect live news and run the BahuvuNewsAI production pipeline."
        )
    )

    parser.add_argument(
        "--mode",
        choices=[
            ProductionMode.DRY_RUN.value,
            ProductionMode.RENDER_ONLY.value,
            ProductionMode.UPLOAD_PRIVATE.value,
            ProductionMode.FULL_PRODUCTION.value,
        ],
        default=ProductionMode.DRY_RUN.value,
        help=(
            "Production mode. The default dry-run stops after editorial "
            "selection."
        ),
    )

    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Collect and display live articles without running production.",
    )

    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("outputs/production"),
        help="Parent directory for live production outputs.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Maximum articles passed into the editorial pipeline.",
    )

    parser.add_argument(
        "--no-force",
        action="store_true",
        help="Respect each source's configured fetch interval.",
    )

    parser.add_argument(
        "--sequential",
        action="store_true",
        help="Disable concurrent source collection.",
    )

    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    if arguments.limit < 1:
        raise ValueError("--limit must be at least 1.")

    production_id = build_production_id()
    production_directory = ensure_directory(
        arguments.output_root / production_id
    )

    sources = build_default_sources()

    print("BahuvuNewsAI live bulletin runner")
    print(f"Production ID : {production_id}")
    print(f"Sources       : {len(sources)}")
    print(f"Output        : {production_directory}")

    fetch_result, articles = collect_live_articles(
        sources,
        force=not arguments.no_force,
        concurrent=not arguments.sequential,
    )

    print_collection_report(fetch_result, articles)

    snapshot_path = save_collection_snapshot(
        production_directory,
        fetch_result,
    )

    print(f"Collection snapshot: {snapshot_path}")

    if not articles:
        print(
            "Live collection returned no articles. "
            "Production was not started."
        )
        return 2

    if arguments.collect_only:
        print()
        print("Collection-only run completed successfully.")
        return 0
    candidate_articles = articles[: arguments.limit]

    print()
    print("=" * 72)
    print("ENRICHING LIVE ARTICLES")
    print("=" * 72)
    print(
        f"Articles selected for enrichment: "
        f"{len(candidate_articles)}"
    )

    selected_articles, enrichment_failures = enrich_articles(
        candidate_articles
    )

    print("-" * 72)
    print(
        f"Articles enriched successfully : "
        f"{len(selected_articles)}"
    )
    print(
        f"Article enrichment failures    : "
        f"{enrichment_failures}"
    )
    print("=" * 72)

    if not selected_articles:
        print(
            "No articles contained sufficient page text. "
            "Production was not started."
        )
        return 3

    mode = parse_mode(arguments.mode)
    stop_stage = default_stop_stage(mode)

    request = build_request(
        production_id=production_id,
        mode=mode,
        articles=selected_articles,
        stop_stage=stop_stage,
    )

    result = run_production(
        request,
        output_root=arguments.output_root,
    )

    print_production_report(result)

    if result.status.value in {"completed", "partial"}:
        return 0

    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        raise SystemExit(130)
    except Exception as exc:
        print()
        print("=" * 72)
        print("LIVE BULLETIN RUN FAILED")
        print("=" * 72)
        print(f"{type(exc).__name__}: {exc}")
        print("=" * 72)
        raise