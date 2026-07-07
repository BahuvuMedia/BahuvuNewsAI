# agents/broadcast_layout.py

WIDTH = 1280
HEIGHT = 720

# Global spacing
MARGIN_X = 50
MARGIN_Y = 30

# Header
HEADER_X = 0
HEADER_Y = 0
HEADER_W = WIDTH
HEADER_H = 88

LOGO_X = 40
LOGO_Y = 24

# Main news image area
IMAGE_X = 50
IMAGE_Y = 120
IMAGE_W = 540
IMAGE_H = 360

# Text panel
TEXT_X = 630
TEXT_Y = 125
TEXT_W = 590

HEADLINE_X = TEXT_X
HEADLINE_Y = TEXT_Y
HEADLINE_W = TEXT_W

SUMMARY_X = TEXT_X
SUMMARY_Y = 390
SUMMARY_W = TEXT_W

# Footer
FOOTER_X = 0
FOOTER_Y = 650
FOOTER_W = WIDTH
FOOTER_H = 70

FOOTER_TEXT_X = 50
FOOTER_TEXT_Y = 668


def get_layout():
    return {
        "width": WIDTH,
        "height": HEIGHT,

        "margin_x": MARGIN_X,
        "margin_y": MARGIN_Y,

        "header_x": HEADER_X,
        "header_y": HEADER_Y,
        "header_w": HEADER_W,
        "header_h": HEADER_H,

        "logo_x": LOGO_X,
        "logo_y": LOGO_Y,

        "image_x": IMAGE_X,
        "image_y": IMAGE_Y,
        "image_w": IMAGE_W,
        "image_h": IMAGE_H,

        "text_x": TEXT_X,
        "text_y": TEXT_Y,
        "text_w": TEXT_W,

        "headline_x": HEADLINE_X,
        "headline_y": HEADLINE_Y,
        "headline_w": HEADLINE_W,

        "summary_x": SUMMARY_X,
        "summary_y": SUMMARY_Y,
        "summary_w": SUMMARY_W,

        "footer_x": FOOTER_X,
        "footer_y": FOOTER_Y,
        "footer_w": FOOTER_W,
        "footer_h": FOOTER_H,

        "footer_text_x": FOOTER_TEXT_X,
        "footer_text_y": FOOTER_TEXT_Y,
    }