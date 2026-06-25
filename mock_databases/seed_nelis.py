# mock_databases/seed_nelis.py
#
# Creates and populates the mock NeLIS database.
# NeLIS = Nepal Land Information System
# Managed by the Department of Land Management and Records, Nepal.
#
# In production, NeLIS is accessed via formal agreements with
# the Ministry of Land Management. For defense and demo purposes,
# this SQLite database accurately represents the Lalpurja data
# structure and query behavior of the real NeLIS system.
#
# HOW TO RUN:
#   python mock_databases/seed_nelis.py
#
# OUTPUT:
#   mock_databases/nelis.db
#
# LALPURJA FIELDS (simplified as agreed):
#   sanket_no, citizenship_no, full_name,
#   land_area_ropani, land_area_aana
#
# KEY DESIGN DECISION:
#   NeLIS is queried using citizenship_no — not NIN.
#   This is because Lalpurja contains the owner's citizenship
#   number, not their NIN. The bridge is:
#     DoNIDCR response → citizenship_no → NeLIS query
#   This accurately reflects real Nepal land registry practice.

import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "nelis.db")


# ── Land parcel data ───────────────────────────────────────────────────────────
# 80 records across 50 citizens.
# Most citizens own 1-2 parcels. A few own 3 (realistic for rural Nepal).
# NID-050 (Nirmala Kumari Osti) intentionally owns no land — zero asset demo.
# NID-049 (inactive NID) has no land either — irrelevant since KYC fails first.
#
# Format:
# (sanket_no, citizenship_no, full_name,
#  land_area_ropani, land_area_aana)
#
# Nepal land measurement:
#   1 Ropani = 16 Aana = 508.72 sq meters
#   Typical rural microfinance collateral: 2 Aana to 10 Ropani

