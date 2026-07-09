# agents/news_source_manager.py

"""
BahuvuNewsAI - News Source Manager
Version: v2.1

Purpose:
- Central place to manage all news sources.
- Supports future RSS, API, website, and manual providers.
- Normalizes incoming news into clean article dictionaries.
- Removes duplicate stories.
- Keeps the rest of the pipeline independent from source details.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional
import hashlib


@dataclass
class NewsSource:
    name: str
    source_type: str
    url: str
    language: str = "en"
    region: str = "India"
    category: str = "general"
    active: bool = True
    priority: int = 5


@dataclass
class SourceArticle:
    title: str
    summary: str
    source_name: str
    url: str = ""
    category: str = "general"
    language: str = "en"
    region: str = "India"
    published_at: Optional[str] = None
    image_url: Optional[str] = None
    importance_score: int = 0
    article_id: str = field(default="")


class NewsSourceManager:
    def __init__(self):
        self.sources: List[NewsSource] = []

    def add_source(self, source: NewsSource):
        if source.active:
            self.sources.append(source)

    def get_sources(self) -> List[NewsSource]:
        return sorted(
            self.sources,
            key=lambda item: item.priority,
            reverse=True,
        )

    def create_article_id(self, title: str, source_name: str) -> str:
        raw = f"{title.strip().lower()}::{source_name.strip().lower()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def normalize_article(
        self,
        title: str,
        summary: str,
        source_name: str,
        url: str = "",
        category: str = "general",
        language: str = "en",
        region: str = "India",
        published_at: Optional[str] = None,
        image_url: Optional[str] = None,
    ) -> SourceArticle:

        article_id = self.create_article_id(title, source_name)

        return SourceArticle(
            title=title.strip(),
            summary=summary.strip(),
            source_name=source_name.strip(),
            url=url.strip(),
            category=category.strip().lower(),
            language=language.strip().lower(),
            region=region.strip(),
            published_at=published_at or datetime.now().isoformat(timespec="seconds"),
            image_url=image_url,
            article_id=article_id,
        )

    def remove_duplicates(self, articles: List[SourceArticle]) -> List[SourceArticle]:
        seen = set()
        unique_articles = []

        for article in articles:
            key = article.title.strip().lower()

            if key not in seen:
                seen.add(key)
                unique_articles.append(article)

        return unique_articles

    def fetch_mock_articles(self) -> List[SourceArticle]:
        """
        Temporary test provider.
        Later this will be replaced by real RSS/API fetching.
        """

        articles = [
            self.normalize_article(
                title="Heavy Rain Continues Across Andhra Pradesh",
                summary="Officials advise people to stay alert as heavy rainfall continues in several districts.",
                source_name="Mock Weather Source",
                category="weather",
                language="en",
                region="Andhra Pradesh",
                image_url="assets/images/sample.jpg",
            ),
            self.normalize_article(
                title="Government Reviews Flood Preparedness Measures",
                summary="Authorities reviewed emergency response systems and district-level preparedness.",
                source_name="Mock Governance Source",
                category="governance",
                language="en",
                region="India",
                image_url="assets/images/sample.jpg",
            ),
        ]

        return self.remove_duplicates(articles)

    def get_latest_articles(self) -> List[SourceArticle]:
        """
        Main public method used by the rest of BahuvuNewsAI.
        """

        articles = self.fetch_mock_articles()
        return self.remove_duplicates(articles)


def build_default_source_manager() -> NewsSourceManager:
    manager = NewsSourceManager()

    manager.add_source(
        NewsSource(
            name="Mock Weather Source",
            source_type="mock",
            url="local://mock-weather",
            language="en",
            region="Andhra Pradesh",
            category="weather",
            priority=10,
        )
    )

    manager.add_source(
        NewsSource(
            name="Mock Governance Source",
            source_type="mock",
            url="local://mock-governance",
            language="en",
            region="India",
            category="governance",
            priority=8,
        )
    )

    return manager


if __name__ == "__main__":
    manager = build_default_source_manager()
    articles = manager.get_latest_articles()

    print("=" * 60)
    print("BahuvuNewsAI News Source Manager v2.1")
    print("=" * 60)
    print(f"Active sources: {len(manager.get_sources())}")
    print(f"Articles fetched: {len(articles)}")
    print("-" * 60)

    for index, article in enumerate(articles, start=1):
        print(f"{index}. {article.title}")
        print(f"   Category : {article.category}")
        print(f"   Region   : {article.region}")
        print(f"   Source   : {article.source_name}")
        print(f"   Image    : {article.image_url}")
        print(f"   ID       : {article.article_id}")
        print()