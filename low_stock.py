"""
low_stock.py - which stocks need restocking?

    python low_stock.py                       # all low + out of stock items
    python low_stock.py --status out          # only items with 0 units
    python low_stock.py --sector Banking --limit 20
    python low_stock.py --csv restock.csv     # save the order list
"""
import argparse

import pandas as pd

from db import STOCK_SQL, fetch_all, inr


def load(sector=None, status="all", target=2.0):
    df = pd.DataFrame(fetch_all(STOCK_SQL))
    if df.empty:
        return df
    for c in ("unit_cost", "price", "prev_close"):
        df[c] = df[c].astype(float)
    df["stock"] = df["stock"].astype(int)
    df["status"] = df.apply(lambda r: "OUT" if r["stock"] <= 0 else ("LOW" if r["stock"] <= r["reorder_level"] else "OK"), axis=1)
    df["to_order"] = (df["reorder_level"] * target - df["stock"]).clip(lower=0).round().astype(int)
    df["order_cost"] = df["to_order"] * df["unit_cost"]
    df["cover_pct"] = (df["stock"] / df["reorder_level"].clip(lower=1) * 100).round().astype(int)
    df = df[df["status"] != "OK"]
    if status in ("low", "out"):
        df = df[df["status"] == status.upper()]
    if sector:
        df = df[df["category"].str.lower() == sector.lower()]
    return df.sort_values(["status", "cover_pct"], ascending=[False, True])   # OUT first, then least cover


def main():
    ap = argparse.ArgumentParser(description="Low stock report")
    ap.add_argument("--sector")
    ap.add_argument("--status", choices=["all", "low", "out"], default="all")
    ap.add_argument("--target", type=float, default=2.0, help="restock up to reorder level x this (default 2)")
    ap.add_argument("--limit", type=int, default=30, help="rows to print (default 30, 0 = all)")
    ap.add_argument("--csv", help="save the full list to this CSV file")
    a = ap.parse_args()

    df = load(a.sector, a.status, a.target)
    print("\nLOW STOCK ITEMS\n")
    if df.empty:
        print("Nothing to restock - every stock is above its reorder level.")
        return
    out = df.rename(columns={"product_name": "company", "category": "sector", "reorder_level": "reorder"})
    show = out[["symbol", "company", "sector", "stock", "reorder", "status", "to_order"]]
    print((show if a.limit == 0 else show.head(a.limit)).to_string(index=False))
    if a.limit and len(show) > a.limit:
        print(f"... and {len(show) - a.limit} more (use --limit 0 or --csv to see all)")
    print(f"\n{len(df)} stocks need attention: {(df['status'] == 'OUT').sum()} out, {(df['status'] == 'LOW').sum()} low")
    print(f"Units to order: {df['to_order'].sum():,}   Estimated cost: {inr(df['order_cost'].sum())}")
    by = df.groupby("category").agg(items=("symbol", "count"), cost=("order_cost", "sum")).sort_values("cost", ascending=False).head(5)
    print("\nBiggest restock bills by sector:")
    for sec, r in by.iterrows():
        print(f"  {sec:<16} {int(r['items']):>4} items   {inr(r['cost'])}")
    if a.csv:
        out.to_csv(a.csv, index=False)
        print(f"\nSaved {len(out)} rows to {a.csv}")


if __name__ == "__main__":
    main()