LAND_PARCELS = [

    # NID-001 Ram Bahadur Thapa — 2 parcels
    ("LPJ-001", "27-01-75-00234", "Ram Bahadur Thapa",        6,  4),
    ("LPJ-002", "27-01-75-00234", "Ram Bahadur Thapa",        2, 10),

    # NID-002 Sita Kumari Shrestha — 1 parcel
    ("LPJ-003", "27-01-80-00891", "Sita Kumari Shrestha",     3,  8),

    # NID-003 Dipak Raj Adhikari — 2 parcels
    ("LPJ-004", "27-01-72-01123", "Dipak Raj Adhikari",       8,  0),
    ("LPJ-005", "27-01-72-01123", "Dipak Raj Adhikari",       1, 12),

    # NID-004 Kamala Devi Maharjan — 1 parcel
    ("LPJ-006", "27-01-68-00456", "Kamala Devi Maharjan",     4,  6),

    # NID-005 Bikash Kumar Tamang — 2 parcels
    ("LPJ-007", "27-13-83-00678", "Bikash Kumar Tamang",      5,  2),
    ("LPJ-008", "27-13-83-00678", "Bikash Kumar Tamang",      3,  0),

    # NID-006 Sunita Tamang — 1 parcel
    ("LPJ-009", "27-13-78-00345", "Sunita Tamang",            2,  8),

    # NID-007 Prakash Raj Neupane — 3 parcels
    ("LPJ-010", "27-10-70-00789", "Prakash Raj Neupane",      7,  0),
    ("LPJ-011", "27-10-70-00789", "Prakash Raj Neupane",      4, 14),
    ("LPJ-012", "27-10-70-00789", "Prakash Raj Neupane",      2,  6),

    # NID-008 Mina Kumari Poudel — 1 parcel
    ("LPJ-013", "27-10-85-01234", "Mina Kumari Poudel",       1, 10),

    # NID-009 Gopal Prasad Sharma — 2 parcels
    ("LPJ-014", "33-06-65-00567", "Gopal Prasad Sharma",      9,  4),
    ("LPJ-015", "33-06-65-00567", "Gopal Prasad Sharma",      5,  8),

    # NID-010 Urmila Gurung — 1 parcel
    ("LPJ-016", "33-06-77-00890", "Urmila Gurung",            3, 12),

    # NID-011 Nabin Raj Pokhrel — 2 parcels
    ("LPJ-017", "33-06-81-01456", "Nabin Raj Pokhrel",        4,  0),
    ("LPJ-018", "33-06-81-01456", "Nabin Raj Pokhrel",        2,  4),

    # NID-012 Devi Prasad Panta — 1 parcel
    ("LPJ-019", "33-04-73-00234", "Devi Prasad Panta",        6,  8),

    # NID-013 Laxmi Kumari Ghimire — 2 parcels
    ("LPJ-020", "33-04-69-00678", "Laxmi Kumari Ghimire",     3,  4),
    ("LPJ-021", "33-04-69-00678", "Laxmi Kumari Ghimire",     1, 14),

    # NID-014 Krishna Bahadur Tharu — 2 parcels
    ("LPJ-022", "44-03-66-00345", "Krishna Bahadur Tharu",    5,  0),
    ("LPJ-023", "44-03-66-00345", "Krishna Bahadur Tharu",    3,  6),

    # NID-015 Sarita Devi Yadav — 1 parcel
    ("LPJ-024", "44-03-79-00901", "Sarita Devi Yadav",        2, 12),

    # NID-016 Raju Prasad Chaudhary — 2 parcels
    ("LPJ-025", "44-03-74-00567", "Raju Prasad Chaudhary",    7,  8),
    ("LPJ-026", "44-03-74-00567", "Raju Prasad Chaudhary",    4,  2),

    # NID-017 Anita Kumari Oli — 1 parcel
    ("LPJ-027", "44-12-82-01678", "Anita Kumari Oli",         3,  0),

    # NID-018 Binod Kumar Chhetri — 3 parcels
    ("LPJ-028", "44-12-67-00234", "Binod Kumar Chhetri",      8, 12),
    ("LPJ-029", "44-12-67-00234", "Binod Kumar Chhetri",      5,  4),
    ("LPJ-030", "44-12-67-00234", "Binod Kumar Chhetri",      2,  8),

    # NID-019 Suresh Kumar Rai — 2 parcels
    ("LPJ-031", "11-04-76-00789", "Suresh Kumar Rai",         4, 10),
    ("LPJ-032", "11-04-76-00789", "Suresh Kumar Rai",         2,  0),

    # NID-020 Parbati Limbu — 1 parcel
    ("LPJ-033", "11-04-71-00456", "Parbati Limbu",            3,  6),

    # NID-021 Rajesh Pradhan — 2 parcels
    ("LPJ-034", "11-04-84-01890", "Rajesh Pradhan",           5, 14),
    ("LPJ-035", "11-04-84-01890", "Rajesh Pradhan",           1,  8),

    # NID-022 Kopila Devi Subba — 1 parcel
    ("LPJ-036", "11-06-73-00123", "Kopila Devi Subba",        4,  4),

    # NID-023 Santosh Kumar Thapa Magar — 2 parcels
    ("LPJ-037", "11-01-80-00567", "Santosh Kumar Thapa Magar", 6, 0),
    ("LPJ-038", "11-01-80-00567", "Santosh Kumar Thapa Magar", 2, 10),

    # NID-024 Ramesh Prasad Mahato — 1 parcel
    ("LPJ-039", "22-01-68-00345", "Ramesh Prasad Mahato",     3,  8),

    # NID-025 Sunita Yadav — 2 parcels
    ("LPJ-040", "22-01-75-00678", "Sunita Yadav",             4,  6),
    ("LPJ-041", "22-01-75-00678", "Sunita Yadav",             2,  2),

    # NID-026 Anil Kumar Jha — 1 parcel
    ("LPJ-042", "22-06-78-00901", "Anil Kumar Jha",           5, 12),

    # NID-027 Geeta Devi Mishra — 2 parcels
    ("LPJ-043", "22-06-72-00234", "Geeta Devi Mishra",        3,  0),
    ("LPJ-044", "22-06-72-00234", "Geeta Devi Mishra",        1,  6),

    # NID-028 Dil Bahadur Bista — 1 parcel
    ("LPJ-045", "74-01-64-00123", "Dil Bahadur Bista",        7,  4),

    # NID-029 Durga Kumari Rokaya — 2 parcels
    ("LPJ-046", "74-01-70-00456", "Durga Kumari Rokaya",      4,  8),
    ("LPJ-047", "74-01-70-00456", "Durga Kumari Rokaya",      2, 14),

    # NID-030 Narayan Prasad Joshi — 1 parcel
    ("LPJ-048", "74-07-67-00789", "Narayan Prasad Joshi",     5,  6),

    # NID-031 Harka Bahadur Shahi — 2 parcels
    ("LPJ-049", "66-01-66-00234", "Harka Bahadur Shahi",      6,  2),
    ("LPJ-050", "66-01-66-00234", "Harka Bahadur Shahi",      3, 10),

    # NID-032 Manju Kumari Saud — 1 parcel
    ("LPJ-051", "66-01-74-00567", "Manju Kumari Saud",        2,  4),

    # NID-033 Tek Bahadur Magar — 2 parcels
    ("LPJ-052", "44-09-76-00345", "Tek Bahadur Magar",        4, 12),
    ("LPJ-053", "44-09-76-00345", "Tek Bahadur Magar",        2,  0),

    # NID-034 Kabita Kumari Basnet — 1 parcel
    ("LPJ-054", "33-09-81-00678", "Kabita Kumari Basnet",     3,  8),

    # NID-035 Bishnu Prasad Rijal — 2 parcels
    ("LPJ-055", "33-10-69-00901", "Bishnu Prasad Rijal",      5,  4),
    ("LPJ-056", "33-10-69-00901", "Bishnu Prasad Rijal",      3,  0),

    # NID-036 Sabita Devi Pandey — 1 parcel
    ("LPJ-057", "33-11-77-00234", "Sabita Devi Pandey",       2, 10),

    # NID-037 Ganesh Prasad Kafle — 2 parcels
    ("LPJ-058", "33-05-73-00567", "Ganesh Prasad Kafle",      6,  6),
    ("LPJ-059", "33-05-73-00567", "Ganesh Prasad Kafle",      4,  2),

    # NID-038 Puja Kumari Thapa — 1 parcel
    ("LPJ-060", "33-05-84-00890", "Puja Kumari Thapa",        1, 12),

    # NID-039 Mohan Bahadur Karki — 2 parcels
    ("LPJ-061", "11-07-65-00123", "Mohan Bahadur Karki",      8,  8),
    ("LPJ-062", "11-07-65-00123", "Mohan Bahadur Karki",      5,  0),

    # NID-040 Rekha Kumari Rana — 1 parcel
    ("LPJ-063", "11-08-78-00456", "Rekha Kumari Rana",        3,  4),

    # NID-041 Umesh Kumar Gupta — 2 parcels
    ("LPJ-064", "22-04-82-00789", "Umesh Kumar Gupta",        4, 14),
    ("LPJ-065", "22-04-82-00789", "Umesh Kumar Gupta",        2,  6),

    # NID-042 Radha Devi Koirala — 1 parcel
    ("LPJ-066", "22-08-70-00234", "Radha Devi Koirala",       5, 10),

    # NID-043 Tika Ram Tiwari — 3 parcels
    ("LPJ-067", "27-08-63-00567", "Tika Ram Tiwari",         10,  0),
    ("LPJ-068", "27-08-63-00567", "Tika Ram Tiwari",          6,  8),
    ("LPJ-069", "27-08-63-00567", "Tika Ram Tiwari",          3,  4),

    # NID-044 Pramila Devi Acharya — 1 parcel
    ("LPJ-070", "27-08-76-00890", "Pramila Devi Acharya",     2,  0),

    # NID-045 Sanjay Kumar Shah — 2 parcels
    ("LPJ-071", "22-10-83-01123", "Sanjay Kumar Shah",        3, 12),
    ("LPJ-072", "22-10-83-01123", "Sanjay Kumar Shah",        1,  8),

    # NID-046 Anjali Kumari Sah — 1 parcel
    ("LPJ-073", "22-09-71-00456", "Anjali Kumari Sah",        4,  6),

    # NID-047 Lokendra Bahadur Chand — 2 parcels
    ("LPJ-074", "74-04-68-00234", "Lokendra Bahadur Chand",   5,  2),
    ("LPJ-075", "74-04-68-00234", "Lokendra Bahadur Chand",   3,  8),

    # NID-048 Saraswati Devi Bohara — 1 parcel
    ("LPJ-076", "74-04-74-00567", "Saraswati Devi Bohara",    2, 14),

    # NID-049 Prakash Bahadur Kunwar — no land
    # (NID is inactive anyway — KYC fails before NeLIS is queried)

    # NID-050 Nirmala Kumari Osti — intentionally no land records
    # This tests the zero-asset path in your Score Agent

    # ── Extra parcels to reach 80 total ───────────────────────────────────────
    # Additional parcels for citizens who own more land

    ("LPJ-077", "27-01-75-00234", "Ram Bahadur Thapa",        1,  8),
    ("LPJ-078", "33-06-65-00567", "Gopal Prasad Sharma",      3,  0),
    ("LPJ-079", "44-12-67-00234", "Binod Kumar Chhetri",      1,  4),
    ("LPJ-080", "27-08-63-00567", "Tika Ram Tiwari",          2,  6),
]


