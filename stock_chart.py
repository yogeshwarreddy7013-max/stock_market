"""
stock_chart.py - interactive candlestick chart (matplotlib).

    python stock_chart.py                    # biggest stock by inventory value
    python stock_chart.py TCS --days 90
    python stock_chart.py INFY --type line
    python stock_chart.py HDFCBANK --mode stock   # chart UNITS IN STOCK instead of price
    python stock_chart.py TCS --save tcs.png      # no window, just save the picture

On the chart:  hover = details | scroll = zoom | drag = move | C = candles/line | M = moving averages | R = reset
"""
import argparse

import matplotlib
import numpy as np
import pandas as pd

from db import STOCK_SQL, fetch_all, fetch_one

BG, PANEL, GRID, TXT = "#0b1016", "#111821", "#222f40", "#c9d4e5"
UP, DOWN, GOLD, BLUE = "#2fbf8a", "#ef5a6a", "#e3b04b", "#6aa5ff"


def pick_stock(symbol):
    if symbol:
        row = fetch_one("SELECT product_id, symbol, product_name FROM products WHERE symbol = %s OR product_name = %s", (symbol.upper(), symbol))
        if not row:
            raise SystemExit(f"Stock '{symbol}' not found. Try a symbol like TCS or RELIANCE.")
        return row
    rows = fetch_all(STOCK_SQL)
    if not rows:
        raise SystemExit("No stocks found - run reset_database.py first.")
    best = max(rows, key=lambda r: int(r["stock"]) * float(r["price"]))
    return dict(product_id=best["product_id"], symbol=best["symbol"], product_name=best["product_name"])


def price_data(pid, days):
    rows = fetch_all("SELECT trade_date AS date, open, high, low, close, volume FROM price_history "
                     "WHERE product_id = %s ORDER BY trade_date DESC LIMIT %s", (pid, days))
    df = pd.DataFrame(rows).iloc[::-1].reset_index(drop=True)
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].astype(float)
    df["vin"], df["vout"] = df["volume"].astype(float), 0.0
    df["date"] = pd.to_datetime(df["date"])
    return df


def stock_level_data(pid, days):
    """Running units-in-stock per day as candles (open/high/low/close) + IN/OUT volume."""
    rows = fetch_all("SELECT DATE(transaction_date) AS d, transaction_type AS t, quantity AS q FROM stock_transactions "
                     "WHERE product_id = %s ORDER BY transaction_date, transaction_id", (pid,))
    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("This stock has no movements yet.")
    df["q"] = df["q"].astype(float)
    df["signed"] = np.where(df["t"] == "IN", df["q"], -df["q"])
    df["after"] = df["signed"].cumsum()
    df["before"] = df["after"] - df["signed"]
    g = df.groupby("d")
    out = pd.DataFrame({
        "open": g["before"].first(), "close": g["after"].last(),
        "high": g.apply(lambda x: max(x["before"].max(), x["after"].max())),
        "low": g.apply(lambda x: min(x["before"].min(), x["after"].min())),
        "vin": g.apply(lambda x: x.loc[x["t"] == "IN", "q"].sum()),
        "vout": g.apply(lambda x: x.loc[x["t"] != "IN", "q"].sum()),
    })
    out.index = pd.to_datetime(out.index)
    out = out.reindex(pd.date_range(out.index.min(), out.index.max(), freq="D"))
    out["close"] = out["close"].ffill()
    for c in ("open", "high", "low"):
        out[c] = out[c].fillna(out["close"])
    out[["vin", "vout"]] = out[["vin", "vout"]].fillna(0)
    out = out.tail(days).rename_axis("date").reset_index()
    out["volume"] = out["vin"] + out["vout"]
    return out


