# mock_databases/seed_donidcr.py
#
# Creates and populates the mock DoNIDCR database.
# DoNIDCR = Department of National ID and Civil Registration, Nepal
#
# This SQLite database represents the government's National ID system.
# In production, this would be accessed via NRB-mediated API agreements.
# For defense and demo purposes, this accurately represents the data
# structure and query behavior of the real DoNIDCR system.
#
# HOW TO RUN:
#   python mock_databases/seed_donidcr.py
#
# OUTPUT:
#   mock_databases/donidcr.db
#
# NID CARD FIELDS (exactly what appears on a real Nepal NID card):
#   NIN, Full Name, Date of Issue, Nationality,
#   Date of Birth, Sex, Permanent Address,
#   Citizenship Type, Citizenship Number

import sqlite3
import os

# ── Path setup ────────────────────────────────────────────────────────────────
# Resolve path relative to this file so the script works from any directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "donidcr.db")


# ── Synthetic citizen data ─────────────────────────────────────────────────────
# 50 records representing realistic Nepali loan applicants.
# All names, districts, and citizenship numbers follow real Nepal formats.
# Citizenship number format: DD-CC-YY-NNNNN
#   DD = district code, CC = sub-district, YY = year, NNNNN = sequence
#
# SPECIAL RECORDS (for demo scenarios):
#   NID-049 → is_active = False  (expired/revoked NID — tests rejection)
#   NID-050 → owns no land       (tests zero-asset scenario)

