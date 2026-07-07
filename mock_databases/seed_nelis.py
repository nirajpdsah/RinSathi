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
# LALPURJA FIELDS (expanded to include valuation):
#   sanket_no, citizenship_no, full_name,
#   land_area_ropani, land_area_aana,
#   district, land_type, estimated_value_npr
#
# KEY DESIGN DECISION — QUERY BRIDGE:
#   NeLIS is queried using citizenship_no — not NIN.
#   This is because Lalpurja contains the owner's citizenship
#   number, not their NIN. The bridge is:
#     DoNIDCR response → citizenship_no → NeLIS query
#   This accurately reflects real Nepal land registry practice.
#
# KEY DESIGN DECISION — VALUATION:
#   Land area alone (e.g. "5 Ropani") is not asset value. Two parcels
#   of identical size can differ enormously in worth depending on
#   district and land type. This mirrors how NRB and licensed valuers
#   maintain per-district rate guides for loan collateral assessment.
#   We approximate that here with a simplified rate table.

import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "nelis.db")


# ══════════════════════════════════════════════════════════════════════════
# RAW LAND PARCEL DATA
# 80 records across 50 citizens. Most own 1-2 parcels, a few own 3.
# NID-050 intentionally owns no land — zero asset demo.
# NID-049 (deceased) has no land — irrelevant since KYC fails first anyway.
#
# Format: (sanket_no, citizenship_no, full_name, land_area_ropani, land_area_aana)
# Nepal land measurement: 1 Ropani = 16 Aana = 508.72 sq meters
# ══════════════════════════════════════════════════════════════════════════

