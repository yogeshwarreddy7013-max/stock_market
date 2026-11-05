"""
app.py - StockVault backend (Flask + MySQL).

    python app.py          ->  http://127.0.0.1:5000

The page (static/index.html) talks to this JSON API:
  GET  /api/summary            totals, sectors, gainers, losers, restock list
  GET  /api/stocks             search / filter / sort / pages (works with 3000 stocks)
  GET  /api/stocks/<id>        one stock + facts + recent movements
  GET  /api/stocks/<id>/candles?days=90
  POST /api/stocks             add a stock               PATCH/DELETE /api/stocks/<id>
  POST /api/trade              IN (buy / restock) or OUT (sell)
  GET  /api/orders             recent movements
  GET  /api/live?since=N       price ticks since version N  (the page polls this)
  GET  /api/ticker, /api/sectors, /api/health, /export.csv
"""
import csv
import io
import math
import os
import random
import threading
import time
from datetime import date, datetime
from decimal import Decimal

from db import MAX_STOCKS, STOCK_SQL, fetch_all, fetch_one, pool, session, status_of
import mysql.connector
from flask import Flask, Response, jsonify, request, send_from_directory
from flask.json.provider import DefaultJSONProvider

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")

TICK_SECONDS = 2        # how often the simulated market moves
CIRCUIT_LIMIT = 0.10    # a price cannot move more than 10% from the previous close (like a real circuit limit)
FLUSH_SECONDS = 30      # how often live prices are saved to MySQL
SORTS = {"symbol": "symbol", "name": "name", "sector": "sector", "price": "price", "chg": "chg_pct",
         "stock": "stock", "value": "value", "pnl": "pnl"}


class Provider(DefaultJSONProvider):
    sort_keys = False

    @staticmethod
    def default(o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (datetime, date)):
            return o.isoformat(sep=" ") if isinstance(o, datetime) else o.isoformat()
        return DefaultJSONProvider.default(o)


app.json = Provider(app)


def err(msg, code=400):
    return jsonify(error=msg), code


# ------------------------------------------------------------------
# LIVE MARKET (prices move every few seconds, saved to MySQL regularly)
# ------------------------------------------------------------------
class Live:
    def __init__(self):
        self.lock = threading.RLock()
        self.px, self.prev, self.ver, self.dirty = {}, {}, {}, set()
        self.v, self.started = 0, False
        self.rng = random.Random()

    def start(self):
        with self.lock:
            if self.started:
                return
            for r in fetch_all("SELECT product_id, price, prev_close FROM products", pooled=True):
                self.px[r["product_id"]] = float(r["price"])
                self.prev[r["product_id"]] = float(r["prev_close"] or r["price"])
            self.started = True
        threading.Thread(target=self._loop, daemon=True).start()

    def register(self, pid, price):
        with self.lock:
            self.px[pid] = self.prev[pid] = float(price)

    def remove(self, pid):
        with self.lock:
            for d in (self.px, self.prev, self.ver):
                d.pop(pid, None)
            self.dirty.discard(pid)

    def tick(self):
        with self.lock:
            ids = list(self.px)
            for pid in self.rng.sample(ids, min(len(ids), max(5, int(len(ids) * 0.04)))):
                old, prev = self.px[pid], self.prev[pid]
                new = round(min(max(old * (1 + self.rng.gauss(0, 0.0012)), prev * (1 - CIRCUIT_LIMIT)), prev * (1 + CIRCUIT_LIMIT)), 2)
                if new > 0 and new != old:
                    self.px[pid] = new
                    self.v += 1
                    self.ver[pid] = self.v
                    self.dirty.add(pid)

    def flush(self):
        with self.lock:
            rows = [(self.px[p], p) for p in self.dirty if p in self.px]
            self.dirty.clear()
        if rows:
            with session(commit=True, pooled=True) as cur:
                cur.executemany("UPDATE products SET price = %s WHERE product_id = %s", rows)

    def _loop(self):
        last = time.time()
        while True:
            time.sleep(TICK_SECONDS)
            try:
                self.tick()
                if time.time() - last >= FLUSH_SECONDS:
                    self.flush()
                    last = time.time()
            except Exception as e:      # never let the thread die
                print("live market error:", e)

    def since(self, v):
        with self.lock:
            if v > self.v:
                v = 0
            return self.v, {pid: [self.px[pid], self.change(pid)] for pid, ver in self.ver.items() if ver > v and pid in self.px}

    def change(self, pid):
        prev = self.prev.get(pid) or 0
        return round((self.px[pid] - prev) / prev * 100, 2) if prev else 0


