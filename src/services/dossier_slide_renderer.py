import os
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# BRAND PALETTE & CONSTANTS (#0F172A Deep Slate Theme)
# ---------------------------------------------------------------------------
COLOR_BG = (15, 23, 42, 255)          # #0F172A Deep Slate outer margin
COLOR_CARD = (0, 0, 0, 255)           # Pure Black inner card container
COLOR_CARD_BORDER = (51, 65, 85, 255) # Slate Border (#334155)
COLOR_GOLD = (168, 153, 123)          # Antique Gold (#A8997B)
COLOR_ROSE = (185, 159, 159)          # Muted Metallic Rose (#B99F9F)
COLOR_CYAN = (56, 189, 248)           # Sky Blue (#38BDF8)
COLOR_AMBER = (245, 158, 11)          # Warning Amber (#F59E0B)
COLOR_TEXT_WHITE = (248, 250, 252)    # Slate White
COLOR_TEXT_BODY = (203, 213, 225)     # Body Slate (#CBD5E1)
COLOR_TEXT_MUTED = (148, 163, 184)    # Slate 400
COLOR_CARD_TRANSLUCENT = (24, 34, 58, 255) # Translucent Navy Slate


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


def draw_vector_arrow(draw: ImageDraw.Draw, x: int, y: int, length: int = 14):
    draw.line([(x - length, y), (x, y)], fill=COLOR_GOLD, width=2)
    draw.line([(x - 5, y - 5), (x, y), (x - 5, y + 5)], fill=COLOR_GOLD, width=2)


def draw_multiline_headline(
    draw: ImageDraw.Draw,
    text: str,
    x: int,
    y: int,
    max_width_px: int = 880,
    max_font_size: int = 40,
    min_font_size: int = 26,
):
    font_size = max_font_size
    text = clean_text(text)
    while font_size >= min_font_size:
        font = resolve_font("bold", font_size)
        if draw.textlength(text, font=font) <= max_width_px:
            draw.text((x, y), text, font=font, fill=COLOR_GOLD)
            return y + font_size + 16

        approx_chars = max(
            15,
            int(len(text) * (max_width_px / max(1, draw.textlength(text, font=font)))),
        )
        lines = textwrap.wrap(text, width=approx_chars)
        if len(lines) <= 2 and all(
            draw.textlength(l, font=font) <= max_width_px for l in lines
        ):
            curr_y = y
            for line in lines:
                draw.text((x, curr_y), line, font=font, fill=COLOR_GOLD)
                curr_y += font_size + 10
            return curr_y + 10
        font_size -= 2

    font = resolve_font("bold", min_font_size)
    lines = textwrap.wrap(text, width=42)
    curr_y = y
    for line in lines[:2]:
        draw.text((x, curr_y), line, font=font, fill=COLOR_GOLD)
        curr_y += min_font_size + 8
    return curr_y + 10


def get_logo_image(size: int = 44):
    """Imports proven logo resolver from social_slide_renderer with fallback path checking."""
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
        Path("C:/Project/newspaper_upsc_ai/static/logo.png"),
        Path("static/logo.png"),
        Path("public/logo.png"),
        Path("logo.png"),
    ]

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


def create_base_canvas(slide_num: str, tier_badge: str, status_tag: str = "ACTIVE"):
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

    # Topic badge pill
    clean_badge = clean_text(tier_badge).upper()
    font_badge = resolve_font("bold", 16)
    badge_width = int(draw.textlength(clean_badge, font=font_badge)) + 32
    draw.rounded_rectangle(
        [96, 178, 96 + badge_width, 224],
        radius=12,
        fill=(28, 38, 64),
        outline=COLOR_GOLD,
        width=2,
    )
    draw.text((112, 192), clean_badge, font=font_badge, fill=COLOR_GOLD)

    # Living status indicator pill
    is_active = status_tag.upper() == "ACTIVE"
    status_label = "● ACTIVE DOSSIER" if is_active else "✔ SETTLED RATIO"
    status_col = COLOR_AMBER if is_active else COLOR_CYAN
    status_w = int(draw.textlength(status_label, font=font_badge)) + 26
    start_x = 96 + badge_width + 16
    draw.rounded_rectangle(
        [start_x, 178, start_x + status_w, 224],
        radius=12,
        fill=(20, 26, 44),
        outline=status_col,
        width=1,
    )
    draw.text((start_x + 13, 192), status_label, font=font_badge, fill=status_col)

    # Footer: measured CTA text length prevents overlap with arrow
    draw.line([(96, H - 120), (W - 96, H - 120)], fill=COLOR_CARD_BORDER, width=2)
    draw.text(
        (96, H - 88),
        "politymentor.com",
        font=resolve_font("medium", 21),
        fill=COLOR_TEXT_MUTED,
    )

    cta_text = "Swipe to track issue"
    cta_font = resolve_font("bold", 21)
    text_w = int(draw.textlength(cta_text, font=cta_font))
    arrow_margin = 48
    arrow_x = W - 96 - arrow_margin
    text_x = arrow_x - text_w - 18

    draw.text((text_x, H - 88), cta_text, font=cta_font, fill=COLOR_GOLD)
    draw_vector_arrow(draw, arrow_x, H - 77, length=12)

    return img, draw, W, H


