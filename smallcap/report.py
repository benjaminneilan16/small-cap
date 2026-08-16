"""
Genererar rapporten som committas tillbaka till repot.

SE och US far separata rapportfiler (latest.md / latest_us.md).
"""
from datetime import datetime, timezone

from . import config
from .store import connect


def build(screen: dict, actions: dict, perf: dict, market: str = "se") -> str:
    cfg = config.get_config(market)
    cur = cfg.currency
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pf = perf["portfolio"]
    L = []

    L.append(f"# Smabolagsrapport — {cfg.label}\n")
    L.append(f"*Genererad {now}*\n")

    L.append("## Portfolj\n")
    L.append(f"| | |")
    L.append(f"|---|---|")
    L.append(f"| Totalt varde | {pf['total']:,.0f} {cur} |")
    L.append(f"| Varav kontant | {pf['cash']:,.0f} {cur} |")
    L.append(f"| Avkastning | {pf['return_pct']:+.2f} % |")
    L.append(f"| Exponering | {pf['exposure_pct']:.0f} % (tak {cfg.max_exposure_pct:.0f} %) |")
    L.append(f"| Kapital i vila | {pf['idle_capital_pct']:.0f} % |")
    L.append(f"| Oppna positioner | {pf['open_positions']} |")
    L.append("")

    near_cap = pf['exposure_pct'] >= cfg.max_exposure_pct * 0.9
    if near_cap:
        L.append(f"> Exponeringen ({pf['exposure_pct']:.0f} %) ligger nara taket "
                 f"({cfg.max_exposure_pct:.0f} %). Fa eller inga nya ordrar laggs "
                 "forran positioner stangs och frigor kapital.\n")

    fills = actions.get("fills", [])
    exits = actions.get("exits", [])
    placed = actions.get("placed", [])
    cancels = actions.get("cancels", [])

    L.append("## Dagens handelser\n")
    if not (fills or exits or placed or cancels):
        L.append("Inget hande. Det ar normalt — de flesta ordrar ligger och vantar.\n")
    else:
        if exits:
            L.append("**Stangda positioner**\n")
            L.append("| Bolag | Anledning | Resultat | Dagar | Max motgang |")
            L.append("|---|---|---|---|---|")
            for e in exits:
                L.append(f"| {e['ticker']} | {e['reason']} | {e['pnl']:+.0f} {cur} | "
                         f"{e['days']} | {e['mae_pct']:.1f} % |")
            L.append("")
        if fills:
            L.append("**Nya positioner**\n")
            L.append("| Bolag | Pris | Antal | Mal | Gap vid fyllnad |")
            L.append("|---|---|---|---|---|")
            for f in fills:
                gap_flag = " ⚠️" if f.get("gap_warning") else ""
                L.append(f"| {f['ticker']} | {f['price']:.2f} | {f['shares']:.0f} | "
                         f"{f['target']:.2f} | {f.get('gap_pct', 0):.1f} %{gap_flag} |")
            gap_warned = [f for f in fills if f.get("gap_warning")]
            if gap_warned:
                L.append("")
                L.append(f"⚠️ {len(gap_warned)} fyllnad(er) hade ett ovanligt stort gap "
                         f"(> {cfg.fill_gap_warning_pct:.0f} %) mellan limitpris och "
                         "dagens lagsta — kan betyda att aktien gappade ner kraftigt "
                         "snarare an att studsa vid en sund niva.")
            L.append("")
        if placed:
            L.append(f"**{len(placed)} nya kopordrar lagda**\n")
            L.append("| Bolag | Limitpris | Antal |")
            L.append("|---|---|---|")
            for p in placed[:15]:
                L.append(f"| {p['ticker']} | {p['limit_price']:.2f} | {p['shares']} |")
            if len(placed) > 15:
                L.append(f"| ... | +{len(placed)-15} till | |")
            L.append("")
        if cancels:
            L.append(f"**{len(cancels)} ordrar togs bort** (inte fyllda i tid)\n")

    L.append("## Resultat hittills\n")
    if perf.get("closed_trades", 0) == 0:
        L.append("Inga avslutade affarer an.\n")
    else:
        L.append("| | |")
        L.append("|---|---|")
        L.append(f"| Avslutade affarer | {perf['closed_trades']} |")
        L.append(f"| Resultat | {perf['total_pnl']:+,.0f} {cur} |")
        L.append(f"| Vinstandel | {perf['win_rate_pct']:.0f} % |")
        if perf.get("avg_win"):
            L.append(f"| Snittvinst | {perf['avg_win']:+,.0f} {cur} |")
        if perf.get("avg_loss"):
            L.append(f"| Snittforlust | {perf['avg_loss']:+,.0f} {cur} |")
        if perf.get("profit_factor"):
            L.append(f"| Profit factor | {perf['profit_factor']} |")
        if perf.get("avg_days_held"):
            L.append(f"| Snitt halltid | {perf['avg_days_held']:.0f} dagar |")
        L.append("")
        L.append("### Nyckeltal for strategin\n")
        L.append(f"**Fyllnadsgrad: {perf.get('fill_rate_pct')} %** — andelen ordrar "
                 "som blev affarer. Lag siffra ar normalt.\n")
        if perf.get("avg_mae_pct") is not None:
            L.append(f"**Genomsnittlig maximal motgang: {perf['avg_mae_pct']:.1f} %** "
                     "— hur langt ner positionerna gick innan de stangdes.\n")
        if perf.get("avg_gap_pct") is not None:
            L.append(f"**Genomsnittligt gap vid fyllnad: {perf['avg_gap_pct']:.1f} %** "
                     f"— {perf.get('large_gap_fills', 0)} fyllnad(er) hade ett gap over "
                     f"{cfg.fill_gap_warning_pct:.0f} %.\n")
        if perf.get("exit_reasons"):
            L.append("**Exit-orsaker:** " + ", ".join(
                f"{k} ({v})" for k, v in perf["exit_reasons"].items()) + "\n")
        if perf.get("note"):
            L.append(f"> {perf['note']}\n")

    cands = screen.get("candidates", [])
    L.append("## Screener\n")
    L.append(f"{len(cands)} av {screen.get('screened', 0)} bolag passar kriterierna.\n")
    if cands:
        L.append(f"| Bolag | Poang | Dagligt spann | Eff. ratio | Omsattning | Kurs | |")
        L.append("|---|---|---|---|---|---|---|")
        for c in cands[:20]:
            spike_flag = " 📊" if c.get("volume_spike") else ""
            news_flag = " 📰" if c.get("news") else ""
            L.append(f"| {c['ticker']} | {c['score']:.2f} | "
                     f"{c['median_daily_range_pct']:.1f} % | "
                     f"{c['efficiency_ratio_60']} | "
                     f"{c['median_turnover']:,.0f} {cur} | "
                     f"{c['last_close']:.2f} |{spike_flag}{news_flag} |")
        L.append("")
        warned = [c for c in cands if c.get("warning")]
        if warned:
            L.append("### Varningar\n")
            for c in warned[:10]:
                L.append(f"- **{c['ticker']}**: {c['warning']}")
            L.append("")

        spiked = [c for c in cands if c.get("volume_spike")]
        if spiked:
            L.append("### 📊 Volymspikar (mojlig nyhetshandelse)\n")
            L.append(
                "Onormal volym kombinerat med stort prisfall — kan betyda att "
                "nagot hant snarare an normal oscillation.\n"
            )
            for c in spiked[:10]:
                vs = c["volume_spike"]
                L.append(f"- **{c['ticker']}**: {vs['volume_ratio']:.1f}x normal "
                         f"volym, {vs['price_change_pct']:+.1f} % samma dag")
            L.append("")

        newsy = [c for c in cands if c.get("news")]
        if newsy:
            L.append("### 📰 Farska nyheter (senaste dygnet)\n")
            L.append(
                "Verifierat relevanta nyhetsartiklar for dessa bolag senaste "
                "dygnet — en grov signal, inte en bedomning av om nyheten ar "
                "bra eller dalig. Las sjalv innan du litar pa fyndet.\n"
            )
            for c in newsy[:10]:
                n = c["news"]
                extra = f" (+{n['article_count']-1} till)" if n["article_count"] > 1 else ""
                L.append(f"- **{c['ticker']}**: \"{n['latest_title']}\" "
                         f"— {n['latest_publisher']}{extra}")
            L.append("")

    L.append("---\n")
    L.append("*Simulerad handel med latsaspengar. Fyllnad antas bara nar priset "
             "gick IGENOM limitnivan, inte nar det nuddade den.*")

    return "\n".join(L)