LIVE = Live()
_snap = {"t": 0, "rows": []}
_snap_lock = threading.Lock()


def snapshot():
    """All stocks with stock levels (cached for 2 seconds, so 3000 stocks stay fast)."""
    LIVE.start()
    with _snap_lock:
        if time.time() - _snap["t"] > 2:
            _snap["rows"] = fetch_all(STOCK_SQL, pooled=True)
            _snap["t"] = time.time()
        rows = _snap["rows"]
    return [enrich(r) for r in rows]


def invalidate():
    _snap["t"] = 0


def enrich(r):
    pid = r["product_id"]
    px = LIVE.px.get(pid, float(r["price"]))
    prev = LIVE.prev.get(pid, float(r["prev_close"] or px))
    stock, reorder, cost = int(r["stock"] or 0), int(r["reorder_level"] or 0), float(r["unit_cost"] or 0)
    return dict(id=pid, symbol=r["symbol"], name=r["product_name"], sector=r["category"], price=px, prev=prev,
                change=round(px - prev, 2), chg_pct=round((px - prev) / prev * 100, 2) if prev else 0,
                cost=cost, stock=stock, reorder=reorder, value=round(stock * px, 2), pnl=round((px - cost) * stock, 2),
                status=status_of(stock, reorder), suggested=max(0, reorder * 2 - stock))


def get_stock(pid):
    row = fetch_one(STOCK_SQL + " WHERE p.product_id = %s", (pid,), pooled=True)
    LIVE.start()
    return enrich(row) if row else None


# ------------------------------------------------------------------
# PAGES
# ------------------------------------------------------------------
@app.route("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/health")
def health():
    row = fetch_one("SELECT COUNT(*) AS stocks FROM products", pooled=True)
    return jsonify(ok=True, stocks=row["stocks"], live_version=LIVE.v)


# ------------------------------------------------------------------
# READ
# ------------------------------------------------------------------
@app.route("/api/summary")
def summary():
    rows = snapshot()
    sectors = {}
    for r in rows:
        s = sectors.setdefault(r["sector"], dict(sector=r["sector"], count=0, value=0.0, pnl=0.0))
        s["count"] += 1
        s["value"] += r["value"]
        s["pnl"] += r["pnl"]
    by = sorted(rows, key=lambda r: r["chg_pct"])
    slim = lambda r: {k: r[k] for k in ("id", "symbol", "name", "price", "chg_pct", "stock", "reorder", "status", "suggested")}
    need = sorted((r for r in rows if r["status"] != "in"), key=lambda r: (r["stock"] / max(r["reorder"], 1)))
    return jsonify(
        stocks=len(rows), units=sum(r["stock"] for r in rows),
        value=round(sum(r["value"] for r in rows), 2),
        day_pnl=round(sum((r["price"] - r["prev"]) * r["stock"] for r in rows), 2),
        pnl=round(sum(r["pnl"] for r in rows), 2),
        low=sum(r["status"] == "low" for r in rows), out=sum(r["status"] == "out" for r in rows),
        advancers=sum(r["chg_pct"] > 0 for r in rows), decliners=sum(r["chg_pct"] < 0 for r in rows),
        sectors=sorted(sectors.values(), key=lambda s: -s["value"]),
        gainers=[slim(r) for r in by[::-1][:6]], losers=[slim(r) for r in by[:6]],
        restock=[slim(r) for r in need[:8]], max_stocks=MAX_STOCKS)


@app.route("/api/sectors")
def sectors():
    return jsonify([r["category"] for r in fetch_all("SELECT DISTINCT category FROM products ORDER BY category", pooled=True)])


@app.route("/api/stocks")
def stocks():
    a = request.args
    rows = snapshot()
    q = a.get("q", "").strip().lower()
    if q:
        rows = [r for r in rows if q in r["symbol"].lower() or q in r["name"].lower()]
    if a.get("sector"):
        rows = [r for r in rows if r["sector"] == a["sector"]]
    if a.get("status") in ("in", "low", "out"):
        rows = [r for r in rows if r["status"] == a["status"]]
    if a.get("ids"):
        want = {int(x) for x in a["ids"].split(",") if x.strip().isdigit()}
        rows = [r for r in rows if r["id"] in want]
    key = SORTS.get(a.get("sort", "value"), "value")
    if key in ("symbol", "name", "sector"):
        rows.sort(key=lambda r: str(r[key]).lower(), reverse=a.get("order") == "desc")
    else:
        rows.sort(key=lambda r: r[key], reverse=a.get("order", "desc") == "desc")
    per = min(max(a.get("per_page", 25, type=int), 5), 100)
    pages = max(1, math.ceil(len(rows) / per))
    page = min(max(a.get("page", 1, type=int), 1), pages)
    return jsonify(items=rows[(page - 1) * per: page * per], total=len(rows), page=page, pages=pages, per_page=per)