def draw_tracking_banner(draw: ImageDraw.Draw, W: int, H: int, notice_text: str):
    """Renders the cyan multi-update banner pinned uniformly above the footer."""
    if not notice_text:
        return
    y_notice = H - 192
    draw.rounded_rectangle(
        [96, y_notice, W - 96, y_notice + 56],
        radius=14,
        fill=(18, 30, 52),
        outline=COLOR_CYAN,
        width=1,
    )
    draw_vector_arrow(draw, 126, y_notice + 28, length=12)
    draw.text(
        (142, y_notice + 16),
        clean_text(notice_text),
        font=resolve_font("bold", 18),
        fill=COLOR_CYAN,
    )


# ---------------------------------------------------------------------------
# SLIDE 1: DOSSIER HOOK & DISPUTE GENESIS
# ---------------------------------------------------------------------------
def render_dossier_slide_1(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(
        slide["slide_num"], slide["tier_badge"], slide.get("status", "ACTIVE")
    )

    next_y = draw_multiline_headline(
        draw, slide["headline"], 96, 260, max_width_px=880, max_font_size=40, min_font_size=28
    )
    draw.text(
        (96, next_y),
        clean_text(slide.get("subheadline", "The Living Constitutional Standoff")),
        font=resolve_font("bold", 25),
        fill=COLOR_ROSE,
    )

    y_pos = next_y + 44
    summary = clean_text(slide.get("summary", ""))
    font_summary = resolve_font("medium", 22)
    line_h_sum = 32

    lines = textwrap.wrap(summary, width=48)
    card_h = 54 + (len(lines) * line_h_sum) + 18
    draw.rounded_rectangle(
        [96, y_pos, W - 96, y_pos + card_h],
        radius=16,
        fill=(30, 41, 70),
        outline=COLOR_ROSE,
        width=2,
    )
    draw.text(
        (120, y_pos + 18),
        "DISPUTE GENESIS",
        font=resolve_font("bold", 19),
        fill=COLOR_ROSE,
    )

    y_l = y_pos + 56
    for l in lines:
        draw.text((120, y_l), l, font=font_summary, fill=COLOR_TEXT_WHITE)
        y_l += line_h_sum

    y_chips = y_pos + card_h + 28
    font_chip = resolve_font("bold", 20)
    for chip in slide.get("chips", []):
        draw.rounded_rectangle(
            [96, y_chips, W - 96, y_chips + 56],
            radius=16,
            fill=COLOR_CARD_TRANSLUCENT,
            outline=COLOR_CARD_BORDER,
            width=2,
        )
        draw.ellipse([120, y_chips + 23, 130, y_chips + 33], fill=COLOR_GOLD)
        draw.text(
            (146, y_chips + 16), clean_text(chip), font=font_chip, fill=COLOR_GOLD
        )
        y_chips += 70

    if slide.get("more_updates_notice"):
        draw_tracking_banner(draw, W, H, slide["more_updates_notice"])

    img.save(output_path, "PNG")


# ---------------------------------------------------------------------------
# SLIDE 2: STATIC CONSTITUTIONAL ANCHORS
# ---------------------------------------------------------------------------
def render_dossier_slide_2(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(
        slide["slide_num"], slide["tier_badge"], slide.get("status", "ACTIVE")
    )

    next_y = draw_multiline_headline(
        draw,
        slide.get("headline", "Constitutional & Statutory Anchors"),
        96,
        260,
        max_width_px=880,
        max_font_size=40,
    )
    draw.text(
        (96, next_y),
        clean_text(slide.get("subheadline", "Static Law Grounding the Dynamic Dispute")),
        font=resolve_font("bold", 25),
        fill=COLOR_ROSE,
    )

    y_card = next_y + 46
    anchors = slide.get("anchors", [])
    font_title = resolve_font("bold", 23)
    font_body = resolve_font("regular", 22)
    line_h = 32

    for item in anchors[:3]:
        title = clean_text(item.get("title", ""))
        desc = clean_text(item.get("desc", ""))

        if not desc:
            desc = "Constitutional provision governing statutory limits and executive authority in this dispute."

        lines = textwrap.wrap(desc, width=50)
        c_height = 52 + (len(lines) * line_h) + 16

        draw.rounded_rectangle(
            [96, y_card, W - 96, y_card + c_height],
            radius=16,
            fill=COLOR_CARD_TRANSLUCENT,
            outline=COLOR_CARD_BORDER,
            width=2,
        )
        draw.rounded_rectangle(
            [112, y_card + 16, 117, y_card + c_height - 16],
            radius=2,
            fill=COLOR_CYAN,
        )
        draw.text((134, y_card + 14), title, font=font_title, fill=COLOR_CYAN)
        y_t = y_card + 52
        for l in lines:
            draw.text((134, y_t), l, font=font_body, fill=COLOR_TEXT_BODY)
            y_t += line_h
        y_card += c_height + 26

    if slide.get("more_updates_notice"):
        draw_tracking_banner(draw, W, H, slide["more_updates_notice"])

    img.save(output_path, "PNG")


# ---------------------------------------------------------------------------
# SLIDE 3: DISPUTE TIMELINE
# ---------------------------------------------------------------------------
def render_dossier_slide_3(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(
        slide["slide_num"], slide["tier_badge"], slide.get("status", "ACTIVE")
    )

    headline = clean_text(slide.get("headline", "Evolutionary Trajectory"))
    next_y = draw_multiline_headline(
        draw, headline, 96, 260, max_width_px=880, max_font_size=40
    )
    draw.text(
        (96, next_y),
        clean_text(slide.get("subheadline", "Documenting Key Interventions")),
        font=resolve_font("bold", 25),
        fill=COLOR_ROSE,
    )

    nodes = slide.get("nodes", [])
    y_card = next_y + 44
    font_tag = resolve_font("bold", 16)
    font_title = resolve_font("bold", 22)
    font_body = resolve_font("regular", 21)
    line_h_body = 30
    line_h_title = 28

    for idx, node in enumerate(nodes[:2], start=1):
        date_str = clean_text(node.get("date", "2026"))
        pub_str = clean_text(node.get("publication", "Official Notice")).upper()
        raw_title = clean_text(node.get("title", f"Event Node #{idx}"))
        body = clean_text(node.get("body", ""))

        title_lines = textwrap.wrap(raw_title, width=44)
        body_lines = textwrap.wrap(body, width=48)

        title_block_h = len(title_lines) * line_h_title
        body_block_h = len(body_lines) * line_h_body
        box_h = 44 + title_block_h + 16 + body_block_h + 18

        draw.rounded_rectangle(
            [96, y_card, W - 96, y_card + box_h],
            radius=16,
            fill=COLOR_CARD_TRANSLUCENT,
            outline=COLOR_CARD_BORDER,
            width=2,
        )

        tag_text = f"MILESTONE #{idx} • {date_str} • {pub_str}"
        draw.text((120, y_card + 16), tag_text, font=font_tag, fill=COLOR_GOLD)

        cur_title_y = y_card + 44
        for t_line in title_lines:
            draw.text((120, cur_title_y), t_line, font=font_title, fill=COLOR_TEXT_WHITE)
            cur_title_y += line_h_title

        cur_body_y = cur_title_y + 12
        for b_line in body_lines:
            draw.text((120, cur_body_y), b_line, font=font_body, fill=COLOR_TEXT_BODY)
            cur_body_y += line_h_body

        y_card += box_h + 24

    if slide.get("more_updates_notice"):
        draw_tracking_banner(draw, W, H, slide["more_updates_notice"])

    img.save(output_path, "PNG")


# ---------------------------------------------------------------------------
# SLIDE 4: RECENT ESCALATION / RAMIFICATIONS
# ---------------------------------------------------------------------------
def render_dossier_slide_4(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(
        slide["slide_num"], slide["tier_badge"], slide.get("status", "ACTIVE")
    )

    headline = clean_text(slide.get("headline", "Legal Ramifications & Thresholds"))
    next_y = draw_multiline_headline(
        draw, headline, 96, 260, max_width_px=880, max_font_size=40
    )
    draw.text(
        (96, next_y),
        clean_text(slide.get("subheadline", "Institutional Impact & Future Contestation")),
        font=resolve_font("bold", 25),
        fill=COLOR_ROSE,
    )

    points = slide.get("points", [])
    y_card = next_y + 44
    font_title = resolve_font("bold", 23)
    font_body = resolve_font("regular", 22)
    line_h = 31

    for idx, item in enumerate(points[:3], start=1):
        title = clean_text(item.get("title", f"Dimension #{idx}"))
        desc = clean_text(item.get("desc", ""))
        lines = textwrap.wrap(desc, width=50)
        c_height = 50 + (len(lines) * line_h) + 16

        draw.rounded_rectangle(
            [96, y_card, W - 96, y_card + c_height],
            radius=16,
            fill=COLOR_CARD_TRANSLUCENT,
            outline=COLOR_CARD_BORDER,
            width=2,
        )
        draw.rounded_rectangle(
            [112, y_card + 16, 117, y_card + c_height - 16],
            radius=2,
            fill=COLOR_AMBER,
        )
        draw.text((134, y_card + 14), title, font=font_title, fill=COLOR_AMBER)
        y_t = y_card + 50
        for l in lines:
            draw.text((134, y_t), l, font=font_body, fill=COLOR_TEXT_BODY)
            y_t += line_h
        y_card += c_height + 24

    if slide.get("more_updates_notice"):
        draw_tracking_banner(draw, W, H, slide["more_updates_notice"])

    img.save(output_path, "PNG")


# ---------------------------------------------------------------------------
# SLIDE 5: THE DIALECTICAL STANDOFF
# ---------------------------------------------------------------------------
def render_dossier_slide_5(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(
        slide["slide_num"], slide["tier_badge"], slide.get("status", "ACTIVE")
    )

    next_y = draw_multiline_headline(
        draw, "The Constitutional Stand-Off", 96, 260, max_width_px=880, max_font_size=40
    )
    draw.text(
        (96, next_y),
        "Thesis vs. Jurisprudential Critique",
        font=resolve_font("bold", 25),
        fill=COLOR_ROSE,
    )

    y_box = next_y + 46
    font_head = resolve_font("bold", 18)
    font_body = resolve_font("regular", 22)
    line_height = 32

    # 1. Thesis (Cyan Box)
    thesis_text = clean_text(slide.get("thesis", ""))
    lines_t = textwrap.wrap(thesis_text, width=48)
    box1_h = 56 + (len(lines_t) * line_height) + 18
    draw.rounded_rectangle(
        [96, y_box, W - 96, y_box + box1_h],
        radius=16,
        fill=(18, 26, 46),
        outline=COLOR_CYAN,
        width=2,
    )
    draw.text(
        (120, y_box + 18),
        "THE CONSTITUTIONAL THESIS (STATE MANDATE)",
        font=font_head,
        fill=COLOR_CYAN,
    )
    y_l = y_box + 54
    for l in lines_t:
        draw.text((120, y_l), l, font=font_body, fill=COLOR_TEXT_WHITE)
        y_l += line_height

    y_box += box1_h + 28

    # 2. Critique (Amber Box)
    critique_text = clean_text(slide.get("critique", ""))
    lines_c = textwrap.wrap(critique_text, width=48)
    box2_h = 56 + (len(lines_c) * line_height) + 18
    draw.rounded_rectangle(
        [96, y_box, W - 96, y_box + box2_h],
        radius=16,
        fill=(35, 24, 30),
        outline=COLOR_AMBER,
        width=2,
    )
    draw.text(
        (120, y_box + 18),
        "THE DIALECTICAL CRITIQUE (CONSTITUTIONAL TEST)",
        font=font_head,
        fill=COLOR_AMBER,
    )
    y_l = y_box + 54
    for l in lines_c:
        draw.text((120, y_l), l, font=font_body, fill=COLOR_TEXT_BODY)
        y_l += line_height

    if slide.get("more_updates_notice"):
        draw_tracking_banner(draw, W, H, slide["more_updates_notice"])

    img.save(output_path, "PNG")


# ---------------------------------------------------------------------------
# SLIDE 6: ECOSYSTEM REUSE
# ---------------------------------------------------------------------------
def render_dossier_slide_6(slide: dict, output_path: str):
    from src.services.social_slide_renderer import render_slide_6
    render_slide_6(slide, output_path)