class Chart:
    def __init__(self, title, df, unit, ctype):
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        from matplotlib.ticker import FuncFormatter, MaxNLocator
        self.plt, self.df, self.n, self.ctype, self.unit, self.press, self.show_ma = plt, df, len(df), ctype, unit, None, True
        x = np.arange(self.n)
        self.fig, (self.ax, self.axv) = plt.subplots(2, 1, figsize=(14, 8), sharex=True, facecolor=BG,
                                                     gridspec_kw={"height_ratios": [4, 1], "hspace": 0.05})
        for a in (self.ax, self.axv):
            a.set_facecolor(PANEL)
            a.grid(True, color=GRID, linewidth=0.6)
            a.tick_params(colors=TXT)
            a.yaxis.tick_right()
            for s in a.spines.values():
                s.set_color(GRID)
        self.axv.xaxis.set_major_locator(MaxNLocator(nbins=10, integer=True))
        self.axv.xaxis.set_major_formatter(FuncFormatter(lambda v, p: df["date"].iloc[int(round(v))].strftime("%d %b") if 0 <= round(v) < self.n else ""))

        self.candles = []
        for i, r in df.iterrows():
            col = UP if r["close"] >= r["open"] else DOWN
            wick, = self.ax.plot([i, i], [r["low"], r["high"]], color=col, lw=1.2, zorder=2)
            body = Rectangle((i - 0.32, min(r["open"], r["close"])), 0.64, max(abs(r["close"] - r["open"]), (df["high"].max() - df["low"].min()) * 0.002), fc=col, ec=col, zorder=3)
            self.ax.add_patch(body)
            self.candles += [wick, body]
        last, first = df["close"].iloc[-1], df["close"].iloc[0]
        main = UP if last >= first else DOWN
        self.line, = self.ax.plot(x, df["close"], color=main, lw=2, zorder=3)
        self.mas = []
        for period, col in ((20, GOLD), (50, BLUE)):
            if self.n > period:
                ln, = self.ax.plot(x, df["close"].rolling(period).mean(), color=col, lw=1.3, label=f"MA{period}", zorder=4)
                self.mas.append(ln)
        if self.mas:
            self.ax.legend(loc="upper left", facecolor=PANEL, edgecolor=GRID, labelcolor=TXT)
        self.ax.axhline(last, color=main, ls="--", lw=0.9)
        prev = df["close"].iloc[-2] if self.n > 1 else first
        chg = last - prev
        self.ax.set_title(f"{title}   {last:,.2f} {unit}   {'▲' if chg >= 0 else '▼'} {chg:+,.2f} ({chg / prev * 100 if prev else 0:+.2f}%)",
                          color=main, fontsize=16, fontweight="bold", loc="left", pad=34)
        self.axv.bar(x, df["vin"], color=UP, alpha=0.75, width=0.7)
        self.axv.bar(x, -df["vout"], color=DOWN, alpha=0.75, width=0.7)
        self.axv.axhline(0, color=GRID)
        self.axv.set_ylabel("Volume", color=TXT)
        kw = dict(color="#8fa0c4", lw=0.8, ls=":", visible=False, zorder=10)
        self.v1, self.v2 = self.ax.axvline(0, **kw), self.axv.axvline(0, **kw)
        self.info = self.ax.text(0, 1.02, "", transform=self.ax.transAxes, color=TXT, fontsize=10, family="monospace", va="bottom")
        self.fig.text(0.5, 0.012, "Hover = details  ·  Scroll = zoom  ·  Drag = move  ·  C = candles/line  ·  M = averages  ·  R = reset", ha="center", color="#6c7ea6", fontsize=9)
        self.fig.subplots_adjust(left=0.04, right=0.94, top=0.88, bottom=0.08)
        c = self.fig.canvas
        for ev, fn in (("motion_notify_event", self.move), ("scroll_event", self.scroll), ("button_press_event", self.down),
                       ("button_release_event", lambda e: setattr(self, "press", None)), ("key_press_event", self.key)):
            c.mpl_connect(ev, fn)
        self.set_type(ctype)
        self.reset()

    def set_type(self, t):
        self.ctype = t
        for a in self.candles:
            a.set_visible(t == "candle")
        self.line.set_visible(t == "line")
        self.fig.canvas.draw_idle()

    def fit_y(self):
        l, r = self.ax.get_xlim()
        seg = self.df.iloc[max(0, int(np.floor(l))): min(self.n, int(np.ceil(r)) + 1)]
        if seg.empty:
            return
        lo, hi = seg["low"].min(), seg["high"].max()
        pad = (hi - lo) * 0.1 or 1
        self.ax.set_ylim(lo - pad, hi + pad)
        vm = max(seg["vin"].max(), seg["vout"].max(), 1)
        self.axv.set_ylim(-vm * 1.2 if seg["vout"].max() else 0, vm * 1.2)

    def reset(self):
        self.ax.set_xlim(-1, self.n)
        self.fit_y()
        self.fig.canvas.draw_idle()

    def move(self, e):
        if self.press and e.x is not None:
            x0, l, r, w = self.press
            s = (x0 - e.x) / w * (r - l)
            self.ax.set_xlim(l + s, r + s)
            self.fit_y()
            self.fig.canvas.draw_idle()
            return
        if e.inaxes not in (self.ax, self.axv) or e.xdata is None:
            return
        i = int(np.clip(round(e.xdata), 0, self.n - 1))
        r = self.df.iloc[i]
        for v in (self.v1, self.v2):
            v.set_xdata([i, i])
            v.set_visible(True)
        pc = (r["close"] - r["open"]) / r["open"] * 100 if r["open"] else 0
        self.info.set_text(f"{r['date']:%d %b %Y}  O {r['open']:,.2f}  H {r['high']:,.2f}  L {r['low']:,.2f}  C {r['close']:,.2f}  {pc:+.2f}%  Vol {r['vin'] + r['vout']:,.0f}")
        self.info.set_color(UP if r["close"] >= r["open"] else DOWN)
        self.fig.canvas.draw_idle()

    def scroll(self, e):
        if e.inaxes not in (self.ax, self.axv) or e.xdata is None:
            return
        f = 0.8 if e.step > 0 else 1.25
        l, r = self.ax.get_xlim()
        nl, nr = e.xdata - (e.xdata - l) * f, e.xdata + (r - e.xdata) * f
        if nr - nl < 6:
            return
        self.ax.set_xlim(max(nl, -2), min(nr, self.n + 1))
        self.fit_y()
        self.fig.canvas.draw_idle()

    def down(self, e):
        if e.button == 1 and e.inaxes in (self.ax, self.axv):
            l, r = self.ax.get_xlim()
            self.press = (e.x, l, r, self.ax.bbox.width)

    def key(self, e):
        k = (e.key or "").lower()
        if k == "c":
            self.set_type("line" if self.ctype == "candle" else "candle")
        elif k == "m":
            self.show_ma = not self.show_ma
            for m in self.mas:
                m.set_visible(self.show_ma)
            self.fig.canvas.draw_idle()
        elif k == "r":
            self.reset()


def main():
    ap = argparse.ArgumentParser(description="Interactive stock chart")
    ap.add_argument("symbol", nargs="?", help="e.g. TCS (default: biggest stock by value)")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--type", choices=["candle", "line"], default="candle")
    ap.add_argument("--mode", choices=["price", "stock"], default="price", help="price = share price, stock = units in stock")
    ap.add_argument("--save", help="save as PNG/PDF instead of opening a window")
    a = ap.parse_args()
    if a.save:
        matplotlib.use("Agg")
    s = pick_stock(a.symbol)
    df = price_data(s["product_id"], a.days) if a.mode == "price" else stock_level_data(s["product_id"], a.days)
    if len(df) < 2:
        raise SystemExit("Not enough data to draw a chart.")
    print(f"{s['symbol']} - {s['product_name']}: {len(df)} candles ({a.mode})")
    chart = Chart(f"{s['symbol']}  {s['product_name']}", df, "INR" if a.mode == "price" else "units", a.type)
    if a.save:
        chart.fig.savefig(a.save, dpi=130, facecolor=BG)
        print(f"Saved {a.save}")
    else:
        chart.plt.show()


if __name__ == "__main__":
    main()
