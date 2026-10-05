"""
S1 Classic: park_chg20+z120+kyle_z60
parkinson_vol30|chg20|- + parkinson_vol30|z120|- + kyle_lambda|z60|+
Backtest: Sharpe 2.53, DD -33.3%, WR 60.7%.
"""
import sys, os, json, time, logging, socket
from pathlib import Path
from datetime import datetime, timezone

_orig = socket.getaddrinfo
def _ipv4(*a, **k): return [r for r in _orig(*a, **k) if r[0] == socket.AF_INET]
socket.getaddrinfo = _ipv4

import numpy as np, pandas as pd, ccxt
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [s1] %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "trader.log"), logging.StreamHandler()])
log = logging.getLogger("s1")

DATA_DIR = Path.home() / "Desktop/datacryp/derived/panel_wide"
STATE_FILE = Path(__file__).parent / "live_state.json"

ALPHAS = [
    {
        "name": "parkinson_vol30|chg20|-",
        "weight": 0.3333
    },
    {
        "name": "parkinson_vol30|z120|-",
        "weight": 0.3333
    },
    {
        "name": "kyle_lambda|z60|+",
        "weight": 0.3333
    }
]
TOP_N = 30; LEVERAGE = 5; GROSS_TARGET = 5.5; FREE_PCT = 0.33
SL_PCT = 30; MIN_NOTIONAL = 5.0; REBALANCE_INTERVAL = 3600
DRY_RUN = os.getenv("LIVE_DRY_RUN", "1") == "1"
EQUAL_WEIGHT = True; FUNDING_FILTER = True; FUNDING_FILTER_THRESHOLD = 0.03

def load_panels(tf="1d"):
    panels = {}
    for f in ["close","volume","open","high","low","quote_volume"]:
        p = DATA_DIR / tf / f"{f}.parquet"
        if p.exists(): panels[f] = pd.read_parquet(p)
    return panels if panels else None

def _compute_factor(name, panels, liq):
    close,high,low = panels["close"],panels["high"],panels["low"]
    volume,QV = panels["volume"],panels["quote_volume"]
    ret = close.pct_change()
    parts = name.split("|"); fn,tf,dr = parts[0],parts[1],parts[2]
    sgn = 1 if dr=="+" else -1
    if fn=="parkinson_vol30":
        loghl=np.log(high/low); raw=(loghl**2/(4*np.log(2))).rolling(30,15).mean().apply(np.sqrt)*np.sqrt(365)
    elif fn=="amihud": raw=(ret.abs()/(QV+1e-12)).rolling(20,10).mean()
    elif fn=="ivol": mkt=ret.mean(axis=1); raw=ret.sub(mkt,axis=0).rolling(20,10).std()*np.sqrt(365)
    elif fn=="ret_vol_20": raw=ret.rolling(20,10).std()
    elif fn=="kyle_lambda": raw=(ret.abs()/(volume*close+1e-12)).rolling(20,10).mean()
    elif fn=="residual_vol": mkt=ret.mean(axis=1); raw=ret.sub(mkt,axis=0).rolling(20,10).std()
    elif fn=="rvol_ratio": raw=ret.rolling(5,3).std()/ret.rolling(60,30).std().replace(0,np.nan)
    elif fn=="trend60": raw=close.pct_change(60)
    elif fn=="max_ret": raw=ret.rolling(20,10).max()
    elif fn=="momentum_20": raw=close.pct_change(20)
    elif fn=="iskew": raw=ret.rolling(20,10).skew()
    else: return None
    if tf=="lvl": F=raw
    elif tf=="chg20": F=raw-raw.shift(20)
    elif tf=="chg60": F=raw-raw.shift(60)
    elif tf=="z20": F=(raw-raw.rolling(20,10).mean())/raw.rolling(20,10).std().replace(0,np.nan)
    elif tf=="z60": F=(raw-raw.rolling(60,30).mean())/raw.rolling(60,30).std().replace(0,np.nan)
    elif tf=="z120": F=(raw-raw.rolling(120,60).mean())/raw.rolling(120,60).std().replace(0,np.nan)
    else: F=raw
    sig=F.where(liq)
    sig=sig.sub(sig.mean(axis=1),axis=0).div(sig.std(axis=1).replace(0,np.nan),axis=0)*sgn
    m,s=sig.mean(axis=1),sig.std(axis=1)
    sig=sig.clip(lower=(m-3*s),upper=(m+3*s),axis=0)
    g=sig.abs().sum(axis=1).replace(0,np.nan)
    return sig.div(g,axis=0).fillna(0)

def compute_signals():
    panels = load_panels("1d")
    if not panels: return {}, None
    if "quote_volume" not in panels: log.error("No QV"); return {}, None
    QV = panels["quote_volume"]
    liq = QV.rank(axis=1, ascending=False) <= 100
    ens = None
    for a in ALPHAS:
        w = _compute_factor(a["name"], panels, liq)
        if w is None: continue
        weighted = w * a["weight"]
        ens = weighted if ens is None else ens.add(weighted, fill_value=0)
    if ens is None: return {}, None
    last = ens.iloc[-1].dropna()
    top = last.abs().sort_values(ascending=False).head(TOP_N)
    last = last.reindex(top.index)
    if EQUAL_WEIGHT:
        dirs = np.sign(last); n = len(last)
        if n > 0: last = dirs * (GROSS_TARGET / n)
    data_date = str(panels["close"].index[-1])
    data_dt = pd.Timestamp(data_date)
    now_utc = pd.Timestamp.now(tz="UTC")
    if (data_dt.tz_localize("UTC") if data_dt.tz is None else data_dt) >= now_utc.normalize():
        return {}, data_date
    positions = {s: round(float(v),8) for s,v in last.items() if abs(v)>1e-6}
    log.info(f"  Signal: {len(positions)} pos")
    return positions, data_date

