print("BAHUVU News AI is working!")from openai import OpenAI

client = OpenAI(
    api_key="freellmapi-anything",
    base_url="http://localhost:3001/v1"
)

news_text = input("Paste news article:\n\n")

prompt = f"""
You are a Telugu news editor for BAHUVU News.

Based on the news below generate:

1. Telugu Anchor Script
2. YouTube Title
3. Thumbnail Text
4. YouTube Description

News:
{news_text}
"""

response = client.chat.completions.create(
    model="auto",
    messages=[
        {"role": "user", "content": prompt}
    ]
)

print("\n")
print("=" * 60)
print(response.choices[0].message.content)
print("=" * 60)