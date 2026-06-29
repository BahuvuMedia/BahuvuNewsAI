import feedparser
from bs4 import BeautifulSoup

from config import RSS_URL, BAD_KEYWORDS


def clean_html(text):
    """Remove HTML tags from RSS descriptions."""
    if not text:
        return ""

    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(" ", strip=True)


def is_valid_news(title):
    """Skip advertisements and market reports."""
    title = title.lower()

    return not any(keyword in title for keyword in BAD_KEYWORDS)


def fetch_latest_news():
    """Fetch the latest real news article from Google News RSS."""

    print("Fetching latest news...")

    feed = feedparser.parse(RSS_URL)

    if not feed.entries:
        print("No news found.")
        return None

    for entry in feed.entries:

        title = entry.get("title", "").strip()

        if not is_valid_news(title):
            continue

        description = clean_html(entry.get("summary", ""))

        image = None

        if "media_content" in entry:
            image = entry.media_content[0].get("url")

        elif "media_thumbnail" in entry:
            image = entry.media_thumbnail[0].get("url")

        article = {
            "title": title,
            "description": description,
            "content": description,
            "image": image,
            "link": entry.get("link")
        }

        print("News selected:")
        print(title)

        return article

    print("No suitable news article found.")
    return None