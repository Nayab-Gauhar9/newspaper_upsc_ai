import os
import textwrap
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# BRAND PALETTE & CONSTANTS
# ---------------------------------------------------------------------------
COLOR_BG = (15, 23, 42, 255)          # #0F172A Deep Slate for the outer background margins
COLOR_CARD = (0, 0, 0, 255)           # Pure Black for the inner container surface
COLOR_CARD_BORDER = (51, 65, 85, 255) # Slate Border (#334155)
COLOR_GOLD = (168, 153, 123)          # #A8997B Warm Antique Gold
COLOR_ROSE = (185, 159, 159)          # #B99F9F Muted Metallic Rose
COLOR_CYAN = (56, 189, 248)           # #38BDF8 Soft Sky for Rules
COLOR_AMBER = (245, 158, 11)          # #F59E0B Warning Amber for Traps
COLOR_TEXT_WHITE = (248, 250, 252)    # Slate White
COLOR_TEXT_BODY = (203, 213, 225)     # #CBD5E1 Body Slate
COLOR_TEXT_MUTED = (148, 163, 184)    # Slate 400

# Inner content card box background (Navy Slate)
COLOR_CARD_TRANSLUCENT = (24, 34, 58, 255)

def resolve_font(style: str = "regular", size: int = 24):
    paths = {
        "black": [
            "/usr/share/fonts/truetype/lato/Lato-Black.ttf",
            "C:\\Windows\\Fonts\\ariblk.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        ],
        "bold": [
            "/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "C:\\Windows\\Fonts\\segoeuib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        ],
        "medium": [
            "/usr/share/fonts/truetype/lato/Lato-Medium.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ],
        "regular": [
            "/usr/share/fonts/truetype/lato/Lato-Regular.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ]
    }
    for candidate in paths.get(style, paths["regular"]):
        if os.path.exists(candidate):
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()

def clean_text(t: str) -> str:
    if not t:
        return ""
    replacements = {
        "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": " - ",
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2026": "...", "\u00a0": " ", "\u200b": "", "\u200e": "",
        "\u2713": "", "\u2714": "", "\u26a0": "", "\u2794": "->",
        "\u2192": "->"
    }
    for k, v in replacements.items():
        t = t.replace(k, v)
    return t.strip()

def draw_vector_check(draw: ImageDraw.Draw, x: int, y: int, radius: int = 11):
    draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(56, 189, 248, 35), outline=COLOR_CYAN, width=2)
    draw.line([(x - 5, y), (x - 1, y + 4), (x + 5, y - 4)], fill=COLOR_CYAN, width=2)

def draw_vector_alert(draw: ImageDraw.Draw, x: int, y: int, radius: int = 11):
    draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(245, 158, 11, 35), outline=COLOR_AMBER, width=2)
    draw.line([(x, y - 5), (x, y + 1)], fill=COLOR_AMBER, width=2)
    draw.point([(x, y + 4), (x, y + 5)], fill=COLOR_AMBER)

def draw_vector_arrow(draw: ImageDraw.Draw, x: int, y: int, length: int = 14):
    draw.line([(x - length, y), (x, y)], fill=COLOR_GOLD, width=2)
    draw.line([(x - 5, y - 5), (x, y), (x - 5, y + 5)], fill=COLOR_GOLD, width=2)

def draw_multiline_headline(draw: ImageDraw.Draw, text: str, x: int, y: int, max_width_px: int = 880, max_font_size: int = 38, min_font_size: int = 26):
    font_size = max_font_size
    text = clean_text(text)
    
    while font_size >= min_font_size:
        font = resolve_font("bold", font_size)
        if draw.textlength(text, font=font) <= max_width_px:
            draw.text((x, y), text, font=font, fill=COLOR_GOLD)
            return y + font_size + 14
        
        approx_chars = max(15, int(len(text) * (max_width_px / draw.textlength(text, font=font))))
        lines = textwrap.wrap(text, width=approx_chars)
        if len(lines) <= 2 and all(draw.textlength(l, font=font) <= max_width_px for l in lines):
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
        "public/logo.png.png"
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
    # Base outer canvas filled with #0F172A
    img = Image.new("RGBA", (W, H), COLOR_BG)
    draw = ImageDraw.Draw(img)

    # Inner container filled with solid Black
    card_margin = 46
    draw.rounded_rectangle(
        [card_margin, card_margin, W - card_margin, H - card_margin],
        radius=24,
        fill=COLOR_CARD,
        outline=COLOR_CARD_BORDER,
        width=2
    )

    # Header Logo + Brand Title
    logo = get_logo_image(size=44)
    text_x = 96
    if logo:
        img.paste(logo, (96, 84), logo)
        draw.ellipse([94, 82, 142, 130], outline=COLOR_GOLD, width=1)
        text_x = 152
    else:
        draw.ellipse([96, 84, 138, 126], fill=(28, 38, 64), outline=COLOR_GOLD, width=2)
        draw.line([(117, 92), (117, 118)], fill=COLOR_GOLD, width=2)
        draw.line([(106, 100), (128, 100)], fill=COLOR_GOLD, width=2)
        text_x = 152

    font_brand = resolve_font("black", 25)
    font_slide = resolve_font("bold", 20)
    draw.text((text_x, 92), "POLITY MENTOR", font=font_brand, fill=COLOR_GOLD)
    draw.text((W - 96 - 130, 96), f"SLIDE {slide_num}", font=font_slide, fill=COLOR_ROSE)
    draw.line([(96, 140), (W - 96, 140)], fill=COLOR_CARD_BORDER, width=2)

    # Category Pill Badge
    clean_badge = clean_text(tier_badge).upper()
    font_badge = resolve_font("bold", 17)
    badge_width = int(draw.textlength(clean_badge, font=font_badge)) + 38
    draw.rounded_rectangle([96, 178, 96 + badge_width, 226], radius=12, fill=(28, 38, 64), outline=COLOR_GOLD, width=2)
    draw.text((115, 192), clean_badge, font=font_badge, fill=COLOR_GOLD)

    # Footer
    draw.line([(96, H - 120), (W - 96, H - 120)], fill=COLOR_CARD_BORDER, width=2)
    font_footer = resolve_font("medium", 21)
    draw.text((96, H - 88), "politymentor.com", font=font_footer, fill=COLOR_TEXT_MUTED)
    
    cta_font = resolve_font("bold", 21)
    draw.text((W - 96 - 275, H - 88), "Swipe to continue", font=cta_font, fill=COLOR_GOLD)
    draw_vector_arrow(draw, W - 96 - 55, H - 77, length=12)

    return img, draw, W, H

# ---------------------------------------------------------------------------
# SLIDE 1: HOOK / THESIS
# ---------------------------------------------------------------------------
def render_slide_1(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])
    
    font_hero = resolve_font("black", 78)
    draw.text((96, 275), clean_text(slide["headline"]), font=font_hero, fill=COLOR_GOLD)

    font_sub = resolve_font("bold", 30)
    draw.text((96, 380), clean_text(slide.get("subheadline", "")), font=font_sub, fill=COLOR_ROSE)

    font_body = resolve_font("regular", 26)
    thesis_clean = clean_text(slide.get("thesis", ""))
    lines = textwrap.wrap(thesis_clean, width=46)
    y_pos = 460
    for line in lines:
        draw.text((96, y_pos), line, font=font_body, fill=COLOR_TEXT_BODY)
        y_pos += 40

    chip_y = max(y_pos + 45, 780)
    font_chip = resolve_font("bold", 20)
    for chip in slide.get("chips", []):
        chip_clean = clean_text(chip)
        draw.rounded_rectangle([96, chip_y, 96 + 500, chip_y + 52], radius=18, fill=COLOR_CARD_TRANSLUCENT, outline=COLOR_CARD_BORDER, width=2)
        draw.ellipse([118, chip_y + 21, 128, chip_y + 31], fill=COLOR_ROSE)
        draw.text((144, chip_y + 14), chip_clean, font=font_chip, fill=COLOR_ROSE)
        chip_y += 68

    img.save(output_path, "PNG")

