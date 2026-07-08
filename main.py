# main.py
"""
BahuvuNewsAI - Master Orchestrator
Version: v1.3

Connects the stable editorial news pipeline with the future video pipeline.
"""

from agents.news_pipeline import run_news_pipeline


def get_sample_news():
    return [
        {
            "title": "Heavy Rain Continues Across Andhra Pradesh as Officials Issue Alert",
            "summary": "Officials advise people to stay alert as heavy rainfall continues in several districts of Andhra Pradesh.",
            "category": "weather",
            "image_path": "assets/images/sample.jpg",
            "source": "BAHUVU NEWS",
        },
        {
            "title": "Government Announces New Education Support Measures for Students",
            "summary": "Officials said the new measures are designed to support students and improve access to education services across the state.",
            "category": "education",
            "image_path": "assets/images/sample.jpg",
            "source": "BAHUVU NEWS",
        },
    ]


def main():
    print("=" * 50)
    print("BAHUVU NEWS AI - MASTER ORCHESTRATOR v1.3")
    print("=" * 50)

    print("\n[1/1] Running professional editorial news pipeline...")

    news_items = get_sample_news()
    output_path = run_news_pipeline(news_items)

    if not output_path:
        print("\nNo publishable story was found.")
        return

    print("\n[OK] Editorial pipeline completed")
    print("Output:", output_path)

    print("\n" + "=" * 50)
    print("SUCCESS")
    print("Bahuvu News graphic package created successfully.")
    print("=" * 50)


if __name__ == "__main__":
    main()