CITIZENS = [
    # (nin, full_name, date_of_issue, nationality, date_of_birth,
    #  sex, permanent_address, citizenship_type, citizenship_no, is_active)

    ("NID-001", "Ram Bahadur Thapa",
     "2078-05-14", "Nepali", "1985-03-15",
     "Male", "Tokha-7, Kathmandu",
     "By Descent", "27-01-75-00234", True),

    ("NID-002", "Sita Kumari Shrestha",
     "2077-09-22", "Nepali", "1990-07-22",
     "Female", "Jorpati-3, Kathmandu",
     "By Descent", "27-01-80-00891", True),

    ("NID-003", "Dipak Raj Adhikari",
     "2076-03-08", "Nepali", "1982-11-08",
     "Male", "Kirtipur-5, Kathmandu",
     "By Descent", "27-01-72-01123", True),

    ("NID-004", "Kamala Devi Maharjan",
     "2075-11-30", "Nepali", "1978-05-30",
     "Female", "Mangal Bazar-10, Lalitpur",
     "By Descent", "27-01-68-00456", True),

    ("NID-005", "Bikash Kumar Tamang",
     "2079-02-14", "Nepali", "1993-02-14",
     "Male", "Chautara-4, Sindhupalchok",
     "By Descent", "27-13-83-00678", True),

    ("NID-006", "Sunita Tamang",
     "2077-06-03", "Nepali", "1988-09-03",
     "Female", "Balefi-2, Sindhupalchok",
     "By Descent", "27-13-78-00345", True),

    ("NID-007", "Prakash Raj Neupane",
     "2076-09-19", "Nepali", "1980-12-19",
     "Male", "Hetauda-8, Makwanpur",
     "By Descent", "27-10-70-00789", True),

    ("NID-008", "Mina Kumari Poudel",
     "2079-10-11", "Nepali", "1995-06-11",
     "Female", "Manahari-1, Makwanpur",
     "By Descent", "27-10-85-01234", True),

    ("NID-009", "Gopal Prasad Sharma",
     "2075-08-25", "Nepali", "1975-04-25",
     "Male", "Lakeside-16, Kaski",
     "By Descent", "33-06-65-00567", True),

    ("NID-010", "Urmila Gurung",
     "2077-12-17", "Nepali", "1987-08-17",
     "Female", "Lwang Ghalel-3, Kaski",
     "By Descent", "33-06-77-00890", True),

    ("NID-011", "Nabin Raj Pokhrel",
     "2078-05-29", "Nepali", "1991-01-29",
     "Male", "Dhampus-5, Kaski",
     "By Descent", "33-06-81-01456", True),

    ("NID-012", "Devi Prasad Panta",
     "2076-07-06", "Nepali", "1983-10-06",
     "Male", "Prithvi Chowk-2, Gorkha",
     "By Descent", "33-04-73-00234", True),

    ("NID-013", "Laxmi Kumari Ghimire",
     "2075-07-21", "Nepali", "1979-03-21",
     "Female", "Khahare-6, Gorkha",
     "By Descent", "33-04-69-00678", True),

    ("NID-014", "Krishna Bahadur Tharu",
     "2075-04-14", "Nepali", "1976-07-14",
     "Male", "Traffic Chowk-11, Rupandehi",
     "By Descent", "44-03-66-00345", True),

    ("NID-015", "Sarita Devi Yadav",
     "2078-08-02", "Nepali", "1989-11-02",
     "Female", "Manigram-4, Rupandehi",
     "By Descent", "44-03-79-00901", True),

    ("NID-016", "Raju Prasad Chaudhary",
     "2076-09-18", "Nepali", "1984-05-18",
     "Male", "Devdaha-7, Rupandehi",
     "By Descent", "44-03-74-00567", True),

    ("NID-017", "Anita Kumari Oli",
     "2079-01-27", "Nepali", "1992-09-27",
     "Female", "Naya Bazar-9, Dang",
     "By Descent", "44-12-82-01678", True),

    ("NID-018", "Binod Kumar Chhetri",
     "2075-06-08", "Nepali", "1977-02-08",
     "Male", "Shantinagar-3, Dang",
     "By Descent", "44-12-67-00234", True),

    ("NID-019", "Suresh Kumar Rai",
     "2077-08-09", "Nepali", "1986-04-09",
     "Male", "Rangeli Road-5, Morang",
     "By Descent", "11-04-76-00789", True),

    ("NID-020", "Parbati Limbu",
     "2076-04-23", "Nepali", "1981-12-23",
     "Female", "Letang-2, Morang",
     "By Descent", "11-04-71-00456", True),

    ("NID-021", "Rajesh Pradhan",
     "2079-10-16", "Nepali", "1994-06-16",
     "Male", "Pathari Bazar-8, Morang",
     "By Descent", "11-04-84-01890", True),

    ("NID-022", "Kopila Devi Subba",
     "2076-06-31", "Nepali", "1983-08-31",
     "Female", "Hile Bazar-4, Dhankuta",
     "By Descent", "11-06-73-00123", True),

    ("NID-023", "Santosh Kumar Thapa Magar",
     "2078-07-07", "Nepali", "1990-03-07",
     "Male", "Taplejung Bazar-1, Taplejung",
     "By Descent", "11-01-80-00567", True),

    ("NID-024", "Ramesh Prasad Mahato",
     "2075-02-14", "Nepali", "1978-10-14",
     "Male", "Rajbiraj Bazar-6, Saptari",
     "By Descent", "22-01-68-00345", True),

    ("NID-025", "Sunita Yadav",
     "2077-11-19", "Nepali", "1985-07-19",
     "Female", "Kanchanpur Bazar-3, Saptari",
     "By Descent", "22-01-75-00678", True),

    ("NID-026", "Anil Kumar Jha",
     "2078-06-28", "Nepali", "1988-02-28",
     "Male", "Ram Mandir Marg-12, Dhanusha",
     "By Descent", "22-06-78-00901", True),

    ("NID-027", "Geeta Devi Mishra",
     "2076-09-11", "Nepali", "1982-05-11",
     "Female", "Dhanushadham-5, Dhanusha",
     "By Descent", "22-06-72-00234", True),

    ("NID-028", "Dil Bahadur Bista",
     "2074-01-06", "Nepali", "1974-09-06",
     "Male", "Chainpur Bazar-2, Bajhang",
     "By Descent", "74-01-64-00123", True),

    ("NID-029", "Durga Kumari Rokaya",
     "2076-05-17", "Nepali", "1980-01-17",
     "Female", "Thalara Bazar-4, Bajhang",
     "By Descent", "74-01-70-00456", True),

    ("NID-030", "Narayan Prasad Joshi",
     "2075-10-22", "Nepali", "1977-06-22",
     "Male", "Bhimdatta Chowk-7, Kanchanpur",
     "By Descent", "74-07-67-00789", True),

    ("NID-031", "Harka Bahadur Shahi",
     "2074-03-03", "Nepali", "1976-11-03",
     "Male", "Surkhet Bazar-4, Surkhet",
     "By Descent", "66-01-66-00234", True),

    ("NID-032", "Manju Kumari Saud",
     "2076-08-28", "Nepali", "1984-04-28",
     "Female", "Gurbhakot Bazar-6, Surkhet",
     "By Descent", "66-01-74-00567", True),

    ("NID-033", "Tek Bahadur Magar",
     "2077-04-15", "Nepali", "1986-12-15",
     "Male", "Tansen-3, Palpa",
     "By Descent", "44-09-76-00345", True),

    ("NID-034", "Kabita Kumari Basnet",
     "2078-09-20", "Nepali", "1991-05-20",
     "Female", "Waling-5, Syangja",
     "By Descent", "33-09-81-00678", True),

    ("NID-035", "Bishnu Prasad Rijal",
     "2075-12-10", "Nepali", "1979-08-10",
     "Male", "Baglung Bazar-2, Baglung",
     "By Descent", "33-10-69-00901", True),

    ("NID-036", "Sabita Devi Pandey",
     "2077-03-25", "Nepali", "1987-01-25",
     "Female", "Kushma-4, Parbat",
     "By Descent", "33-11-77-00234", True),

    ("NID-037", "Ganesh Prasad Kafle",
     "2076-07-14", "Nepali", "1983-04-14",
     "Male", "Damauli-6, Tanahun",
     "By Descent", "33-05-73-00567", True),

    ("NID-038", "Puja Kumari Thapa",
     "2079-01-08", "Nepali", "1994-10-08",
     "Female", "Bhimad-3, Tanahun",
     "By Descent", "33-05-84-00890", True),

    ("NID-039", "Mohan Bahadur Karki",
     "2075-06-19", "Nepali", "1975-02-19",
     "Male", "Ilam Bazar-1, Ilam",
     "By Descent", "11-07-65-00123", True),

    ("NID-040", "Rekha Kumari Rana",
     "2077-10-05", "Nepali", "1988-06-05",
     "Female", "Mechinagar-7, Jhapa",
     "By Descent", "11-08-78-00456", True),

    ("NID-041", "Umesh Kumar Gupta",
     "2078-04-30", "Nepali", "1992-12-30",
     "Male", "Lahan-4, Siraha",
     "By Descent", "22-04-82-00789", True),

    ("NID-042", "Radha Devi Koirala",
     "2076-02-16", "Nepali", "1980-09-16",
     "Female", "Gaur-8, Rautahat",
     "By Descent", "22-08-70-00234", True),

    ("NID-043", "Tika Ram Tiwari",
     "2074-08-27", "Nepali", "1973-06-27",
     "Male", "Bharatpur-11, Chitwan",
     "By Descent", "27-08-63-00567", True),

    ("NID-044", "Pramila Devi Acharya",
     "2077-05-13", "Nepali", "1986-01-13",
     "Female", "Ratnanagar-4, Chitwan",
     "By Descent", "27-08-76-00890", True),

    ("NID-045", "Sanjay Kumar Shah",
     "2078-11-22", "Nepali", "1993-07-22",
     "Male", "Birganj-9, Parsa",
     "By Descent", "22-10-83-01123", True),

    ("NID-046", "Anjali Kumari Sah",
     "2076-06-07", "Nepali", "1981-03-07",
     "Female", "Kalaiya-5, Bara",
     "By Descent", "22-09-71-00456", True),

    ("NID-047", "Lokendra Bahadur Chand",
     "2075-09-18", "Nepali", "1978-07-18",
     "Male", "Dipayal-3, Doti",
     "By Descent", "74-04-68-00234", True),

    ("NID-048", "Saraswati Devi Bohara",
     "2077-01-09", "Nepali", "1984-11-09",
     "Female", "Silgadhi-6, Doti",
     "By Descent", "74-04-74-00567", True),

    # ── SPECIAL RECORD: Inactive/revoked NID ─────────────────────────────────
    # Used to demonstrate rejection scenario during defense demo.
    # When your Identity Agent encounters is_active = False,
    # it must reject the application with a clear KYC failure message.
    ("NID-049", "Prakash Bahadur Kunwar",
     "2070-03-14", "Nepali", "1970-11-14",
     "Male", "Nepalgunj-2, Banke",
     "By Descent", "55-01-60-00123", "Deceased"),  # ← INACTIVE — demo rejection case

    # ── SPECIAL RECORD: Valid NID but zero land ownership ────────────────────
    # Used to demonstrate zero-asset scenario.
    # NeLIS will return empty list for this citizenship number.
    # Your Score Agent should handle this gracefully.
    ("NID-050", "Nirmala Kumari Osti",
     "2079-07-01", "Nepali", "1996-03-21",
     "Female", "Dhangadhi-4, Kailali",
     "By Descent", "74-06-86-00890", True),   # ← VALID but owns no land
]