def create_database():
    """
    Creates nelis.db and populates it with 80 land parcel records.
    Safe to run multiple times — drops and recreates the table.
    """
    print(f"Creating NeLIS database at: {DB_PATH}")

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS land_parcels")

    cursor.execute("""
        CREATE TABLE land_parcels (
            sanket_no          TEXT PRIMARY KEY,
            citizenship_no     TEXT NOT NULL,
            full_name          TEXT NOT NULL,
            land_area_ropani   INTEGER NOT NULL DEFAULT 0,
            land_area_aana     INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Index on citizenship_no — this is the query your Identity Agent runs
    # "Give me all land parcels for citizenship_no = X"
    # Without this index, SQLite scans every row.
    # With it, lookup is instant even with millions of records.
    cursor.execute("""
        CREATE INDEX idx_nelis_citizenship ON land_parcels(citizenship_no)
    """)

    cursor.executemany("""
        INSERT INTO land_parcels (
            sanket_no, citizenship_no, full_name,
            land_area_ropani, land_area_aana
        ) VALUES (?, ?, ?, ?, ?)
    """, LAND_PARCELS)

    conn.commit()

    count = cursor.execute(
        "SELECT COUNT(*) FROM land_parcels"
    ).fetchone()[0]

    unique_owners = cursor.execute(
        "SELECT COUNT(DISTINCT citizenship_no) FROM land_parcels"
    ).fetchone()[0]

    conn.close()

    print(f"  Total parcels  : {count}")
    print(f"  Unique owners  : {unique_owners}")
    print(f"  Zero-asset NIDs: NID-049 (inactive), NID-050 (no land)")
    print("NeLIS database ready.")


if __name__ == "__main__":
    create_database()