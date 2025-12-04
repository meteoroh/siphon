import sqlite3
import os

db_path = 'instance/siphon.db'

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Check if column exists
    cursor.execute("PRAGMA table_info(performer)")
    columns = [info[1] for info in cursor.fetchall()]
    
    if 'auto_download' not in columns:
        print("Adding auto_download column...")
        cursor.execute("ALTER TABLE performer ADD COLUMN auto_download BOOLEAN DEFAULT 0")
        conn.commit()
        print("Column added successfully.")
    else:
        print("Column auto_download already exists.")
        
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
