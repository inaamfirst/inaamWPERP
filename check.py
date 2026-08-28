import sqlite3

try:
    with sqlite3.connect("runtime_data/local_offline_erp.db") as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    print([row[0] for row in tables])
except Exception as e:
    print(e)
