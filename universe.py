"""
universe.py - the list of stocks StockVault trades (100 to 3000).

The first ~90 are well-known NSE companies. Prices are APPROXIMATE reference
values used as a starting point for simulated prices - not live market data.
The rest are generated company names, so the same seed always gives the same list.
"""
import math
import random
import re

# symbol | company | sector | approx price (INR)
REAL = """
RELIANCE|Reliance Industries|Energy|1420
TCS|Tata Consultancy Services|IT Services|3200
HDFCBANK|HDFC Bank|Banking|1000
INFY|Infosys|IT Services|1550
ICICIBANK|ICICI Bank|Banking|1350
HINDUNILVR|Hindustan Unilever|FMCG|2400
ITC|ITC|FMCG|420
SBIN|State Bank of India|Banking|820
BHARTIARTL|Bharti Airtel|Telecom|1900
KOTAKBANK|Kotak Mahindra Bank|Banking|2000
LT|Larsen & Toubro|Infrastructure|3600
AXISBANK|Axis Bank|Banking|1150
ASIANPAINT|Asian Paints|Consumer|2400
MARUTI|Maruti Suzuki|Auto|12500
SUNPHARMA|Sun Pharmaceutical|Pharma|1700
TITAN|Titan Company|Consumer|3500
BAJFINANCE|Bajaj Finance|Finance|1000
NESTLEIND|Nestle India|FMCG|1250
ULTRACEMCO|UltraTech Cement|Materials|11500
WIPRO|Wipro|IT Services|260
HCLTECH|HCL Technologies|IT Services|1500
TECHM|Tech Mahindra|IT Services|1500
POWERGRID|Power Grid Corporation|Power|300
NTPC|NTPC|Power|340
ONGC|Oil and Natural Gas Corp|Energy|240
COALINDIA|Coal India|Energy|400
TATAMOTORS|Tata Motors|Auto|700
TATASTEEL|Tata Steel|Metals|160
JSWSTEEL|JSW Steel|Metals|1050
HINDALCO|Hindalco Industries|Metals|750
ADANIPORTS|Adani Ports|Infrastructure|1400
DRREDDY|Dr. Reddy's Laboratories|Pharma|1250
CIPLA|Cipla|Pharma|1500
DIVISLAB|Divi's Laboratories|Pharma|6000
APOLLOHOSP|Apollo Hospitals|Healthcare|7500
EICHERMOT|Eicher Motors|Auto|5500
HEROMOTOCO|Hero MotoCorp|Auto|4500
BRITANNIA|Britannia Industries|FMCG|5800
GRASIM|Grasim Industries|Materials|2700
SHREECEM|Shree Cement|Materials|26000
INDUSINDBK|IndusInd Bank|Banking|800
BPCL|Bharat Petroleum|Energy|330
IOC|Indian Oil Corporation|Energy|160
GAIL|GAIL India|Energy|180
VEDL|Vedanta|Metals|450
DLF|DLF|Realty|800
GODREJCP|Godrej Consumer Products|FMCG|1200
PIDILITIND|Pidilite Industries|Consumer|3000
HAVELLS|Havells India|Industrials|1500
SIEMENS|Siemens|Industrials|3200
ABB|ABB India|Industrials|5500
BEL|Bharat Electronics|Defence|400
HAL|Hindustan Aeronautics|Defence|4500
ZOMATO|Zomato|Internet|270
NYKAA|FSN E-Commerce (Nykaa)|Internet|200
PAYTM|One 97 Communications|Internet|1000
IRCTC|IRCTC|Travel|750
DMART|Avenue Supermarts|Retail|4000
TRENT|Trent|Retail|5000
BANKBARODA|Bank of Baroda|Banking|250
PNB|Punjab National Bank|Banking|110
CANBK|Canara Bank|Banking|120
IDFCFIRSTB|IDFC First Bank|Banking|70
YESBANK|Yes Bank|Banking|20
TATAPOWER|Tata Power|Power|400
ADANIGREEN|Adani Green Energy|Power|1000
SBILIFE|SBI Life Insurance|Insurance|1800
HDFCLIFE|HDFC Life Insurance|Insurance|750
ICICIGI|ICICI Lombard|Insurance|1900
LICI|Life Insurance Corporation|Insurance|900
MUTHOOTFIN|Muthoot Finance|Finance|2500
CHOLAFIN|Cholamandalam Investment|Finance|1600
SHRIRAMFIN|Shriram Finance|Finance|650
LUPIN|Lupin|Pharma|2000
AUROPHARMA|Aurobindo Pharma|Pharma|1200
TORNTPHARM|Torrent Pharmaceuticals|Pharma|3400
MAXHEALTH|Max Healthcare|Healthcare|1100
BAJAJHLDNG|Bajaj Holdings|Finance|12000
DABUR|Dabur India|FMCG|520
MARICO|Marico|FMCG|700
COLPAL|Colgate-Palmolive India|FMCG|2600
BERGEPAINT|Berger Paints|Consumer|520
VOLTAS|Voltas|Consumer|1400
CUMMINSIND|Cummins India|Industrials|3300
BHEL|Bharat Heavy Electricals|Industrials|230
RVNL|Rail Vikas Nigam|Infrastructure|400
IRFC|Indian Railway Finance Corp|Finance|130
NHPC|NHPC|Power|85
SJVN|SJVN|Power|100
SAIL|Steel Authority of India|Metals|130
NMDC|NMDC|Metals|70
JINDALSTEL|Jindal Steel & Power|Metals|950
AMBUJACEM|Ambuja Cements|Materials|550
ACC|ACC|Materials|1900
PERSISTENT|Persistent Systems|IT Services|5500
LTIM|LTIMindtree|IT Services|5200
MPHASIS|Mphasis|IT Services|2700
INDIGO|InterGlobe Aviation|Travel|5000
""".strip().splitlines()