LAND_PARCELS = [
    ("LPJ-001", "27-01-75-00234", "Ram Bahadur Thapa",        6,  4),
    ("LPJ-002", "27-01-75-00234", "Ram Bahadur Thapa",        2, 10),
    ("LPJ-003", "27-01-80-00891", "Sita Kumari Shrestha",     3,  8),
    ("LPJ-004", "27-01-72-01123", "Dipak Raj Adhikari",       8,  0),
    ("LPJ-005", "27-01-72-01123", "Dipak Raj Adhikari",       1, 12),
    ("LPJ-006", "27-01-68-00456", "Kamala Devi Maharjan",     4,  6),
    ("LPJ-007", "27-13-83-00678", "Bikash Kumar Tamang",      5,  2),
    ("LPJ-008", "27-13-83-00678", "Bikash Kumar Tamang",      3,  0),
    ("LPJ-009", "27-13-78-00345", "Sunita Tamang",            2,  8),
    ("LPJ-010", "27-10-70-00789", "Prakash Raj Neupane",      7,  0),
    ("LPJ-011", "27-10-70-00789", "Prakash Raj Neupane",      4, 14),
    ("LPJ-012", "27-10-70-00789", "Prakash Raj Neupane",      2,  6),
    ("LPJ-013", "27-10-85-01234", "Mina Kumari Poudel",       1, 10),
    ("LPJ-014", "33-06-65-00567", "Gopal Prasad Sharma",      9,  4),
    ("LPJ-015", "33-06-65-00567", "Gopal Prasad Sharma",      5,  8),
    ("LPJ-016", "33-06-77-00890", "Urmila Gurung",            3, 12),
    ("LPJ-017", "33-06-81-01456", "Nabin Raj Pokhrel",        4,  0),
    ("LPJ-018", "33-06-81-01456", "Nabin Raj Pokhrel",        2,  4),
    ("LPJ-019", "33-04-73-00234", "Devi Prasad Panta",        6,  8),
    ("LPJ-020", "33-04-69-00678", "Laxmi Kumari Ghimire",     3,  4),
    ("LPJ-021", "33-04-69-00678", "Laxmi Kumari Ghimire",     1, 14),
    ("LPJ-022", "44-03-66-00345", "Krishna Bahadur Tharu",    5,  0),
    ("LPJ-023", "44-03-66-00345", "Krishna Bahadur Tharu",    3,  6),
    ("LPJ-024", "44-03-79-00901", "Sarita Devi Yadav",        2, 12),
    ("LPJ-025", "44-03-74-00567", "Raju Prasad Chaudhary",    7,  8),
    ("LPJ-026", "44-03-74-00567", "Raju Prasad Chaudhary",    4,  2),
    ("LPJ-027", "44-12-82-01678", "Anita Kumari Oli",         3,  0),
    ("LPJ-028", "44-12-67-00234", "Binod Kumar Chhetri",      8, 12),
    ("LPJ-029", "44-12-67-00234", "Binod Kumar Chhetri",      5,  4),
    ("LPJ-030", "44-12-67-00234", "Binod Kumar Chhetri",      2,  8),
    ("LPJ-031", "11-04-76-00789", "Suresh Kumar Rai",         4, 10),
    ("LPJ-032", "11-04-76-00789", "Suresh Kumar Rai",         2,  0),
    ("LPJ-033", "11-04-71-00456", "Parbati Limbu",            3,  6),
    ("LPJ-034", "11-04-84-01890", "Rajesh Pradhan",           5, 14),
    ("LPJ-035", "11-04-84-01890", "Rajesh Pradhan",           1,  8),
    ("LPJ-036", "11-06-73-00123", "Kopila Devi Subba",        4,  4),
    ("LPJ-037", "11-01-80-00567", "Santosh Kumar Thapa Magar", 6, 0),
    ("LPJ-038", "11-01-80-00567", "Santosh Kumar Thapa Magar", 2, 10),
    ("LPJ-039", "22-01-68-00345", "Ramesh Prasad Mahato",     3,  8),
    ("LPJ-040", "22-01-75-00678", "Sunita Yadav",             4,  6),
    ("LPJ-041", "22-01-75-00678", "Sunita Yadav",             2,  2),
    ("LPJ-042", "22-06-78-00901", "Anil Kumar Jha",           5, 12),
    ("LPJ-043", "22-06-72-00234", "Geeta Devi Mishra",        3,  0),
    ("LPJ-044", "22-06-72-00234", "Geeta Devi Mishra",        1,  6),
    ("LPJ-045", "74-01-64-00123", "Dil Bahadur Bista",        7,  4),
    ("LPJ-046", "74-01-70-00456", "Durga Kumari Rokaya",      4,  8),
    ("LPJ-047", "74-01-70-00456", "Durga Kumari Rokaya",      2, 14),
    ("LPJ-048", "74-07-67-00789", "Narayan Prasad Joshi",     5,  6),
    ("LPJ-049", "66-01-66-00234", "Harka Bahadur Shahi",      6,  2),
    ("LPJ-050", "66-01-66-00234", "Harka Bahadur Shahi",      3, 10),
    ("LPJ-051", "66-01-74-00567", "Manju Kumari Saud",        2,  4),
    ("LPJ-052", "44-09-76-00345", "Tek Bahadur Magar",        4, 12),
    ("LPJ-053", "44-09-76-00345", "Tek Bahadur Magar",        2,  0),
    ("LPJ-054", "33-09-81-00678", "Kabita Kumari Basnet",     3,  8),
    ("LPJ-055", "33-10-69-00901", "Bishnu Prasad Rijal",      5,  4),
    ("LPJ-056", "33-10-69-00901", "Bishnu Prasad Rijal",      3,  0),
    ("LPJ-057", "33-11-77-00234", "Sabita Devi Pandey",       2, 10),
    ("LPJ-058", "33-05-73-00567", "Ganesh Prasad Kafle",      6,  6),
    ("LPJ-059", "33-05-73-00567", "Ganesh Prasad Kafle",      4,  2),
    ("LPJ-060", "33-05-84-00890", "Puja Kumari Thapa",        1, 12),
    ("LPJ-061", "11-07-65-00123", "Mohan Bahadur Karki",      8,  8),
    ("LPJ-062", "11-07-65-00123", "Mohan Bahadur Karki",      5,  0),
    ("LPJ-063", "11-08-78-00456", "Rekha Kumari Rana",        3,  4),
    ("LPJ-064", "22-04-82-00789", "Umesh Kumar Gupta",        4, 14),
    ("LPJ-065", "22-04-82-00789", "Umesh Kumar Gupta",        2,  6),
    ("LPJ-066", "22-08-70-00234", "Radha Devi Koirala",       5, 10),
    ("LPJ-067", "27-08-63-00567", "Tika Ram Tiwari",         10,  0),
    ("LPJ-068", "27-08-63-00567", "Tika Ram Tiwari",          6,  8),
    ("LPJ-069", "27-08-63-00567", "Tika Ram Tiwari",          3,  4),
    ("LPJ-070", "27-08-76-00890", "Pramila Devi Acharya",     2,  0),
    ("LPJ-071", "22-10-83-01123", "Sanjay Kumar Shah",        3, 12),
    ("LPJ-072", "22-10-83-01123", "Sanjay Kumar Shah",        1,  8),
    ("LPJ-073", "22-09-71-00456", "Anjali Kumari Sah",        4,  6),
    ("LPJ-074", "74-04-68-00234", "Lokendra Bahadur Chand",   5,  2),
    ("LPJ-075", "74-04-68-00234", "Lokendra Bahadur Chand",   3,  8),
    ("LPJ-076", "74-04-74-00567", "Saraswati Devi Bohara",    2, 14),
    # NID-049 (deceased) and NID-050 (zero-asset demo) intentionally have no parcels
    ("LPJ-077", "27-01-75-00234", "Ram Bahadur Thapa",        1,  8),
    ("LPJ-078", "33-06-65-00567", "Gopal Prasad Sharma",      3,  0),
    ("LPJ-079", "44-12-67-00234", "Binod Kumar Chhetri",      1,  4),
    ("LPJ-080", "27-08-63-00567", "Tika Ram Tiwari",          2,  6),
]