# ---------------------------------------------------------------------------
# SLIDE 2: CAD CRUCIBLE
# ---------------------------------------------------------------------------
def render_slide_2(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])
    
    next_y = draw_multiline_headline(draw, slide["headline"], 96, 260, max_width_px=880, max_font_size=40)

    font_label = resolve_font("bold", 18)
    font_box_text = resolve_font("regular", 21)
    y_cursor = next_y + 10

    # 1. Colonial Roots
    colonial_text = clean_text(slide.get("colonial_context", "Derived from colonial statutory precedents."))
    lines_col = textwrap.wrap(colonial_text, width=54)
    box1_height = 46 + (len(lines_col) * 30) + 16
    draw.rounded_rectangle([96, y_cursor, W - 96, y_cursor + box1_height], radius=16, fill=COLOR_CARD_TRANSLUCENT, outline=COLOR_CARD_BORDER, width=2)
    draw.text((120, y_cursor + 14), clean_text(slide.get("colonial_title", "COLONIAL ROOTS (STATUTE ANCESTRY)")), font=font_label, fill=COLOR_ROSE)
    y_line = y_cursor + 44
    for l in lines_col:
        draw.text((120, y_line), l, font=font_box_text, fill=COLOR_TEXT_BODY)
        y_line += 30

    # 2. CAD Quote
    y_cursor += box1_height + 22
    raw_quote = clean_text(slide.get("cad_quote", ""))
    if not raw_quote or len(raw_quote) < 15:
        raw_quote = "The Governor under the Constitution has no functions which he can discharge by himself; no functions at all. While he has no functions, he has certain duties to perform."
    raw_quote = raw_quote.strip('\"')
    
    speaker = clean_text(slide.get("cad_speaker", "Dr. B.R. Ambedkar"))

    lines_q = textwrap.wrap(raw_quote, width=50)
    box2_height = 46 + (len(lines_q) * 32) + 48
    draw.rounded_rectangle([96, y_cursor, W - 96, y_cursor + box2_height], radius=16, fill=(30, 41, 70), outline=COLOR_ROSE, width=2)
    draw.text((120, y_cursor + 14), "CONSTITUENT ASSEMBLY CRUCIBLE", font=font_label, fill=COLOR_ROSE)
    font_quote = resolve_font("medium", 22)
    y_line = y_cursor + 48
    for idx, l in enumerate(lines_q):
        prefix = '“ ' if idx == 0 else '  '
        suffix = ' ”' if idx == len(lines_q) - 1 else ''
        draw.text((120, y_line), f"{prefix}{l}{suffix}", font=font_quote, fill=COLOR_TEXT_WHITE)
        y_line += 32
    draw.text((120, y_line + 8), f"- {speaker}", font=font_label, fill=COLOR_GOLD)

    # 3. Paradox Box
    y_cursor += box2_height + 22
    paradox_text = clean_text(slide.get("analytical_insight", "The constitutional architecture creates an inherent institutional friction."))
    lines_p = textwrap.wrap(paradox_text, width=54)
    box3_height = 46 + (len(lines_p) * 30) + 16
    draw.rounded_rectangle([96, y_cursor, W - 96, y_cursor + box3_height], radius=16, fill=COLOR_CARD_TRANSLUCENT, outline=COLOR_CARD_BORDER, width=2)
    draw.text((120, y_cursor + 14), "THE JURISPRUDENTIAL PARADOX", font=font_label, fill=COLOR_GOLD)
    y_line = y_cursor + 44
    for l in lines_p:
        draw.text((120, y_line), l, font=font_box_text, fill=COLOR_TEXT_BODY)
        y_line += 30

    img.save(output_path, "PNG")

