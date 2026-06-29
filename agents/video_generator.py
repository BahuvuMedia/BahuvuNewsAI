from moviepy import ImageClip, AudioFileClip

from config import NEWS_IMAGE, OUTPUT_AUDIO, OUTPUT_VIDEO


def create_video():

    print("\nCreating video...")

    audio = AudioFileClip(OUTPUT_AUDIO)

    duration = audio.duration

    image = (
        ImageClip(NEWS_IMAGE)
        .with_duration(duration)
        .with_audio(audio)
    )

    image.write_videofile(
        OUTPUT_VIDEO,
        fps=24,
        codec="libx264",
        audio_codec="aac"
    )

    print("Video saved:")
    print(OUTPUT_VIDEO)