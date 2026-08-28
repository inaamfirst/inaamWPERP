import sqlite3

with sqlite3.connect("runtime_data/local_offline_erp.db") as conn:
    result = conn.execute(
        "SELECT status FROM products WHERE id='c8c548a2-42db-4610-a38e-b9f28110533a'"
    ).fetchone()
print(result)