# ---------------------------------------------------------------------------
# SLIDE 3: LANDMARK PRECEDENT
# ---------------------------------------------------------------------------
def render_slide_3(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])
    
    next_y = draw_multiline_headline(draw, slide["headline"], 96, 260, max_width_px=880, max_font_size=36, min_font_size=26)

    font_sub = resolve_font("bold", 25)
    draw.text((96, next_y), clean_text(slide.get("subheadline", "Doctrinal Milestone")), font=font_sub, fill=COLOR_ROSE)

    points = slide.get("points", [])
    if not points:
        points = [
            {"title": "1. Judicial Threshold", "desc": slide.get("condition_precedent", "")},
            {"title": "2. Proviso Mandate", "desc": slide.get("legislative_supremacy", "")},
            {"title": "3. Scope of Review", "desc": slide.get("justiciability", "")}
        ]

    y_card = next_y + 45
    for idx, item in enumerate(points[:3], 1):
        title = clean_text(item.get("title", f"{idx}. Legal Doctrine"))
        desc = clean_text(item.get("desc", ""))
        lines = textwrap.wrap(desc, width=54)
        c_height = 42 + (len(lines) * 27) + 16

        draw.rounded_rectangle([96, y_card, W - 96, y_card + c_height], radius=16, fill=COLOR_CARD_TRANSLUCENT, outline=COLOR_CARD_BORDER, width=2)
        draw.text((120, y_card + 12), title, font=resolve_font("bold", 21), fill=COLOR_GOLD)
        y_t = y_card + 42
        for l in lines:
            draw.text((120, y_t), l, font=resolve_font("regular", 20), fill=COLOR_TEXT_BODY)
            y_t += 27
        y_card += c_height + 18

    img.save(output_path, "PNG")

