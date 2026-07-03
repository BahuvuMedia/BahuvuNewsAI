def create_news_template(news):
    img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background_dark"])

    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, WIDTH, 90), fill="#b00020")

    font = get_font(36)
    draw.text((40, 25), "BAHUVU NEWS", font=font, fill=COLORS["text_white"])

    headline_font = get_font(56)
    draw.text(
        (60, 150),
        news["title"],
        fill=COLORS["text_white"],
        font=headline_font,
    )

    summary_font = get_font(30)
    draw.text(
        (60, 240),
        news["summary"],
        fill=COLORS["text_light"],
        font=summary_font,
    )

    draw.rounded_rectangle(
        (820, 130, 1220, 560),
        radius=25,
        outline=COLORS["text_light"],
        width=3,
    )

    placeholder_font = get_font(26)
    draw.text(
        (955, 335),
        "NEWS IMAGE",
        fill=COLORS["text_light"],
        font=placeholder_font,
    )

    img.save(OUTPUT_DIR / "news_template.png")
    print("Created news_template.png")