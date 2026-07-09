# agents/rss_feed_engine.py

"""
BahuvuNewsAI - RSS Feed Engine
Version: v2.2

Purpose:
- Fetch RSS feeds using built-in Python libraries.
- Parse feed items safely.
- Convert RSS entries into standardized SourceArticle objects.
- Work with NewsSourceManager without disturbing downstream agents.
"""

from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from xml.etree import ElementTree as ET
from typing import List, Optional
from html import unescape
import re

from agents.news_source_manager import (
    NewsSource,
    NewsSourceManager,
    SourceArticle,
    build_default_source_manager,
)


USER_AGENT = "BahuvuNewsAI/2.2"


def clean_html(text: Optional[str]) -> str:
    if not text:
        return ""

    text = unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_child_text(item, tag_name: str) -> str:
    child = item.find(tag_name)
    if child is not None and child.text:
        return clean_html(child.text)
    return ""


def fetch_rss_xml(url: str, timeout: int = 10) -> Optional[bytes]:
    try:
        request = Request(
            url,
            headers={"User-Agent": USER_AGENT},
        )

        with urlopen(request, timeout=timeout) as response:
            return response.read()

    except HTTPError as error:
        print(f"HTTP error while fetching RSS: {url} | {error}")

    except URLError as error:
        print(f"URL error while fetching RSS: {url} | {error}")

    except Exception as error:
        print(f"Unexpected error while fetching RSS: {url} | {error}")

    return None


def parse_rss_items(
    xml_data: bytes,
    source: NewsSource,
    manager: NewsSourceManager,
    limit: int = 10,
) -> List[SourceArticle]:

    articles: List[SourceArticle] = []

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as error:
        print(f"RSS parse error for {source.name}: {error}")
        return articles

    items = root.findall(".//item")

    for item in items[:limit]:
        title = get_child_text(item, "title")
        summary = get_child_text(item, "description")
        link = get_child_text(item, "link")
        published_at = get_child_text(item, "pubDate")

        if not title:
            continue

        if not summary:
            summary = title

        article = manager.normalize_article(
            title=title,
            summary=summary,
            source_name=source.name,
            url=link,
            category=source.category,
            language=source.language,
            region=source.region,
            published_at=published_at,
            image_url=None,
        )

        articles.append(article)

    return articles


class RSSFeedEngine:
    def __init__(self, manager: NewsSourceManager):
        self.manager = manager

    def get_rss_sources(self) -> List[NewsSource]:
        return [
            source
            for source in self.manager.get_sources()
            if source.active and source.source_type.lower() == "rss"
        ]

    def fetch_from_source(
        self,
        source: NewsSource,
        limit: int = 10,
    ) -> List[SourceArticle]:

        xml_data = fetch_rss_xml(source.url)

        if not xml_data:
            return []

        return parse_rss_items(
            xml_data=xml_data,
            source=source,
            manager=self.manager,
            limit=limit,
        )

    def fetch_latest_articles(self, limit_per_source: int = 10) -> List[SourceArticle]:
        all_articles: List[SourceArticle] = []

        for source in self.get_rss_sources():
            print(f"Fetching RSS: {source.name}")
            articles = self.fetch_from_source(
                source=source,
                limit=limit_per_source,
            )
            all_articles.extend(articles)

        return self.manager.remove_duplicates(all_articles)


def build_test_rss_manager() -> NewsSourceManager:
    manager = build_default_source_manager()

    manager.add_source(
        NewsSource(
            name="BBC World News",
            source_type="rss",
            url="https://feeds.bbci.co.uk/news/world/rss.xml",
            language="en",
            region="World",
            category="world",
            priority=9,
        )
    )

    manager.add_source(
        NewsSource(
            name="The Hindu National",
            source_type="rss",
            url="https://www.thehindu.com/news/national/feeder/default.rss",
            language="en",
            region="India",
            category="national",
            priority=9,
        )
    )

    return manager


if __name__ == "__main__":
    manager = build_test_rss_manager()
    engine = RSSFeedEngine(manager)

    articles = engine.fetch_latest_articles(limit_per_source=3)

    print("=" * 60)
    print("BahuvuNewsAI RSS Feed Engine v2.2")
    print("=" * 60)
    print(f"RSS sources: {len(engine.get_rss_sources())}")
    print(f"Articles fetched: {len(articles)}")
    print("-" * 60)

    for index, article in enumerate(articles, start=1):
        print(f"{index}. {article.title}")
        print(f"   Source   : {article.source_name}")
        print(f"   Category : {article.category}")
        print(f"   Region   : {article.region}")
        print(f"   URL      : {article.url}")
        print(f"   ID       : {article.article_id}")
        print()