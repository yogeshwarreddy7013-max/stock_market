"""
stock_report.py - full inventory report.

    python stock_report.py                  # print report
    python stock_report.py --top 15
    python stock_report.py --xlsx report.xlsx   # Excel file with one sheet per section
    python stock_report.py --csv report.csv
"""
import argparse

import pandas as pd

from db import STOCK_SQL, fetch_all, inr


def load():
    df = pd.DataFrame(fetch_all(STOCK_SQL))
    for c in ("unit_cost", "price", "prev_close"):
        df[c] = df[c].astype(float)
    df["stock"] = df["stock"].astype(int)
    df["value"] = df["stock"] * df["price"]
    df["cost_value"] = df["stock"] * df["unit_cost"]
    df["pnl"] = df["value"] - df["cost_value"]
    df["day_pnl"] = (df["price"] - df["prev_close"]) * df["stock"]
    df["chg_pct"] = ((df["price"] / df["prev_close"].replace(0, float("nan")) - 1) * 100).fillna(0).round(2)
    df["status"] = df.apply(lambda r: "OUT" if r["stock"] <= 0 else ("LOW" if r["stock"] <= r["reorder_level"] else "IN STOCK"), axis=1)
    return df


def sectors(df):
    g = df.groupby("category").agg(stocks=("symbol", "count"), units=("stock", "sum"), value=("value", "sum"),
                                   pnl=("pnl", "sum"), day_pnl=("day_pnl", "sum")).sort_values("value", ascending=False)
    g["share_%"] = (g["value"] / g["value"].sum() * 100).round(1)
    return g.reset_index().rename(columns={"category": "sector"})


def cols(df, extra):
    return df.rename(columns={"product_name": "company", "category": "sector"})[["symbol", "company", "sector"] + extra]


def main():
    ap = argparse.ArgumentParser(description="Inventory report")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--csv")
    ap.add_argument("--xlsx")
    a = ap.parse_args()
    df = load()
    if df.empty:
        raise SystemExit("No stocks found - run reset_database.py first.")

    sec = sectors(df)
    top = cols(df.nlargest(a.top, "value"), ["price", "stock", "value"])
    gain = cols(df.nlargest(a.top, "chg_pct"), ["price", "chg_pct"])
    lose = cols(df.nsmallest(a.top, "chg_pct"), ["price", "chg_pct"])
    best = cols(df.nlargest(a.top, "pnl"), ["unit_cost", "price", "stock", "pnl"])
    worst = cols(df.nsmallest(a.top, "pnl"), ["unit_cost", "price", "stock", "pnl"])

    print("\nCURRENT STOCK REPORT\n")
    print(f"Stocks: {len(df):,}    Units in stock: {df['stock'].sum():,}")
    print(f"Inventory value (market): {inr(df['value'].sum())}    Cost value: {inr(df['cost_value'].sum())}")
    print(f"Unrealised P&L: {inr(df['pnl'].sum())}    Change since previous close: {inr(df['day_pnl'].sum())}")
    print("Status:", ", ".join(f"{k} {v}" for k, v in df["status"].value_counts().items()))
    print(f"Advancers {int((df['chg_pct'] > 0).sum())}  |  Decliners {int((df['chg_pct'] < 0).sum())}")
    fmt = {"float_format": lambda x: f"{x:,.2f}"}
    for title, part in (("BY SECTOR", sec), (f"TOP {a.top} BY INVENTORY VALUE", top), (f"TOP {a.top} GAINERS", gain),
                        (f"TOP {a.top} LOSERS", lose), (f"BEST {a.top} BY P&L", best), (f"WORST {a.top} BY P&L", worst)):
        print(f"\n{title}\n")
        print(part.to_string(index=False, **fmt))
    print("\nTOTAL INVENTORY VALUE:")
    print(round(df["value"].sum(), 2))

    full = cols(df, ["price", "prev_close", "chg_pct", "stock", "reorder_level", "unit_cost", "value", "pnl", "status"])
    if a.csv:
        full.to_csv(a.csv, index=False)
        print(f"\nSaved CSV: {a.csv}")
    if a.xlsx:
        with pd.ExcelWriter(a.xlsx) as xl:
            for name, part in (("All stocks", full), ("Sectors", sec), ("Top value", top), ("Gainers", gain),
                               ("Losers", lose), ("Best P&L", best), ("Worst P&L", worst)):
                part.to_excel(xl, sheet_name=name, index=False)
        print(f"\nSaved Excel: {a.xlsx}")


if __name__ == "__main__":
    main()
