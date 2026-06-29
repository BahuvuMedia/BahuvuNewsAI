import edge_tts

from config import OUTPUT_SCRIPT, OUTPUT_AUDIO, TELUGU_VOICE


def extract_anchor_script():

    with open(OUTPUT_SCRIPT, "r", encoding="utf-8") as f:
        text = f.read()

    start = text.find("ANCHOR SCRIPT")
    end = text.find("YOUTUBE TITLE")

    if start == -1 or end == -1:
        raise Exception("ANCHOR SCRIPT section not found.")

    script = text[start:end]

    script = script.replace("ANCHOR SCRIPT", "")
    script = script.replace("=", "")

    return script.strip()


async def generate_voice():

    print("\nGenerating Telugu voice...")

    script = extract_anchor_script()

    communicate = edge_tts.Communicate(
        text=script,
        voice=TELUGU_VOICE
    )

    await communicate.save(OUTPUT_AUDIO)

    print("Voice saved:")
    print(OUTPUT_AUDIO)