# typical daily volatility per sector
SECTOR_VOL = {
    "Energy": .014, "IT Services": .015, "Banking": .015, "FMCG": .009, "Telecom": .013,
    "Infrastructure": .016, "Consumer": .012, "Auto": .016, "Pharma": .014, "Finance": .017,
    "Materials": .015, "Metals": .020, "Power": .016, "Healthcare": .013, "Realty": .021,
    "Industrials": .016, "Defence": .022, "Internet": .024, "Travel": .018, "Retail": .016,
    "Insurance": .015,
}

PREFIX = ["Aarav", "Bharat", "Chola", "Deccan", "Ekta", "Fortune", "Ganga", "Himalaya", "Indus", "Jaya",
          "Kaveri", "Lotus", "Mahi", "Narmada", "Orient", "Prime", "Quest", "Rajat", "Surya", "Tapti",
          "Uday", "Vijay", "Western", "Yamuna", "Zenith", "Apex", "Coastal", "Delta", "Emerald", "Falcon",
          "Granite", "Horizon", "Ivory", "Jupiter", "Kestrel", "Lumen", "Meridian", "Nova", "Orbit",
          "Pinnacle", "Quantum", "Redwood", "Summit", "Titan", "Unity", "Vertex", "Wave", "Sahyadri"]
WORDS = {
    "Energy": ["Petro", "Gas", "Solar", "Refinery"], "IT Services": ["Infotech", "Software", "Digital", "Systems"],
    "Banking": ["Bank", "Cooperative Bank", "Finserv", "Credit"], "FMCG": ["Foods", "Consumer", "Beverages", "Agro"],
    "Telecom": ["Telecom", "Networks", "Broadband", "Towers"], "Infrastructure": ["Infra", "Construction", "Roads", "Projects"],
    "Consumer": ["Home", "Brands", "Appliances", "Lifestyle"], "Auto": ["Motors", "Auto Parts", "Tyres", "Forge"],
    "Pharma": ["Pharma", "Labs", "Lifesciences", "Biotech"], "Finance": ["Capital", "Finance", "Leasing", "Housing Finance"],
    "Materials": ["Cement", "Chemicals", "Paper", "Glass"], "Metals": ["Steel", "Alloys", "Metals", "Aluminium"],
    "Power": ["Power", "Energy", "Hydro", "Transmission"], "Healthcare": ["Hospitals", "Diagnostics", "Care", "Medical"],
    "Realty": ["Realty", "Estates", "Developers", "Properties"], "Industrials": ["Engineering", "Electricals", "Machines", "Tools"],
    "Defence": ["Aerospace", "Defence", "Dynamics", "Shipyard"], "Internet": ["Online", "Tech", "Commerce", "Platforms"],
    "Travel": ["Airlines", "Travels", "Hotels", "Logistics"], "Retail": ["Retail", "Stores", "Mart", "Fashion"],
    "Insurance": ["Insurance", "Assurance", "General Insurance", "Life"],
}
SUFFIX = ["Ltd", "Limited", "Industries"]


def _real():
    out = []
    for line in REAL:
        sym, name, sector, price = line.split("|")
        out.append(dict(symbol=sym, name=name, sector=sector, price=float(price), real=True))
    return out


def build_universe(count, seed=42):
    """Return `count` stocks (real ones first, then generated ones)."""
    rng = random.Random(seed)
    real = _real()
    stocks = real[:count]
    used_sym = {s["symbol"] for s in stocks}
    used_name = {s["name"] for s in stocks}
    sectors = sorted(WORDS)
    while len(stocks) < count:
        sector = rng.choice(sectors)
        pre, word, suf = rng.choice(PREFIX), rng.choice(WORDS[sector]), rng.choice(SUFFIX)
        name = f"{pre} {word} {suf}"
        if name in used_name:
            continue
        base = re.sub(r"[^A-Z]", "", (pre + word).upper())[:9]
        sym, k = base, 1
        while sym in used_sym:
            k += 1
            sym = f"{base[:8]}{k}"
        price = min(9000, max(15, math.exp(rng.gauss(6.0, 1.1))))
        used_sym.add(sym)
        used_name.add(name)
        stocks.append(dict(symbol=sym, name=name, sector=sector, price=round(price, 2), real=False))
    for s in stocks:
        s["vol"] = SECTOR_VOL.get(s["sector"], .015)
    return stocks
