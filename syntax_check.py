
import ast
import sys

files = [
    "app/seed_data/doctypes/data.py",
    "app/seed_data/codes/data.py"
]

for fpath in files:
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            ast.parse(f.read())
        print(f"[OK] {fpath}")
    except Exception as e:
        print(f"[ERROR] {fpath}: {e}")
        sys.exit(1)
