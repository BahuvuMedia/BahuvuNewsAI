# agents/news_pipeline.py
"""
BahuvuNewsAI - Professional News Pipeline
Version: v1.2

This module connects the editorial policy engine with the graphics generator.

Responsibilities:
- Receive raw news items
- Apply Bahuvu editorial policy
- Select the best story
- Convert story data into final graphic input
- Generate a publishable news graphic
"""

from pathlib import Path
from typing import Dict, List, Optional

from agents.news_policy import filter_news_items
from agents.final_graphic_generator import generate_final_news_graphic

OUTPUT_PATH = Path("outputs/graphics/pipeline_news_graphic.png")


def clean_text(value: Optional[str]) -> str:
    if not value:
        return ""

    return " ".join(str(value).strip().split())


def select_top_story(news_items: List[Dict]) -> Optional[Dict]:
    accepted_items = filter_news_items(news_items)

    if not accepted_items:
        return None

    return accepted_items[0]


def prepare_graphic_input(story: Dict) -> Dict:
    return {
        "title": clean_text(story.get("title")),
        "summary": clean_text(story.get("summary")),
        "category": clean_text(story.get("category")) or "GENERAL",
        "image_path": clean_text(story.get("image_path")) or "assets/images/sample.jpg",
    }


def run_news_pipeline(news_items: List[Dict]) -> Optional[Path]:
    top_story = select_top_story(news_items)

    if not top_story:
        print("No publishable stories found.")
        return None

    graphic_input = prepare_graphic_input(top_story)

    print("BahuvuNewsAI Pipeline")
    print("=" * 40)
    print("Selected Story:", graphic_input["title"])
    print("Category:", graphic_input["category"])
    print("Score:", top_story.get("score"))
    print("Image:", graphic_input["image_path"])
    print("=" * 40)

    generate_final_news_graphic(
    news=graphic_input,
    filename="pipeline_news_graphic.png",
)
    print("Pipeline graphic created:", OUTPUT_PATH)

    return OUTPUT_PATH


if __name__ == "__main__":
    sample_news_items = [
        {
            "title": "Heavy Rain Continues Across Andhra Pradesh as Officials Issue Alert",
            "summary": "Officials advise people to stay alert as heavy rainfall continues in several districts of Andhra Pradesh.",
            "category": "weather",
            "image_path": "assets/images/sample.jpg",
            "source": "Sample",
        },
        {
            "title": "Short news",
            "summary": "Too small.",
            "category": "general",
        },
        {
            "title": "Government Announces New Education Support Measures for Students",
            "summary": "Officials said the new measures are designed to support students and improve access to education services across the state.",
            "category": "education",
            "image_path": "assets/images/sample.jpg",
            "source": "Sample",
        },
    ]

    run_news_pipeline(sample_news_items)