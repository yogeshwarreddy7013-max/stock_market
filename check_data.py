"""
check_data.py - health check for inventory_db.

    python check_data.py
It only READS the database (changes nothing) and tells you what is wrong, so the
website, the reports and the charts show correct numbers.
Exit code: 0 = fine (warnings allowed), 1 = problems found.
"""
import sys
from datetime import date

from db import CONFIG, MAX_STOCKS, MIN_STOCKS, STOCK_SQL, connect, inr
import mysql.connector

REQUIRED = {
    "suppliers": ["supplier_id", "supplier_name"],
    "products": ["product_id", "symbol", "product_name", "category", "unit_cost", "price", "prev_close", "reorder_level"],
    "price_history": ["product_id", "trade_date", "open", "high", "low", "close", "volume"],
    "stock_transactions": ["transaction_id", "product_id", "transaction_date", "transaction_type", "quantity", "price"],
}
problems = warnings = 0


def ok(m):
    print(f"  ✅ {m}")


def warn(m):
    global warnings
    warnings += 1
    print(f"  ⚠️  {m}")


def bad(m):
    global problems
    problems += 1
    print(f"  ❌ {m}")


def title(t):
    print(f"\n=== {t} ===")


def check(count, good, problem, fn=bad):
    (fn if count else ok)(problem.format(n=count) if count else good)


