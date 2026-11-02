import os
import json
import textwrap
import requests
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import or_

# Database session & models
from src.database.session import SessionLocal
from src.database.models import ConstitutionalArticleModel

# ---------------------------------------------------------------------------
# 1. BRAND PALETTE & TYPOGRAPHY
# ---------------------------------------------------------------------------
COLOR_BG = (15, 23, 42, 255)          # #0F172A Deep Slate Background
COLOR_CARD = (22, 32, 54, 255)        # #162036 Elevated Card Surface
COLOR_CARD_BORDER = (51, 65, 85, 255) # #334155 Slate Border
COLOR_GOLD = (168, 153, 123)          # #A8997B Warm Antique Gold (Hero Headers)
COLOR_ROSE = (185, 159, 159)          # #B99F9F Muted Metallic Rose (Subheads)
COLOR_CYAN = (56, 189, 248)           # #38BDF8 Soft Sky for Rules
COLOR_AMBER = (245, 158, 11)          # #F59E0B Warning Amber for Traps
COLOR_TEXT_WHITE = (248, 250, 252)    # Slate White
COLOR_TEXT_BODY = (203, 213, 225)     # #CBD5E1 Body Slate
COLOR_TEXT_MUTED = (148, 163, 184)    # Slate 400

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
    """Sanitizes unicode dashes, smart quotes, and unrendered glyphs."""
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
    """Dynamically wraps and auto-scales headlines so long citations never clip."""
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
        width=2
    )

    # Top Brand Navigation
    font_brand = resolve_font("black", 25)
    font_slide = resolve_font("bold", 20)
    draw.text((96, 92), "POLITY MENTOR", font=font_brand, fill=COLOR_GOLD)
    draw.text((W - 96 - 130, 96), f"SLIDE {slide_num}", font=font_slide, fill=COLOR_ROSE)
    draw.line([(96, 140), (W - 96, 140)], fill=COLOR_CARD_BORDER, width=2)

    # Category Pill
    clean_badge = clean_text(tier_badge).upper()
    font_badge = resolve_font("bold", 17)
    badge_width = int(draw.textlength(clean_badge, font=font_badge)) + 38
    draw.rounded_rectangle([96, 178, 96 + badge_width, 226], radius=12, fill=(28, 38, 64), outline=COLOR_GOLD, width=2)
    draw.text((115, 192), clean_badge, font=font_badge, fill=COLOR_GOLD)

    # Bottom Footer
    draw.line([(96, H - 120), (W - 96, H - 120)], fill=COLOR_CARD_BORDER, width=2)
    font_footer = resolve_font("medium", 21)
    draw.text((96, H - 88), "politymentor.com", font=font_footer, fill=COLOR_TEXT_MUTED)
    
    cta_font = resolve_font("bold", 21)
    draw.text((W - 96 - 275, H - 88), "Swipe to continue", font=cta_font, fill=COLOR_GOLD)
    draw_vector_arrow(draw, W - 96 - 55, H - 77, length=12)

    return img, draw, W, H

# ---------------------------------------------------------------------------
# 2. SLIDE RENDERERS
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
        draw.rounded_rectangle([96, chip_y, 96 + 500, chip_y + 52], radius=18, fill=(28, 38, 64), outline=COLOR_CARD_BORDER, width=2)
        draw.ellipse([118, chip_y + 21, 128, chip_y + 31], fill=COLOR_ROSE)
        draw.text((144, chip_y + 14), chip_clean, font=font_chip, fill=COLOR_ROSE)
        chip_y += 68

    img.save(output_path, "PNG")

def render_slide_2(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])
    
    next_y = draw_multiline_headline(draw, slide["headline"], 96, 260, max_width_px=880, max_font_size=40)

    font_label = resolve_font("bold", 18)
    font_box_text = resolve_font("regular", 21)
    y_cursor = next_y + 10

    # 1. Colonial Genesis Box
    colonial_text = clean_text(slide.get("colonial_context", "Derived from colonial statutory precedents."))
    lines_col = textwrap.wrap(colonial_text, width=54)
    box1_height = 46 + (len(lines_col) * 30) + 16
    draw.rounded_rectangle([96, y_cursor, W - 96, y_cursor + box1_height], radius=16, fill=(24, 34, 58), outline=COLOR_CARD_BORDER, width=2)
    draw.text((120, y_cursor + 14), clean_text(slide.get("colonial_title", "COLONIAL ROOTS (GOI ACT 1935)")), font=font_label, fill=COLOR_ROSE)
    y_line = y_cursor + 44
    for l in lines_col:
        draw.text((120, y_line), l, font=font_box_text, fill=COLOR_TEXT_BODY)
        y_line += 30

    # 2. CAD Crucible Quote Card (Guaranteed substantive quote)
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

    # 3. Structural Paradox Box
    y_cursor += box2_height + 22
    paradox_text = clean_text(slide.get("analytical_insight", "The constitutional architecture creates an inherent institutional friction."))
    lines_p = textwrap.wrap(paradox_text, width=54)
    box3_height = 46 + (len(lines_p) * 30) + 16
    draw.rounded_rectangle([96, y_cursor, W - 96, y_cursor + box3_height], radius=16, fill=(24, 34, 58), outline=COLOR_CARD_BORDER, width=2)
    draw.text((120, y_cursor + 14), "THE JURISPRUDENTIAL PARADOX", font=font_label, fill=COLOR_GOLD)
    y_line = y_cursor + 44
    for l in lines_p:
        draw.text((120, y_line), l, font=font_box_text, fill=COLOR_TEXT_BODY)
        y_line += 30

    img.save(output_path, "PNG")

