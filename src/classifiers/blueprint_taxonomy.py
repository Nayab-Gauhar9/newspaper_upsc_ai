"""
Taxonomy mapping official UPSC Prelims Polity syllabus lines
to Laxmikanth 8th Edition chapters, key constitutional articles, and micro-topics.
"""

PRELIMS_SYLLABUS_BLUEPRINT = [
    {
        "module_id": "MOD_01_CONSTITUTIONAL_FOUNDATIONS",
        "title": "Module 1: Constitutional Foundations & Philosophy",
        "official_line": "Constitution – Historical underpinnings, evolution, features, amendments, significant provisions and basic structure.",
        "chapter_range": [1, 2, 3, 4, 11],
        "key_articles": [368],
        "subtopics": [
            "Acts of 1773 to 1947 & Constituent Assembly",
            "Preamble: Keywords, Significance & Amendability",
            "Basic Structure Doctrine & Evolution",
        ],
    },
    {
        "module_id": "MOD_02_CITIZENSHIP_TERRITORY",
        "title": "Module 2: Territory, Citizenship & Federal Boundary",
        "official_line": "Political System – Union and its Territory, Admission & Reorganisation of States, Citizenship framework.",
        "chapter_range": [5, 6],
        "key_articles": [1, 2, 3, 4, 5, 9, 10, 11],
        "subtopics": [
            "Articles 1–4 Reorganisation Procedures",
            "Citizenship Criteria & Constitutional Provisions (Art 5–11)",
        ],
    },
    {
        "module_id": "MOD_03_RIGHTS_DUTIES_DPSP",
        "title": "Module 3: Rights, Directive Principles & Fundamental Duties",
        "official_line": "Rights Issues, Fundamental Rights, Directive Principles of State Policy, and Duties of Citizens.",
        "chapter_range": [7, 8, 9, 10],
        "key_articles": [12, 13, 14, 15, 19, 21, 32, 36, 44, 51],
        "subtopics": [
            "Fundamental Rights & Reasonable Restrictions (Art 12–35)",
            "Prerogative Writs & Remedies (Art 32 & 226)",
            "DPSPs Classification & Judicial Interplay (Art 36–51)",
            "Fundamental Duties (Art 51A)",
        ],
    },
    {
        "module_id": "MOD_04_UNION_EXECUTIVE",
        "title": "Module 4: Union & State Executive",
        "official_line": "Political System – Structure, organisation and functioning of the Executive, Ministries and Departments.",
        "chapter_range": [17, 18, 19, 20, 21, 30, 31, 32],
        "key_articles": [52, 61, 72, 74, 75, 76, 123, 153, 161, 163, 164, 213],
        "subtopics": [
            "President & Governor: Election, Impeachment & Powers",
            "Pardoning & Ordinance Making Comparison (Art 72/161 & 123/213)",
            "Council of Ministers, Prime Minister & Chief Minister",
        ],
    },
    {
        "module_id": "MOD_05_PARLIAMENT_LEGISLATURE",
        "title": "Module 5: Parliament & State Legislatures",
        "official_line": "Political System – Parliament and State Legislatures: Structure, functioning, conduct of business, powers & privileges.",
        "chapter_range": [22, 23, 24, 25, 33],
        "key_articles": [79, 80, 81, 102, 105, 107, 108, 109, 110, 112, 191],
        "subtopics": [
            "Legislative Procedure: Ordinary, Money (Art 110) & Financial Bills",
            "Parliamentary Motions, Resolutions & Privileges",
            "Parliamentary Committees (PAC, Estimates, CoPU)",
            "Anti-Defection Law (10th Schedule)",
        ],
    },
    {
        "module_id": "MOD_06_INTEGRATED_JUDICIARY",
        "title": "Module 6: Integrated Judicial System",
        "official_line": "Structure, organisation and functioning of the Judiciary – Supreme Court, High Courts, Subordinate Courts.",
        "chapter_range": [26, 27, 28, 29, 34, 35],
        "key_articles": [124, 129, 131, 136, 137, 141, 142, 143, 214, 226, 227],
        "subtopics": [
            "Supreme Court Jurisdictions (Original Art 131, Appellate, Advisory Art 143)",
            "Appointments & Collegium System",
            "High Courts & Writ Comparison",

            "Contempt of Court & Complete Justice (Art 142)",
        ],
    },
    {
        "module_id": "MOD_07_FEDERALISM_EMERGENCY",
        "title": "Module 7: Federal Dynamics & Emergency Provisions",
        "official_line": "Issues and challenges pertaining to federal structure, devolution of powers and emergency frameworks.",
        "chapter_range": [12, 13, 14, 15, 16],
        "key_articles": [245, 246, 248, 249, 250, 262, 263, 352, 356, 360],
        "subtopics": [
            "Centre-State Legislative, Administrative & Financial Relations",
            "7th Schedule Lists & Inter-State Council (Art 263)",
            "National, President's Rule & Financial Emergency (Art 352, 356, 360)",
        ],
    },
    {
        "module_id": "MOD_08_LOCAL_GOVERNANCE",
        "title": "Module 8: Local Self-Government (Panchayati Raj & Municipalities)",
        "official_line": "Panchayati Raj & Public Policy – Devolution of powers and finances up to local levels and challenges therein.",
        "chapter_range": [38, 39, 40],
        "key_articles": [243],
        "subtopics": [
            "73rd & 74th Constitutional Amendment Acts",
            "Compulsory vs Voluntary Provisions",
            "PESA Act 1996 & Gram Sabha Powers",
            "State Election Commission & State Finance Commission",
        ],
    },
    {
        "module_id": "MOD_09_CONSTITUTIONAL_BODIES",
        "title": "Module 9: Constitutional Bodies",
        "official_line": "Appointment to various Constitutional posts, powers, functions and responsibilities of various Constitutional Bodies.",
        "chapter_range": [43, 44, 45, 46, 47, 48, 49, 50, 51, 52],
        "key_articles": [76, 148, 149, 280, 315, 324, 338, 340],
        "subtopics": [
            "Election Commission of India (Art 324)",
            "Comptroller and Auditor General of India (Art 148–151)",
            "Finance Commission (Art 280)",
            "UPSC & SPSC (Art 315–323)",
            "Attorney General & Advocate General (Art 76/165)",
        ],
    },
    {
        "module_id": "MOD_10_STATUTORY_REGULATORY",
        "title": "Module 10: Non-Constitutional, Statutory & Regulatory Bodies",
        "official_line": "Statutory, regulatory and various quasi-judicial bodies, public policy frameworks and governance monitors.",
        "chapter_range": [53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64],
        "key_articles": [],
        "subtopics": [
            "NITI Aayog & Development Planning",
            "National & State Human Rights Commissions",
            "Central Information Commission (CIC) & CVC",
            "Lokpal and Lokayuktas",
        ],
    },
]