def init_exchange():
    ex = ccxt.binance({"apiKey": os.getenv("BINANCE_API_KEY"), "secret": os.getenv("BINANCE_API_SECRET"),
                        "options": {"defaultType": "future"}, "enableRateLimit": True})
    ex.set_sandbox_mode(False); return ex

def resolve_symbol(sym, mi):
    base = sym.replace("USDT","") if sym.endswith("USDT") else sym
    for c in [f"{base}/USDT:USDT"]:
        if c in mi: return c
    return None

def round_qty(qty, step):
    if step <= 0: return qty
    p = max(0,-int(np.floor(np.log10(step))))
    return round(np.floor(qty/step)*step, p)

def rebalance(ex, target, capital):
    markets = ex.load_markets()
    mi = {s:m for s,m in markets.items() if (m.get("future") or m.get("swap")) and m.get("active") and ":USDT" in s and "USDT-" not in s}
    positions = ex.fetch_positions()
    current = {}
    for p in positions:
        if abs(float(p["contracts"])) > 0:
            current[p["symbol"]] = {"amount": float(p["contracts"])*(1 if p["side"]=="long" else -1),
                "notional": abs(float(p.get("notionalValue") or p.get("notional") or 0))}
    sym_map = {s: resolve_symbol(s, mi) for s in target}; sym_map = {k:v for k,v in sym_map.items() if v}
    all_s = set(sym_map.values()) | set(current.keys())
    tickers = ex.fetch_tickers(list(all_s)) if all_s else {}
    prices = {s: float(tickers[s]["last"]) for s in all_s if s in tickers and tickers[s].get("last")}
    orders = []
    for sym, weight in target.items():
        csym = sym_map.get(sym)
        if not csym or csym not in prices: continue
        m = mi.get(csym, {}); price = prices[csym]
        tn = abs(weight)*capital
        if tn < MIN_NOTIONAL: continue
        qs = float(m.get("precision",{}).get("amount",0.001) or 0.001)
        tq = round_qty(tn/price, qs)
        ca = current.get(csym,{}).get("amount",0)
        ta = tq if weight>0 else -tq; diff = ta-ca
        if abs(diff)*price < MIN_NOTIONAL: continue
        orders.append({"symbol":csym,"side":"buy" if diff>0 else "sell","qty":round_qty(abs(diff),qs),"notional":abs(diff)*price})
    for sym in current:
        if sym not in sym_map.values() and abs(current[sym]["amount"])>0:
            orders.append({"symbol":sym,"side":"sell" if current[sym]["amount"]>0 else "buy","qty":abs(current[sym]["amount"]),"notional":current[sym]["notional"]})
    if DRY_RUN:
        for o in orders: log.info(f"  [DRY] {o['side']} {o['qty']} {o['symbol']}")
        return
    executed = 0
    for o in orders:
        try:
            try: ex.set_leverage(LEVERAGE, o["symbol"])
            except: pass
            ex.create_order(symbol=o["symbol"],type="market",side=o["side"],amount=o["qty"])
            log.info(f"  OK: {o['side']} {o['symbol']}"); executed += 1; time.sleep(0.1)
        except Exception as e: log.error(f"  FAIL: {o['symbol']} — {e}")
    log.info(f"  Executed: {executed}/{len(orders)}")

def main():
    log.info(f"Trader starting — DRY={DRY_RUN}")
    ex = init_exchange()
    bal = ex.fetch_balance()
    wallet = float(bal["total"].get("USDT",0))
    log.info(f"Balance: ${wallet:.2f}")
    last_dd = None
    while True:
        try:
            target, dd = compute_signals()
            if not target: time.sleep(300); continue
            if dd == last_dd: time.sleep(REBALANCE_INTERVAL); continue
            bal = ex.fetch_balance()
            for a in bal.get("info",{}).get("assets",[]):
                if a.get("asset")=="USDT": wallet=float(a.get("walletBalance",wallet)); break
            merged_gross = sum(abs(v) for v in target.values())
            capital = wallet*(1-FREE_PCT)*LEVERAGE / merged_gross if merged_gross > 0 else wallet*(1-FREE_PCT)
            log.info(f"  Wallet: ${wallet:.2f} Capital: ${capital:.0f}")
            rebalance(ex, target, capital)
            last_dd = dd
            STATE_FILE.write_text(json.dumps({"last_rebalance":datetime.now(timezone.utc).isoformat(),"data_date":dd,"capital":capital},indent=2))
        except Exception as e: log.error(f"Error: {e}")
        time.sleep(REBALANCE_INTERVAL)

if __name__ == "__main__": main()
