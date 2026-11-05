# StockVault - inventory managed like a stock market

Python + MySQL + Flask. 100 to 3000 stocks, daily price history, live price ticks,
candlestick charts, buy/sell orders that change real stock levels, reports and alerts.

## Setup (once)
1. `pip install -r requirements.txt`
2. Open `.env` and check `DB_PASSWORD` (MySQL must be running). Keep `.env` private.

## Run in VS Code (read this first)
1. Unzip, then **File > Open Folder... > choose the `stockvault` folder itself** (the one that contains `app.py` and `db.py`), not the folder above it.
2. Pick your Python: `Ctrl+Shift+P` > **Python: Select Interpreter**.
3. Open a terminal: **Terminal > New Terminal** and install once: `python -m pip install -r requirements.txt`
4. Start MySQL, check the password in `.env`, then press **F5** and choose
   *StockVault: run everything (500 stocks)*  (or run `python run_project.py --count 500 --skip-chart --serve`).
5. Open http://127.0.0.1:5000

Problems:
* `can't open file ... main.py` - fixed: every script now starts the others by full path, so any folder works.
* `Missing Python package 'mysql'` - the selected interpreter has no packages. Run step 3 with the same Python.
* `Can't connect to MySQL server` - MySQL is not running, or `DB_PASSWORD` in `.env` is wrong.
* `run_project.py` and `reset_database.py` DELETE the old tables (products, stock_transactions, suppliers). Use `--no-reset` to keep data.

## Run
| What | Command |
|---|---|
| Everything in order | `python run_project.py --count 500` |
| Biggest data set | `python run_project.py --count 3000 --skip-chart --serve` |
| Only the website | `python app.py`  then open http://127.0.0.1:5000 |
| Menu | `python main.py` |

## Files
| File | Job |
|---|---|
| `db.py` | one place for DB settings, connection pool, shared SQL |
| `universe.py` | the stock list: ~98 real NSE names + generated companies (prices are simulated) |
| `reset_database.py` | creates tables and fills them. `--count 100..3000`, `--days`, `--seed` |
| `insert_data.py` | new trading day + random movements, CSV import, `--add` one stock |
| `check_data.py` | read-only health check (schema, bad quantities, negative stock, bad candles) |
| `low_stock.py` | restock list with suggested order and cost. `--sector --status --csv` |
| `stock_report.py` | value by sector, gainers/losers, P&L. `--xlsx --csv` |
| `stock_chart.py` | desktop candlestick chart: `python stock_chart.py TCS --days 90` |
| `main.py`, `run_project.py` | menu and one-command runner |
| `app.py` | Flask JSON API + live market engine |
| `static/index.html` | the website (replaces `index_.html`) |

## Website
Search, sector/status filters, sorting, pages of 25/50/100, watchlist (saved in the browser),
candle/line chart with 20/50 averages and volume, Buy (adds stock) / Sell (removes stock) tickets,
edit reorder level and cost, add/delete stocks, CSV export.
Keys: `/` search, Up/Down move between stocks.

## Good to know
* Prices are simulated random walks, not real market data. They move every 2 seconds on the server
  and are saved to MySQL every 30 seconds. A price cannot move more than 10% from the previous close.
* Selling more than the units in stock is refused, and the stock row is locked while the order is saved.
* Run `python insert_data.py` on a new day to add the next price candle.
