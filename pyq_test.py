import pdfplumber
import re
import json

# Replace with the exact filename of your PDF
PDF_PATH = "upsc-prelims-indian-polity.pdf" 

def test_extract_first_few_questions(pdf_path, max_questions=4):
    extracted_questions = []
    
    with pdfplumber.open(pdf_path) as pdf:
        # Read only the first 2 pages for testing
        test_text = ""
        for i in range(min(2, len(pdf.pages))):
            page_text = pdf.pages[i].extract_text()
            if page_text:
                test_text += "\n" + page_text

    # Regex targeting: Q<num>. ... (a)... (b)... (c)... (d)... Answer: (x)
    pattern = re.compile(
        r"(?:UPSC\s+(?P<year>\d{4}))?"
        r"(?:\s+Indian Polity\s*>\s*(?P<subtopic>[^\n]+))?\n+"
        r"(?P<q_num>Q\d+)\.\s*(?P<q_text>[\s\S]+?)\n+"
        r"\(a\)\s*(?P<opt_a>[\s\S]+?)\n+"
        r"\(b\)\s*(?P<opt_b>[\s\S]+?)\n+"
        r"\(c\)\s*(?P<opt_c>[\s\S]+?)\n+"
        r"\(d\)\s*(?P<opt_d>[\s\S]+?)\n+"
        r"Answer:\s*\((?P<ans>[a-d])\)",
        re.IGNORECASE
    )

    matches = list(pattern.finditer(test_text))
    print(f"--- Matches detected: {len(matches)} ---")

    for match in matches[:max_questions]:
        data = match.groupdict()
        
        # Clean extracted text strings
        q_num = int(data["q_num"].replace("Q", "").strip())
        year = int(data["year"]) if data.get("year") else 2026
        subtopic = (data.get("subtopic") or "General Polity").strip()
        q_text = " ".join(data["q_text"].split())
        
        full_content = f"{q_text} {data['opt_a']} {data['opt_b']} {data['opt_c']} {data['opt_d']}"

        # Automatic Article tagging
        articles_found = re.findall(r"Article\s+(\d+[A-Z]?)", full_content, re.IGNORECASE)
        clean_articles = list({int(re.sub(r"\D", "", a)) for a in articles_found if re.sub(r"\D", "", a).isdigit() and int(re.sub(r"\D", "", a)) <= 395})

        # Automatic Chapter tagging based on subtopic keywords
        sub_lower = subtopic.lower()
        if "theory" in sub_lower or "concept" in sub_lower:
            chapter_slug = "political-theory-concepts"
        elif "fundamental right" in sub_lower:
            chapter_slug = "fundamental-rights"
        elif "judiciary" in sub_lower:
            chapter_slug = "judiciary"
        else:
            chapter_slug = "governance-administration"

        question_obj = {
            "year": year,
            "question_number": q_num,
            "chapter_slug": chapter_slug,
            "topic_name": subtopic,
            "mapped_articles": clean_articles,
            "question_text": q_text,
            "options": {
                "A": " ".join(data["opt_a"].split()),
                "B": " ".join(data["opt_b"].split()),
                "C": " ".join(data["opt_c"].split()),
                "D": " ".join(data["opt_d"].split()),
            },
            "correct_option": data["ans"].strip().upper(),
        }
        extracted_questions.append(question_obj)

    return extracted_questions

if __name__ == "__main__":
    results = test_extract_first_few_questions(PDF_PATH, max_questions=4)
    print(json.dumps(results, indent=2, ensure_ascii=False))