def build_morning_summary(status: dict, market: str = "se") -> str:
    """
    Kort statustext for morgonkollen.
    """
    cfg = config.get_config(market)
    pf = status.get("portfolio", {})
    lines = [f"☀️ Morgonkoll {cfg.label}"]
    if pf:
        lines.append(f"{pf.get('total', 0):,.0f} {cfg.currency} "
                     f"({pf.get('return_pct', 0):+.2f} %)")
    lines.append(f"{status.get('checked', 0)} oppna kopordrar kollade")

    fills = status.get("fills", [])
    if not fills:
        lines.append("Inget nytt sen igar.")
        return "\n".join(lines)

    lines.append(f"\n{len(fills)} fylld(a) i oppningsauktionen:")
    for f in fills:
        flag = " ⚠️ stort gap" if f.get("gap_warning") else ""
        lines.append(f"  {f['ticker']} @ {f['price']:.2f}{flag}")

    large_gaps = [f for f in fills if f.get("gap_warning")]
    if large_gaps:
        lines.append(
            f"\n{len(large_gaps)} av dem hade ovanligt stort gap."
        )

    return "\n".join(lines)


def build_midday_summary(market: str = "se") -> str:
    """
    Kort "lever"-statuskoll mitt pa dagen.
    """
    from . import paper
    cfg = config.get_config(market)
    pf = paper.portfolio(market)

    with connect(market) as c:
        open_orders = c.execute(
            "SELECT COUNT(*) n FROM orders WHERE status = 'open' AND side = 'buy'"
        ).fetchone()["n"]

    lines = [
        f"☀️ Mitt pa dagen — {cfg.label}",
        f"{pf['total']:,.0f} {cfg.currency} ({pf['return_pct']:+.2f} %)",
        f"{pf['open_positions']} oppna positioner, {open_orders} vantande ordrar",
        "(baserat pa senaste stangning — ingen ny data hamtad nu)",
    ]
    return "\n".join(lines)


def write(text: str, market: str = "se"):
    cfg = config.get_config(market)
    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    (cfg.reports_dir / cfg.report_file).write_text(text, encoding="utf-8")


def export_csv(market: str = "se"):
    """Positioner och ordrar som CSV."""
    import csv
    cfg = config.get_config(market)
    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if market == "se" else "_us"

    with connect(market) as c:
        for table, fname in (("positions", f"positions{suffix}.csv"),
                              ("orders", f"orders{suffix}.csv")):
            rows = c.execute(f"SELECT * FROM {table} ORDER BY id DESC").fetchall()
            if not rows:
                continue
            with open(cfg.reports_dir / fname, "w", newline="", encoding="utf-8") as f:
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