# ══════════════════════════════════════════════════════════════════════════
# VALUATION REFERENCE DATA
# ══════════════════════════════════════════════════════════════════════════

# Approximate NPR value per Ropani, by district.
# Mirrors how NRB and banks maintain internal land valuation guides for
# collateral assessment. Real rates vary parcel-by-parcel based on exact
# location and road access — this is a defensible simplified baseline.
DISTRICT_RATE_PER_ROPANI = {
    "Kathmandu":     8_500_000,
    "Lalitpur":      7_800_000,
    "Kaski":         4_200_000,
    "Rupandehi":     2_600_000,
    "Morang":        2_100_000,
    "Chitwan":       2_400_000,
    "Makwanpur":     1_800_000,
    "Gorkha":          900_000,
    "Sindhupalchok":   650_000,
    "Dhankuta":        700_000,
    "Dang":            950_000,
    "Saptari":         800_000,
    "Dhanusha":        850_000,
    "Bajhang":         280_000,
    "Surkhet":         750_000,
    "Kailali":         900_000,
    "DEFAULT":         500_000,   # fallback for any district not listed
}

# Land type multiplier relative to the district's base rate
LAND_TYPE_MULTIPLIER = {
    "residential":  1.3,
    "commercial":   1.8,
    "agricultural": 0.6,
}

# Which district each citizen's land sits in.
# In a real system this comes directly from the Lalpurja record itself —
# here we derive it from the matching DoNIDCR citizen record, since our
# mock data was written by hand across two separate files.
CITIZEN_DISTRICT = {
    "27-01-75-00234": "Kathmandu",
    "27-01-80-00891": "Kathmandu",
    "27-01-72-01123": "Kathmandu",
    "27-01-68-00456": "Lalitpur",
    "27-13-83-00678": "Sindhupalchok",
    "27-13-78-00345": "Sindhupalchok",
    "27-10-70-00789": "Makwanpur",
    "27-10-85-01234": "Makwanpur",
    "33-06-65-00567": "Kaski",
    "33-06-77-00890": "Kaski",
    "33-06-81-01456": "Kaski",
    "33-04-73-00234": "Gorkha",
    "33-04-69-00678": "Gorkha",
    "44-03-66-00345": "Rupandehi",
    "44-03-79-00901": "Rupandehi",
    "44-03-74-00567": "Rupandehi",
    "44-12-82-01678": "Dang",
    "44-12-67-00234": "Dang",
    "11-04-76-00789": "Morang",
    "11-04-71-00456": "Morang",
    "11-04-84-01890": "Morang",
    "11-06-73-00123": "Dhankuta",
    "11-01-80-00567": "Dhankuta",
    "22-01-68-00345": "Saptari",
    "22-01-75-00678": "Saptari",
    "22-06-78-00901": "Dhanusha",
    "22-06-72-00234": "Dhanusha",
    "74-01-64-00123": "Bajhang",
    "74-01-70-00456": "Bajhang",
    "74-07-67-00789": "Kailali",
    "66-01-66-00234": "Surkhet",
    "66-01-74-00567": "Surkhet",
    "44-09-76-00345": "Dang",
    "33-09-81-00678": "Kaski",
    "33-10-69-00901": "Kaski",
    "33-11-77-00234": "Kaski",
    "33-05-73-00567": "Gorkha",
    "33-05-84-00890": "Gorkha",
    "11-07-65-00123": "Dhankuta",
    "11-08-78-00456": "Morang",
    "22-04-82-00789": "Saptari",
    "22-08-70-00234": "Dhanusha",
    "27-08-63-00567": "Chitwan",
    "27-08-76-00890": "Chitwan",
    "22-10-83-01123": "Dhanusha",
    "22-09-71-00456": "Saptari",
    "74-04-68-00234": "Bajhang",
    "74-04-74-00567": "Bajhang",
}