# ---------------------------------------------------------------------------
# SLIDE 4: PROCEDURAL MATRIX & TRAPS
# ---------------------------------------------------------------------------
def render_slide_4(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])
    
    next_y = draw_multiline_headline(draw, slide["headline"], 96, 260, max_width_px=880, max_font_size=38)

    font_sub = resolve_font("bold", 25)
    draw.text((96, next_y), "Constitutional Rule vs. Prelims Trap", font=font_sub, fill=COLOR_ROSE)

    rows = slide.get("rows", [])
    y_table = next_y + 45
    font_param = resolve_font("bold", 20)
    font_content = resolve_font("regular", 19)
    font_content_bold = resolve_font("bold", 19)

    for r in rows:
        param = clean_text(r.get("param", ""))
        rule = clean_text(r.get("rule", ""))
        trap = clean_text(r.get("trap", ""))

        lines_rule = textwrap.wrap(f"Rule: {rule}", width=50)
        lines_trap = textwrap.wrap(f"Trap: {trap}", width=50)
        card_h = 32 + ((len(lines_rule) + len(lines_trap)) * 25) + 14

        draw.rounded_rectangle([96, y_table, W - 96, y_table + card_h], radius=14, fill=COLOR_CARD_TRANSLUCENT, outline=COLOR_CARD_BORDER, width=2)
        draw.text((120, y_table + 10), param, font=font_param, fill=COLOR_TEXT_WHITE)

        # Rule
        y_row = y_table + 38
        draw_vector_check(draw, 126, y_row + 10, radius=8)
        for idx, l in enumerate(lines_rule):
            draw.text((144, y_row), l, font=font_content_bold if idx == 0 else font_content, fill=COLOR_CYAN)
            y_row += 25

        # Trap
        draw_vector_alert(draw, 126, y_row + 10, radius=8)
        for idx, l in enumerate(lines_trap):
            draw.text((144, y_row), l, font=font_content, fill=COLOR_AMBER)
            y_row += 25

        y_table += card_h + 14

    img.save(output_path, "PNG")

# ---------------------------------------------------------------------------
# SLIDE 5: MAINS BLUEPRINT
# ---------------------------------------------------------------------------
def render_slide_5(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])
    
    next_y = draw_multiline_headline(draw, slide["headline"], 96, 260, max_width_px=880, max_font_size=38)

    font_sub = resolve_font("bold", 25)
    draw.text((96, next_y), "High-Scoring GS-II Structure", font=font_sub, fill=COLOR_ROSE)

    dimensions = slide.get("dimensions", [])
    y_box = next_y + 45
    for item in dimensions:
        label = clean_text(item[0])
        text = clean_text(item[1]).rstrip('.').rstrip(' ') + '.'

        lines = textwrap.wrap(text, width=54)
        box_h = 38 + (len(lines) * 26) + 14

        draw.rounded_rectangle([96, y_box, W - 96, y_box + box_h], radius=16, fill=COLOR_CARD_TRANSLUCENT, outline=COLOR_CARD_BORDER, width=2)
        draw.text((120, y_box + 12), label, font=resolve_font("bold", 21), fill=COLOR_GOLD)
        y_t = y_box + 40
        for l in lines:
            draw.text((120, y_t), l, font=resolve_font("regular", 19), fill=COLOR_TEXT_BODY)
            y_t += 26
        y_box += box_h + 16

    img.save(output_path, "PNG")