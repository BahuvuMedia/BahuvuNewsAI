# agents/text_layout.py

"""
Text Layout Engine
BahuvuNewsAI v0.5
"""

import textwrap


DEFAULT_WIDTH = 22


def wrap_headline(text, width=DEFAULT_WIDTH):
    """
    Wrap long headlines into multiple lines.
    """

    if not text:
        return ""

    # Remove extra spaces
    text = " ".join(text.split())

    # Wrap headline
    return textwrap.fill(text, width=width)


if __name__ == "__main__":
    sample = (
        "HEAVY RAINS EXPECTED ACROSS ANDHRA PRADESH "
        "AND TELANGANA THIS WEEK CAUSING FLOODING"
    )

    print(wrap_headline(sample))