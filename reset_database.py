"""
reset_database.py - (re)build inventory_db from scratch with 100 to 3000 stocks.

    python reset_database.py                 # 500 stocks (default)
    python reset_database.py --count 3000    # maximum
    python reset_database.py --count 100 --days 90 --yes

Creates the database and all tables, then fills them with:
  * stocks (real NSE names first, generated names after that)
  * daily price history (open / high / low / close / volume) for every stock
  * inventory movements (IN = restock, OUT = sale) so stock levels are realistic
WARNING: this DELETES the old tables.
"""
import argparse
import sys
import time
from datetime import date, datetime, timedelta

import numpy as np

from db import DB_NAME, MAX_STOCKS, MIN_STOCKS, DEFAULT_STOCKS, connect
from universe import build_universe

SUPPLIERS = ["TechSupplier", "OfficeMart", "Global Electronics", "Smart Tech",
             "Prime Distributors", "Bharat Wholesale", "Metro Traders", "Sunrise Supply Co"]

SCHEMA = [
    "DROP TABLE IF EXISTS stock_transactions",
    "DROP TABLE IF EXISTS price_history",
    "DROP TABLE IF EXISTS products",
    "DROP TABLE IF EXISTS suppliers",
    """CREATE TABLE suppliers (
        supplier_id INT AUTO_INCREMENT PRIMARY KEY,
        supplier_name VARCHAR(100) NOT NULL
    ) ENGINE=InnoDB""",
    """CREATE TABLE products (
        product_id INT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL UNIQUE,
        product_name VARCHAR(120) NOT NULL,
        category VARCHAR(60) NOT NULL,
        unit_cost DECIMAL(12,2) NOT NULL DEFAULT 0,
        price DECIMAL(12,2) NOT NULL DEFAULT 0,
        prev_close DECIMAL(12,2) NOT NULL DEFAULT 0,
        reorder_level INT NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_category (category),
        INDEX idx_name (product_name)
    ) ENGINE=InnoDB""",
    """CREATE TABLE price_history (
        product_id INT NOT NULL,
        trade_date DATE NOT NULL,
        open DECIMAL(12,2) NOT NULL,
        high DECIMAL(12,2) NOT NULL,
        low DECIMAL(12,2) NOT NULL,
        close DECIMAL(12,2) NOT NULL,
        volume BIGINT NOT NULL DEFAULT 0,
        PRIMARY KEY (product_id, trade_date),
        FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE
    ) ENGINE=InnoDB""",
    """CREATE TABLE stock_transactions (
        transaction_id INT AUTO_INCREMENT PRIMARY KEY,
        product_id INT NOT NULL,
        supplier_id INT NULL,
        transaction_date DATETIME NOT NULL,
        transaction_type ENUM('IN','OUT') NOT NULL,
        quantity INT NOT NULL CHECK (quantity > 0),
        price DECIMAL(12,2) NOT NULL DEFAULT 0,
        note VARCHAR(200) NULL,
        INDEX idx_product (product_id),
        INDEX idx_date (transaction_date),
        FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE,
        FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id) ON DELETE SET NULL
    ) ENGINE=InnoDB""",
]


def business_days(n):
    d, out = date.today(), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def make_prices(rng, stocks, days):
    """Random-walk OHLCV for every stock; the last close equals the stock's target price."""
    n = len(stocks)
    vol = np.array([s["vol"] for s in stocks])[:, None]
    target = np.array([s["price"] for s in stocks])[:, None]
    ret = np.clip(rng.normal(0.0003, 1, (n, days)) * vol, -0.18, 0.18)
    close = np.cumprod(1 + ret, axis=1)
    close = close / close[:, -1:] * target
    open_ = np.empty_like(close)
    open_[:, 0] = close[:, 0]
    open_[:, 1:] = close[:, :-1] * (1 + rng.normal(0, 0.003, (n, days - 1)))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, (n, days))))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, (n, days))))
    volume = rng.lognormal(11.2, 0.7, (n, days)).astype(np.int64)
    return [np.round(a, 2) for a in (open_, high, low, close)] + [volume]


