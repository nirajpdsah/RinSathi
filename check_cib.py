import sqlite3

conn = sqlite3.connect('mock_databases/cib.db')
cursor = conn.cursor()

cursor.execute("SELECT COUNT(*) FROM cib_records")
total = cursor.fetchone()[0]
print(f"Total rows in cib_records: {total}")

cursor.execute("SELECT * FROM cib_records WHERE citizenship_no = '33-06-65-00567'")
rows = cursor.fetchall()
print(f"Rows for Gopal Prasad Sharma: {len(rows)}")
for row in rows:
    print(row)

conn.close()