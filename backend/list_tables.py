import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect(r'D:\code\api-automation\backend\db.sqlite3')
cur = conn.cursor()

# Parameters for port list interfaces (53-58)
cur.execute("SELECT id, name, location, data_type, required, description, example, interface_id FROM api_parameters WHERE interface_id IN (53,54,55,56,57,58)")
params = cur.fetchall()
print(f"=== Parameters ({len(params)}) ===")
for p in params:
    print(f"\n  Interface={p[7]} | {p[1]} ({p[2]}, {p[3]}) required={p[4]}")
    print(f"    desc: {str(p[5])[:200]}")
    print(f"    example: {str(p[6])[:200]}")

conn.close()
