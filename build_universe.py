"""
Bygger universe.txt / universe_us.txt automatiskt från bolagsnamn.

VARFÖR DET HÄR BEHÖVS:
Bolagsnamn -> ticker är inte förutsägbart. "Nordic Flanges Group" handlas
som NFGAB, "White Pearl Technology Group" som WPTG. Att gissa sig till
tickers från namnet ger fel resultat. Det här scriptet slår istället upp
varje bolag mot Yahoo Finance sök-API, som känner till både namn och
ticker.

TVÅ MARKNADER:
  --market se (standard): läser company_names.txt, kräver .ST-suffix,
      skriver universe.txt. Det här är First North-listan.
  --market us: läser company_names_us.txt, kräver Nasdaq/NYSE (INTE
      OTC/Pink Sheets — se motivering i README), skriver universe_us.txt.

ANVÄNDNING:
    python build_universe.py                 (svenska marknaden)
    python build_universe.py --market us      (amerikanska marknaden)

Bolag som inte gick att slå upp eller inte matchade rätt marknad hamnar
i unresolved.txt / unresolved_us.txt så du kan slå upp dem manuellt.

Detta körs separat från paper-motorn eftersom det bara behöver göras om
när bolagslistan ändras — inte varje dag.
"""
import argparse
import sys
import time
import json
import urllib.request
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).parent
SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}

MARKET_SETTINGS = {
    "se": {
        "names_file": ROOT / "company_names.txt",
        "universe_file": ROOT / "universe.txt",
        "unresolved_file": ROOT / "unresolved.txt",
        "label": "Sverige (First North)",
    },
    "us": {
        "names_file": ROOT / "company_names_us.txt",
        "universe_file": ROOT / "universe_us.txt",
        "unresolved_file": ROOT / "unresolved_us.txt",
        "label": "USA (Nasdaq/NYSE small cap)",
    },
}


def search_yahoo(name: str) -> list[dict]:
    """Frågar Yahoos sök-API efter en bolagsnamn-sträng."""
    params = urllib.parse.urlencode({"q": name, "quotesCount": 5, "newsCount": 0})
    req = urllib.request.Request(f"{SEARCH_URL}?{params}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data.get("quotes", [])
    except Exception as e:
        print(f"  fel vid sökning: {e}", file=sys.stderr)
        return []


def best_match_se(quotes: list[dict]) -> str | None:
    """Bästa träff som handlas på .ST (Stockholmsbörsen/First North)."""
    candidates = [
        q for q in quotes
        if q.get("symbol", "").endswith(".ST")
        and q.get("quoteType") == "EQUITY"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda q: len(q["symbol"]))
    return candidates[0]["symbol"]


def best_match_us(quotes: list[dict]) -> str | None:
    """
    Bästa träff på Nasdaq eller NYSE (INTE OTC/Pink Sheets).

    Yahoo taggar börs via `exchange`. De vanligaste koderna för de
    reglerade huvudlistorna är NMS/NGM/NCM (Nasdaq-varianter) och NYQ
    (NYSE) samt ASE (NYSE American). OTC-noteringar taggas ofta PNK
    eller OQB/OQX — de filtreras bort medvetet, se README för
    resonemanget kring varför Nasdaq/NYSE valdes först.
    """
    us_exchanges = {"NMS", "NGM", "NCM", "NYQ", "ASE"}
    candidates = [
        q for q in quotes
        if q.get("exchange") in us_exchanges
        and q.get("quoteType") == "EQUITY"
        # Inget suffix (t.ex. inte "AAPL.MX") — vill ha den amerikanska
        # primärnoteringen, inte en utländsk sekundärnotering av samma bolag
        and "." not in q.get("symbol", "")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda q: len(q["symbol"]))
    return candidates[0]["symbol"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["se", "us"], default="se",
                    help="vilken marknad som ska byggas (standard: se)")
    args = ap.parse_args()

    settings = MARKET_SETTINGS[args.market]
    names_file = settings["names_file"]
    universe_file = settings["universe_file"]
    unresolved_file = settings["unresolved_file"]

    if not names_file.exists():
        print(f"Skapa {names_file} med ett bolagsnamn per rad först.")
        sys.exit(1)

    names = [n.strip() for n in names_file.read_text(encoding="utf-8").splitlines()
              if n.strip() and not n.strip().startswith("#")]

    matcher = best_match_se if args.market == "se" else best_match_us

    resolved = []
    unresolved = []

    print(f"Bygger universum: {settings['label']}")
    print(f"{len(names)} bolagsnamn att slå upp\n")

    for i, name in enumerate(names, 1):
        quotes = search_yahoo(name)
        ticker = matcher(quotes)
        if ticker:
            resolved.append((name, ticker))
            print(f"[{i}/{len(names)}] {name} -> {ticker}")
        else:
            unresolved.append(name)
            print(f"[{i}/{len(names)}] {name} -> INGEN TRÄFF")
        time.sleep(0.3)  # snäll mot Yahoos API

    with open(universe_file, "w", encoding="utf-8") as f:
        f.write(f"# Auto-genererad av build_universe.py --market {args.market}\n")
        f.write("# Kör 'python run_daily.py --market "
                f"{args.market}' för att hämta data och se vilka som\n")
        f.write("# faktiskt har tillräcklig historik och omsättning.\n\n")
        for name, ticker in resolved:
            if args.market == "se":
                base = ticker.removesuffix(".ST")
                f.write(f"{base}  # {name}\n")
            else:
                f.write(f"{ticker}  # {name}\n")

    if unresolved:
        with open(unresolved_file, "w", encoding="utf-8") as f:
            f.write("# Bolag som inte gick att matcha automatiskt.\n")
            f.write("# Slå upp tickern manuellt och lägg till i "
                    f"{universe_file.name} om du vill ha med dem.\n\n")
            for name in unresolved:
                f.write(f"{name}\n")

    print(f"\nKlart: {len(resolved)} matchade, {len(unresolved)} omatchade.")
    print(f"Skrev {universe_file}")
    if unresolved:
        print(f"Omatchade bolag i {unresolved_file}")


if __name__ == "__main__":
    main()