def make_transactions(rng, stocks, ids, dates, close):
    """Opening stock + restocks + sales. A few stocks end low or out so alerts have data."""
    rows, ndays = [], len(dates)
    for i, s in enumerate(stocks):
        pid = ids[s["symbol"]]
        base = int(np.clip(rng.lognormal(4.4, 0.8), 15, 2000))
        reorder = max(3, int(base * rng.uniform(0.12, 0.25)))
        level = base
        rows.append((pid, int(rng.integers(1, len(SUPPLIERS) + 1)), datetime.combine(dates[0], datetime.min.time()).replace(hour=9),
                     "IN", base, float(close[i, 0]), "Opening stock"))
        for di in sorted(rng.choice(np.arange(1, ndays), size=int(rng.integers(4, 11)), replace=False)):
            when = datetime.combine(dates[di], datetime.min.time()).replace(hour=int(rng.integers(9, 16)), minute=int(rng.integers(0, 60)))
            if rng.random() < 0.62 and level > 2:
                q = min(level, max(1, int(level * rng.uniform(0.05, 0.35))))
                rows.append((pid, None, when, "OUT", q, float(close[i, di]), "Sale"))
                level -= q
            else:
                q = max(1, int(base * rng.uniform(0.2, 0.6)))
                rows.append((pid, int(rng.integers(1, len(SUPPLIERS) + 1)), when, "IN", q, float(close[i, di]), "Restock"))
                level += q
        roll, last = rng.random(), datetime.combine(dates[-1], datetime.min.time()).replace(hour=15)
        target = 0 if roll < 0.03 else (int(rng.integers(1, reorder + 1)) if roll < 0.12 else None)
        if target is not None and level > target:
            rows.append((pid, None, last, "OUT", level - target, float(close[i, -1]), "Sale"))
            level = target
        stocks[i]["reorder"], stocks[i]["level"] = reorder, level
    return rows


def batches(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def main():
    ap = argparse.ArgumentParser(description="Rebuild inventory_db with sample stocks.")
    ap.add_argument("--count", type=int, default=DEFAULT_STOCKS, help=f"number of stocks ({MIN_STOCKS}-{MAX_STOCKS})")
    ap.add_argument("--days", type=int, default=130, help="days of price history (30-400)")
    ap.add_argument("--seed", type=int, default=42, help="same seed = same data")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    a = ap.parse_args()
    if not MIN_STOCKS <= a.count <= MAX_STOCKS:
        sys.exit(f"--count must be between {MIN_STOCKS} and {MAX_STOCKS}")
    if not 30 <= a.days <= 400:
        sys.exit("--days must be between 30 and 400")
    if not a.yes and input(f"This DELETES all data in '{DB_NAME}' and creates {a.count} stocks. Continue? [y/N] ").lower() != "y":
        sys.exit("Cancelled.")

    t0 = time.time()
    rng = np.random.default_rng(a.seed)
    stocks = build_universe(a.count, a.seed)
    dates = business_days(a.days)

    conn = connect(with_db=False)
    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4")
    cur.execute(f"USE `{DB_NAME}`")
    print("1/5 Creating tables ...")
    for stmt in SCHEMA:
        cur.execute(stmt)
    cur.executemany("INSERT INTO suppliers (supplier_name) VALUES (%s)", [(s,) for s in SUPPLIERS])

    print(f"2/5 Generating prices for {len(stocks)} stocks x {a.days} days ...")
    o, h, l, c, v = make_prices(rng, stocks, a.days)

    print("3/5 Inserting stocks ...")
    prod_rows = [(s["symbol"], s["name"], s["sector"], round(float(c[i, -1]) * float(rng.uniform(0.7, 1.1)), 2),
                  float(c[i, -1]), float(c[i, -2])) for i, s in enumerate(stocks)]
    cur.executemany("INSERT INTO products (symbol, product_name, category, unit_cost, price, prev_close) VALUES (%s,%s,%s,%s,%s,%s)", prod_rows)
    cur.execute("SELECT symbol, product_id FROM products")
    ids = dict(cur.fetchall())

    print("4/5 Inserting price history ...")
    hist = [(ids[s["symbol"]], dates[d], float(o[i, d]), float(h[i, d]), float(l[i, d]), float(c[i, d]), int(v[i, d]))
            for i, s in enumerate(stocks) for d in range(a.days)]
    for chunk in batches(hist, 10000):
        cur.executemany("INSERT INTO price_history (product_id, trade_date, open, high, low, close, volume) VALUES (%s,%s,%s,%s,%s,%s,%s)", chunk)
    conn.commit()

    print("5/5 Inserting stock movements and reorder levels ...")
    tx = make_transactions(rng, stocks, ids, dates, c)
    for chunk in batches(tx, 10000):
        cur.executemany("INSERT INTO stock_transactions (product_id, supplier_id, transaction_date, transaction_type, quantity, price, note) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)", chunk)
    cur.executemany("UPDATE products SET reorder_level = %s WHERE product_id = %s", [(s["reorder"], ids[s["symbol"]]) for s in stocks])
    conn.commit()
    conn.close()

    low = sum(1 for s in stocks if 0 < s["level"] <= s["reorder"])
    out = sum(1 for s in stocks if s["level"] == 0)
    print(f"\nDatabase reset successfully in {time.time() - t0:.1f}s")
    print(f"  {len(stocks)} stocks | {len(hist):,} price candles | {len(tx):,} stock movements | {low} low | {out} out of stock")


if __name__ == "__main__":
    main()
