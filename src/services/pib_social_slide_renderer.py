import os
import textwrap
from PIL import Image, ImageDraw, ImageFont

COLOR_BG = (15, 23, 42, 255)          # Slate #0F172A outer
COLOR_CARD = (0, 0, 0, 255)           # Pure Black inner
COLOR_CARD_BORDER = (51, 65, 85, 255) # Slate Border (#334155)
COLOR_GOLD = (168, 153, 123)          # Antique Gold
COLOR_ROSE = (185, 159, 159)          # Muted Rose
COLOR_CYAN = (56, 189, 248)           # Sky Blue
COLOR_AMBER = (245, 158, 11)          # Warning Amber
COLOR_TEXT_WHITE = (248, 250, 252)
COLOR_TEXT_BODY = (203, 213, 225)
COLOR_TEXT_MUTED = (148, 163, 184)
COLOR_CARD_TRANSLUCENT = (24, 34, 58, 255)


def resolve_font(style: str = "regular", size: int = 24):
    paths = {
        "black": [
            "/usr/share/fonts/truetype/lato/Lato-Black.ttf",
            "C:\\Windows\\Fonts\\ariblk.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ],
        "bold": [
            "/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "C:\\Windows\\Fonts\\segoeuib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ],
        "medium": [
            "/usr/share/fonts/truetype/lato/Lato-Medium.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ],
        "regular": [
            "/usr/share/fonts/truetype/lato/Lato-Regular.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ],
    }
    for candidate in paths.get(style, paths["regular"]):
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    return ImageFont.load_default()


def clean_text(t: str) -> str:
    if not t:
        return ""
    replacements = {
        "₹": "Rs. ",
        "\u202f": " ",
        "\u00a0": " ",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": " - ",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u200b": "",
        "\u200e": "",
        "\u2713": "",
        "\u2714": "",
        "\u26a0": "",
        "\u2794": "->",
        "\u2192": "->",
    }
    for k, v in replacements.items():
        t = t.replace(k, v)
    return t.strip()


def draw_vector_check(draw: ImageDraw.Draw, x: int, y: int, radius: int = 11):
    draw.ellipse(
        [x - radius, y - radius, x + radius, y + radius],
        fill=(56, 189, 248, 35),
        outline=COLOR_CYAN,
        width=2,
    )
    draw.line(
        [(x - 5, y), (x - 1, y + 4), (x + 5, y - 4)],
        fill=COLOR_CYAN,
        width=2,
    )


def draw_vector_alert(draw: ImageDraw.Draw, x: int, y: int, radius: int = 11):
    draw.ellipse(
        [x - radius, y - radius, x + radius, y + radius],
        fill=(245, 158, 11, 35),
        outline=COLOR_AMBER,
        width=2,
    )
    draw.line([(x, y - 5), (x, y + 1)], fill=COLOR_AMBER, width=2)
    draw.point([(x, y + 4), (x, y + 5)], fill=COLOR_AMBER)


def draw_vector_arrow(draw: ImageDraw.Draw, x: int, y: int, length: int = 14):
    draw.line([(x - length, y), (x, y)], fill=COLOR_GOLD, width=2)
    draw.line(
        [(x - 5, y - 5), (x, y), (x - 5, y + 5)], fill=COLOR_GOLD, width=2
    )


def draw_multiline_headline(
    draw: ImageDraw.Draw,
    text: str,
    x: int,
    y: int,
    max_width_px: int = 880,
    max_font_size: int = 38,
    min_font_size: int = 26,
):
    font_size = max_font_size
    text = clean_text(text)
    while font_size >= min_font_size:
        font = resolve_font("bold", font_size)
        if draw.textlength(text, font=font) <= max_width_px:
            draw.text((x, y), text, font=font, fill=COLOR_GOLD)
            return y + font_size + 14

        approx_chars = max(
            15, int(len(text) * (max_width_px / max(1, draw.textlength(text, font=font))))
        )
        lines = textwrap.wrap(text, width=approx_chars)
        if len(lines) <= 2 and all(
            draw.textlength(l, font=font) <= max_width_px for l in lines
        ):
            curr_y = y
            for line in lines:
                draw.text((x, curr_y), line, font=font, fill=COLOR_GOLD)
                curr_y += font_size + 8
            return curr_y + 8
        font_size -= 2

    font = resolve_font("bold", min_font_size)
    lines = textwrap.wrap(text, width=40)
    curr_y = y
    for line in lines[:2]:
        draw.text((x, curr_y), line, font=font, fill=COLOR_GOLD)
        curr_y += min_font_size + 6
    return curr_y + 8


def get_logo_image(size: int = 44):
    candidates = [
        "static/logo.png",
        "public/logo.png",
        "logo.png",
        "static/logo.png.png",
        "public/logo.png.png",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                logo = Image.open(p).convert("RGBA")
                logo = logo.resize((size, size), Image.Resampling.LANCZOS)
                mask = Image.new("L", (size, size), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse((0, 0, size, size), fill=255)
                output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                output.paste(logo, (0, 0), mask=mask)
                return output
            except Exception:
                pass
    return None


def create_base_canvas(slide_num: str, tier_badge: str):
    W, H = 1080, 1350
    img = Image.new("RGBA", (W, H), COLOR_BG)
    draw = ImageDraw.Draw(img)

    card_margin = 46
    draw.rounded_rectangle(
        [card_margin, card_margin, W - card_margin, H - card_margin],
        radius=24,
        fill=COLOR_CARD,
        outline=COLOR_CARD_BORDER,
        width=2,
    )

    logo = get_logo_image(size=44)
    text_x = 96
    if logo:
        img.paste(logo, (96, 84), logo)
        draw.ellipse([94, 82, 142, 130], outline=COLOR_GOLD, width=1)
        text_x = 152
    else:
        draw.ellipse(
            [96, 84, 138, 126], fill=(28, 38, 64), outline=COLOR_GOLD, width=2
        )
        draw.line([(117, 92), (117, 118)], fill=COLOR_GOLD, width=2)
        draw.line([(106, 100), (128, 100)], fill=COLOR_GOLD, width=2)
        text_x = 152

    draw.text(
        (text_x, 92),
        "POLITY MENTOR",
        font=resolve_font("black", 25),
        fill=COLOR_GOLD,
    )
    draw.text(
        (W - 96 - 130, 96),
        f"SLIDE {slide_num}",
        font=resolve_font("bold", 20),
        fill=COLOR_ROSE,
    )
    draw.line([(96, 140), (W - 96, 140)], fill=COLOR_CARD_BORDER, width=2)

    clean_badge = clean_text(tier_badge).upper()
    font_badge = resolve_font("bold", 17)
    badge_width = int(draw.textlength(clean_badge, font=font_badge)) + 38
    draw.rounded_rectangle(
        [96, 178, 96 + badge_width, 226],
        radius=12,
        fill=(28, 38, 64),
        outline=COLOR_GOLD,
        width=2,
    )
    draw.text((115, 192), clean_badge, font=font_badge, fill=COLOR_GOLD)

    draw.line([(96, H - 120), (W - 96, H - 120)], fill=COLOR_CARD_BORDER, width=2)
    draw.text(
        (96, H - 88),
        "politymentor.com",
        font=resolve_font("medium", 21),
        fill=COLOR_TEXT_MUTED,
    )
    draw.text(
        (W - 96 - 275, H - 88),
        "Swipe to continue",
        font=resolve_font("bold", 21),
        fill=COLOR_GOLD,
    )
    draw_vector_arrow(draw, W - 96 - 55, H - 77, length=12)

    return img, draw, W, H


# ---------------------------------------------------------------------------
# PIB SLIDE 1: OVERVIEW & HOOK
# ---------------------------------------------------------------------------
def render_pib_slide_1(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])

    font_hero = resolve_font("black", 72)
    draw.text(
        (96, 275), clean_text(slide["headline"]), font=font_hero, fill=COLOR_GOLD
    )

    font_sub = resolve_font("bold", 26)
    draw.text(
        (96, 375),
        clean_text(slide.get("subheadline", "")),
        font=font_sub,
        fill=COLOR_ROSE,
    )

    font_body = resolve_font("regular", 24)
    thesis_clean = clean_text(slide.get("thesis", ""))
    lines = textwrap.wrap(thesis_clean, width=48)
    y_pos = 450
    for line in lines:
        draw.text((96, y_pos), line, font=font_body, fill=COLOR_TEXT_BODY)
        y_pos += 38

    chip_y = max(y_pos + 40, 780)
    font_chip = resolve_font("bold", 20)
    for chip in slide.get("chips", []):
        chip_clean = clean_text(chip)
        draw.rounded_rectangle(
            [96, chip_y, 96 + 540, chip_y + 52],
            radius=18,
            fill=COLOR_CARD_TRANSLUCENT,
            outline=COLOR_CARD_BORDER,
            width=2,
        )
        draw.ellipse([118, chip_y + 21, 128, chip_y + 31], fill=COLOR_ROSE)
        draw.text(
            (144, chip_y + 14), chip_clean, font=font_chip, fill=COLOR_ROSE
        )
        chip_y += 68

    img.save(output_path, "PNG")


# ---------------------------------------------------------------------------
# PIB SLIDE 2: WHY IT MATTERS FOR UPSC
# ---------------------------------------------------------------------------
def render_pib_slide_2(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])

    next_y = draw_multiline_headline(
        draw, slide["headline"], 96, 260, max_width_px=880, max_font_size=38
    )
    draw.text(
        (96, next_y),
        clean_text(
            slide.get(
                "subheadline", "Strategic Governance & Institutional Analysis"
            )
        ),
        font=resolve_font("bold", 24),
        fill=COLOR_ROSE,
    )
    y_cursor = next_y + 40

    narrative = clean_text(slide.get("analytical_insight", ""))
    lines_nar = textwrap.wrap(narrative, width=52)
    box1_h = 48 + (len(lines_nar) * 32) + 16
    draw.rounded_rectangle(
        [96, y_cursor, W - 96, y_cursor + box1_h],
        radius=16,
        fill=(30, 41, 70),
        outline=COLOR_ROSE,
        width=2,
    )
    draw.text(
        (120, y_cursor + 16),
        "STRATEGIC UPSC VALUE",
        font=resolve_font("bold", 18),
        fill=COLOR_ROSE,
    )
    y_l = y_cursor + 50
    for l in lines_nar:
        draw.text(
            (120, y_l), l, font=resolve_font("medium", 21), fill=COLOR_TEXT_WHITE
        )
        y_l += 32

    y_cursor += box1_h + 24
    for item in slide.get("points", [])[:2]:
        title = clean_text(item.get("title", ""))
        desc = clean_text(item.get("desc", ""))
        lines_p = textwrap.wrap(desc, width=54)
        box2_h = 44 + (len(lines_p) * 28) + 14

        draw.rounded_rectangle(
            [96, y_cursor, W - 96, y_cursor + box2_h],
            radius=16,
            fill=COLOR_CARD_TRANSLUCENT,
            outline=COLOR_CARD_BORDER,
            width=2,
        )
        draw.text(
            (120, y_cursor + 14),
            title,
            font=resolve_font("bold", 20),
            fill=COLOR_GOLD,
        )
        y_l = y_cursor + 44
        for l in lines_p:
            draw.text(
                (120, y_l),
                l,
                font=resolve_font("regular", 19),
                fill=COLOR_TEXT_BODY,
            )
            y_l += 28
        y_cursor += box2_h + 18

    img.save(output_path, "PNG")


# ---------------------------------------------------------------------------
# PIB SLIDE 3: SMART NOTES (CORE ANALYTICAL DOSSIER)
# ---------------------------------------------------------------------------
def render_pib_slide_3(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])

    next_y = draw_multiline_headline(
        draw, slide["headline"], 96, 260, max_width_px=880, max_font_size=36
    )
    draw.text(
        (96, next_y),
        clean_text(
            slide.get(
                "subheadline", "Targeted UPSC Current Affairs Deconstruction"
            )
        ),
        font=resolve_font("bold", 24),
        fill=COLOR_ROSE,
    )

    notes = slide.get("notes", [])
    y_card = next_y + 40
    font_title = resolve_font("bold", 20)
    font_body = resolve_font("regular", 19)

    for idx, item in enumerate(notes[:4], 1):
        title = clean_text(item.get("title", f"Takeaway #{idx}"))
        text = clean_text(item.get("desc", ""))

        lines = textwrap.wrap(text, width=54)
        box_h = 44 + (len(lines) * 27) + 10

        draw.rounded_rectangle(
            [96, y_card, W - 96, y_card + box_h],
            radius=14,
            fill=COLOR_CARD_TRANSLUCENT,
            outline=COLOR_CARD_BORDER,
            width=2,
        )
        draw.rounded_rectangle(
            [112, y_card + 14, 117, y_card + box_h - 14],
            radius=2,
            fill=COLOR_GOLD,
        )
        draw.text((134, y_card + 12), title, font=font_title, fill=COLOR_GOLD)

        y_text = y_card + 40
        for l in lines:
            draw.text(
                (134, y_text), l, font=font_body, fill=COLOR_TEXT_BODY
            )
            y_text += 27

        y_card += box_h + 16

    img.save(output_path, "PNG")


# ---------------------------------------------------------------------------
# PIB SLIDE 4: ALL BACKWARD LINKAGES (2-COLUMN DYNAMIC GRID)
# ---------------------------------------------------------------------------
def render_pib_slide_4(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])

    next_y = draw_multiline_headline(
        draw, slide["headline"], 96, 260, max_width_px=880, max_font_size=36
    )
    draw.text(
        (96, next_y),
        clean_text(
            slide.get(
                "subheadline", "Constitutional Articles & Landmark Precedents"
            )
        ),
        font=resolve_font("bold", 24),
        fill=COLOR_ROSE,
    )

    points = slide.get("points", [])
    total_items = len(points)

    if total_items <= 5:
        y_card = next_y + 42
        for item in points:
            title = clean_text(item.get("title", ""))
            desc = clean_text(item.get("desc", ""))
            lines = textwrap.wrap(desc, width=54) if desc else []
            box_h = 52 + (len(lines) * 26)

            draw.rounded_rectangle(
                [96, y_card, W - 96, y_card + box_h],
                radius=14,
                fill=COLOR_CARD_TRANSLUCENT,
                outline=COLOR_CARD_BORDER,
                width=2,
            )
            draw.ellipse([118, y_card + 19, 126, y_card + 27], fill=COLOR_GOLD)
            draw.text(
                (140, y_card + 14),
                title,
                font=resolve_font("bold", 21),
                fill=COLOR_TEXT_WHITE,
            )

            if lines:
                y_d = y_card + 46
                for l in lines:
                    draw.text(
                        (140, y_d),
                        l,
                        font=resolve_font("regular", 18),
                        fill=COLOR_TEXT_BODY,
                    )
                    y_d += 26
            y_card += box_h + 20
    else:
        col_w = 428
        left_x = 96
        right_x = W - 96 - col_w
        start_y = next_y + 36

        num_rows = (min(total_items, 12) + 1) // 2
        available_height = (H - 140) - start_y
        row_gap = 14
        box_h = min(
            115, int((available_height - (num_rows * row_gap)) / num_rows)
        )

        font_tile_title = resolve_font("bold", 17)
        font_tile_desc = resolve_font("regular", 15)

        for idx, item in enumerate(points[:12]):
            col = idx % 2
            row = idx // 2

            x_pos = left_x if col == 0 else right_x
            y_pos = start_y + (row * (box_h + row_gap))

            title = clean_text(item.get("title", ""))
            desc = clean_text(item.get("desc", ""))

            draw.rounded_rectangle(
                [x_pos, y_pos, x_pos + col_w, y_pos + box_h],
                radius=12,
                fill=COLOR_CARD_TRANSLUCENT,
                outline=COLOR_CARD_BORDER,
                width=2,
            )

            draw.ellipse(
                [x_pos + 16, y_pos + 16, x_pos + 23, y_pos + 23],
                fill=COLOR_GOLD,
            )

            draw.text(
                (x_pos + 32, y_pos + 11),
                title[:30],
                font=font_tile_title,
                fill=COLOR_TEXT_WHITE,
            )

            if desc:
                lines = textwrap.wrap(desc, width=32)
                y_desc = y_pos + 38
                for l in lines[:2]:
                    draw.text(
                        (x_pos + 32, y_desc),
                        l,
                        font=font_tile_desc,
                        fill=COLOR_TEXT_BODY,
                    )
                    y_desc += 20

    img.save(output_path, "PNG")


# ---------------------------------------------------------------------------
# PIB SLIDE 5: PRELIMS DRILL & MAINS ANALYTICAL QUESTION
# ---------------------------------------------------------------------------
def render_pib_slide_5(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])

    next_y = draw_multiline_headline(
        draw, slide["headline"], 96, 260, max_width_px=880, max_font_size=36
    )
    draw.text(
        (96, next_y),
        "Prelims Traps & Mains Analytical Question",
        font=resolve_font("bold", 24),
        fill=COLOR_ROSE,
    )
    y_cursor = next_y + 40

    font_param = resolve_font("bold", 19)
    font_content = resolve_font("regular", 18)
    font_content_bold = resolve_font("bold", 18)

    for r in slide.get("rows", [])[:2]:
        param = clean_text(r.get("param", ""))
        rule = clean_text(r.get("rule", ""))
        trap = clean_text(r.get("trap", ""))

        lines_rule = textwrap.wrap(f"Rule: {rule}", width=52)
        lines_trap = textwrap.wrap(f"Trap: {trap}", width=52)
        card_h = 32 + ((len(lines_rule) + len(lines_trap)) * 24) + 12

        draw.rounded_rectangle(
            [96, y_cursor, W - 96, y_cursor + card_h],
            radius=14,
            fill=COLOR_CARD_TRANSLUCENT,
            outline=COLOR_CARD_BORDER,
            width=2,
        )
        draw.text(
            (120, y_cursor + 8),
            param,
            font=font_param,
            fill=COLOR_TEXT_WHITE,
        )

        y_row = y_cursor + 34
        draw_vector_check(draw, 126, y_row + 10, radius=8)
        for idx, l in enumerate(lines_rule):
            draw.text(
                (144, y_row),
                l,
                font=font_content_bold if idx == 0 else font_content,
                fill=COLOR_CYAN,
            )
            y_row += 24

        draw_vector_alert(draw, 126, y_row + 10, radius=8)
        for idx, l in enumerate(lines_trap):
            draw.text((144, y_row), l, font=font_content, fill=COLOR_AMBER)
            y_row += 24

        y_cursor += card_h + 14

    mains_q = clean_text(slide.get("mains_question", ""))
    if mains_q:
        q_lines = textwrap.wrap(mains_q, width=54)
        q_h = 40 + (len(q_lines) * 25) + 12
        draw.rounded_rectangle(
            [96, y_cursor, W - 96, y_cursor + q_h],
            radius=14,
            fill=(30, 41, 70),
            outline=COLOR_ROSE,
            width=2,
        )
        draw.text(
            (120, y_cursor + 12),
            "MAINS ANALYTICAL QUESTION",
            font=resolve_font("bold", 17),
            fill=COLOR_ROSE,
        )
        y_ql = y_cursor + 38
        for l in q_lines:
            draw.text(
                (120, y_ql),
                l,
                font=resolve_font("regular", 18),
                fill=COLOR_TEXT_WHITE,
            )
            y_ql += 25

    img.save(output_path, "PNG")


# ---------------------------------------------------------------------------
# PIB SLIDE 6: ECOSYSTEM & CALL TO ACTION
# ---------------------------------------------------------------------------
def render_pib_slide_6(slide: dict, output_path: str):
    from src.services.social_slide_renderer import render_slide_6

    render_slide_6(slide, output_path)