# Districts where land near the citizen is plausibly residential rather
# than purely agricultural — used to give a realistic land type mix.
URBAN_DISTRICTS = {"Kathmandu", "Lalitpur", "Kaski"}


def infer_land_type(district: str, parcel_index: int) -> str:
    """
    Assigns a realistic land type per parcel.
    Urban districts get a mix of residential and agricultural;
    rural districts are predominantly agricultural — matching
    real land use patterns across Nepal.
    """
    if district in URBAN_DISTRICTS and parcel_index % 3 == 0:
        return "residential"
    return "agricultural"


def calculate_parcel_value(district: str, land_type: str, total_ropani: float) -> int:
    """
    Estimates a parcel's market value in NPR.

    value = area (in Ropani) × district base rate × land type multiplier

    This mirrors how a bank's internal valuation team produces a rough
    collateral estimate before a licensed valuer confirms the final figure.
    """
    base_rate  = DISTRICT_RATE_PER_ROPANI.get(district, DISTRICT_RATE_PER_ROPANI["DEFAULT"])
    multiplier = LAND_TYPE_MULTIPLIER.get(land_type, 1.0)
    return round(total_ropani * base_rate * multiplier)


def create_database():
    """
    Creates nelis.db and populates it with 80 land parcel records,
    each carrying a calculated market value based on district and land type.

    Safe to run multiple times — drops and recreates the table each time.
    """
    print(f"Creating NeLIS database at: {DB_PATH}")

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS land_parcels")

    cursor.execute("""
        CREATE TABLE land_parcels (
            sanket_no           TEXT PRIMARY KEY,
            citizenship_no      TEXT NOT NULL,
            full_name           TEXT NOT NULL,
            land_area_ropani    INTEGER NOT NULL DEFAULT 0,
            land_area_aana      INTEGER NOT NULL DEFAULT 0,
            district            TEXT NOT NULL DEFAULT 'Unknown',
            land_type           TEXT NOT NULL DEFAULT 'agricultural',
            estimated_value_npr INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Index on citizenship_no — this is the query your Identity Agent runs:
    # "Give me all land parcels for citizenship_no = X"
    cursor.execute("""
        CREATE INDEX idx_nelis_citizenship ON land_parcels(citizenship_no)
    """)

    # ── Enrich each raw parcel with district, land type, and value ───────────
    enriched_parcels = []
    for idx, (sanket_no, citizenship_no, full_name, ropani, aana) in enumerate(LAND_PARCELS):
        district  = CITIZEN_DISTRICT.get(citizenship_no, "DEFAULT")
        land_type = infer_land_type(district, idx)

        # 16 Aana = 1 Ropani, so we express the full area as a single
        # decimal Ropani figure before valuing it — otherwise we'd
        # silently ignore the Aana portion of every parcel's value.
        total_ropani_equivalent = ropani + (aana / 16)
        value = calculate_parcel_value(district, land_type, total_ropani_equivalent)

        enriched_parcels.append((
            sanket_no, citizenship_no, full_name,
            ropani, aana, district, land_type, value
        ))

    cursor.executemany("""
        INSERT INTO land_parcels (
            sanket_no, citizenship_no, full_name,
            land_area_ropani, land_area_aana,
            district, land_type, estimated_value_npr
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, enriched_parcels)

    conn.commit()

    count = cursor.execute("SELECT COUNT(*) FROM land_parcels").fetchone()[0]
    unique_owners = cursor.execute(
        "SELECT COUNT(DISTINCT citizenship_no) FROM land_parcels"
    ).fetchone()[0]
    total_value = cursor.execute(
        "SELECT SUM(estimated_value_npr) FROM land_parcels"
    ).fetchone()[0]
    sample = cursor.execute(
        "SELECT sanket_no, district, land_type, land_area_ropani, "
        "land_area_aana, estimated_value_npr FROM land_parcels LIMIT 3"
    ).fetchall()

    conn.close()

    print(f"  Total parcels       : {count}")
    print(f"  Unique owners       : {unique_owners}")
    print(f"  Combined asset value: NPR {total_value:,}")
    print(f"  Sample parcels:")
    for row in sample:
        print(f"    {row[0]} — {row[1]}, {row[2]}, "
              f"{row[3]} Ropani {row[4]} Aana → NPR {row[5]:,}")
    print("NeLIS database ready.")


if __name__ == "__main__":
    create_database()