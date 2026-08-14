"""
Bygger universe.txt automatiskt från en lista First North-bolagsnamn.

VARFÖR DET HÄR BEHÖVS:
Bolagsnamn -> ticker är inte förutsägbart. "Nordic Flanges Group" handlas
som NFGAB, "White Pearl Technology Group" som WPTG. Att gissa sig till
tickers från namnet ger fel resultat. Det här scriptet slår istället upp
varje bolag mot Yahoo Finance sök-API, som känner till både namn och
ticker, och behåller bara träffar som faktiskt är listade i Stockholm
(.ST) och har riktig kursdata.

ANVÄNDNING:

    python build_universe.py

Läser namn från company_names.txt (en per rad), skriver resultatet till
universe.txt. Bolag som inte gick att slå upp eller sakna .ST-notering
hamnar i unresolved.txt så du kan slå upp dem manuellt om du vill.

Detta körs separat från paper-motorn eftersom det bara behöver göras om
när First North-listan ändras — inte varje dag.
"""
import sys
import time
import json
import urllib.request
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).parent
NAMES_FILE = ROOT / "company_names.txt"
UNIVERSE_FILE = ROOT / "universe.txt"
UNRESOLVED_FILE = ROOT / "unresolved.txt"

SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}


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


def best_st_match(name: str, quotes: list[dict]) -> str | None:
    """
    Väljer bästa träff som handlas på .ST (Stockholmsbörsen/First North).

    Föredrar EQUITY-typ och kortare symboler (undviker warranter,
    teckningsrätter etc. som ofta har längre suffix).
    """
    candidates = [
        q for q in quotes
        if q.get("symbol", "").endswith(".ST")
        and q.get("quoteType") == "EQUITY"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda q: len(q["symbol"]))
    return candidates[0]["symbol"]


def main():
    if not NAMES_FILE.exists():
        print(f"Skapa {NAMES_FILE} med ett bolagsnamn per rad först.")
        sys.exit(1)

    names = [n.strip() for n in NAMES_FILE.read_text(encoding="utf-8").splitlines()
              if n.strip() and not n.strip().startswith("#")]

    resolved = []
    unresolved = []

    for i, name in enumerate(names, 1):
        quotes = search_yahoo(name)
        ticker = best_st_match(name, quotes)
        if ticker:
            resolved.append((name, ticker))
            print(f"[{i}/{len(names)}] {name} -> {ticker}")
        else:
            unresolved.append(name)
            print(f"[{i}/{len(names)}] {name} -> INGEN TRÄFF")
        time.sleep(0.3)  # snäll mot Yahoos API

    with open(UNIVERSE_FILE, "w", encoding="utf-8") as f:
        f.write("# Auto-genererad av build_universe.py från First North-listan.\n")
        f.write("# Kör 'python run_daily.py' för att hämta data och se vilka\n")
        f.write("# som faktiskt har tillräcklig historik och omsättning.\n\n")
        for name, ticker in resolved:
            base = ticker.removesuffix(".ST")
            f.write(f"{base}  # {name}\n")

    if unresolved:
        with open(UNRESOLVED_FILE, "w", encoding="utf-8") as f:
            f.write("# Bolag som inte gick att matcha automatiskt.\n")
            f.write("# Slå upp tickern manuellt (t.ex. på Avanza) och lägg\n")
            f.write("# till i universe.txt om du vill ha med dem.\n\n")
            for name in unresolved:
                f.write(f"{name}\n")

    print(f"\nKlart: {len(resolved)} matchade, {len(unresolved)} omatchade.")
    print(f"Skrev {UNIVERSE_FILE}")
    if unresolved:
        print(f"Omatchade bolag i {UNRESOLVED_FILE}")


if __name__ == "__main__":
    main()
