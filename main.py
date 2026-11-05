"""
main.py - start here.

    python main.py          # connection check, then a menu
    python main.py ping     # connection check only
    python main.py web      # start the website directly
"""
import subprocess
import sys
from pathlib import Path

# --- make sure ALL project files are in this folder (a missing db.py is the most common start-up error)
_HERE = Path(__file__).resolve().parent
_MISSING = [f for f in ['db.py', 'universe.py', 'app.py', 'main.py', 'reset_database.py', 'insert_data.py', 'check_data.py', 'low_stock.py', 'stock_report.py', 'stock_chart.py', 'static/index.html', 'requirements.txt'] if not (_HERE / f).exists()]
if _MISSING:
    sys.exit("\nThese project files are missing next to %s:\n  - %s\n\n"
             "Copy the WHOLE 'stockvault' folder (every file, plus the 'static' folder), not just some files.\n"
             "Folder being used: %s\n" % (Path(__file__).name, "\n  - ".join(_MISSING), _HERE))

from db import CONFIG, ROOT, connect
import mysql.connector

MENU = [
    ("1", "Check data health", ["check_data.py"]),
    ("2", "Low stock report", ["low_stock.py"]),
    ("3", "Full stock report", ["stock_report.py"]),
    ("4", "Stock chart (biggest stock)", ["stock_chart.py"]),
    ("5", "Add new trading day + random movements", ["insert_data.py"]),
    ("6", "Start the website  (http://127.0.0.1:5000)", ["app.py"]),
    ("7", "Reset database (asks first)", ["reset_database.py"]),
]


def ping():
    try:
        conn = connect()
    except mysql.connector.Error as e:
        print(f"Database connection FAILED: {e}")
        print("Check that MySQL is running and the settings in .env are correct. If the database does not exist yet, run: python reset_database.py")
        return False
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT VERSION() AS v")
    version = cur.fetchone()["v"]
    print(f"Database Connected Successfully!  (MySQL {version}, database '{CONFIG['database']}')")
    try:
        cur.execute("SELECT COUNT(*) AS n, COALESCE(SUM(price), 0) AS p FROM products")
        r = cur.fetchone()
        print(f"  {r['n']:,} stocks in the database")
    except mysql.connector.Error:
        print("  Tables not found yet - choose 'Reset database' to create them.")
    conn.close()
    return True


def run(script, *args):
    return subprocess.call([sys.executable, str(ROOT / script), *args], cwd=ROOT)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "ping":
        sys.exit(0 if ping() else 1)
    if cmd == "web":
        sys.exit(run("app.py"))
    if not ping():
        sys.exit(1)
    while True:
        print("\nStockVault")
        for k, label, _ in MENU:
            print(f"  {k}. {label}")
        print("  0. Exit")
        choice = input("Choose: ").strip()
        if choice == "0":
            break
        for k, _, script in MENU:
            if k == choice:
                run(*script)
                break
        else:
            print("Please enter a number from the menu.")


if __name__ == "__main__":
    main()
