"""
Genererar rapporten som committas tillbaka till repot.

Poängen: du ska kunna öppna GitHub och läsa vad som hänt utan att köra
något. Rapporten skrivs över varje körning, och git-historiken bevarar
alla tidigare versioner.
"""
from datetime import datetime, timezone

from . import config
from .store import connect


def build(screen: dict, actions: dict, perf: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pf = perf["portfolio"]
    L = []

    L.append(f"# Småbolagsrapport\n")
    L.append(f"*Genererad {now}*\n")

    # --- Portfölj ---
    L.append("## Portfölj\n")
    L.append(f"| | |")
    L.append(f"|---|---|")
    L.append(f"| Totalt värde | {pf['total']:,.0f} kr |")
    L.append(f"| Varav kontant | {pf['cash']:,.0f} kr |")
    L.append(f"| Avkastning | {pf['return_pct']:+.2f} % |")
    L.append(f"| Exponering | {pf['exposure_pct']:.0f} % (tak {config.MAX_EXPOSURE_PCT:.0f} %) |")
    L.append(f"| Öppna positioner | {pf['open_positions']} |")
    L.append("")

    # --- Dagens händelser ---
    fills = actions.get("fills", [])
    exits = actions.get("exits", [])
    placed = actions.get("placed", [])
    cancels = actions.get("cancels", [])

    L.append("## Dagens händelser\n")
    if not (fills or exits or placed or cancels):
        L.append("Inget hände. Det är normalt — de flesta ordrar ligger och väntar.\n")
    else:
        if exits:
            L.append("**Stängda positioner**\n")
            L.append("| Bolag | Anledning | Resultat | Dagar | Max motgång |")
            L.append("|---|---|---|---|---|")
            for e in exits:
                L.append(f"| {e['ticker']} | {e['reason']} | {e['pnl']:+.0f} kr | "
                         f"{e['days']} | {e['mae_pct']:.1f} % |")
            L.append("")
        if fills:
            L.append("**Nya positioner**\n")
            L.append("| Bolag | Pris | Antal | Mål |")
            L.append("|---|---|---|---|")
            for f in fills:
                L.append(f"| {f['ticker']} | {f['price']:.2f} | {f['shares']:.0f} | "
                         f"{f['target']:.2f} |")
            L.append("")
        if placed:
            L.append(f"**{len(placed)} nya köpordrar lagda**\n")
            L.append("| Bolag | Limitpris | Antal |")
            L.append("|---|---|---|")
            for p in placed[:15]:
                L.append(f"| {p['ticker']} | {p['limit_price']:.2f} | {p['shares']} |")
            if len(placed) > 15:
                L.append(f"| ... | +{len(placed)-15} till | |")
            L.append("")
        if cancels:
            L.append(f"**{len(cancels)} ordrar togs bort** (inte fyllda i tid)\n")

    # --- Resultat ---
    L.append("## Resultat hittills\n")
    if perf.get("closed_trades", 0) == 0:
        L.append("Inga avslutade affärer än.\n")
    else:
        L.append("| | |")
        L.append("|---|---|")
        L.append(f"| Avslutade affärer | {perf['closed_trades']} |")
        L.append(f"| Resultat | {perf['total_pnl']:+,.0f} kr |")
        L.append(f"| Vinstandel | {perf['win_rate_pct']:.0f} % |")
        if perf.get("avg_win"):
            L.append(f"| Snittvinst | {perf['avg_win']:+,.0f} kr |")
        if perf.get("avg_loss"):
            L.append(f"| Snittförlust | {perf['avg_loss']:+,.0f} kr |")
        if perf.get("profit_factor"):
            L.append(f"| Profit factor | {perf['profit_factor']} |")
        if perf.get("avg_days_held"):
            L.append(f"| Snitt hålltid | {perf['avg_days_held']:.0f} dagar |")
        L.append("")
        L.append("### Nyckeltal för strategin\n")
        L.append(f"**Fyllnadsgrad: {perf.get('fill_rate_pct')} %** — andelen ordrar "
                 "som blev affärer. Låg siffra är normalt: *\"de flesta ordrar blir "
                 "aldrig affärer\"*.\n")
        if perf.get("avg_mae_pct") is not None:
            L.append(f"**Genomsnittlig maximal motgång: {perf['avg_mae_pct']:.1f} %** "
                     "— hur långt ner positionerna gick innan de stängdes. Detta är "
                     "måttet på adverse selection: blir du systematiskt fylld precis "
                     "innan det fortsätter ner?\n")
        if perf.get("exit_reasons"):
            L.append("**Exit-orsaker:** " + ", ".join(
                f"{k} ({v})" for k, v in perf["exit_reasons"].items()) + "\n")
        if perf.get("note"):
            L.append(f"> {perf['note']}\n")

    # --- Screener ---
    cands = screen.get("candidates", [])
    L.append("## Screener\n")
    L.append(f"{len(cands)} av {screen.get('screened', 0)} bolag passar kriterierna.\n")
    if cands:
        L.append("| Bolag | Poäng | Dagligt spann | Eff. ratio | Omsättning | Kurs |")
        L.append("|---|---|---|---|---|---|")
        for c in cands[:20]:
            L.append(f"| {c['ticker']} | {c['score']:.2f} | "
                     f"{c['median_daily_range_pct']:.1f} % | "
                     f"{c['efficiency_ratio_60']} | "
                     f"{c['median_turnover_sek']:,.0f} kr | "
                     f"{c['last_close']:.2f} |")
        L.append("")
        warned = [c for c in cands if c.get("warning")]
        if warned:
            L.append("### Varningar\n")
            for c in warned[:10]:
                L.append(f"- **{c['ticker']}**: {c['warning']}")
            L.append("")

    L.append("---\n")
    L.append("*Simulerad handel med låtsaspengar. Fyllnad antas bara när priset "
             "gick IGENOM limitnivån, inte när det nuddade den — det underskattar "
             "antalet affärer, vilket är rätt håll att fela på.*")

    return "\n".join(L)


def write(text: str):
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (config.REPORTS_DIR / "latest.md").write_text(text, encoding="utf-8")


def export_csv():
    """Positioner och ordrar som CSV, så du kan öppna dem i Excel."""
    import csv
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    with connect() as c:
        for table, fname in (("positions", "positions.csv"), ("orders", "orders.csv")):
            rows = c.execute(f"SELECT * FROM {table} ORDER BY id DESC").fetchall()
            if not rows:
                continue
            with open(config.REPORTS_DIR / fname, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(rows[0].keys())
                for r in rows:
                    w.writerow(list(r))


def telegram(text: str) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    try:
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text[:4000]},
            timeout=15,
        )
        return r.ok
    except Exception:
        return False
