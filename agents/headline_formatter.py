# agents/headline_formatter.py

MAX_WORDS = 10


def format_headline(text):
    """
    Clean and format news headlines for graphics.
    """

    if not text:
        return "BREAKING NEWS"

    # Remove extra spaces
    text = " ".join(text.split())

    # Limit headline length
    words = text.split()

    if len(words) > MAX_WORDS:
        text = " ".join(words[:MAX_WORDS]) + "..."

    return text.upper()


if __name__ == "__main__":
    sample = (
        "Heavy rains expected across Andhra Pradesh and Telangana this week "
        "causing severe flooding in several districts"
    )

    print(format_headline(sample))