@app.route("/api/stocks/<int:pid>")
def stock_detail(pid):
    s = get_stock(pid)
    if not s:
        return err("Stock not found.", 404)
    h = fetch_one("SELECT MAX(high) AS hi, MIN(low) AS lo, AVG(volume) AS vol, COUNT(*) AS days "
                  "FROM price_history WHERE product_id = %s", (pid,), pooled=True)
    s.update(period_high=float(h["hi"] or s["price"]), period_low=float(h["lo"] or s["price"]),
             avg_volume=int(h["vol"] or 0), history_days=h["days"])
    s["recent"] = fetch_all(
        "SELECT t.transaction_type AS type, t.quantity, t.price, t.transaction_date AS at, t.note, sp.supplier_name AS supplier "
        "FROM stock_transactions t LEFT JOIN suppliers sp ON sp.supplier_id = t.supplier_id "
        "WHERE t.product_id = %s ORDER BY t.transaction_date DESC, t.transaction_id DESC LIMIT 8", (pid,), pooled=True)
    return jsonify(s)


@app.route("/api/stocks/<int:pid>/candles")
def candles(pid):
    days = min(max(request.args.get("days", 90, type=int), 5), 500)
    rows = fetch_all("SELECT trade_date AS t, open AS o, high AS h, low AS l, close AS c, volume AS v "
                     "FROM price_history WHERE product_id = %s ORDER BY trade_date DESC LIMIT %s", (pid, days), pooled=True)
    return jsonify(candles=rows[::-1])


@app.route("/api/orders")
def orders():
    limit = min(request.args.get("limit", 12, type=int), 100)
    return jsonify(fetch_all(
        "SELECT t.transaction_id AS id, p.product_id AS stock_id, p.symbol, p.product_name AS name, t.transaction_type AS type, "
        "t.quantity, t.price, t.transaction_date AS at FROM stock_transactions t JOIN products p ON p.product_id = t.product_id "
        "ORDER BY t.transaction_date DESC, t.transaction_id DESC LIMIT %s", (limit,), pooled=True))


@app.route("/api/ticker")
def ticker():
    rows = sorted(snapshot(), key=lambda r: -r["value"])[:40]
    return jsonify([dict(id=r["id"], symbol=r["symbol"], price=r["price"], chg_pct=r["chg_pct"]) for r in rows])


@app.route("/api/live")
def live():
    LIVE.start()
    v, ticks = LIVE.since(request.args.get("since", 0, type=int))
    return jsonify(v=v, ticks=ticks)


@app.route("/export.csv")
def export_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Symbol", "Company", "Sector", "Price", "Prev Close", "Change %", "Units", "Reorder Level",
                "Avg Cost", "Market Value", "Unrealised P&L", "Status"])
    for r in sorted(snapshot(), key=lambda r: r["symbol"]):
        w.writerow([r["symbol"], r["name"], r["sector"], r["price"], r["prev"], r["chg_pct"], r["stock"], r["reorder"],
                    r["cost"], r["value"], r["pnl"], r["status"].upper()])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=stockvault_report.csv"})


# ------------------------------------------------------------------
# WRITE
# ------------------------------------------------------------------
@app.route("/api/trade", methods=["POST"])
def trade():
    d = request.get_json(silent=True) or {}
    ttype = str(d.get("type", "")).upper()
    try:
        pid, qty = int(d.get("id")), int(d.get("quantity"))
    except (TypeError, ValueError):
        return err("Choose a stock and enter a whole-number quantity.")
    if ttype not in ("IN", "OUT") or qty <= 0 or qty > 1_000_000:
        return err("Enter a quantity between 1 and 1,000,000.")
    LIVE.start()
    with session(commit=True, pooled=True) as cur:
        cur.execute("SELECT symbol, price FROM products WHERE product_id = %s FOR UPDATE", (pid,))   # lock row: no double selling
        p = cur.fetchone()
        if not p:
            return err("Stock not found.", 404)
        cur.execute("SELECT COALESCE(SUM(CASE WHEN transaction_type='IN' THEN quantity ELSE -quantity END),0) AS s "
                    "FROM stock_transactions WHERE product_id = %s", (pid,))
        have = int(cur.fetchone()["s"])
        if ttype == "OUT" and qty > have:
            return err(f"Only {have} units of {p['symbol']} in stock.")
        price = LIVE.px.get(pid, float(p["price"]))
        cur.execute("INSERT INTO stock_transactions (product_id, transaction_date, transaction_type, quantity, price, note) "
                    "VALUES (%s, NOW(), %s, %s, %s, %s)", (pid, ttype, qty, price, "Restock" if ttype == "IN" else "Sale"))
    invalidate()
    return jsonify(ok=True, stock=have + qty if ttype == "IN" else have - qty, price=price,
                   message=f"{'Bought' if ttype == 'IN' else 'Sold'} {qty} x {p['symbol']} at {price:,.2f}")


