"""
run_project.py - run the whole project in order.

    python run_project.py                    # reset with 500 stocks, check, reports, chart
    python run_project.py --count 3000       # biggest data set
    python run_project.py --no-reset         # keep the current data
    python run_project.py --skip-chart --serve   # no chart window, then start the website
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

# --- make sure ALL project files are in this folder (a missing db.py is the most common start-up error)
_HERE = Path(__file__).resolve().parent
_MISSING = [f for f in ['db.py', 'universe.py', 'app.py', 'main.py', 'reset_database.py', 'insert_data.py', 'check_data.py', 'low_stock.py', 'stock_report.py', 'stock_chart.py', 'static/index.html', 'requirements.txt'] if not (_HERE / f).exists()]
if _MISSING:
    sys.exit("\nThese project files are missing next to %s:\n  - %s\n\n"
             "Copy the WHOLE 'stockvault' folder (every file, plus the 'static' folder), not just some files.\n"
             "Folder being used: %s\n" % (Path(__file__).name, "\n  - ".join(_MISSING), _HERE))

from db import DEFAULT_STOCKS, MAX_STOCKS, MIN_STOCKS, ROOT


def step(n, total, title, *cmd, required=True):
    print(f"\n{n}/{total}. {title}...")
    # always use the full path and run inside the project folder, so it works from any VS Code folder
    code = subprocess.call([sys.executable, str(ROOT / cmd[0]), *cmd[1:]], cwd=ROOT)
    if code != 0:
        print(f"   -> '{' '.join(cmd)}' finished with problems (exit code {code})")
        if required:
            sys.exit(f"\nStopped at step {n}. Fix the message above and run again.")
    return code


def main():
    ap = argparse.ArgumentParser(description="Run every StockVault step")
    ap.add_argument("--count", type=int, default=DEFAULT_STOCKS, help=f"stocks to create ({MIN_STOCKS}-{MAX_STOCKS})")
    ap.add_argument("--no-reset", action="store_true", help="keep existing data")
    ap.add_argument("--skip-chart", action="store_true", help="do not open the chart window")
    ap.add_argument("--serve", action="store_true", help="start the website at the end")
    a = ap.parse_args()

    t0 = time.time()
    plan = [("Connecting to the database", ["main.py", "ping"], True)]
    if not a.no_reset:
        plan.append((f"Resetting database with {a.count} stocks", ["reset_database.py", "--count", str(a.count), "--yes"], True))
    plan += [("Adding a new trading day and random movements", ["insert_data.py"], True),
             ("Checking data", ["check_data.py"], False),
             ("Low stock report", ["low_stock.py", "--limit", "15"], True),
             ("Stock report", ["stock_report.py", "--top", "5"], True)]
    if not a.skip_chart:
        plan.append(("Displaying stock chart (close the window to continue)", ["stock_chart.py"], False))
    for i, (title, cmd, required) in enumerate(plan, 1):
        step(i, len(plan), title, *cmd, required=required)

    print(f"\nPROJECT EXECUTED SUCCESSFULLY in {time.time() - t0:.0f}s")
    if a.serve:
        print("Starting website at http://127.0.0.1:5000  (press Ctrl+C to stop)")
        subprocess.call([sys.executable, str(ROOT / "app.py")], cwd=ROOT)
    else:
        print("Start the website with:  python app.py")


if __name__ == "__main__":
    main()
