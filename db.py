"""
db.py - shared settings, connection helpers and SQL used by every StockVault file.

Settings come from environment variables or from the .env file next to this file,
so the password is written in ONE place only.
"""
import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent

try:
    import mysql.connector
    from mysql.connector import pooling
except ModuleNotFoundError as e:       # most common VS Code problem: packages not installed for the selected Python
    sys.exit(
        f"\nMissing Python package '{e.name}' for this Python:\n  {sys.executable}\n\n"
        f"Install everything with:\n  \"{sys.executable}\" -m pip install -r \"{ROOT / 'requirements.txt'}\"\n\n"
        "In VS Code: press Ctrl+Shift+P > 'Python: Select Interpreter' and pick the same Python you installed into.\n")


def _load_dotenv():
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

CONFIG = dict(
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", ""),
    database=os.getenv("DB_NAME", "inventory_db"),
)
DB_NAME = CONFIG["database"]

MIN_STOCKS, DEFAULT_STOCKS, MAX_STOCKS = 100, 500, 3000

# Units on hand per product = all IN minus all OUT.  Used by the website and every report.
STOCK_SQL = """
SELECT p.product_id, p.symbol, p.product_name, p.category, p.unit_cost, p.price,
       p.prev_close, p.reorder_level, COALESCE(t.stock, 0) AS stock
FROM products p
LEFT JOIN (
    SELECT product_id,
           SUM(CASE WHEN transaction_type = 'IN' THEN quantity ELSE -quantity END) AS stock
    FROM stock_transactions GROUP BY product_id
) t ON t.product_id = p.product_id
"""

_pool = None


def connect(with_db=True):
    cfg = dict(CONFIG)
    if not with_db:
        cfg.pop("database")
    return mysql.connector.connect(**cfg)


def pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="stockvault", pool_size=int(os.getenv("DB_POOL", "8")),
            pool_reset_session=True, **CONFIG)
    return _pool


@contextmanager
def session(dictionary=True, commit=False, pooled=False):
    """with session(commit=True) as cur: cur.execute(...)   (rolls back on error)"""
    conn = pool().get_connection() if pooled else connect()
    try:
        cur = conn.cursor(dictionary=dictionary)
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        conn.close()


def fetch_all(sql, params=(), pooled=False):
    with session(pooled=pooled) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one(sql, params=(), pooled=False):
    with session(pooled=pooled) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def status_of(stock, reorder):
    if stock <= 0:
        return "out"
    return "low" if stock <= reorder else "in"


def inr(n, decimals=0):
    """12345678 -> ₹1,23,45,678 (Indian digit grouping)."""
    n = float(n or 0)
    whole, _, frac = f"{abs(n):.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail, parts = whole[:-3], whole[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + "₹" + whole + ("." + frac if decimals else "")
