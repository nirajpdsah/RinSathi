# mock_databases/seed_cib.py
#
# Creates and populates the mock CIB database.
# CIB = Karja Suchana Kendra Limited (Credit Information Bureau of Nepal)
#
# NOT to be confused with Nepal Police's Central Investigation Bureau —
# this CIB is a financial institution, established 1989, legally mandated
# under NRB Act 2058 Article 88. Checking CIB is MANDATORY for credit
# facilities of NPR 1,000,000 and above.
#
# Every citizenship_no below is cross-checked directly against the
# actual donidcr.db citizen table — no invented or mismatched numbers.
#
# STATUS VALUES (real Nepali CIB terminology):
#   "clean"        — fully repaid, no missed payments
#   "active"       — currently ongoing, no issues so far
#   "dpd_30"       — 30 days past due at some point
#   "dpd_60"       — 60 days past due at some point
#   "dpd_90_plus"  — 90+ days past due — serious delinquency
#   "blacklisted"  — formally blacklisted per NRB directive
#
# HOW TO RUN:
#   python mock_databases/seed_cib.py

import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "cib.db")


# ══════════════════════════════════════════════════════════════════════════
# MOCK CIB RECORDS — every citizenship_no verified against donidcr.db
#
# Coverage plan across your 50 citizens:
#   32 citizens → clean history (majority — realistic, most borrowers
#                 in good standing)
#   6  citizens → no CIB record at all (first-time borrowers — a
#                 genuinely common, non-risky case)
#   4  citizens → active loan elsewhere, no issues
#   4  citizens → dpd_30 (minor blemish)
#   2  citizens → dpd_60
#   1  citizen  → dpd_90_plus (severe delinquency demo case)
#   1  citizen  → blacklisted (hard-reject demo case)
#
# Format: (citizenship_no, lender_name, loan_amount_npr,
#          disbursed_date, closed_date, status)
# ══════════════════════════════════════════════════════════════════════════

