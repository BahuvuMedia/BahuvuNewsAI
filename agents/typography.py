# agents/typography.py

"""
Typography Engine
BahuvuNewsAI v0.6
"""

from agents.fonts import get_font


def get_headline_font(text):
    """
    Choose headline font size based on text length.
    """

    length = len(text)

    if length <= 35:
        size = 64
    elif length <= 60:
        size = 56
    elif length <= 90:
        size = 48
    else:
        size = 42

    return get_font(size)


def get_summary_font(text):
    """
    Choose summary font size.
    """

    return get_font(30)


if __name__ == "__main__":
    sample = "Heavy Rain Continues Across Andhra Pradesh"
    font = get_headline_font(sample)
    print("Typography Engine working")