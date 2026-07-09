# agents/story_clustering_engine.py

"""
BahuvuNewsAI - Story Clustering Engine
Version: v2.4

Purpose:
- Group similar articles into story clusters.
- Reduce repeated coverage of the same event.
- Prepare stories for duplicate detection, fact verification, ranking, and bulletin generation.
- Keep clustering deterministic, testable, and AI-independent.
"""

from dataclasses import dataclass, field
from typing import List, Set
import re

from agents.news_source_manager import SourceArticle
from agents.rss_feed_engine import RSSFeedEngine, build_test_rss_manager
from agents.story_ranking_engine import rank_articles


STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "with", "without",
    "in", "on", "at", "to", "from", "for", "of", "by", "as", "is", "are",
    "was", "were", "be", "been", "being", "this", "that", "these", "those",
    "it", "its", "into", "over", "after", "before", "about", "who", "what",
    "when", "where", "why", "how", "new", "latest", "watch", "video",
}


@dataclass
class StoryCluster:
    cluster_id: str
    lead_article: SourceArticle
    articles: List[SourceArticle] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    confidence_score: int = 0

    @property
    def story_count(self) -> int:
        return len(self.articles)

    @property
    def sources(self) -> List[str]:
        return sorted({article.source_name for article in self.articles})


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokenize(text: str) -> Set[str]:
    normalized = normalize_text(text)
    words = normalized.split()

    return {
        word
        for word in words
        if len(word) >= 3 and word not in STOPWORDS
    }


def article_tokens(article: SourceArticle) -> Set[str]:
    return tokenize(f"{article.title} {article.summary}")


def similarity_score(first: Set[str], second: Set[str]) -> float:
    if not first or not second:
        return 0.0

    intersection = first.intersection(second)
    union = first.union(second)

    return len(intersection) / len(union)


def extract_keywords(articles: List[SourceArticle], limit: int = 8) -> List[str]:
    frequency = {}

    for article in articles:
        for token in article_tokens(article):
            frequency[token] = frequency.get(token, 0) + 1

    ranked = sorted(
        frequency.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    return [word for word, count in ranked[:limit]]


def create_cluster_id(article: SourceArticle, index: int) -> str:
    base = article.article_id or str(index)
    return f"cluster-{base[:8]}"


def calculate_cluster_confidence(cluster: StoryCluster) -> int:
    source_bonus = min(len(cluster.sources) * 15, 45)
    article_bonus = min(cluster.story_count * 10, 30)
    lead_score = min(cluster.lead_article.importance_score, 25)

    return min(source_bonus + article_bonus + lead_score, 100)


def cluster_articles(
    articles: List[SourceArticle],
    similarity_threshold: float = 0.28,
) -> List[StoryCluster]:

    ranked_articles = rank_articles(articles)
    clusters: List[StoryCluster] = []

    for index, article in enumerate(ranked_articles, start=1):
        current_tokens = article_tokens(article)
        matched_cluster = None
        best_score = 0.0

        for cluster in clusters:
            lead_tokens = article_tokens(cluster.lead_article)
            score = similarity_score(current_tokens, lead_tokens)

            if score > best_score:
                best_score = score
                matched_cluster = cluster

        if matched_cluster and best_score >= similarity_threshold:
            matched_cluster.articles.append(article)
        else:
            clusters.append(
                StoryCluster(
                    cluster_id=create_cluster_id(article, index),
                    lead_article=article,
                    articles=[article],
                )
            )

    for cluster in clusters:
        cluster.articles = rank_articles(cluster.articles)
        cluster.lead_article = cluster.articles[0]
        cluster.keywords = extract_keywords(cluster.articles)
        cluster.confidence_score = calculate_cluster_confidence(cluster)

    return sorted(
        clusters,
        key=lambda item: (
            item.lead_article.importance_score,
            item.confidence_score,
            item.story_count,
        ),
        reverse=True,
    )


def get_top_clusters(
    articles: List[SourceArticle],
    limit: int = 5,
) -> List[StoryCluster]:
    return cluster_articles(articles)[:limit]


if __name__ == "__main__":
    manager = build_test_rss_manager()
    rss_engine = RSSFeedEngine(manager)

    articles = rss_engine.fetch_latest_articles(limit_per_source=8)
    clusters = cluster_articles(articles)

    print("=" * 60)
    print("BahuvuNewsAI Story Clustering Engine v2.4")
    print("=" * 60)
    print(f"Articles received : {len(articles)}")
    print(f"Clusters created  : {len(clusters)}")
    print("-" * 60)

    for index, cluster in enumerate(clusters, start=1):
        print(f"{index}. {cluster.lead_article.title}")
        print(f"   Cluster ID : {cluster.cluster_id}")
        print(f"   Stories    : {cluster.story_count}")
        print(f"   Sources    : {', '.join(cluster.sources)}")
        print(f"   Score      : {cluster.lead_article.importance_score}")
        print(f"   Confidence : {cluster.confidence_score}")
        print(f"   Keywords   : {', '.join(cluster.keywords)}")
        print()