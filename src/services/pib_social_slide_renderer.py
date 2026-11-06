import os
import re
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

COLOR_BG = (15, 23, 42, 255)          # Slate #0F172A outer container
COLOR_CARD = (0, 0, 0, 255)           # Pure Black inner card
COLOR_CARD_BORDER = (51, 65, 85, 255) # Slate Border (#334155)
COLOR_GOLD = (212, 175, 55, 255)      # Metallic Gold (#D4AF37)
COLOR_ROSE = (226, 232, 240, 255)     # Slate White/Rose (#E2E8F0)
COLOR_CYAN = (56, 189, 248, 255)      # Terminal Sky Blue (#38BDF8)
COLOR_AMBER = (245, 158, 11, 255)     # Warning Amber (#F59E0B)
COLOR_TEXT_WHITE = (255, 255, 255, 255)
COLOR_TEXT_BODY = (226, 232, 240, 255)
COLOR_TEXT_MUTED = (148, 163, 184, 255)
COLOR_CARD_TRANSLUCENT = (18, 26, 46, 255)
COLOR_HERO_CARD = (22, 33, 58, 255)


def resolve_font(style: str = "regular", size: int = 24):
    candidates_map = {
        "black": [
            "fonts/PlusJakartaSans-ExtraBold.ttf",
            "fonts/Inter-Black.ttf",
            "/usr/share/fonts/truetype/plus-jakarta-sans/PlusJakartaSans-ExtraBold.ttf",
            "/usr/share/fonts/truetype/inter/Inter-Black.ttf",
            "/usr/share/fonts/truetype/lato/Lato-Black.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf",
            "C:\\Windows\\Fonts\\ariblk.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ],
        "bold": [
            "fonts/PlusJakartaSans-Bold.ttf",
            "fonts/Inter-Bold.ttf",
            "/usr/share/fonts/truetype/plus-jakarta-sans/PlusJakartaSans-Bold.ttf",
            "/usr/share/fonts/truetype/inter/Inter-Bold.ttf",
            "/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
            "C:\\Windows\\Fonts\\segoeuib.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ],
        "medium": [
            "fonts/PlusJakartaSans-SemiBold.ttf",
            "fonts/Inter-Medium.ttf",
            "/usr/share/fonts/truetype/plus-jakarta-sans/PlusJakartaSans-Medium.ttf",
            "/usr/share/fonts/truetype/inter/Inter-Medium.ttf",
            "/usr/share/fonts/truetype/lato/Lato-Medium.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ],
        "regular": [
            "fonts/PlusJakartaSans-Regular.ttf",
            "fonts/Inter-Regular.ttf",
            "/usr/share/fonts/truetype/plus-jakarta-sans/PlusJakartaSans-Regular.ttf",
            "/usr/share/fonts/truetype/inter/Inter-Regular.ttf",
            "/usr/share/fonts/truetype/lato/Lato-Regular.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ],
    }

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent

    for candidate in candidates_map.get(style, candidates_map["regular"]):
        paths_to_check = [
            candidate,
            str(project_root / candidate),
            str(script_dir / candidate),
            str(project_root / "static" / candidate),
        ]
        for p in paths_to_check:
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, int(size))
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
    x, y, radius = int(x), int(y), int(radius)
    draw.ellipse(
        [x - radius, y - radius, x + radius, y + radius],
        fill=(56, 189, 248, 40),
        outline=COLOR_CYAN,
        width=2,
    )
    draw.line(
        [(x - 5, y), (x - 1, y + 4), (x + 5, y - 4)],
        fill=COLOR_CYAN,
        width=2,
    )


def draw_vector_alert(draw: ImageDraw.Draw, x: int, y: int, radius: int = 11):
    x, y, radius = int(x), int(y), int(radius)
    draw.ellipse(
        [x - radius, y - radius, x + radius, y + radius],
        fill=(245, 158, 11, 40),
        outline=COLOR_AMBER,
        width=2,
    )
    draw.line([(x, y - 5), (x, y + 1)], fill=COLOR_AMBER, width=2)
    draw.point([(x, y + 4), (x, y + 5)], fill=COLOR_AMBER)


def draw_vector_arrow(draw: ImageDraw.Draw, x: int, y: int, length: int = 14):
    x, y, length = int(x), int(y), int(length)
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
    max_font_size: int = 40,
    min_font_size: int = 28,
):
    font_size = int(max_font_size)
    text = clean_text(text)
    while font_size >= min_font_size:
        font = resolve_font("bold", font_size)
        if draw.textlength(text, font=font) <= max_width_px:
            draw.text((x, y), text, font=font, fill=COLOR_GOLD)
            return int(y + font_size + 14)

        approx_chars = max(
            15, int(len(text) * (max_width_px / max(1, draw.textlength(text, font=font))))
        )
        lines = textwrap.wrap(text, width=approx_chars)
        if len(lines) <= 2 and all(
            draw.textlength(l, font=font) <= max_width_px for l in lines
        ):
            curr_y = int(y)
            for line in lines:
                draw.text((x, curr_y), line, font=font, fill=COLOR_GOLD)
                curr_y += font_size + 8
            return int(curr_y + 8)
        font_size -= 2

    font = resolve_font("bold", int(min_font_size))
    lines = textwrap.wrap(text, width=38)
    curr_y = int(y)
    for line in lines[:2]:
        draw.text((x, curr_y), line, font=font, fill=COLOR_GOLD)
        curr_y += int(min_font_size + 6)
    return int(curr_y + 8)


def get_logo_image(size: int = 46):
    try:
        from src.services.social_slide_renderer import get_logo_image as base_get_logo
        logo = base_get_logo(size=size)
        if logo:
            return logo
    except Exception:
        pass

    script_path = Path(__file__).resolve()
    backend_root = script_path.parent.parent.parent
    cwd = Path.cwd()

    candidate_paths = [
        os.getenv("POLITY_LOGO_PATH", ""),
        backend_root / "static" / "logo.png",
        backend_root / "public" / "logo.png",
        backend_root / "logo.png",
        cwd / "static" / "logo.png",
        cwd / "public" / "logo.png",
        cwd / "logo.png",
        cwd.parent / "static" / "logo.png",
        Path("static/logo.png"),
        Path("public/logo.png"),
        Path("logo.png")
    ]

    size = int(size)
    for p in candidate_paths:
        if p and os.path.exists(str(p)):
            try:
                logo = Image.open(str(p)).convert("RGBA")
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
        radius=26,
        fill=COLOR_CARD,
        outline=COLOR_CARD_BORDER,
        width=2,
    )

    logo = get_logo_image(size=46)
    text_x = 96
    if logo:
        img.paste(logo, (96, 84), logo)
        draw.ellipse([94, 82, 144, 132], outline=COLOR_GOLD, width=1)
        text_x = 156
    else:
        draw.ellipse([96, 84, 142, 130], fill=(28, 38, 64), outline=COLOR_GOLD, width=2)
        text_x = 156

    draw.text(
        (text_x, 92),
        "POLITY MENTOR",
        font=resolve_font("black", 26),
        fill=COLOR_GOLD,
    )
    draw.text(
        (W - 96 - 130, 96),
        f"SLIDE {slide_num}",
        font=resolve_font("bold", 20),
        fill=COLOR_TEXT_MUTED,
    )
    draw.line([(96, 144), (W - 96, 144)], fill=COLOR_CARD_BORDER, width=2)

    clean_badge = clean_text(tier_badge).upper()
    font_badge = resolve_font("bold", 17)
    badge_width = int(draw.textlength(clean_badge, font=font_badge)) + 38
    draw.rounded_rectangle(
        [96, 180, 96 + badge_width, 228],
        radius=12,
        fill=(28, 38, 64),
        outline=COLOR_GOLD,
        width=2,
    )
    draw.text((115, 194), clean_badge, font=font_badge, fill=COLOR_GOLD)

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
# PIB SLIDE 1: CLEAN TITLE & ANCHOR FOCUS CARD
# ---------------------------------------------------------------------------
def render_pib_slide_1(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])

    font_hero = resolve_font("black", 72)
    draw.text(
        (96, 275), clean_text(slide["headline"]), font=font_hero, fill=COLOR_GOLD
    )

    subhead_raw = clean_text(slide.get("subheadline", ""))
    font_size_sub = 22 if len(subhead_raw) > 52 else 25
    font_sub = resolve_font("bold", font_size_sub)
    subhead_lines = textwrap.wrap(subhead_raw, width=48)

    sub_y = 370
    for s_line in subhead_lines[:2]:
        cleaned_line = s_line.rstrip(" •–-").strip()
        draw.text((96, sub_y), cleaned_line, font=font_sub, fill=COLOR_CYAN)
        sub_y += 34

    # Robust thesis / core hook rendering
    font_body = resolve_font("regular", 22)
    hook_clean = clean_text(slide.get("core_hook", slide.get("thesis", "")))
    lines = textwrap.wrap(hook_clean, width=50)
    y_pos = sub_y + 32
    for line in lines:
        draw.text((96, y_pos), line, font=font_body, fill=COLOR_TEXT_BODY)
        y_pos += 34

    chip_y = max(y_pos + 46, 730)
    font_chip_title = resolve_font("bold", 19)
    font_chip_sub = resolve_font("medium", 16)

    chips = slide.get("chips", [])[:3]
    for chip in chips:
        if isinstance(chip, dict):
            c_title = clean_text(chip.get("article", chip.get("title", "")))
            c_desc = clean_text(chip.get("tagline", chip.get("desc", "")))
        else:
            c_raw = clean_text(str(chip))
            if "•" in c_raw:
                parts = c_raw.split("•", 1)
                c_title, c_desc = parts[0].strip(), parts[1].strip()
            elif ":" in c_raw:
                parts = c_raw.split(":", 1)
                c_title, c_desc = parts[0].strip(), parts[1].strip()
            else:
                c_title, c_desc = c_raw, ""

        c_title = textwrap.shorten(c_title, width=54, placeholder="...")

        pill_h = 72 if c_desc else 54
        half_h = int(pill_h // 2)

        draw.rounded_rectangle(
            [96, chip_y, W - 96, chip_y + pill_h],
            radius=16,
            fill=COLOR_CARD_TRANSLUCENT,
            outline=COLOR_CARD_BORDER,
            width=2,
        )
        draw.ellipse(
            [118, chip_y + half_h - 5, 128, chip_y + half_h + 5],
            fill=COLOR_CYAN,
        )

        draw.text(
            (144, chip_y + (10 if c_desc else 15)),
            c_title,
            font=font_chip_title,
            fill=COLOR_CYAN,
        )
        if c_desc:
            desc_clipped = textwrap.shorten(c_desc, width=68, placeholder="...")
            draw.text(
                (144, chip_y + 38),
                desc_clipped,
                font=font_chip_sub,
                fill=COLOR_TEXT_BODY,
            )

        chip_y += int(pill_h + 18)

    img.save(output_path, "PNG")


# ---------------------------------------------------------------------------
# PIB SLIDE 2: COMPLETE SUMMARY & STRATEGIC UPSC VALUE (EQUAL 21PX FONTS)
# ---------------------------------------------------------------------------
def render_pib_slide_2(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])

    next_y = draw_multiline_headline(
        draw, slide["headline"], 96, 260, max_width_px=880, max_font_size=40
    )
    draw.text(
        (96, next_y),
        clean_text(
            slide.get(
                "subheadline", "Strategic Governance & Institutional Analysis"
            )
        ),
        font=resolve_font("bold", 25),
        fill=COLOR_CYAN,
    )
    y_cursor = next_y + 32

    font_body_shared = resolve_font("medium", 21)
    line_h = 32

    # 1. Full Executive Summary Container
    summary_text = clean_text(slide.get("full_summary", slide.get("summary", "")))
    if summary_text:
        lines_sum = textwrap.wrap(summary_text, width=50)
        sum_h = int(52 + (len(lines_sum) * line_h) + 16)

        draw.rounded_rectangle(
            [96, y_cursor, W - 96, y_cursor + sum_h],
            radius=16,
            fill=COLOR_CARD_TRANSLUCENT,
            outline=COLOR_CARD_BORDER,
            width=2,
        )
        draw.text(
            (122, y_cursor + 16),
            "PIB EXECUTIVE CONTEXT",
            font=resolve_font("bold", 17),
            fill=COLOR_GOLD,
        )
        y_sl = y_cursor + 50
        for l in lines_sum:
            draw.text(
                (122, y_sl), l, font=font_body_shared, fill=COLOR_TEXT_WHITE
            )
            y_sl += line_h

        y_cursor += int(sum_h + 20)

    # 2. Strategic UPSC Value Hero Container
    narrative = clean_text(slide.get("analytical_insight", ""))
    if not narrative:
        narrative = "Examines structural institutional implications and governance impacts for GS-II."

    lines_nar = textwrap.wrap(narrative, width=50)
    box_padding_top = 74
    box_padding_bottom = 24
    box_h = int(box_padding_top + (len(lines_nar) * line_h) + box_padding_bottom)

    draw.rounded_rectangle(
        [96, y_cursor, W - 96, y_cursor + box_h],
        radius=18,
        fill=COLOR_HERO_CARD,
        outline=COLOR_CYAN,
        width=2,
    )
    draw.rounded_rectangle(
        [96, y_cursor, W - 96, y_cursor + 8],
        radius=4,
        fill=COLOR_GOLD,
    )

    draw.rounded_rectangle(
        [122, y_cursor + 20, 390, y_cursor + 56],
        radius=10,
        fill=(15, 23, 42),
        outline=COLOR_GOLD,
        width=2,
    )
    draw.text(
        (138, y_cursor + 28),
        "STRATEGIC UPSC VALUE",
        font=resolve_font("bold", 17),
        fill=COLOR_GOLD,
    )

    y_line = y_cursor + box_padding_top + 4
    for l in lines_nar:
        draw.text(
            (122, y_line), l, font=font_body_shared, fill=COLOR_TEXT_WHITE
        )
        y_line += line_h

    img.save(output_path, "PNG")