def render_slide_3(slide: dict, output_path: str):
    img, draw, W, H = create_base_canvas(slide["slide_num"], slide["tier_badge"])
    
    # Auto-scaling multi-line headline for long citations
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

        draw.rounded_rectangle([96, y_card, W - 96, y_card + c_height], radius=16, fill=(24, 34, 58), outline=COLOR_CARD_BORDER, width=2)
        draw.text((120, y_card + 12), title, font=resolve_font("bold", 21), fill=COLOR_GOLD)
        y_t = y_card + 42
        for l in lines:
            draw.text((120, y_t), l, font=resolve_font("regular", 20), fill=COLOR_TEXT_BODY)
            y_t += 27
        y_card += c_height + 18

    img.save(output_path, "PNG")

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

        draw.rounded_rectangle([96, y_table, W - 96, y_table + card_h], radius=14, fill=(24, 34, 58), outline=COLOR_CARD_BORDER, width=2)
        draw.text((120, y_table + 10), param, font=font_param, fill=COLOR_TEXT_WHITE)

        # Rule row
        y_row = y_table + 38
        draw_vector_check(draw, 126, y_row + 10, radius=8)
        for idx, l in enumerate(lines_rule):
            draw.text((144, y_row), l, font=font_content_bold if idx == 0 else font_content, fill=COLOR_CYAN)
            y_row += 25

        # Trap row
        draw_vector_alert(draw, 126, y_row + 10, radius=8)
        for idx, l in enumerate(lines_trap):
            draw.text((144, y_row), l, font=font_content, fill=COLOR_AMBER)
            y_row += 25

        y_table += card_h + 14

    img.save(output_path, "PNG")

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

        draw.rounded_rectangle([96, y_box, W - 96, y_box + box_h], radius=16, fill=(24, 34, 58), outline=COLOR_CARD_BORDER, width=2)
        draw.text((120, y_box + 12), label, font=resolve_font("bold", 21), fill=COLOR_GOLD)
        y_t = y_box + 40
        for l in lines:
            draw.text((120, y_t), l, font=resolve_font("regular", 19), fill=COLOR_TEXT_BODY)
            y_t += 26
        y_box += box_h + 16

    img.save(output_path, "PNG")

# ---------------------------------------------------------------------------
# 3. GROQ SYNTHESIS (Strict Context Grounding & No Ellipses)
# ---------------------------------------------------------------------------
GROQ_SYSTEM_PROMPT = """
You are a senior constitutional scholar and UPSC GS-II mentor.
Analyze the provided database record of a Constitutional Article in rigorous depth.

CRITICAL INSTRUCTIONS:
1. Stay strictly factual to the provided provision. For Article 200, it is strictly about the GOVERNOR and STATE LEGISLATIVE ASSEMBLY (never mix with Article 111 / President / Parliament).
2. For Slide 2: Ensure cad_quote contains a full substantive 2-3 sentence debate excerpt from the Constituent Assembly. Never leave it blank.
3. For Slide 3: Use the exact milestone case name from the database context as headline (e.g. State of Punjab v. Principal Secretary to Governor, 2023). Output 3 dynamic points with clear short titles and rigorous legal analysis.
4. For Slide 5: Provide complete, polished academic sentences. NEVER use trailing ellipses (...) anywhere in your output.

Return STRICT JSON ONLY matching this exact structure:
{
  "slides": [
    {
      "slide_num": "1 / 5",
      "tier_badge": "JURISPRUDENTIAL ARCHITECTURE • GS-II",
      "headline": "ARTICLE NUMBER",
      "subheadline": "CORE DOCTRINAL CATCHPHRASE",
      "thesis": "Concise 30-word thesis capturing the core constitutional friction.",
      "chips": ["Cluster: ...", "Domain: ...", "Pillar: ..."]
    },
    {
      "slide_num": "2 / 5",
      "tier_badge": "CONSTITUENT ASSEMBLY CRUCIBLE",
      "headline": "Colonial Genesis vs. Framers' Vision",
      "colonial_title": "COLONIAL ROOTS (STATUTE ANCESTRY)",
      "colonial_context": "Statute ancestry from Government of India Act 1935...",
      "cad_speaker": "Speaker name (e.g. Dr. B.R. Ambedkar)",
      "cad_quote": "Substantive Constituent Assembly debate excerpt...",
      "analytical_insight": "The structural constitutional paradox..."
    },
    {
      "slide_num": "3 / 5",
      "tier_badge": "THE JURISPRUDENTIAL TURNING POINT",
      "headline": "Exact Landmark Case Name from database",
      "subheadline": "Analytical Breakdown",
      "points": [
        {"title": "1. Short Point Title", "desc": "Legal analysis..."},
        {"title": "2. Short Point Title", "desc": "Legal analysis..."},
        {"title": "3. Short Point Title", "desc": "Legal analysis..."}
      ]
    },
    {
      "slide_num": "4 / 5",
      "tier_badge": "PROCEDURAL MATRIX & EXAM TRAPS",
      "headline": "Constitutional Parameters & Traps",
      "rows": [
        {"param": "Parameter 1", "rule": "Exact rule", "trap": "Verified exam trap"},
        {"param": "Parameter 2", "rule": "Exact rule", "trap": "Verified exam trap"},
        {"param": "Parameter 3", "rule": "Exact rule", "trap": "Verified exam trap"},
        {"param": "Parameter 4", "rule": "Exact rule", "trap": "Verified exam trap"}
      ]
    },
    {
      "slide_num": "5 / 5",
      "tier_badge": "MAINS ANSWER-BUILDING BLUEPRINT",
      "headline": "GS-II Dialectical Framework",
      "dimensions": [
        ["1. Constitutional Anchor", "Complete sentence without ellipses..."],
        ["2. Jurisprudential Evolution", "Complete sentence without ellipses..."],
        ["3. Federal Friction Points", "Complete sentence without ellipses..."],
        ["4. Commission Recommendations", "Complete sentence without ellipses..."]
      ]
    }
  ]
}
"""