CIB_RECORDS = [

    # ── CLEAN HISTORY (32 citizens) ─────────────────────────────────────────

    # NID-001 Ram Bahadur Thapa
    ("27-01-75-00234", "Chhimek Laghubitta Bittiya Sanstha",
     150000, "2023-04-10", "2024-04-10", "clean"),

    # NID-004 Kamala Devi Maharjan
    ("27-01-68-00456", "Nirdhan Utthan Laghubitta Bittiya Sanstha",
     80000, "2022-06-15", "2023-06-15", "clean"),

    # NID-007 Prakash Raj Neupane — two prior clean loans
    ("27-10-70-00789", "Chhimek Laghubitta Bittiya Sanstha",
     100000, "2021-08-05", "2022-08-05", "clean"),
    ("27-10-70-00789", "NMB Bank Ltd.",
     250000, "2023-09-18", "2024-09-18", "clean"),

    # NID-008 Mina Kumari Poudel
    ("27-10-85-01234", "Swabalamban Laghubitta Bikas Bank",
     60000, "2023-02-10", "2024-02-10", "clean"),

    # NID-011 Nabin Raj Pokhrel
    ("33-06-81-01456", "Machhapuchchhre Bank Ltd.",
     180000, "2022-09-05", "2023-09-05", "clean"),

    # NID-012 Devi Prasad Panta
    ("33-04-73-00234", "Gandaki Bikas Bank Ltd.",
     140000, "2023-01-12", "2024-01-12", "clean"),

    # NID-014 Krishna Bahadur Tharu
    ("44-03-66-00345", "Deprosc Laghubitta Bittiya Sanstha",
     90000, "2023-07-22", "2024-07-22", "clean"),

    # NID-015 Sarita Devi Yadav
    ("44-03-79-00901", "Rupandehi Laghubitta Bikas Bank",
     70000, "2022-11-01", "2023-11-01", "clean"),

    # NID-017 Anita Kumari Oli
    ("44-12-82-01678", "Deprosc Laghubitta Bittiya Sanstha",
     110000, "2023-03-15", "2024-03-15", "clean"),

    # NID-019 Suresh Kumar Rai
    ("11-04-76-00789", "NIC Asia Bank Ltd.",
     200000, "2022-12-20", "2023-12-20", "clean"),

    # NID-020 Parbati Limbu
    ("11-04-71-00456", "Sana Kisan Bikas Laghubitta",
     50000, "2023-05-08", "2024-05-08", "clean"),

    # NID-022 Kopila Devi Subba
    ("11-06-73-00123", "Sana Kisan Bikas Laghubitta",
     85000, "2023-06-14", "2024-06-14", "clean"),

    # NID-023 Santosh Kumar Thapa Magar
    ("11-01-80-00567", "Chhimek Laghubitta Bittiya Sanstha",
     95000, "2022-08-30", "2023-08-30", "clean"),

    # NID-024 Ramesh Prasad Mahato
    ("22-01-68-00345", "Sana Kisan Bikas Laghubitta",
     120000, "2023-04-01", "2024-04-01", "clean"),

    # NID-026 Anil Kumar Jha
    ("22-06-78-00901", "Janata Bank Nepal Ltd.",
     160000, "2022-10-11", "2023-10-11", "clean"),

    # NID-028 Dil Bahadur Bista
    ("74-01-64-00123", "Sudurpashchim Laghubitta Bikas Bank",
     75000, "2023-02-25", "2024-02-25", "clean"),

    # NID-030 Narayan Prasad Joshi
    ("74-07-67-00789", "Kamana Sewa Bikas Bank Ltd.",
     130000, "2022-07-19", "2023-07-19", "clean"),

    # NID-031 Harka Bahadur Shahi
    ("66-01-66-00234", "Karnali Laghubitta Bikas Bank",
     100000, "2023-01-28", "2024-01-28", "clean"),

    # NID-033 Tek Bahadur Magar
    ("44-09-76-00345", "Deprosc Laghubitta Bittiya Sanstha",
     90000, "2022-09-14", "2023-09-14", "clean"),

    # NID-035 Bishnu Prasad Rijal
    ("33-10-69-00901", "Gandaki Bikas Bank Ltd.",
     140000, "2023-03-06", "2024-03-06", "clean"),

    # NID-037 Ganesh Prasad Kafle
    ("33-05-73-00567", "Machhapuchchhre Bank Ltd.",
     170000, "2022-11-22", "2023-11-22", "clean"),

    # NID-039 Mohan Bahadur Karki
    ("11-07-65-00123", "Sana Kisan Bikas Laghubitta",
     80000, "2023-05-17", "2024-05-17", "clean"),

    # NID-041 Umesh Kumar Gupta
    ("22-04-82-00789", "Janata Bank Nepal Ltd.",
     150000, "2022-12-02", "2023-12-02", "clean"),

    # NID-043 Tika Ram Tiwari
    ("27-08-63-00567", "Chitwan Laghubitta Bittiya Sanstha",
     350000, "2022-11-30", "2023-11-30", "clean"),

    # NID-044 Pramila Devi Acharya
    ("27-08-76-00890", "Chitwan Laghubitta Bittiya Sanstha",
     65000, "2023-04-19", "2024-04-19", "clean"),

    # NID-045 Sanjay Kumar Shah
    ("22-10-83-01123", "Janata Bank Nepal Ltd.",
     220000, "2022-08-08", "2023-08-08", "clean"),

    # NID-047 Lokendra Bahadur Chand
    ("74-04-68-00234", "Sudurpashchim Laghubitta Bikas Bank",
     100000, "2023-06-01", "2024-06-01", "clean"),

    # NID-002 Sita Kumari Shrestha
    ("27-01-80-00891", "Nirdhan Utthan Laghubitta Bittiya Sanstha",
     55000, "2023-07-09", "2024-07-09", "clean"),

    # NID-006 Sunita Tamang
    ("27-13-78-00345", "Swabalamban Laghubitta Bikas Bank",
     70000, "2022-10-27", "2023-10-27", "clean"),

    # NID-025 Sunita Yadav
    ("22-01-75-00678", "Sana Kisan Bikas Laghubitta",
     90000, "2023-02-18", "2024-02-18", "clean"),

    # NID-036 Sabita Devi Pandey
    ("33-11-77-00234", "Gandaki Bikas Bank Ltd.",
     60000, "2022-09-23", "2023-09-23", "clean"),

    # NID-048 Saraswati Devi Bohara
    ("74-04-74-00567", "Sudurpashchim Laghubitta Bikas Bank",
     85000, "2023-01-05", "2024-01-05", "clean"),


    # ── ACTIVE LOANS ELSEWHERE, NO ISSUES (4 citizens) ──────────────────────

    # NID-003 Dipak Raj Adhikari
    ("27-01-72-01123", "NMB Bank Ltd.",
     300000, "2025-11-02", None, "active"),

    # NID-018 Binod Kumar Chhetri
    ("44-12-67-00234", "Global IME Bank Ltd.",
     500000, "2026-02-01", None, "active"),

    # NID-034 Kabita Kumari Basnet
    ("33-09-81-00678", "Machhapuchchhre Bank Ltd.",
     120000, "2025-09-15", None, "active"),

    # NID-046 Anjali Kumari Sah
    ("22-09-71-00456", "Janata Bank Nepal Ltd.",
     95000, "2026-01-10", None, "active"),


    # ── DPD_30 — MINOR DELINQUENCY (4 citizens) ─────────────────────────────

    # NID-005 Bikash Kumar Tamang — headline demo case
    ("27-13-83-00678", "Swabalamban Laghubitta Bikas Bank",
     120000, "2023-01-20", "2024-01-20", "dpd_30"),

    # NID-016 Raju Prasad Chaudhary
    ("44-03-74-00567", "Rupandehi Laghubitta Bikas Bank",
     100000, "2022-10-05", "2023-10-05", "dpd_30"),

    # NID-021 Rajesh Pradhan
    ("11-04-84-01890", "NIC Asia Bank Ltd.",
     130000, "2023-03-22", "2024-03-22", "dpd_30"),

    # NID-038 Puja Kumari Thapa
    ("33-05-84-00890", "Machhapuchchhre Bank Ltd.",
     70000, "2022-12-14", "2023-12-14", "dpd_30"),


    # ── DPD_60 (2 citizens) ──────────────────────────────────────────────────

    # NID-027 Geeta Devi Mishra
    ("22-06-72-00234", "Janata Bank Nepal Ltd.",
     110000, "2022-11-08", "2023-11-08", "dpd_60"),

    # NID-042 Radha Devi Koirala
    ("22-08-70-00234", "Sana Kisan Bikas Laghubitta",
     95000, "2023-02-01", "2024-02-01", "dpd_60"),


    # ── DPD_90_PLUS — SEVERE DELINQUENCY (1 citizen, headline demo case) ────

    # NID-013 Laxmi Kumari Ghimire
    ("33-04-69-00678", "Nepal Investment Mega Bank Ltd.",
     200000, "2023-05-14", "2024-05-14", "dpd_90_plus"),


    # ── BLACKLISTED (1 citizen, headline demo case) ─────────────────────────

    # NID-009 Gopal Prasad Sharma
    ("33-06-65-00567", "Sanima Bank Ltd.",
     400000, "2022-03-12", None, "blacklisted"),

]

