# agents/news_pipeline.py

"""
BahuvuNewsAI - News Pipeline Orchestrator
Version: v1.9
"""

from pathlib import Path
from typing import Dict, List, Optional

from agents.news_fetcher import fetch_news
from agents.news_cleaner import clean_articles
from agents.news_filter import filter_articles
from agents.news_ranker import rank_articles, get_top_article
from agents.news_policy import filter_news_items
from agents.final_graphic_generator import generate_final_news_graphic

OUTPUT_PATH = Path("outputs/graphics/pipeline_news_graphic.png")


def clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join(str(value).strip().split())


def prepare_graphic_input(story: Dict) -> Dict:
    return {
        "title": clean_text(story.get("title")),
        "summary": clean_text(story.get("summary") or story.get("description")),
        "category": clean_text(story.get("category")) or "GENERAL",
        "image_path": clean_text(story.get("image_path") or story.get("image"))
        or "assets/images/sample.jpg",
    }


def collect_ranked_news(limit: int = 20) -> List[Dict]:
    print("BahuvuNewsAI News Collection Pipeline")
    print("=" * 50)

    raw_articles = fetch_news(limit=limit)
    print("Raw articles:", len(raw_articles))

    cleaned_articles = clean_articles(raw_articles)
    print("Cleaned articles:", len(cleaned_articles))

    filtered_articles = filter_articles(cleaned_articles)
    print("Filtered articles:", len(filtered_articles))

    ranked_articles = rank_articles(filtered_articles)
    print("Ranked articles:", len(ranked_articles))

    print("=" * 50)

    return ranked_articles


def select_top_story(news_items: List[Dict]) -> Optional[Dict]:
    policy_approved_items = filter_news_items(news_items)

    if policy_approved_items:
        return policy_approved_items[0]

    return get_top_article(news_items)


def run_news_pipeline(news_items: Optional[List[Dict]] = None) -> Optional[Path]:
    if news_items is None:
        news_items = collect_ranked_news(limit=20)

    if not news_items:
        print("No news items available.")
        return None

    top_story = select_top_story(news_items)

    if not top_story:
        print("No publishable stories found.")
        return None

    graphic_input = prepare_graphic_input(top_story)

    print("Selected Story:", graphic_input["title"])
    print("Category:", graphic_input["category"])
    print("Rank Score:", top_story.get("rank_score", top_story.get("score", 0)))
    print("Image:", graphic_input["image_path"])

    generate_final_news_graphic(
        news=graphic_input,
        filename="pipeline_news_graphic.png",
    )

    print("Pipeline graphic created:", OUTPUT_PATH)

    return OUTPUT_PATH


if __name__ == "__main__":
    run_news_pipeline()