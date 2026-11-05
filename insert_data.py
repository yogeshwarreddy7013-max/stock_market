"""
insert_data.py - add new data to inventory_db without wiping it.

    python insert_data.py                      # simulate the next trading day + 50 random movements
    python insert_data.py --trades 200         # only add 200 random IN/OUT movements
    python insert_data.py --no-day             # skip the new price candle
    python insert_data.py --csv movements.csv  # import from a CSV file
    python insert_data.py --add RAMCO "Ramco Cements" Materials 850 40

CSV columns: symbol, type (IN/OUT), quantity [, price] [, date YYYY-MM-DD]
"""
import argparse
import csv
import random
from datetime import date, datetime, timedelta

from db import MAX_STOCKS, STOCK_SQL, session, status_of


def next_business_day(d):
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def simulate_day(cur, rng):
    """Add one new daily candle for every stock (random walk from its last close)."""
    cur.execute("SELECT MAX(trade_date) AS d FROM price_history")
    last = cur.fetchone()["d"]
    if not last:
        print("No price history yet - run reset_database.py first.")
        return
    day = next_business_day(last)
    if day > date.today():
        print(f"Prices are already up to date (latest candle: {last}).")
        return
    cur.execute("SELECT h.product_id, h.close, p.category FROM price_history h "
                "JOIN products p ON p.product_id = h.product_id WHERE h.trade_date = %s", (last,))
    rows = cur.fetchall()
    candles, updates = [], []
    for r in rows:
        c0 = float(r["close"])
        c1 = max(1.0, round(c0 * (1 + rng.gauss(0.0003, 0.015)), 2))
        o = round(c0 * (1 + rng.gauss(0, 0.003)), 2)
        h = round(max(o, c1) * (1 + abs(rng.gauss(0, 0.006))), 2)
        l = round(min(o, c1) * (1 - abs(rng.gauss(0, 0.006))), 2)
        candles.append((r["product_id"], day, o, h, l, c1, int(rng.lognormvariate(11.2, 0.7))))
        updates.append((c1, c0, r["product_id"]))
    cur.executemany("INSERT INTO price_history (product_id, trade_date, open, high, low, close, volume) VALUES (%s,%s,%s,%s,%s,%s,%s)", candles)
    cur.executemany("UPDATE products SET price = %s, prev_close = %s WHERE product_id = %s", updates)
    print(f"Added price candle for {day} to {len(candles)} stocks.")


def random_trades(cur, rng, n):
    """Random sales and restocks. Never sells more than what is in stock."""
    cur.execute(STOCK_SQL)
    stocks = cur.fetchall()
    if not stocks:
        print("No stocks found.")
        return
    cur.execute("SELECT supplier_id FROM suppliers")
    suppliers = [r["supplier_id"] for r in cur.fetchall()] or [None]
    rows = []
    for s in rng.sample(stocks, min(n, len(stocks))):
        have, reorder = int(s["stock"]), int(s["reorder_level"])
        needs = status_of(have, reorder) != "in"
        if have > 1 and not needs and rng.random() < 0.65:
            rows.append((s["product_id"], None, "OUT", rng.randint(1, max(1, have // 4)), s["price"], "Sale"))
        else:
            rows.append((s["product_id"], rng.choice(suppliers), "IN", rng.randint(max(2, reorder), max(5, reorder * 3)), s["price"], "Restock"))
    cur.executemany("INSERT INTO stock_transactions (product_id, supplier_id, transaction_date, transaction_type, quantity, price, note) "
                    "VALUES (%s,%s,NOW(),%s,%s,%s,%s)", rows)
    print(f"Added {len(rows)} stock movements ({sum(r[2] == 'IN' for r in rows)} IN / {sum(r[2] == 'OUT' for r in rows)} OUT).")


def import_csv(cur, path):
    cur.execute(STOCK_SQL)
    by_symbol = {r["symbol"].upper(): r for r in cur.fetchall()}
    added = skipped = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            s = by_symbol.get(row.get("symbol", "").upper())
            t = row.get("type", "").upper()
            try:
                qty = int(row.get("quantity", ""))
                when = datetime.strptime(row["date"], "%Y-%m-%d") if row.get("date") else datetime.now()
                price = float(row["price"]) if row.get("price") else float(s["price"])
            except (ValueError, TypeError, KeyError):
                s = None
            if not s or t not in ("IN", "OUT") or qty <= 0 or (t == "OUT" and qty > int(s["stock"])):
                print(f"  line {n}: skipped ({row})")
                skipped += 1
                continue
            cur.execute("INSERT INTO stock_transactions (product_id, transaction_date, transaction_type, quantity, price, note) "
                        "VALUES (%s,%s,%s,%s,%s,'CSV import')", (s["product_id"], when, t, qty, price))
            s["stock"] = int(s["stock"]) + (qty if t == "IN" else -qty)
            added += 1
    print(f"CSV import: {added} added, {skipped} skipped.")


def add_stock(cur, symbol, name, sector, price, qty):
    symbol = symbol.upper()
    cur.execute("SELECT COUNT(*) AS c FROM products")
    if cur.fetchone()["c"] >= MAX_STOCKS:
        raise SystemExit(f"Limit reached ({MAX_STOCKS} stocks).")
    cur.execute("INSERT INTO products (symbol, product_name, category, unit_cost, price, prev_close, reorder_level) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (symbol, name, sector, price, price, price, max(3, qty // 5)))
    pid = cur.lastrowid
    cur.execute("INSERT INTO price_history (product_id, trade_date, open, high, low, close, volume) VALUES (%s,CURDATE(),%s,%s,%s,%s,0)", (pid, price, price, price, price))
    if qty:
        cur.execute("INSERT INTO stock_transactions (product_id, transaction_date, transaction_type, quantity, price, note) VALUES (%s,NOW(),'IN',%s,%s,'Opening stock')", (pid, qty, price))
    print(f"Added {symbol} - {name} ({sector}) at {price} with {qty} units.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trades", type=int, default=50, help="random IN/OUT movements to add (default 50)")
    ap.add_argument("--no-day", action="store_true", help="do not add a new price candle")
    ap.add_argument("--csv", help="import movements from this CSV file")
    ap.add_argument("--add", nargs=5, metavar=("SYMBOL", "NAME", "SECTOR", "PRICE", "QTY"), help="add one stock")
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    with session(commit=True) as cur:
        if a.add:
            add_stock(cur, a.add[0], a.add[1], a.add[2], float(a.add[3]), int(a.add[4]))
        elif a.csv:
            import_csv(cur, a.csv)
        else:
            if not a.no_day:
                simulate_day(cur, rng)
            if a.trades > 0:
                random_trades(cur, rng, a.trades)
    print("Data inserted successfully!")


if __name__ == "__main__":
    main()
