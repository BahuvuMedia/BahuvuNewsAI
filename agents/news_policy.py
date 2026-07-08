# agents/news_policy.py
"""
BahuvuNewsAI - Professional News Policy Engine
Version: v1.2

This module is the editorial safety and quality layer for Bahuvu News.

Responsibilities:
- Validate incoming news items
- Reject weak or incomplete stories
- Normalize categories
- Score editorial importance
- Detect possible duplicate stories
- Prepare clean story objects for the pipeline
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional


VALID_CATEGORIES = {
    "politics": "POLITICS",
    "weather": "WEATHER",
    "sports": "SPORTS",
    "business": "BUSINESS",
    "technology": "TECHNOLOGY",
    "health": "HEALTH",
    "education": "EDUCATION",
    "crime": "CRIME",
    "national": "NATIONAL",
    "international": "INTERNATIONAL",
    "entertainment": "ENTERTAINMENT",
    "general": "GENERAL",
}


REQUIRED_FIELDS = ["title", "summary"]


@dataclass
class PolicyResult:
    accepted: bool
    reason: str
    score: int
    category: str


def clean_text(value: Optional[str]) -> str:
    if not value:
        return ""

    return " ".join(str(value).strip().split())


def normalize_category(category: Optional[str]) -> str:
    if not category:
        return "GENERAL"

    key = clean_text(category).lower()
    return VALID_CATEGORIES.get(key, "GENERAL")


def has_required_fields(news: Dict) -> bool:
    for field in REQUIRED_FIELDS:
        if not clean_text(news.get(field)):
            return False

    return True


def is_too_short(news: Dict) -> bool:
    title = clean_text(news.get("title"))
    summary = clean_text(news.get("summary"))

    return len(title) < 20 or len(summary) < 40


def editorial_score(news: Dict) -> int:
    score = 50

    title = clean_text(news.get("title")).lower()
    summary = clean_text(news.get("summary")).lower()
    category = normalize_category(news.get("category"))

    priority_words = [
        "alert",
        "warning",
        "heavy",
        "rain",
        "flood",
        "cyclone",
        "election",
        "government",
        "minister",
        "court",
        "accident",
        "fire",
        "price",
        "students",
        "health",
        "breaking",
    ]

    for word in priority_words:
        if word in title or word in summary:
            score += 5

    if category in {"POLITICS", "WEATHER", "HEALTH", "EDUCATION", "BUSINESS"}:
        score += 10

    if len(summary) > 120:
        score += 5

    return min(score, 100)


def evaluate_news(news: Dict) -> PolicyResult:
    if not isinstance(news, dict):
        return PolicyResult(False, "News item is not a dictionary", 0, "GENERAL")

    if not has_required_fields(news):
        return PolicyResult(False, "Missing required title or summary", 0, "GENERAL")

    if is_too_short(news):
        return PolicyResult(False, "Story is too short for publication", 20, "GENERAL")

    category = normalize_category(news.get("category"))
    score = editorial_score(news)

    if score < 45:
        return PolicyResult(False, "Editorial score too low", score, category)

    return PolicyResult(True, "Accepted", score, category)


def story_signature(news: Dict) -> str:
    title = clean_text(news.get("title")).lower()
    words = title.split()

    important_words = [
        word for word in words
        if len(word) > 4
    ]

    return " ".join(important_words[:8])


def is_duplicate(news: Dict, existing_news: List[Dict]) -> bool:
    current_signature = story_signature(news)

    if not current_signature:
        return False

    for item in existing_news:
        if story_signature(item) == current_signature:
            return True

    return False


def prepare_story(news: Dict) -> Dict:
    result = evaluate_news(news)

    return {
        "title": clean_text(news.get("title")),
        "summary": clean_text(news.get("summary")),
        "category": result.category,
        "score": result.score,
        "accepted": result.accepted,
        "reason": result.reason,
        "image_path": clean_text(news.get("image_path")) or "assets/images/sample.jpg",
        "source": clean_text(news.get("source")) or "Manual",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def filter_news_items(news_items: List[Dict]) -> List[Dict]:
    accepted_items = []

    for news in news_items:
        prepared = prepare_story(news)

        if not prepared["accepted"]:
            continue

        if is_duplicate(prepared, accepted_items):
            continue

        accepted_items.append(prepared)

    accepted_items.sort(key=lambda item: item["score"], reverse=True)

    return accepted_items


if __name__ == "__main__":
    sample_news = [
        {
            "title": "Heavy Rain Continues Across Andhra Pradesh as Officials Issue Alert",
            "summary": "Officials advise people to stay alert as heavy rainfall continues in several districts of Andhra Pradesh.",
            "category": "weather",
            "image_path": "assets/images/sample.jpg",
            "source": "Sample",
        }
    ]

    results = filter_news_items(sample_news)

    print("BahuvuNewsAI News Policy Test")
    print("=" * 40)

    for item in results:
        print("Title:", item["title"])
        print("Category:", item["category"])
        print("Score:", item["score"])
        print("Accepted:", item["accepted"])
        print("Reason:", item["reason"])