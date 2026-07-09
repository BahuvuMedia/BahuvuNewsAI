# agents/duplicate_detection_engine.py

"""
BahuvuNewsAI - Duplicate Detection Engine
Version: v2.5

Purpose:
- Detect exact and near-duplicate news articles.
- Work after story clustering and before fact verification.
- Preserve all articles while marking duplicate relationships.
- Keep duplicate detection deterministic, testable, and AI-independent.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set
import re

from agents.news_source_manager import SourceArticle
from agents.rss_feed_engine import RSSFeedEngine, build_test_rss_manager
from agents.story_clustering_engine import (
    StoryCluster,
    cluster_articles,
    article_tokens,
    similarity_score,
)


@dataclass
class DuplicateGroup:
    group_id: str
    canonical_article: SourceArticle
    duplicates: List[SourceArticle] = field(default_factory=list)
    duplicate_type: str = "near_duplicate"
    similarity: float = 0.0

    @property
    def total_count(self) -> int:
        return 1 + len(self.duplicates)

    @property
    def sources(self) -> List[str]:
        return sorted(
            {self.canonical_article.source_name}
            | {article.source_name for article in self.duplicates}
        )


@dataclass
class DuplicateDetectionResult:
    total_articles: int
    unique_articles: List[SourceArticle]
    duplicate_groups: List[DuplicateGroup]

    @property
    def duplicate_count(self) -> int:
        return sum(len(group.duplicates) for group in self.duplicate_groups)

    @property
    def unique_count(self) -> int:
        return len(self.unique_articles)


def normalize_duplicate_key(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def exact_duplicate_key(article: SourceArticle) -> str:
    return normalize_duplicate_key(article.title)


def is_same_source_repeat(
    first: SourceArticle,
    second: SourceArticle,
) -> bool:
    return (
        first.source_name.strip().lower() == second.source_name.strip().lower()
        and exact_duplicate_key(first) == exact_duplicate_key(second)
    )


def calculate_article_similarity(
    first: SourceArticle,
    second: SourceArticle,
) -> float:
    return similarity_score(
        article_tokens(first),
        article_tokens(second),
    )


def choose_canonical_article(articles: List[SourceArticle]) -> SourceArticle:
    return sorted(
        articles,
        key=lambda article: (
            article.importance_score,
            bool(article.url),
            bool(article.image_url),
            len(article.summary or ""),
        ),
        reverse=True,
    )[0]


def detect_duplicates_in_articles(
    articles: List[SourceArticle],
    near_duplicate_threshold: float = 0.42,
) -> DuplicateDetectionResult:

    remaining = list(articles)
    duplicate_groups: List[DuplicateGroup] = []
    unique_articles: List[SourceArticle] = []
    used_ids: Set[str] = set()

    for index, article in enumerate(remaining, start=1):
        article_identifier = article.article_id or str(index)

        if article_identifier in used_ids:
            continue

        exact_matches = []
        near_matches = []

        for other_index, other in enumerate(remaining, start=1):
            other_identifier = other.article_id or str(other_index)

            if other_identifier == article_identifier:
                continue

            if other_identifier in used_ids:
                continue

            if exact_duplicate_key(article) == exact_duplicate_key(other):
                exact_matches.append(other)
                continue

            similarity = calculate_article_similarity(article, other)

            if similarity >= near_duplicate_threshold:
                near_matches.append((other, similarity))

        if exact_matches or near_matches:
            candidates = [article] + exact_matches + [
                item for item, score in near_matches
            ]

            canonical = choose_canonical_article(candidates)
            duplicates = [
                item for item in candidates
                if (item.article_id or item.title) != (canonical.article_id or canonical.title)
            ]

            duplicate_type = "exact_duplicate" if exact_matches else "near_duplicate"

            best_similarity = 1.0 if exact_matches else max(
                [score for item, score in near_matches],
                default=0.0,
            )

            group = DuplicateGroup(
                group_id=f"dup-{index:04d}",
                canonical_article=canonical,
                duplicates=duplicates,
                duplicate_type=duplicate_type,
                similarity=round(best_similarity, 3),
            )

            duplicate_groups.append(group)

            for candidate in candidates:
                used_ids.add(candidate.article_id or candidate.title)

            unique_articles.append(canonical)

        else:
            used_ids.add(article_identifier)
            unique_articles.append(article)

    return DuplicateDetectionResult(
        total_articles=len(articles),
        unique_articles=unique_articles,
        duplicate_groups=duplicate_groups,
    )


def detect_duplicates_in_clusters(
    clusters: List[StoryCluster],
    near_duplicate_threshold: float = 0.42,
) -> Dict[str, DuplicateDetectionResult]:

    results = {}

    for cluster in clusters:
        result = detect_duplicates_in_articles(
            cluster.articles,
            near_duplicate_threshold=near_duplicate_threshold,
        )
        results[cluster.cluster_id] = result

    return results


if __name__ == "__main__":
    manager = build_test_rss_manager()
    rss_engine = RSSFeedEngine(manager)

    articles = rss_engine.fetch_latest_articles(limit_per_source=8)
    clusters = cluster_articles(articles)

    cluster_results = detect_duplicates_in_clusters(clusters)

    total_duplicates = sum(
        result.duplicate_count
        for result in cluster_results.values()
    )

    print("=" * 60)
    print("BahuvuNewsAI Duplicate Detection Engine v2.5")
    print("=" * 60)
    print(f"Articles received : {len(articles)}")
    print(f"Clusters received : {len(clusters)}")
    print(f"Duplicates found  : {total_duplicates}")
    print("-" * 60)

    for cluster in clusters:
        result = cluster_results[cluster.cluster_id]

        print(f"Cluster: {cluster.lead_article.title}")
        print(f"Unique articles : {result.unique_count}")
        print(f"Duplicate groups: {len(result.duplicate_groups)}")

        for group in result.duplicate_groups:
            print(f"  Group ID   : {group.group_id}")
            print(f"  Type       : {group.duplicate_type}")
            print(f"  Similarity : {group.similarity}")
            print(f"  Canonical  : {group.canonical_article.title}")
            print(f"  Sources    : {', '.join(group.sources)}")
            print(f"  Duplicates : {len(group.duplicates)}")

        print()