@app.route("/api/stocks", methods=["POST"])
def add_stock():
    d = request.get_json(silent=True) or {}
    symbol = str(d.get("symbol", "")).strip().upper()
    name = str(d.get("name", "")).strip()
    sector = str(d.get("sector", "")).strip() or "General"
    try:
        price, qty = float(d.get("price")), int(d.get("quantity") or 0)
        reorder = int(d.get("reorder") or max(3, qty // 5))
        cost = float(d.get("cost") or price)
    except (TypeError, ValueError):
        return err("Price, quantity and reorder level must be numbers.")
    if not symbol.isalnum() or len(symbol) > 20:
        return err("Symbol must be letters and numbers only (max 20).")
    if not name or len(name) > 120:
        return err("Company name is required (max 120 characters).")
    if price <= 0 or qty < 0 or reorder < 0 or cost < 0:
        return err("Price must be above 0; quantity, reorder level and cost cannot be negative.")
    if fetch_one("SELECT COUNT(*) AS c FROM products", pooled=True)["c"] >= MAX_STOCKS:
        return err(f"Limit reached: StockVault holds up to {MAX_STOCKS:,} stocks.")
    if fetch_one("SELECT 1 AS x FROM products WHERE symbol = %s", (symbol,), pooled=True):
        return err(f"Symbol {symbol} already exists.")
    with session(commit=True, pooled=True) as cur:
        cur.execute("INSERT INTO products (symbol, product_name, category, unit_cost, price, prev_close, reorder_level) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)", (symbol, name, sector, cost, price, price, reorder))
        pid = cur.lastrowid
        cur.execute("INSERT INTO price_history (product_id, trade_date, open, high, low, close, volume) VALUES (%s,CURDATE(),%s,%s,%s,%s,0)",
                    (pid, price, price, price, price))
        if qty:
            cur.execute("INSERT INTO stock_transactions (product_id, transaction_date, transaction_type, quantity, price, note) "
                        "VALUES (%s, NOW(), 'IN', %s, %s, 'Opening stock')", (pid, qty, price))
    LIVE.start()
    LIVE.register(pid, price)
    invalidate()
    return jsonify(ok=True, id=pid, message=f"{symbol} added.")


@app.route("/api/stocks/<int:pid>", methods=["PATCH"])
def edit_stock(pid):
    d = request.get_json(silent=True) or {}
    try:
        reorder, cost = int(d.get("reorder")), float(d.get("cost"))
        if reorder < 0 or cost < 0:
            raise ValueError
    except (TypeError, ValueError):
        return err("Reorder level and cost must be numbers (0 or more).")
    with session(commit=True, pooled=True) as cur:
        cur.execute("UPDATE products SET reorder_level = %s, unit_cost = %s WHERE product_id = %s", (reorder, cost, pid))
    invalidate()
    return jsonify(ok=True, message="Stock updated.")


@app.route("/api/stocks/<int:pid>", methods=["DELETE"])
def delete_stock(pid):
    with session(commit=True, pooled=True) as cur:
        cur.execute("DELETE FROM products WHERE product_id = %s", (pid,))     # history + movements are deleted too
        if not cur.rowcount:
            return err("Stock not found.", 404)
    LIVE.remove(pid)
    invalidate()
    return jsonify(ok=True, message="Stock deleted.")


# ------------------------------------------------------------------
@app.errorhandler(mysql.connector.Error)
def db_error(e):
    return err(f"Database problem: {e}. Run 'python check_data.py' to find the cause.", 500)


@app.errorhandler(404)
def not_found(e):
    return err("Not found.", 404)


if __name__ == "__main__":
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")),
            debug=os.getenv("FLASK_DEBUG") == "1", use_reloader=False, threaded=True)
