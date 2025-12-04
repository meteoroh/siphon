import sqlite3
import os

DB_PATH = 'instance/siphon.db'

def add_column():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Check if column exists
        cursor.execute("PRAGMA table_info(video)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if 'media_ids' not in columns:
            print("Adding media_ids column to video table...")
            cursor.execute("ALTER TABLE video ADD COLUMN media_ids TEXT")
            conn.commit()
            print("Column added successfully.")
        else:
            print("Column media_ids already exists.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    add_column()
