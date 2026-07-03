# agents/final_graphic_generator.py

from pathlib import Path

from agents.news_template import create_news_template

OUTPUT_DIR = Path("outputs/final")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def generate_final_news_graphic(news, filename="final_news.png"):
    image = create_news_template(news)

    output_path = OUTPUT_DIR / filename
    image.save(output_path)

    print(f"Saved: {output_path}")
    return output_path


if __name__ == "__main__":
    sample_news = {
        "title": "Heavy Rain Continues Across Andhra Pradesh",
        "summary": "Officials advise people to stay alert as heavy rainfall continues in several districts.",
        "category": "WEATHER",
    }

    generate_final_news_graphic(
        sample_news,
        filename="weather_news.png"
    )