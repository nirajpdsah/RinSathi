import sqlite3
import os

db = os.path.join('mock_databases', 'donidcr.db')
conn = sqlite3.connect(db)
cursor = conn.cursor()

cursor.execute("UPDATE citizens SET status = 'active' WHERE status = '1'")
cursor.execute("UPDATE citizens SET status = 'deceased' WHERE status = '0'")
conn.commit()

active   = cursor.execute("SELECT COUNT(*) FROM citizens WHERE status = 'active'").fetchone()[0]
deceased = cursor.execute("SELECT COUNT(*) FROM citizens WHERE status = 'Deceased'").fetchone()[0]
other    = cursor.execute("SELECT COUNT(*) FROM citizens WHERE status NOT IN ('active','Deceased')").fetchone()[0]

print(f'Active   : {active}')
print(f'Deceased : {deceased}')
print(f'Other    : {other}')

conn.close()