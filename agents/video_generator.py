import os

from moviepy import ImageClip, AudioFileClip, CompositeVideoClip

from config import NEWS_IMAGE, OUTPUT_AUDIO, OUTPUT_VIDEO
from agents.watermark import create_rotating_watermark_clips


def create_video():

    print("\nCreating video with Bahuvu rotating watermark...")

    audio = AudioFileClip(OUTPUT_AUDIO)
    duration = audio.duration

    video = (
        ImageClip(NEWS_IMAGE)
        .with_duration(duration)
        .with_audio(audio)
    )

    video_width, video_height = video.size

    output_dir = os.path.dirname(OUTPUT_VIDEO)

    watermark_clips = create_rotating_watermark_clips(
        video_width,
        duration,
        output_dir
    )

    final_video = CompositeVideoClip([video] + watermark_clips)

    final_video.write_videofile(
        OUTPUT_VIDEO,
        fps=24,
        codec="libx264",
        audio_codec="aac"
    )

    print("Video saved:")
    print(OUTPUT_VIDEO)