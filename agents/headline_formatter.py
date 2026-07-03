# agents/headline_formatter.py

def format_headline(text, max_words=10):
    """
    Formats news headlines for graphics.
    Keeps headline short, clean, and uppercase.
    """

    if not text:
        return "BREAKING NEWS"

    words = text.strip().split()
    short_text = " ".join(words[:max_words])

    return short_text.upper()


if __name__ == "__main__":
    sample = "Heavy rains expected across Andhra Pradesh and Telangana this week"
    print(format_headline(sample))