# ---------------------------------------------------------------------------
# PIB SLIDE 3: SMART NOTES (DYNAMIC BALANCED BOXES)
# ---------------------------------------------------------------------------
def render_pib_slide_3(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])

    next_y = draw_multiline_headline(
        draw, slide["headline"], 96, 260, max_width_px=880, max_font_size=38
    )
    draw.text(
        (96, next_y),
        clean_text(
            slide.get(
                "subheadline", "Targeted UPSC Current Affairs Deconstruction"
            )
        ),
        font=resolve_font("bold", 25),
        fill=COLOR_CYAN,
    )

    notes = slide.get("notes", [])[:4]
    start_y = next_y + 40
    available_height = (H - 140) - start_y
    card_gap = 16

    n = max(1, len(notes))
    box_h = int(min(175, (available_height - ((n - 1) * card_gap)) // n))

    font_title = resolve_font("bold", 21)
    font_body = resolve_font("regular", 18)

    y_card = start_y
    for idx, item in enumerate(notes, 1):
        title = clean_text(item.get("title", f"Directive #{idx}")).strip("'\"").strip()
        text = clean_text(item.get("desc", ""))

        draw.rounded_rectangle(
            [96, y_card, W - 96, y_card + box_h],
            radius=14,
            fill=COLOR_CARD_TRANSLUCENT,
            outline=COLOR_CARD_BORDER,
            width=2,
        )
        draw.rounded_rectangle(
            [112, y_card + 12, 117, y_card + box_h - 12],
            radius=2,
            fill=COLOR_GOLD,
        )
        draw.text((134, y_card + 14), title, font=font_title, fill=COLOR_GOLD)

        max_desc_lines = max(2, (box_h - 52) // 26)
        lines = textwrap.wrap(text, width=54)

        y_text = y_card + 46
        for l in lines[:max_desc_lines]:
            draw.text((134, y_text), l, font=font_body, fill=COLOR_TEXT_BODY)
            y_text += 26

        y_card += int(box_h + card_gap)

    img.save(output_path, "PNG")


# ---------------------------------------------------------------------------
# PIB SLIDE 4: ALL BACKWARD LINKAGES (NO WORD LIMIT TRUNCATIONS)
# ---------------------------------------------------------------------------
def render_pib_slide_4(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])

    next_y = draw_multiline_headline(
        draw, slide["headline"], 96, 260, max_width_px=880, max_font_size=38
    )
    draw.text(
        (96, next_y),
        clean_text(
            slide.get(
                "subheadline", "Constitutional Articles & Landmark Precedents"
            )
        ),
        font=resolve_font("bold", 25),
        fill=COLOR_CYAN,
    )

    points = slide.get("points", [])[:10]
    total_items = len(points)

    if total_items <= 5:
        y_card = next_y + 36
        for item in points:
            title = clean_text(item.get("title", "")).strip("'\"").strip()
            desc = clean_text(item.get("desc", ""))
            lines = textwrap.wrap(desc, width=54) if desc else []
            box_h = int(52 + (len(lines[:3]) * 25))

            draw.rounded_rectangle(
                [96, y_card, W - 96, y_card + box_h],
                radius=14,
                fill=COLOR_CARD_TRANSLUCENT,
                outline=COLOR_CARD_BORDER,
                width=2,
            )
            draw.ellipse([118, y_card + 19, 126, y_card + 27], fill=COLOR_GOLD)
            draw.text(
                (140, y_card + 12),
                title,
                font=resolve_font("bold", 20),
                fill=COLOR_TEXT_WHITE,
            )

            if lines:
                y_d = y_card + 42
                for l in lines[:3]:
                    draw.text(
                        (140, y_d),
                        l,
                        font=resolve_font("regular", 17),
                        fill=COLOR_TEXT_BODY,
                    )
                    y_d += 24
            y_card += int(box_h + 16)
    else:
        col_w = 428
        left_x = 96
        right_x = W - 96 - col_w
        start_y = next_y + 24

        num_rows = (total_items + 1) // 2
        available_height = (H - 135) - start_y
        row_gap = 10
        box_h = int(min(
            145, max(112, (available_height - (num_rows * row_gap)) // num_rows)
        ))

        font_tile_title = resolve_font("bold", 15)
        font_tile_desc = resolve_font("regular", 13)

        for idx, item in enumerate(points):
            col = idx % 2
            row = idx // 2

            x_pos = left_x if col == 0 else right_x
            y_pos = int(start_y + (row * (box_h + row_gap)))

            title = clean_text(item.get("title", "")).strip("'\"").strip()
            desc = clean_text(item.get("desc", ""))

            draw.rounded_rectangle(
                [x_pos, y_pos, x_pos + col_w, y_pos + box_h],
                radius=12,
                fill=COLOR_CARD_TRANSLUCENT,
                outline=COLOR_CARD_BORDER,
                width=2,
            )

            draw.ellipse(
                [x_pos + 14, y_pos + 14, x_pos + 20, y_pos + 20],
                fill=COLOR_CYAN,
            )

            title_lines = textwrap.wrap(title, width=34)

            # Center title vertically if no description is provided
            if not desc:
                total_title_h = len(title_lines[:2]) * 18
                y_title_cursor = y_pos + max(8, (box_h - total_title_h) // 2)
                for t_line in title_lines[:2]:
                    draw.text(
                        (x_pos + 28, y_title_cursor),
                        t_line,
                        font=font_tile_title,
                        fill=COLOR_TEXT_WHITE,
                    )
                    y_title_cursor += 18
            else:
                y_title_cursor = y_pos + 8
                for t_line in title_lines[:2]:
                    draw.text(
                        (x_pos + 28, y_title_cursor),
                        t_line,
                        font=font_tile_title,
                        fill=COLOR_TEXT_WHITE,
                    )
                    y_title_cursor += 18

                desc_lines = textwrap.wrap(desc, width=36)
                y_desc = max(y_title_cursor + 2, y_pos + (30 if len(title_lines) == 1 else 46))
                
                max_lines = 3 if len(title_lines) == 1 else 2
                for l in desc_lines[:max_lines]:
                    draw.text(
                        (x_pos + 28, y_desc),
                        l,
                        font=font_tile_desc,
                        fill=COLOR_TEXT_BODY,
                    )
                    y_desc += 16

    img.save(output_path, "PNG")


# ---------------------------------------------------------------------------
# PIB SLIDE 5: PRELIMS DRILL & MAINS ANALYTICAL QUESTION
# ---------------------------------------------------------------------------
def render_pib_slide_5(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])

    next_y = draw_multiline_headline(
        draw, slide["headline"], 96, 260, max_width_px=880, max_font_size=38
    )
    draw.text(
        (96, next_y),
        "Prelims Traps & Mains Analytical Question",
        font=resolve_font("bold", 25),
        fill=COLOR_CYAN,
    )
    y_cursor = next_y + 40

    font_param = resolve_font("bold", 20)
    font_content = resolve_font("regular", 18)
    font_content_bold = resolve_font("bold", 18)

    for r in slide.get("rows", [])[:2]:
        param = clean_text(r.get("param", ""))
        rule = clean_text(r.get("rule", ""))
        trap = clean_text(r.get("trap", ""))

        lines_rule = textwrap.wrap(f"Rule: {rule}", width=52)
        lines_trap = textwrap.wrap(f"Trap: {trap}", width=52)
        card_h = int(32 + ((len(lines_rule) + len(lines_trap)) * 26) + 14)

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

        y_row = y_cursor + 36
        draw_vector_check(draw, 126, y_row + 10, radius=8)
        for idx, l in enumerate(lines_rule):
            draw.text(
                (144, y_row),
                l,
                font=font_content_bold if idx == 0 else font_content,
                fill=COLOR_CYAN,
            )
            y_row += 26

        draw_vector_alert(draw, 126, y_row + 10, radius=8)
        for idx, l in enumerate(lines_trap):
            draw.text((144, y_row), l, font=font_content, fill=COLOR_AMBER)
            y_row += 26

        y_cursor += int(card_h + 16)

    mains_q = clean_text(slide.get("mains_question", ""))
    if mains_q:
        q_lines = textwrap.wrap(mains_q, width=52)
        q_h = int(44 + (len(q_lines) * 26) + 14)
        draw.rounded_rectangle(
            [96, y_cursor, W - 96, y_cursor + q_h],
            radius=14,
            fill=(30, 41, 70),
            outline=COLOR_CYAN,
            width=2,
        )
        draw.text(
            (120, y_cursor + 14),
            "MAINS ANALYTICAL QUESTION",
            font=resolve_font("bold", 18),
            fill=COLOR_CYAN,
        )
        y_ql = y_cursor + 42
        for l in q_lines:
            draw.text(
                (120, y_ql),
                l,
                font=resolve_font("regular", 19),
                fill=COLOR_TEXT_WHITE,
            )
            y_ql += 26

    img.save(output_path, "PNG")


# ---------------------------------------------------------------------------
# PIB SLIDE 6: ECOSYSTEM & CALL TO ACTION
# ---------------------------------------------------------------------------
def render_pib_slide_6(slide: dict, output_path: str):
    from src.services.social_slide_renderer import render_slide_6

    render_slide_6(slide, output_path)