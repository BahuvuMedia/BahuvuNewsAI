import asyncio

from agents.news_fetcher import fetch_latest_news
from agents.image_downloader import download_image
from agents.script_writer import generate_script
from agents.voice_generator import generate_voice
from agents.video_generator import create_video


def main():

    print("=" * 50)
    print("BAHUVU NEWS AI v2")
    print("=" * 50)

    print("\n[1/5] Fetching latest news...")

    news = fetch_latest_news()

    if news is None:
        print("No news found.")
        return

    print("[OK] News fetched")

    print("\n[2/5] Downloading image...")

    download_image(news.get("image"))

    print("[OK] Image ready")

    print("\n[3/5] Generating Telugu script...")

    generate_script(news["content"])

    print("[OK] Script ready")

    print("\n[4/5] Generating voice...")

    asyncio.run(generate_voice())

    print("[OK] Voice ready")

    print("\n[5/5] Creating video...")

    create_video()

    print("[OK] Video ready")

    print("\n" + "=" * 50)
    print("SUCCESS")
    print("Bahuvu News video created successfully.")
    print("=" * 50)


if __name__ == "__main__":
    main()