from google import genai

from config import GEMINI_API_KEY, OUTPUT_SCRIPT


client = genai.Client(api_key=GEMINI_API_KEY)


def generate_script(news):

    print("\nGenerating Telugu script...")

    prompt = f"""
You are the chief Telugu news editor for Bahuvu News.

Read the news below and generate professional Telugu news content.

Return ONLY in this exact format.

==================================================
TITLE
==================================================

...

==================================================
ANCHOR SCRIPT
==================================================

...

==================================================
YOUTUBE TITLE
==================================================

...

==================================================
THUMBNAIL TEXT
==================================================

...

==================================================
DESCRIPTION
==================================================

...

NEWS

{news}
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    result = response.text

    with open(OUTPUT_SCRIPT, "w", encoding="utf-8") as f:
        f.write(result)

    print("Script saved:")
    print(OUTPUT_SCRIPT)

    return result