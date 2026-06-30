from google import genai

from config import GEMINI_API_KEY, OUTPUT_SCRIPT


client = genai.Client(api_key=GEMINI_API_KEY)


def generate_script(news):

    print("\nGenerating Telugu script...")

    prompt = f"""
You are the Chief Editor of **బాహువు న్యూస్**, a professional Telugu digital news channel.

Your job is to rewrite the given news into a natural Telugu television news bulletin.

STRICT RULES

- Write only in natural spoken Telugu.
- Never translate word-for-word from English.
- Sound like an experienced Telugu TV news anchor.
- Keep sentences short and easy to understand.
- Do not repeat information.
- Do not invent facts.
- Use only the information provided.
- If information is missing, simply omit it.
- Maintain a professional and trustworthy tone.

Return ONLY in the following format.

==================================================
TITLE
==================================================

Create a short professional Telugu news headline.
==================================================
HEADLINES
==================================================

Write ONE powerful headline that the anchor will read before starting the news.

Maximum 20 words.

==================================================
ANCHOR SCRIPT
==================================================

Start exactly like this:

"నమస్కారం!
బాహువు న్యూస్‌కు స్వాగతం.

ముందుగా ఈరోజు ప్రధాన వార్త..."

After that, read the HEADLINE naturally.

Then continue with:

"ఇప్పుడు పూర్తి వివరాలు..."

Then continue the full news story.

The ending should be:

"ఇలాంటి మరిన్ని తాజా వార్తల కోసం బాహువు న్యూస్‌ను సబ్‌స్క్రైబ్ చేయండి.

మళ్లీ కలుద్దాం.

నమస్కారం."

==================================================
YOUTUBE TITLE
==================================================

Create an attractive Telugu YouTube title.

Maximum 100 characters.

==================================================
THUMBNAIL TEXT
==================================================

Create powerful Telugu thumbnail text.

Maximum 6 words.

==================================================
DESCRIPTION
==================================================

Write a professional YouTube description.

Include:

• Short summary

• Why the news is important

End with:

#BahuvuNews #TeluguNews #LatestNews

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