def create_database():
    """
    Creates the donidcr.db SQLite database and populates it
    with 50 synthetic citizen records.

    Safe to run multiple times — drops and recreates the table
    each time so you always start fresh.
    """
    print(f"Creating DoNIDCR database at: {DB_PATH}")

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Drop existing table so reruns start clean
    cursor.execute("DROP TABLE IF EXISTS citizens")

    # Create table — mirrors exactly what DoNIDCR would expose
    cursor.execute("""
        CREATE TABLE citizens (
            nin               TEXT PRIMARY KEY,
            full_name         TEXT NOT NULL,
            date_of_issue     TEXT NOT NULL,
            nationality       TEXT NOT NULL DEFAULT 'Nepali',
            date_of_birth     TEXT NOT NULL,
            sex               TEXT NOT NULL,
            permanent_address TEXT NOT NULL,
            citizenship_type  TEXT NOT NULL,
            citizenship_no    TEXT NOT NULL UNIQUE,
            status         TEXT NOT NULL DEFAULT 'active'
        )
    """)

    # Create index on citizenship_no for fast lookups from NeLIS bridge query
    cursor.execute("""
        CREATE INDEX idx_citizenship_no ON citizens(citizenship_no)
    """)

    # Insert all records
    cursor.executemany("""
        INSERT INTO citizens (
            nin, full_name, date_of_issue, nationality,
            date_of_birth, sex, permanent_address,
            citizenship_type, citizenship_no, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, CITIZENS)

    conn.commit()

    # Verify
    count = cursor.execute("SELECT COUNT(*) FROM citizens").fetchone()[0]
    active = cursor.execute(
        "SELECT COUNT(*) FROM citizens WHERE status = 'active'"
    ).fetchone()[0]
    deceased = cursor.execute(
        "SELECT COUNT(*) FROM citizens WHERE status = 'deceased'"
    ).fetchone()[0]

    conn.close()

    print(f"  Total records : {count}")
    print(f"  Active NIDs   : {active}")
    print(f"  Deceased NIDs : {deceased}")
    print("DoNIDCR database ready.")


if __name__ == "__main__":
    create_database()