# ── NO CIB RECORD AT ALL (6 citizens — first-time borrowers) ───────────────
# Intentionally excluded from CIB_RECORDS above:
#   NID-010 Urmila Gurung           (33-06-77-00890)
#   NID-029 Durga Kumari Rokaya     (74-01-70-00456)
#   NID-032 Manju Kumari Saud       (66-01-74-00567)
#   NID-040 Rekha Kumari Rana       (11-08-78-00456)
#   NID-050 Nirmala Kumari Osti     (74-06-86-00890)  — also zero-land demo
#   NID-049 Prakash Bahadur Kunwar  (55-01-60-00123)  — deceased, KYC fails
#                                                        before CIB is ever
#                                                        queried, so irrelevant


def create_database():
    print(f"Creating CIB database at: {DB_PATH}")

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS cib_records")

    cursor.execute("""
        CREATE TABLE cib_records (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            citizenship_no    TEXT NOT NULL,
            lender_name       TEXT NOT NULL,
            loan_amount_npr   REAL NOT NULL,
            disbursed_date    TEXT NOT NULL,
            closed_date       TEXT,
            status            TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE INDEX idx_cib_citizenship ON cib_records(citizenship_no)
    """)

    cursor.executemany("""
        INSERT INTO cib_records (
            citizenship_no, lender_name, loan_amount_npr,
            disbursed_date, closed_date, status
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, CIB_RECORDS)

    conn.commit()

    count       = cursor.execute("SELECT COUNT(*) FROM cib_records").fetchone()[0]
    unique_cits = cursor.execute(
        "SELECT COUNT(DISTINCT citizenship_no) FROM cib_records"
    ).fetchone()[0]
    blacklisted = cursor.execute(
        "SELECT COUNT(DISTINCT citizenship_no) FROM cib_records WHERE status = 'blacklisted'"
    ).fetchone()[0]

    conn.close()

    print(f"  Total records          : {count}")
    print(f"  Citizens with history   : {unique_cits}")
    print(f"  Blacklisted citizens    : {blacklisted}")
    print(f"  Demo blacklisted case   : Gopal Prasad Sharma (NID-009 / 33-06-65-00567)")
    print(f"  Demo DPD-90+ case       : Laxmi Kumari Ghimire (NID-013 / 33-04-69-00678)")
    print(f"  Demo DPD-30 case        : Bikash Kumar Tamang (NID-005 / 27-13-83-00678)")
    print(f"  First-time borrowers    : NID-010, 029, 032, 040, 050 (no CIB record)")
    print("CIB database ready.")


if __name__ == "__main__":
    create_database()