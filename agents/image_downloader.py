import requests

from config import NEWS_IMAGE, DEFAULT_IMAGE


def download_image(image_url):
    """
    Download a news image.
    If no image is available, use the default placeholder.
    """

    if not image_url:
        print("No image found. Using placeholder.")
        image_url = DEFAULT_IMAGE

    print("Downloading image...")

    try:

        response = requests.get(image_url, timeout=20)

        response.raise_for_status()

        with open(NEWS_IMAGE, "wb") as f:
            f.write(response.content)

        print("Image saved:")
        print(NEWS_IMAGE)

        return NEWS_IMAGE

    except Exception as e:

        print("Image download failed.")
        print(e)

        return None