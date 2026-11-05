import os
import textwrap
from PIL import Image, ImageDraw, ImageFont

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
COLOR_CARD_TRANSLUCENT = (18, 26, 44, 255) # Translucent Slate Card
COLOR_TILE_BG = (14, 20, 34, 255)          # Questionnaire Option Tile

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
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    return ImageFont.load_default()

def clean_text(t: str) -> str:
    if not t:
        return ""
    replacements = {
        "₹": "Rs. ", "\u202f": " ", "\u00a0": " ", "\u2011": "-", "\u2012": "-",
        "\u2013": "-", "\u2014": " - ", "\u2018": "'", "\u2019": "'", "\u201c": '"',
        "\u201d": '"', "\u2026": "...", "\u200b": "", "\u200e": "", "\u2713": "",
        "\u2714": "", "\u26a0": "", "\u2794": "->", "\u2192": "->"
    }
    for k, v in replacements.items():
        t = t.replace(k, v)
    return t.strip()

def get_logo_image(size: int = 44):
    for p in ["static/logo.png", "public/logo.png", "logo.png", "static/logo.png.png"]:
        if os.path.exists(p):
            try:
                logo = Image.open(p).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
                mask = Image.new("L", (size, size), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
                output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                output.paste(logo, (0, 0), mask=mask)
                return output
            except Exception:
                pass
    return None

def create_trap_canvas(
    slide_num: str, 
    tier_badge: str, 
    format_badge: str = "STATEMENT-I & II CAUSALITY",
    footer_action: str = "Swipe for trap analysis"
):
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

    logo = get_logo_image(size=44)
    text_x = 96
    if logo:
        img.paste(logo, (96, 84), logo)
        draw.ellipse([94, 82, 142, 130], outline=COLOR_GOLD, width=1)
        text_x = 152
    else:
        draw.ellipse([96, 84, 138, 126], fill=(28, 38, 64), outline=COLOR_GOLD, width=2)
        text_x = 152

    draw.text((text_x, 92), "POLITY MENTOR", font=resolve_font("black", 25), fill=COLOR_GOLD)
    draw.text((W - 96 - 130, 96), f"SLIDE {slide_num}", font=resolve_font("bold", 20), fill=COLOR_ROSE)
    draw.line([(96, 140), (W - 96, 140)], fill=COLOR_CARD_BORDER, width=2)

    clean_badge = clean_text(tier_badge).upper()
    if len(clean_badge) > 28:
        clean_badge = clean_badge[:26].strip() + "..."
    
    font_badge = resolve_font("bold", 15)
    badge_width = int(draw.textlength(clean_badge, font=font_badge)) + 28
    draw.rounded_rectangle([96, 178, 96 + badge_width, 224], radius=12, fill=(28, 38, 64), outline=COLOR_GOLD, width=2)
    draw.text((110, 193), clean_badge, font=font_badge, fill=COLOR_GOLD)

    fmt_label = f"● {clean_text(format_badge).upper()}"
    fmt_width = int(draw.textlength(fmt_label, font=font_badge)) + 24
    start_x = 96 + badge_width + 14
    draw.rounded_rectangle([start_x, 178, start_x + fmt_width, 224], radius=12, fill=(20, 26, 44), outline=COLOR_AMBER, width=1)
    draw.text((start_x + 12, 193), fmt_label, font=font_badge, fill=COLOR_AMBER)

    draw.line([(96, H - 120), (W - 96, H - 120)], fill=COLOR_CARD_BORDER, width=2)
    draw.text((96, H - 88), "politymentor.com", font=resolve_font("medium", 21), fill=COLOR_TEXT_MUTED)
    
    font_action = resolve_font("bold", 21)
    action_w = int(draw.textlength(footer_action, font=font_action))
    draw.text((W - 96 - action_w, H - 88), footer_action, font=font_action, fill=COLOR_GOLD)

    return img, draw, W, H

def render_trap_slide_1(data: dict, output_path: str):
    img, draw, W, H = create_trap_canvas(
        "1 / 4", 
        "UPSC PRELIMS DRILL", 
        data.get("question_format", "STATEMENT-I & II"),
        footer_action="Swipe for trap analysis"
    )

    y_pos = 246
    draw.text((96, y_pos), "UPSC PRELIMS DRILL", font=resolve_font("black", 32), fill=COLOR_GOLD)
    draw.text((96, y_pos + 44), "QUESTION 01 • SINGLE CORRECT • INDIAN POLITY GS-II", font=resolve_font("bold", 15), fill=COLOR_ROSE)
    
    # FOOLPROOF STEM TEXT WRAPPING (prevents right-edge overflow on long pyq/dossier stems)
    stem_text = clean_text(data.get("question_stem", "Consider the following statements:"))
    stem_lines = textwrap.wrap(stem_text, width=65)
    stem_y = y_pos + 74
    font_stem = resolve_font("bold", 21)
    for s_line in stem_lines:
        draw.text((96, stem_y), s_line, font=font_stem, fill=COLOR_TEXT_WHITE)
        stem_y += 28
    y_pos = stem_y + 12

    stmts = data.get("statements_payload", {})
    font_lbl = resolve_font("black", 14)
    font_body = resolve_font("regular", 20)
    line_h = 28

    if stmts.get("format") == "STATEMENT_I_II":
        s1 = clean_text(stmts.get("statement_1", ""))
        lines_1 = textwrap.wrap(s1, width=70)
        h1 = 44 + (len(lines_1) * line_h) + 12
        draw.rounded_rectangle([96, y_pos, W - 96, y_pos + h1], radius=14, fill=COLOR_CARD_TRANSLUCENT, outline=COLOR_CYAN, width=2)
        draw.rounded_rectangle([116, y_pos + 12, 236, y_pos + 38], radius=6, fill=(18, 38, 64))
        draw.text((126, y_pos + 14), "STATEMENT I", font=font_lbl, fill=COLOR_CYAN)
        cur_y = y_pos + 46
        for l in lines_1:
            draw.text((118, cur_y), l, font=font_body, fill=COLOR_TEXT_WHITE)
            cur_y += line_h

        y_pos += h1 + 16

        s2 = clean_text(stmts.get("statement_2", ""))
        lines_2 = textwrap.wrap(s2, width=70)
        h2 = 44 + (len(lines_2) * line_h) + 12
        draw.rounded_rectangle([96, y_pos, W - 96, y_pos + h2], radius=14, fill=COLOR_CARD_TRANSLUCENT, outline=COLOR_AMBER, width=2)
        draw.rounded_rectangle([116, y_pos + 12, 242, y_pos + 38], radius=6, fill=(42, 32, 20))
        draw.text((126, y_pos + 14), "STATEMENT II", font=font_lbl, fill=COLOR_AMBER)
        cur_y = y_pos + 46
        for l in lines_2:
            draw.text((118, cur_y), l, font=font_body, fill=COLOR_TEXT_WHITE)
            cur_y += line_h

        y_pos += h2 + 20
    else:
        # UNIVERSAL EXTRACTOR: handles items list, statements list, or statement_1/2/3 keys robustly
        items_list = []
        for key in ['items', 'statements', 'list']:
            if key in stmts and isinstance(stmts[key], list):
                items_list = [item.get('text', item) if isinstance(item, dict) else str(item) for item in stmts[key]]
                break
                
        if not items_list:
            sorted_keys = sorted([k for k in stmts.keys() if 'statement' in k.lower() or k.isdigit() or k in ['1', '2', '3', '4']])
            for k in sorted_keys:
                val = stmts[k]
                if isinstance(val, str):
                    items_list.append(val)
                elif isinstance(val, dict) and 'text' in val:
                    items_list.append(val['text'])
                    
        if not items_list:
            items_list = [v for k, v in stmts.items() if k != 'format' and isinstance(v, str)]

        for idx, s_text in enumerate(items_list, start=1):
            cleaned_s = clean_text(s_text)
            lines = textwrap.wrap(cleaned_s, width=70)
            h = 40 + (len(lines) * line_h) + 12
            
            if y_pos + h + 20 > H - 320:
                break
                
            draw.rounded_rectangle([96, y_pos, W - 96, y_pos + h], radius=14, fill=COLOR_CARD_TRANSLUCENT, outline=COLOR_CARD_BORDER, width=2)
            draw.text((118, y_pos + 12), f"STATEMENT {idx}", font=font_lbl, fill=COLOR_GOLD)
            cur_y = y_pos + 42
            for l in lines:
                draw.text((118, cur_y), l, font=font_body, fill=COLOR_TEXT_BODY)
                cur_y += line_h
            y_pos += h + 14

    draw.text((96, y_pos), "SELECT THE CORRECT CODE:", font=resolve_font("bold", 16), fill=COLOR_GOLD)
    y_pos += 26

    # Options Grid: Clean 2x2 side-by-side layout
    opts = data.get("options", {})
    if opts:
        font_opt_code = resolve_font("black", 16)
        font_opt_txt = resolve_font("medium", 17)
        
        col_width = (W - 192 - 20) // 2
        start_y = y_pos
        row_heights = [0, 0]
        
        for idx, code in enumerate(["A", "B", "C", "D"]):
            txt = clean_text(opts.get(code, ""))
            wrapped_lines = textwrap.wrap(txt, width=38)
            tile_h = 16 + (len(wrapped_lines) * 24) + 10
            row_idx = idx // 2
            if tile_h > row_heights[row_idx]:
                row_heights[row_idx] = tile_h

        cur_y = start_y
        for idx, code in enumerate(["A", "B", "C", "D"]):
            row_idx = idx // 2
            col_idx = idx % 2
            
            if col_idx == 0 and row_idx > 0:
                cur_y += row_heights[row_idx - 1] + 16
                
            cur_x = 96 if col_idx == 0 else 96 + col_width + 20
            txt = clean_text(opts.get(code, ""))
            wrapped_lines = textwrap.wrap(txt, width=38)
            
            draw.rounded_rectangle([cur_x, cur_y, cur_x + col_width, cur_y + row_heights[row_idx]], radius=10, fill=COLOR_TILE_BG, outline=COLOR_CARD_BORDER, width=1)
            
            badge_color = COLOR_CYAN if code in ["A", "C"] else COLOR_AMBER
            draw.rounded_rectangle([cur_x + 18, cur_y + 10, cur_x + 50, cur_y + 38], radius=6, fill=(20, 28, 46))
            draw.text((cur_x + 24, cur_y + 13), code.lower(), font=font_opt_code, fill=badge_color)
            
            for l_idx, l in enumerate(wrapped_lines):
                draw.text((cur_x + 64, cur_y + 12 + (l_idx * 24)), l, font=font_opt_txt, fill=COLOR_TEXT_BODY)

    y_call = H - 192
    draw.rounded_rectangle([96, y_call, W - 96, y_call + 52], radius=12, fill=(18, 30, 52), outline=COLOR_CYAN, width=1)
    draw.text((120, y_call + 16), "Pause & Solve • Test your grasp of constitutional mechanics", font=resolve_font("bold", 18), fill=COLOR_CYAN)

    img.save(output_path, "PNG")

def render_trap_slide_2(data: dict, output_path: str):
    img, draw, W, H = create_trap_canvas(
        "2 / 4", 
        "VERDICT & EXAM-HALL TRAP", 
        data.get("trap_archetype", "TRAP ANALYSIS"),
        footer_action="Swipe for legal ratio"
    )

    corr = data.get("correct_option", "B")
    opts = data.get("options", {})
    ans_text = clean_text(opts.get(corr, f"Option {corr}"))

    draw.text((96, 250), f"CORRECT ANSWER: OPTION ({corr})", font=resolve_font("black", 32), fill=COLOR_CYAN)
    
    lines_ans = textwrap.wrap(ans_text, width=66)
    h_ans = 36 + (len(lines_ans) * 30) + 14
    draw.rounded_rectangle([96, 306, W - 96, 306 + h_ans], radius=14, fill=(20, 36, 56), outline=COLOR_CYAN, width=2)
    cur_y = 320
    for l in lines_ans:
        draw.text((120, cur_y), l, font=resolve_font("bold", 21), fill=COLOR_TEXT_WHITE)
        cur_y += 30

    y_pos = 306 + h_ans + 24
    c_analysis = data.get("conceptual_analysis", {})

    why_fail = clean_text(c_analysis.get("why_candidates_falter", ""))
    lines_fail = textwrap.wrap(why_fail, width=68)
    h_fail = 54 + (len(lines_fail) * 30) + 18
    draw.rounded_rectangle([96, y_pos, W - 96, y_pos + h_fail], radius=16, fill=(40, 24, 28), outline=COLOR_AMBER, width=2)
    draw.text((120, y_pos + 18), "THE COGNITIVE BLINDSPOT (WHY ASPIRANTS FALTER)", font=resolve_font("bold", 18), fill=COLOR_AMBER)
    cur_y = y_pos + 52
    for l in lines_fail:
        draw.text((120, cur_y), l, font=resolve_font("regular", 21), fill=COLOR_TEXT_BODY)
        cur_y += 30

    y_pos += h_fail + 24

    dissect = clean_text(c_analysis.get("distractor_dissection", ""))
    lines_dis = textwrap.wrap(dissect, width=68)
    h_dis = 54 + (len(lines_dis) * 30) + 18
    draw.rounded_rectangle([96, y_pos, W - 96, y_pos + h_dis], radius=16, fill=COLOR_CARD_TRANSLUCENT, outline=COLOR_CARD_BORDER, width=2)
    draw.text((120, y_pos + 18), "THE FORENSIC DECONSTRUCTION", font=resolve_font("bold", 18), fill=COLOR_GOLD)
    cur_y = y_pos + 52
    for l in lines_dis:
        draw.text((120, cur_y), l, font=resolve_font("regular", 21), fill=COLOR_TEXT_BODY)
        cur_y += 30

    img.save(output_path, "PNG")

def render_trap_slide_3(data: dict, output_path: str):
    img, draw, W, H = create_trap_canvas(
        "3 / 4", 
        "CONSTITUTIONAL JURISPRUDENCE", 
        "SUBSTANTIVE LAW",
        footer_action="Swipe for exam heuristic"
    )

    c_analysis = data.get("conceptual_analysis", {})
    raw_doctrine = clean_text(c_analysis.get("core_constitutional_doctrine", "Constitutional Doctrine"))
    
    doc_lines = textwrap.wrap(raw_doctrine, width=54)
    font_doc = resolve_font("black", 26 if len(doc_lines) > 1 else 29)
    
    y_h = 248
    for d_l in doc_lines[:2]:
        draw.text((96, y_h), d_l, font=font_doc, fill=COLOR_GOLD)
        y_h += 34

    draw.text((96, y_h + 4), "Authentic Ratio Decidendi & Threshold Bounds", font=resolve_font("bold", 21), fill=COLOR_ROSE)
    y_pos = y_h + 44

    holding = clean_text(c_analysis.get("substantive_legal_holding", ""))
    lines_h = textwrap.wrap(holding, width=68)
    box_h = 52 + (len(lines_h) * 28) + 16
    draw.rounded_rectangle([96, y_pos, W - 96, y_pos + box_h], radius=16, fill=(24, 38, 64), outline=COLOR_CYAN, width=2)
    draw.text((120, y_pos + 16), "AUTHENTIC LEGAL MECHANISM", font=resolve_font("bold", 17), fill=COLOR_CYAN)
    cur_y = y_pos + 46
    for l in lines_h:
        draw.text((120, cur_y), l, font=resolve_font("regular", 20), fill=COLOR_TEXT_WHITE)
        cur_y += 28

    y_pos += box_h + 20

    cite = clean_text(data.get("source_citation", "Constitution of India"))
    lines_c = textwrap.wrap(cite, width=68)
    c_h = 44 + (len(lines_c) * 26) + 12
    draw.rounded_rectangle([96, y_pos, W - 96, y_pos + c_h], radius=14, fill=COLOR_CARD_TRANSLUCENT, outline=COLOR_GOLD, width=1)
    draw.text((120, y_pos + 14), "PRIMARY LEGAL CITATION", font=resolve_font("bold", 17), fill=COLOR_GOLD)
    cur_y = y_pos + 42
    for l in lines_c:
        draw.text((120, cur_y), l, font=resolve_font("medium", 18), fill=COLOR_TEXT_BODY)
        cur_y += 26

    y_pos += c_h + 20

    max_box_bottom = H - 150
    if max_box_bottom > y_pos + 80:
        draw.rounded_rectangle([96, y_pos, W - 96, max_box_bottom], radius=14, fill=(18, 24, 40), outline=COLOR_CARD_BORDER, width=1)
        draw.text((120, y_pos + 18), "PRELIMS BOUNDARY CONDITIONS (MEMORISE FOR EXAM)", font=resolve_font("bold", 16), fill=COLOR_ROSE)
        
        raw_traps = data.get("db_prelims_traps", [])
        if not raw_traps:
            raw_traps = [
                "Always isolate the legal source: Constitution, Statute, or Executive Rule.",
                "Verify the competent authority (e.g., President vs. Governor).",
                "Do not assume implied doctrines exist without Supreme Court precedent."
            ]
        
        tips = [t if t.startswith("•") else f"• {t}" for t in raw_traps][:3]
        
        cur_tip_y = y_pos + 52
        for tip in tips:
            wrapped_tip = textwrap.wrap(tip, width=68)
            for t_line in wrapped_tip:
                if cur_tip_y + 26 < max_box_bottom:
                    draw.text((120, cur_tip_y), t_line, font=resolve_font("regular", 17), fill=COLOR_TEXT_BODY)
                    cur_tip_y += 26
            cur_tip_y += 6

    img.save(output_path, "PNG")

def render_trap_slide_4(data: dict, output_path: str):
    img, draw, W, H = create_trap_canvas(
        "4 / 4", 
        "EXAM HALL TECHNIQUE", 
        "COGNITIVE HEURISTIC",
        footer_action="Tap Link in Bio →"
    )

    draw.text((96, 250), "Exam Hall Cognitive Heuristic", font=resolve_font("black", 30), fill=COLOR_GOLD)
    draw.text((96, 296), "Systematic Elimination Technique for UPSC Prelims", font=resolve_font("bold", 21), fill=COLOR_ROSE)

    y_pos = 346
    heur = clean_text(data.get("elimination_heuristic", ""))
    lines_heur = textwrap.wrap(heur, width=68)
    box_h = 54 + (len(lines_heur) * 28) + 16
    draw.rounded_rectangle([96, y_pos, W - 96, y_pos + box_h], radius=16, fill=(35, 26, 44), outline=COLOR_AMBER, width=2)
    draw.text((120, y_pos + 18), "HOW TO SOLVE IN UNDER 60 SECONDS", font=resolve_font("bold", 18), fill=COLOR_AMBER)
    cur_y = y_pos + 50
    for l in lines_heur:
        draw.text((120, cur_y), l, font=resolve_font("regular", 20), fill=COLOR_TEXT_WHITE)
        cur_y += 28

    y_pos += box_h + 20

    pitfall_h = 166
    draw.rounded_rectangle([96, y_pos, W - 96, y_pos + pitfall_h], radius=14, fill=(18, 26, 42), outline=COLOR_CARD_BORDER, width=1)
    draw.text((120, y_pos + 18), "THE 3-STEP EXAM HALL VERIFICATION PROTOCOL", font=resolve_font("bold", 16), fill=COLOR_CYAN)
    
    protocols = [
        "1. Isolate the Legal Source: Is it Constitution, Statute, or Executive Rule?",
        "2. Check Competent Authority: Who has the final signature / order?",
        "3. Verify Causality: Does Stmt-II actually trigger Stmt-I, or is it an independent fact?"
    ]
    cur_p_y = y_pos + 50
    for p in protocols:
        draw.text((120, cur_p_y), p, font=resolve_font("medium", 16), fill=COLOR_TEXT_BODY)
        cur_p_y += 32

    y_eco = H - 310
    draw.rounded_rectangle([96, y_eco, W - 96, y_eco + 170], radius=16, fill=COLOR_CARD_TRANSLUCENT, outline=COLOR_CARD_BORDER, width=2)
    draw.text((120, y_eco + 22), "MASTER UPSC POLITY WITH GROUNDED AI PRECISION", font=resolve_font("black", 21), fill=COLOR_GOLD)
    draw.text((120, y_eco + 64), "Interactive Bare Act & 30-Year Traps at politymentor.com", font=resolve_font("medium", 20), fill=COLOR_CYAN)
    draw.text((120, y_eco + 104), "Daily MCQs & Editorials at t.me/polity_mentor_ai", font=resolve_font("regular", 19), fill=COLOR_TEXT_BODY)

    img.save(output_path, "PNG")

def render_trap_campaign_slides(campaign_id: int, payload: dict) -> list[str]:
    import tempfile
    from src.storage.minio_client import NewspaperStorage

    scratch_dir = os.path.join(tempfile.gettempdir(), f"trap_camp_{campaign_id}")
    os.makedirs(scratch_dir, exist_ok=True)

    storage = NewspaperStorage(force_r2=True)
    urls = []
    renderers = [
        render_trap_slide_1,
        render_trap_slide_2,
        render_trap_slide_3,
        render_trap_slide_4
    ]

    cdn_base = os.getenv("R2_PUBLIC_DOMAIN", "https://media.politymentor.com").rstrip("/")

    for idx, render_fn in enumerate(renderers, start=1):
        filename = f"slide_{idx}.png"
        local_png_path = os.path.join(scratch_dir, filename)

        render_fn(payload, local_png_path)

        object_key = f"campaigns/traps/camp_{campaign_id}/{filename}"
        if hasattr(storage, "upload_file"):
            storage.upload_file(local_file_path=local_png_path, object_name=object_key)
        else:
            storage.upload_and_get_presigned_url(local_file_path=local_png_path, object_name=object_key)

        urls.append(f"{cdn_base}/{object_key}")

    return urls

import json
from pathlib import Path
def export_trap_campaign_locally(campaign_id: int, payload: dict, local_export_dir: str):
    """
    Non-disruptive local exporter for YouTube Shorts automation.
    Saves the rendered slides and payload metadata locally without affecting R2/DB pipelines.
    """
    out_dir = Path(local_export_dir) / f"trap_camp_{campaign_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Render identical PNGs locally
    render_trap_slide_1(payload, str(out_dir / "slide_1.png"))
    render_trap_slide_2(payload, str(out_dir / "slide_2.png"))
    render_trap_slide_3(payload, str(out_dir / "slide_3.png"))
    render_trap_slide_4(payload, str(out_dir / "slide_4.png"))

    # 2. Dump the raw engine payload as meta.json
    with open(out_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return out_dir