def synthesize_with_groq(article_record) -> dict:
    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_api_key:
        raise ValueError("GROQ_API_KEY not found in environment.")

    # Pass live DB fields including CAD quote explicitly
    evolution = article_record.evolution_trajectory or {}
    cad = evolution.get("cad_crucible", {})
    cad_quote = cad.get("pivotal_quote", "")

    db_payload = {
        "article_number": article_record.article_number,
        "title": article_record.title,
        "part_number": article_record.part_number,
        "doctrine_cluster_id": article_record.doctrine_cluster_id,
        "aspirant_summary": article_record.aspirant_summary,
        "evolution_trajectory": evolution,
        "stored_cad_quote": cad_quote
    }

    print("🤖 Calling Groq API (openai/gpt-oss-120b) with CAD enforcement...")
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {"role": "system", "content": GROQ_SYSTEM_PROMPT},
            {"role": "user", "content": f"Deconstruct and synthesize this constitutional article record:\n{json.dumps(db_payload)}"}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1
    }

    res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=body, timeout=40)
    res.raise_for_status()
    raw_content = res.json()["choices"][0]["message"]["content"]
    data = json.loads(raw_content)

    # Safety check: if Groq returned an empty CAD quote, restore it from DB
    if not data["slides"][1].get("cad_quote") and cad_quote:
        data["slides"][1]["cad_quote"] = cad_quote

    return data

# ---------------------------------------------------------------------------
# 4. RUNNER
# ---------------------------------------------------------------------------
def run_article_test(target_article: str = "200"):
    print("=" * 60)
    print(f"🚀 POLITY MENTOR: PROGRAMMATIC ASSET ENGINE (ARTICLE {target_article})")
    print("=" * 60)

    db = SessionLocal()
    try:
        article = db.query(ConstitutionalArticleModel).filter(
            or_(
                ConstitutionalArticleModel.article_number.ilike(f"%{target_article}%"),
                ConstitutionalArticleModel.article_slug.ilike(f"%{target_article}%")
            )
        ).first()

        if not article:
            print(f"❌ Article {target_article} not found in constitutional_articles table.")
            return

        print(f"✅ Extracted DB Record: {article.article_number} - {article.title}")

        payload = synthesize_with_groq(article)
        slides = payload.get("slides", [])

        out_dir = os.path.join("output_slides", f"article_{target_article}")
        os.makedirs(out_dir, exist_ok=True)
        print(f"\n🎨 Rendering 5 Visual Slides to `{out_dir}/`...")

        render_slide_1(slides[0], os.path.join(out_dir, "slide_1.png"))
        render_slide_2(slides[1], os.path.join(out_dir, "slide_2.png"))
        render_slide_3(slides[2], os.path.join(out_dir, "slide_3.png"))
        render_slide_4(slides[3], os.path.join(out_dir, "slide_4.png"))
        render_slide_5(slides[4], os.path.join(out_dir, "slide_5.png"))

        print("=" * 60)
        print(f"🎉 SUCCESS! All 5 visual slides rendered in `{out_dir}/`:")
        for i in range(1, 6):
            p = os.path.join(out_dir, f"slide_{i}.png")
            print(f"  • {p} ({os.path.getsize(p) // 1024} KB)")
        print("=" * 60)

    finally:
        db.close()

if __name__ == "__main__":
    # Test on Article 200, or change to any article number in your database (e.g., "356", "72", "324")
    run_article_test("72")