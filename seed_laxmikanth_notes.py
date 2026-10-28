# -*- coding: utf-8 -*-
import os
import sys
import json
import time
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

try:
    from src.storage.minio_client import MinIOStorage
except ImportError:
    from src.storage.minio_client_new import MinIOStorage

CHAPTER_92_PAYLOAD = {
    "chapter_id": 92,
    "chapter_title": "World Constitutions",
    "headline": "Comparative Constitutional Systems: UK Westminster, US Presidentialism, French Diarchy, German Basic Law & Direct Democracy",
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "markdown": """# Chapter 92: World Constitutions
**Comparative Constitutional Systems & Global Governance Masterclass Dossier** | *Canonical Static Syllabus*

---

## 1. Foundational Architecture & Comparative Matrix

### In Layman's Terms: The Global Laboratory of Democratic Governance
When the framers of the Indian Constitution assembled in 1946, they did not draft a constitutional system in a vacuum. Instead, as Dr. B.R. Ambedkar noted in the Constituent Assembly, they *"ransacked the constitutions of the world"* to identify mechanisms that could balance executive stability with parliamentary accountability, individual liberty with affirmative state action, and federal integrity with national unity.

Comparative constitutionalism analyzes how distinct societies structure state authority, resolve Centre-State friction, enforce civil rights, and design executive leadership.

Evaluating the constitutional models of the **United Kingdom, United States, France, Germany, Japan, and Switzerland** provides the contextual foundation for understanding India's unique syncretic design.

---

### Typological Spectrum of Constitutional Systems

[GLOBAL CONSTITUTIONAL ARCHETYPES]

BY CODIFICATION:
├── Written / Codified   -> India, USA, France, Germany, Japan.
└── Unwritten / Uncodified -> United Kingdom, New Zealand, Israel.

BY EXECUTIVE STRUCTURE:
├── Parliamentary System   -> India, United Kingdom, Japan, Germany.
├── Presidential System    -> United States of America.
├── Semi-Presidential      -> France (Dual Executive / Executive Diarchy).
└── Collegial / Plural     -> Switzerland (7-member Federal Council).

BY TERRITORIAL DISTRIBUTION:
├── Federal Structure      -> USA, India (Quasi-Federal), Germany, Switzerland.
└── Unitary Structure      -> United Kingdom, France, Japan.

BY AMENDING RIGIDITY:
├── Rigid (Special Majorities) -> USA, India (partially), Australia.
└── Flexible (Simple Majority) -> United Kingdom, New Zealand.


---

## 2. The United Kingdom: The Westminster Mother of Parliaments

[THE BRITISH CONSTITUTIONAL SPECTRUM]

Unwritten & Evolutionary : Built on statutes (Magna Carta 1215, Bill of Rights 1689),
common law judicial precedents, and unwritten CONVENTIONS.

Parliamentary Sovereignty: Parliament can enact, alter, or repeal ANY law whatsoever.
Courts CANNOT declare primary Acts of Parliament ultra vires.

Constitutional Monarchy  : The King reigns but does NOT rule ("Crown in Parliament").

Unitary Decentralization : Devolution to Scotland, Wales, and Northern Ireland
without creating a formal federal framework.


---

### Comparative Analysis: United Kingdom vs. India

| Institutional Feature | United Kingdom (Westminster) | Republic of India |
|---|---|---|
| **Constitutional Form** | Unwritten, uncodified, evolutionary, flexible. | Written, codified, comprehensive, rigid-flexible blend. |
| **Sovereignty Source** | **Parliamentary Sovereignty:** Parliament is legally omnipotent; no judicial review of primary Acts. | **Constitutional Supremacy:** Parliament is created by and bounded by the written Constitution. |
| **Head of State** | Hereditary Monarch (Constitutional Monarchy). | Elected President (Republic). |
| **Judicial Power** | Cannot invalidate primary Acts of Parliament on constitutional grounds. | Extensive Judicial Review; can invalidate laws violating Part III or Basic Structure. |
| **Federal Design** | Unitary state with statutory legislative devolution. | Union of States with constitutional division of powers (Quasi-federal). |
| **Shadow Cabinet** | Formal institution run by Her Majesty's Opposition. | No formal institutionalization of a Shadow Cabinet. |

---

## 3. The United States of America: Classical Presidentialism & Strict Separation

Formulated at the Philadelphia Convention of 1787, the US Constitution represents the archetype of a rigid, written presidential federalism:

[THE AMERICAN CONSTITUTIONAL ARCHITECTURE]

STRICT SEPARATION OF POWERS (Montesquieu):
├── Legislative : CONGRESS (House of Representatives + Senate).
├── Executive   : PRESIDENT (Elected independently via Electoral College; 4-yr term).
└── Judicial    : SUPREME COURT (Independent review via Article III).

INSTITUTIONAL CHECKS AND BALANCES:
├── President can VETO congressional bills (Congress can override by 2/3rd vote).
├── Senate confirms presidential nominations (Cabinet, Judges) & treaties (2/3rd vote).
└── Supreme Court can strike down laws/orders (Judicial Review - Marbury v. Madison).

DUAL FEDERALISM (Indestructible Union of Indestructible States):
├── Equal representation of all states in Senate (2 Senators per State).
├── Dual Citizenship (Citizen of USA + Citizen of individual State).
└── Residual Powers vested strictly in the STATES (10th Amendment).


---

### Comparative Analysis: United States vs. India

| Dimension | United States of America | Republic of India |
|---|---|---|
| **Executive Form** | Presidential: Chief executive is independent of the legislature; fixed 4-year tenure. | Parliamentary: Executive drawn from and collectively responsible to the Lower House. |
| **Judicial Structure** | Dual Judiciary: Federal courts enforce federal laws; State courts enforce state laws. | Integrated Single Judiciary: Unified hierarchy enforcing both central and state laws. |
| **Citizenship** | Dual Citizenship: US citizenship and State citizenship coexist. | Single National Citizenship across the entire Union. |
| **Residual Powers** | Vested exclusively in the **States** (Tenth Amendment). | Vested exclusively in the **Union Parliament** (Article 248 / Entry 97). |
| **Territorial Integrity**| Indestructible States: Congress cannot alter state boundaries without state consent. | Destructible States: Parliament can redraw state maps unilaterally (Article 3). |
| **Due Process** | Substantive and Procedural "Due Process of Law" explicitly written (5th/14th Amendments). | "Procedure Established by Law" (Art 21), read with substantive fairness (*Maneka Gandhi*). |

---

## 4. France: The Fifth Republic Semi-Presidential Model (1958)

Architected by General Charles de Gaulle, the French Fifth Republic established a hybrid **Semi-Presidential System (Executive Diarchy)**:

[THE FRENCH DUAL EXECUTIVE ARCHITECTURE]

PRESIDENT OF THE REPUBLIC (Elected Directly by the People for a 5-Year Term)
├── Commander-in-Chief of Armed Forces; conducts foreign and defense policy.
├── Appoints the Prime Minister; can dissolve the National Assembly.
└── Emergency powers under Article 16 without prior parliamentary counter-signature.
│
▼ Cooperates / Clashes with
PRIME MINISTER & GOVERNMENT (Appointed by President; must command Assembly confidence)
├── Directs the domestic administration and executes domestic statutes.
└── Accountable to the NATIONAL ASSEMBLY (Can be ousted via a vote of censure).


- **The Phenomenon of Cohabitation:** Occurs when the President belongs to one political party, while the majority in the National Assembly belongs to an opposing party. The President is forced to appoint an opposition leader as Prime Minister, dividing executive authority between foreign affairs (President) and domestic governance (Prime Minister).
- **The Constitutional Council (*Conseil Constitutionnel*):** Features an *a priori* (preventive) model of judicial review. The Council reviews the constitutionality of organic laws and treaties **before they are promulgated**, rather than waiting for an ordinary citizen to bring a post-enactment lawsuit.

---

## 5. Germany: The Basic Law (*Grundgesetz*) of 1949

Crafted after World War II, the German Basic Law was engineered to reconcile parliamentary democracy with safeguards against totalitarian capture:

[GERMAN DEMOCRATIC SAFEGUARDS]

CONSTRUCTIVE VOTE OF NO-CONFIDENCE (Article 67):
└── The Bundestag (Lower House) can remove the Federal Chancellor ONLY by
simultaneously ELECTING A SUCCESSOR with an absolute majority of members.
└── Prevents destabilizing the government without an agreed-upon alternative.

THE ETERNITY CLAUSE (Ewigkeitsklausel - Article 79(3)):
└── Prohibits any constitutional amendment that abolishes:
├── The federal division of the Republic;
├── The basic principles of human dignity (Article 1); or
└── The democratic, social, and constitutional state order.
└── Served as direct comparative inspiration for India's BASIC STRUCTURE DOCTRINE.

DEFENSIVE DEMOCRACY (Streitbare Demokratie):
└── The Federal Constitutional Court can ban political parties that seek to
undermine or abolish the free democratic basic order.


---

## 6. Japan: The 1947 Pacifist Post-War Constitution

Drafted during the Allied occupation, the 1947 Constitution of Japan established a stable parliamentary democracy with a unique constitutional commitment:

[JAPANESE CONSTITUTIONAL MATRIX]

The Emperor          : Stripped of divine status; defined purely as "the symbol
of the State and of the unity of the People."

The National Diet    : Designated as the "highest organ of state power" and the
sole law-making organ of the State.

Cabinet Government   : Prime Minister designated by Diet resolution; collective
responsibility to the House of Representatives.


- **The Renunciation of War (Article 9):**
  > *"Aspiring sincerely to an international peace based on justice and order, the Japanese people forever renounce war as a sovereign right of the nation and the threat or use of force as means of settling international disputes."*
- Prohibits the maintenance of land, sea, and air forces, or other war potential (reconciled in modern statecraft through the strictly defensive **Japan Self-Defense Forces (JSDF)**).

---

## 7. Switzerland: Plural Executive & Direct Democracy

The Swiss Confederation features unique institutional devices:

[SWISS DIRECT DEMOCRACY & PLURAL EXECUTIVE]

THE PLURAL / COLLEGIAL EXECUTIVE (Federal Council):
├── Composed of SEVEN EQUAL MEMBERS elected by the Federal Assembly.
├── No single President: The "President of the Confederation" rotates annually
among the seven members and acts strictly as primus inter pares for ceremonial duties.
└── Enforces collegiate consensus across linguistic (German, French, Italian) divides.

INSTRUMENTS OF DIRECT DEMOCRACY:
├── Mandatory Referendum : Constitutional amendments MUST be approved by a majority
of the people AND a majority of the Cantons (States).
├── Optional Referendum  : 50,000 citizens can demand a nationwide popular vote
on any federal statute passed by the Federal Assembly.
└── Popular Initiative   : 100,000 voters can propose a direct constitutional amendment.

"""
}

def main():
    storage = MinIOStorage()
    object_key = "static/laxmikanth/chapter_92.json"

    print("Writing clean ASCII-safe Chapter 92 (World Constitutions) to MinIO...")
    json_bytes = json.dumps(CHAPTER_92_PAYLOAD, ensure_ascii=True, indent=2).encode("utf-8")
    clean_dict = json.loads(json_bytes.decode("utf-8"))

    try:
        storage.upload_json(object_key, clean_dict)
        print(f"SUCCESS: Written cleanly to {storage.bucket}/{object_key}")
    except Exception as e:
        print(f"Error during ingestion: {e}")

if __name__ == "__main__":
    main()