def main():
    print("StockVault data check")
    try:
        conn = connect()
    except mysql.connector.Error as e:
        print(f"\n❌ Cannot connect to MySQL: {e}")
        print("   Check that MySQL is running and DB_USER / DB_PASSWORD / DB_NAME in .env are correct.")
        return 1
    cur = conn.cursor(dictionary=True)

    def one(sql, params=()):
        cur.execute(sql, params)
        return cur.fetchone()

    def many(sql, params=()):
        cur.execute(sql, params)
        return cur.fetchall()

    print(f"Connected to '{CONFIG['database']}' on {CONFIG['host']}")

    title("1. Tables & columns")
    tables = {list(r.values())[0] for r in many("SHOW TABLES")}
    schema_ok = True
    for table, cols in REQUIRED.items():
        if table not in tables:
            bad(f"Table '{table}' is missing")
            schema_ok = False
            continue
        have = {r["Field"] for r in many(f"SHOW COLUMNS FROM {table}")}
        missing = [c for c in cols if c not in have]
        if missing:
            bad(f"Table '{table}' has no column(s): {', '.join(missing)}")
            schema_ok = False
        else:
            ok(f"'{table}' has all needed columns")
    if not schema_ok:
        print("\nRun  python reset_database.py  to rebuild the tables, then check again.")
        conn.close()
        return 1

    title("2. Row counts")
    n_prod = one("SELECT COUNT(*) AS c FROM products")["c"]
    n_tx = one("SELECT COUNT(*) AS c FROM stock_transactions")["c"]
    n_hist = one("SELECT COUNT(*) AS c FROM price_history")["c"]
    check(0 if n_prod else 1, f"{n_prod:,} stocks", "No stocks in the database")
    if n_prod and n_prod < MIN_STOCKS:
        warn(f"{n_prod} stocks - fewer than the recommended minimum of {MIN_STOCKS}")
    if n_prod > MAX_STOCKS:
        warn(f"{n_prod} stocks - more than {MAX_STOCKS}; the website may slow down")
    check(0 if n_tx else 1, f"{n_tx:,} stock movements", "No stock movements")
    check(0 if n_hist else 1, f"{n_hist:,} daily price candles", "No price history - charts will be empty")

    title("3. Stock movements")
    types = {str(r["t"]): r["c"] for r in many("SELECT transaction_type AS t, COUNT(*) AS c FROM stock_transactions GROUP BY transaction_type")}
    ok("Types found: " + ", ".join(f"{k} = {v:,}" for k, v in types.items())) if types else None
    odd = {k: v for k, v in types.items() if k not in ("IN", "OUT")}
    check(len(odd), "All types are IN or OUT", f"Unexpected transaction_type values {odd}")
    check(one("SELECT COUNT(*) AS c FROM stock_transactions WHERE quantity IS NULL OR quantity <= 0")["c"],
          "All quantities are positive", "{n} movement(s) with empty, zero or negative quantity")
    check(one("SELECT COUNT(*) AS c FROM stock_transactions WHERE transaction_date IS NULL")["c"],
          "All movements have a date", "{n} movement(s) with no date")
    check(one("SELECT COUNT(*) AS c FROM stock_transactions t LEFT JOIN products p ON p.product_id = t.product_id WHERE p.product_id IS NULL")["c"],
          "Every movement belongs to a stock", "{n} movement(s) point to a stock that does not exist")
    check(one("SELECT COUNT(*) AS c FROM stock_transactions WHERE transaction_date > NOW() + INTERVAL 1 DAY")["c"],
          "No movements dated in the future", "{n} movement(s) dated in the future", warn)

    title("4. Stocks")
    check(len(many("SELECT symbol FROM products GROUP BY symbol HAVING COUNT(*) > 1")), "No duplicate symbols", "{n} duplicate symbol(s)")
    check(one("SELECT COUNT(*) AS c FROM products WHERE price IS NULL OR price <= 0")["c"], "All prices are above 0", "{n} stock(s) with price 0 or empty")
    check(one("SELECT COUNT(*) AS c FROM products WHERE prev_close IS NULL OR prev_close <= 0")["c"], "All stocks have a previous close", "{n} stock(s) without previous close (change % shows 0)", warn)
    check(one("SELECT COUNT(*) AS c FROM products WHERE unit_cost <= 0")["c"], "All stocks have an average cost", "{n} stock(s) with cost 0 (P&L will look too high)", warn)
    check(one("SELECT COUNT(*) AS c FROM products WHERE reorder_level <= 0")["c"], "All stocks have a reorder level", "{n} stock(s) with reorder level 0 (never shown as low)", warn)

    rows = many(STOCK_SQL)
    neg = [r for r in rows if int(r["stock"]) < 0]
    for r in neg[:10]:
        bad(f"NEGATIVE stock: {r['symbol']} = {int(r['stock'])} (more OUT than IN)")
    if len(neg) > 10:
        bad(f"... and {len(neg) - 10} more with negative stock")
    if not neg:
        ok("No negative stock")
    no_tx = many("SELECT p.symbol FROM products p LEFT JOIN stock_transactions t ON t.product_id = p.product_id WHERE t.product_id IS NULL")
    check(len(no_tx), "Every stock has movements", "{n} stock(s) with no movements yet (shows 0 units)", warn)

    title("5. Price history & charts")
    check(one("SELECT COUNT(*) AS c FROM price_history WHERE high < GREATEST(open, close) OR low > LEAST(open, close) OR low <= 0")["c"],
          "All candles are valid (low <= open/close <= high)", "{n} invalid candle(s)")
    no_hist = one("SELECT COUNT(*) AS c FROM products p LEFT JOIN price_history h ON h.product_id = p.product_id WHERE h.product_id IS NULL")["c"]
    check(no_hist, "Every stock has price history", "{n} stock(s) without price history (empty chart)", warn)
    last = one("SELECT MAX(trade_date) AS d, MIN(trade_date) AS f FROM price_history")
    if last["d"]:
        age = (date.today() - last["d"]).days
        ok(f"History from {last['f']} to {last['d']}")
        if age > 4:
            warn(f"Latest candle is {age} days old - run  python insert_data.py  to add the new trading day")
    bad_close = one("SELECT COUNT(*) AS c FROM products p JOIN price_history h ON h.product_id = p.product_id "
                    "AND h.trade_date = (SELECT MAX(trade_date) FROM price_history WHERE product_id = p.product_id) "
                    "WHERE ABS(h.close - p.price) / p.price > 0.15")["c"]
    check(bad_close, "Live prices match the latest candle", "{n} stock(s) whose price is >15% away from the last candle", warn)

    title("6. Summary")
    low = [r for r in rows if 0 < int(r["stock"]) <= int(r["reorder_level"] or 0)]
    out = [r for r in rows if int(r["stock"]) == 0]
    value = sum(int(r["stock"]) * float(r["price"] or 0) for r in rows)
    print(f"  Stocks: {len(rows):,}   Units: {sum(int(r['stock']) for r in rows):,}   Inventory value: {inr(value)}")
    print(f"  In stock: {len(rows) - len(low) - len(out) - len(neg):,}   Low: {len(low)}   Out: {len(out)}")
    if low or out:
        print("\n  Most urgent restocks:")
        for r in sorted(low + out, key=lambda r: int(r["stock"]) / max(int(r["reorder_level"]), 1))[:8]:
            tag = "OUT" if int(r["stock"]) == 0 else "LOW"
            print(f"   - [{tag}] {r['symbol']:<12} {r['product_name'][:28]:<28} stock {int(r['stock']):>5}   reorder level {r['reorder_level']}")
    conn.close()

    print("\n" + "=" * 40)
    if problems:
        print(f"❌ {problems} problem(s) and {warnings} warning(s) - fix the problems first.")
        return 1
    print(f"✅ No problems, {warnings} warning(s)." if warnings else "✅ Everything looks perfect!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
