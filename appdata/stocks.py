"""The stock list for the app's search and Explore tab: every NSE stock with its industry, the indices it is in,
its F&O lot (if it has futures) and its Upstox page.

Index lists come from NSE's index files (niftyindices.com), refreshed once a month (owner OK, 27 Nov); an index
that fails to download keeps last month's list. Upstox's stock page opens by ISIN (the name part of the address
is only for reading), so the link is built from the name and the ISIN.
"""

import csv
import gzip
import io
import json
import re

from core import http

INDEX_URL = "https://www.niftyindices.com/IndexConstituent/{}"
INDEX_FILES = {
    "Nifty 50": "ind_nifty50list.csv", "Nifty Next 50": "ind_niftynext50list.csv", "Nifty 100": "ind_nifty100list.csv",
    "Nifty 200": "ind_nifty200list.csv", "Nifty 500": "ind_nifty500list.csv", "Bank Nifty": "ind_niftybanklist.csv",
    "Fin Nifty": "ind_niftyfinancelist.csv", "Midcap 150": "ind_niftymidcap150list.csv",
    "Smallcap 250": "ind_niftysmallcap250list.csv", "IT": "ind_niftyitlist.csv", "Pharma": "ind_niftypharmalist.csv",
    "Auto": "ind_niftyautolist.csv", "FMCG": "ind_niftyfmcglist.csv", "Metal": "ind_niftymetallist.csv",
    "PSU Bank": "ind_niftypsubanklist.csv", "Realty": "ind_niftyrealtylist.csv", "Energy": "ind_niftyenergylist.csv",
}


def upstox_link(name, isin):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().replace("&", " and ")).strip("-")
    return f"https://upstox.com/stocks/{slug}/{isin}"  # isolation-ok: Upstox's public site, not an old resource


def parse_index_csv(text):
    """[{symbol, name, industry, isin}] from an NSE index file."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "Symbol" not in rows[0] or "ISIN Code" not in rows[0]:
        raise ValueError("not an NSE index file")
    return [{"symbol": r["Symbol"].strip(), "name": r["Company Name"].strip(), "industry": r["Industry"].strip(),
             "isin": r["ISIN Code"].strip()} for r in rows if r.get("Symbol")]


def index_lists(last, month, fetch=http.request, files=INDEX_FILES):
    """{month, lists: {index: [...]}, failed}: last month's book unchanged within the same month."""
    if last and last.get("month") == month:
        return last
    old = (last or {}).get("lists") or {}
    lists, failed = {}, []
    for index, name in files.items():
        try:
            lists[index] = parse_index_csv(fetch("GET", INDEX_URL.format(name), timeout=25).decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001 - one index failing keeps its old list; the others still refresh
            failed.append(index)
            if index in old:
                lists[index] = old[index]
    return {"month": month, "lists": lists, "failed": failed}


def fo_lots(gz_bytes, symbols):
    """{symbol: lot size of its nearest stock future} from Upstox's NSE instrument file."""
    near = {}
    for r in json.loads(gzip.decompress(gz_bytes)):
        s = r.get("underlying_symbol")
        if r.get("segment") == "NSE_FO" and r.get("instrument_type") == "FUT" and s in symbols:
            if s not in near or r["expiry"] < near[s][0]:
                near[s] = (r["expiry"], r["lot_size"])
    return {s: lot for s, (_, lot) in near.items()}


def stock_list(eq, lists, lots):
    """[{s, n, ind, ix, lot?, u}] for every NSE stock (short keys: the phone downloads this file)."""
    info, member = {}, {}
    for index, rows in lists.items():
        for r in rows:
            info.setdefault(r["symbol"], r)
            member.setdefault(r["symbol"], []).append(index)
    out = []
    for sym, e in sorted(eq.items()):
        known = info.get(sym)
        name = known["name"] if known else (e.get("name") or sym).title()
        row = {"s": sym, "n": name, "ind": known["industry"] if known else None, "ix": member.get(sym, [])}
        if sym in lots:
            row["lot"] = lots[sym]
        row["u"] = upstox_link(name, e["isin"])
        out.append(row)
    return out
