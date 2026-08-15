"""
Paper trading för spread-strategin.

DEN AVGÖRANDE FRÅGAN: blev limitordern fylld?

Vi har bara dagliga staplar. Vi vet att priset var nere på 10,00 någon
gång under dagen — men inte om DIN order på 10,00 blev fylld. Det beror
på kön, på hur mycket som handlades där, och på om det fanns en motpart.

Gissar vi optimistiskt får vi samma sorts falska resultat som en dålig
backtest. Skillnaden är att felet här kan vara skillnaden mellan +50%
och -10%.

TRE KONSERVATIVA REGLER:

1. FILL KRÄVER GENOMBROTT, INTE BERÖRING
   Köporder på 10,00 fylls bara om dagens LÄGSTA gick UNDER 10,00.
   Nuddade priset exakt nivån räknas det inte — du kan ha legat sist
   i kön. Det underskattar antalet fills, vilket är rätt håll att fela på.

2. INGEN RUNDTUR SAMMA DAG
   Med dagliga staplar vet vi inte om lägsta kom före högsta. En position
   som öppnas dag N kan tidigast stängas dag N+1.

3. VID TVEKSAMHET, ANTA DET SÄMRE
   Nåddes både stop loss och vinstmål samma dag antar vi stop loss,
   eftersom vi inte vet ordningen.

VAD MODELLEN INTE KAN FÅNGA: adverse selection. När din köporder blir
fylld i ett litet bolag är det ofta för att någon säljer av ett skäl du
inte känner till. Vi kan inte modellera det — men vi MÄTER det via MAE
(maximal motgång), som visar hur långt ner positionerna gick innan de
stängdes.

GAP VID FYLLNAD (nytt): utöver MAE mäter vi också hur stort gap som
fanns MELLAN limitpriset och dagens faktiska lägsta när ordern fylldes.
Ett litet gap (dagens låga precis under limiten) är en sund studs —
precis vad strategin jagar. Ett stort gap (dagens låga långt under
limiten) kan betyda att aktien gappade ner kraftigt, t.ex. vid öppning
på dåliga nyheter, och att du blev fylld mitt i ett fall snarare än vid
en naturlig nivå. Detta flaggas i rapporten, inte som ett hårt filter —
det är information för dig att väga in, inte en regel som stoppar affären.
"""
import logging
from datetime import datetime, timezone, date

from .store import connect, get_bars, get_cash, init_account
from . import config

logger = logging.getLogger("paper")


def commission(value: float, market: str = "se") -> float:
    cfg = config.get_config(market)
    return max(value * cfg.commission_pct / 100, cfg.commission_min)


def portfolio(market: str = "se") -> dict:
    cfg = config.get_config(market)
    cash = get_cash(market)
    with connect(market) as c:
        rows = c.execute(
            "SELECT ticker, shares, entry_price FROM positions WHERE status = 'open'"
        ).fetchall()
        acc = c.execute("SELECT starting_capital FROM account WHERE id = 1").fetchone()

    market_value = 0.0
    for r in rows:
        bars = get_bars(r["ticker"], 1, market)
        price = float(bars[-1]["close"]) if bars else float(r["entry_price"])
        market_value += price * float(r["shares"])

    start = float(acc["starting_capital"]) if acc else cfg.starting_capital
    total = cash + market_value
    idle_pct = round(cash / total * 100, 1) if total else 0

    return {
        "cash": round(cash, 2),
        "market_value": round(market_value, 2),
        "total": round(total, 2),
        "starting_capital": start,
        "return_pct": round((total - start) / start * 100, 2) if start else 0,
        "exposure_pct": round(market_value / total * 100, 1) if total else 0,
        # Andel av kapitalet som INTE är investerat just nu. Enligt
        # Folcke är detta en medveten del av strategin, inte spillo:
        # "en stor del av kapitalet aldrig fullt investerat" fungerade
        # som en krockkudde vid covid-raset.
        "idle_capital_pct": idle_pct,
        "open_positions": len(rows),
    }


def place_orders(candidates: list[dict], market: str = "se") -> list[dict]:
    """
    Lägger köporder UNDER marknaden.

    "Jag håller mig där köparna ligger" — priset måste komma ner till dig.
    Ordern läggs vid närmaste starka nivå under senaste kurs, om det
    finns en. Annars en fast procentsats under.

    EXPONERINGSTAKET GÄLLER STRIKT: kollas en gång innan loopen (mot
    portföljens nuvarande exponering) och sedan implicit vid varje
    orderläggning eftersom nytt kapital binds i shares — men taket
    kontrolleras INTE på nytt inne i loopen mot framtida exponering
    efter att flera ordrar lagts. Se _would_exceed_exposure för det.
    """
    cfg = config.get_config(market)
    init_account(cfg.starting_capital, market)
    pf = portfolio(market)
    today = datetime.now(timezone.utc).date().isoformat()

    with connect(market) as c:
        open_count = c.execute(
            "SELECT COUNT(*) n FROM orders WHERE status = 'open' AND side = 'buy'"
        ).fetchone()["n"]
        held = {r["ticker"] for r in c.execute(
            "SELECT ticker FROM positions WHERE status = 'open'").fetchall()}
        pending = {r["ticker"] for r in c.execute(
            "SELECT ticker FROM orders WHERE status = 'open' AND side = 'buy'").fetchall()}

    # Exponeringstaket gäller även planerade köp
    if pf["exposure_pct"] >= cfg.max_exposure_pct:
        logger.info("Exponering %.0f%% vid taket — inga nya ordrar",
                    pf["exposure_pct"])
        return []

    # Simulerad exponering: växer i minnet medan vi lägger ordrar, så att
    # vi aldrig kan lägga så många ordrar på en gång att taket bryts även
    # om alla skulle fyllas direkt. Detta var tidigare bara kollat en
    # gång innan loopen — nu kollas det strikt vid varje ny order också.
    simulated_value_committed = 0.0

    placed = []
    for cand in candidates:
        if open_count >= cfg.max_open_orders:
            break
        ticker = cand["ticker"]
        if ticker in held or ticker in pending:
            continue

        bars = get_bars(ticker, 5, market)
        if not bars:
            continue
        last_close = float(bars[-1]["close"])

        below = [l["price"] for l in cand.get("top_levels", [])
                 if l["price"] < last_close]
        if below:
            limit_price = max(below)
            floor = last_close * (1 - cfg.buy_below_pct * 2 / 100)
            limit_price = max(limit_price, floor)
        else:
            limit_price = last_close * (1 - cfg.buy_below_pct / 100)

        limit_price = round(limit_price, 4)
        value = pf["total"] * cfg.position_size_pct / 100
        shares = int(value / limit_price)
        if shares < 1:
            continue

        # Strikt tak-kontroll: skulle DENNA order (om den fylldes) ta
        # exponeringen över taket, givet allt vi redan planerat lägga
        # i den här körningen?
        prospective_value = pf["market_value"] + simulated_value_committed + (limit_price * shares)
        prospective_exposure = prospective_value / pf["total"] * 100 if pf["total"] else 0
        if prospective_exposure > cfg.max_exposure_pct:
            logger.info("Hoppar över %s — skulle ta exponeringen till %.0f%% (tak %.0f%%)",
                        ticker, prospective_exposure, cfg.max_exposure_pct)
            continue

        with connect(market) as c:
            c.execute(
                "INSERT INTO orders (ticker, side, limit_price, shares, placed_date) "
                "VALUES (?, 'buy', ?, ?, ?)",
                (ticker, limit_price, shares, today),
            )
        placed.append({"ticker": ticker, "limit_price": limit_price,
                       "shares": shares})
        open_count += 1
        simulated_value_committed += limit_price * shares

    return placed


def process(market: str = "se") -> dict:
    """Kollar fills, uppdaterar positioner, stänger dem som nått mål eller stop."""
    cfg = config.get_config(market)
    init_account(cfg.starting_capital, market)
    today = datetime.now(timezone.utc).date()
    fills, exits, cancels = [], [], []

    # --- Köpordrar ---
    with connect(market) as c:
        buy_orders = c.execute(
            "SELECT id, ticker, limit_price, shares, placed_date FROM orders "
            "WHERE status = 'open' AND side = 'buy'"
        ).fetchall()

    for o in buy_orders:
        bars = get_bars(o["ticker"], 30, market)
        after = [b for b in bars if b["date"] > o["placed_date"]]
        limit_price = float(o["limit_price"])

        filled = None
        for b in after:
            # KONSERVATIV REGEL: priset måste gå IGENOM nivån
            if float(b["low"]) < limit_price:
                filled = b
                break

        if filled:
            value = limit_price * float(o["shares"])
            comm = commission(value, market)
            if get_cash(market) < value + comm:
                _cancel(o["id"], "otillräckligt kapital", market)
                cancels.append({"ticker": o["ticker"], "reason": "kapital"})
                continue

            # Gap-flagga: hur långt under limitpriset gick dagens låga?
            # Litet gap = sund studs precis vid nivån. Stort gap = kan
            # betyda att aktien gappade ner kraftigt (t.ex. vid öppning)
            # och att fyllnaden skedde mitt i ett fall snarare än vid
            # en naturlig studs.
            day_low = float(filled["low"])
            gap_pct = round((limit_price - day_low) / limit_price * 100, 2)

            target = round(limit_price * (1 + cfg.target_profit_pct / 100), 4)
            with connect(market) as c:
                c.execute("UPDATE account SET cash = cash - ? WHERE id = 1",
                          (value + comm,))
                cur = c.execute(
                    "INSERT INTO positions (ticker, shares, entry_price, entry_date, "
                    "target_price, commission_paid, gap_pct) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (o["ticker"], o["shares"], limit_price, filled["date"],
                     target, comm, gap_pct),
                )
                pos_id = cur.lastrowid
                c.execute(
                    "UPDATE orders SET status = 'filled', filled_date = ?, "
                    "fill_price = ?, gap_pct = ?, position_id = ? WHERE id = ?",
                    (filled["date"], limit_price, gap_pct, pos_id, o["id"]),
                )
            fills.append({"ticker": o["ticker"], "price": limit_price,
                          "shares": float(o["shares"]), "target": target,
                          "date": filled["date"], "gap_pct": gap_pct,
                          "gap_warning": gap_pct > cfg.fill_gap_warning_pct})
        else:
            age = (today - date.fromisoformat(o["placed_date"])).days
            if age > cfg.order_ttl_days:
                _cancel(o["id"], f"inte fylld inom {cfg.order_ttl_days} dagar", market)
                cancels.append({"ticker": o["ticker"], "reason": "TTL"})

    # --- Öppna positioner ---
    with connect(market) as c:
        positions = c.execute(
            "SELECT id, ticker, shares, entry_price, entry_date, target_price, "
            "commission_paid FROM positions WHERE status = 'open'"
        ).fetchall()

    for p in positions:
        bars = get_bars(p["ticker"], 90, market)
        # KONSERVATIV REGEL: tidigast exit dagen EFTER entry
        after = [b for b in bars if b["date"] > p["entry_date"]]
        if not after:
            continue

        entry = float(p["entry_price"])
        target = float(p["target_price"])
        shares = float(p["shares"])
        stop = entry * (1 + cfg.stop_loss_pct / 100)

        # MAE: hur långt ner gick positionen? Måttet på adverse selection.
        mae = min((float(b["low"]) - entry) / entry * 100 for b in after)

        exit_bar = exit_price = reason = None
        for b in after:
            # Stop kollas FÖRST — nåddes båda samma dag antar vi det sämre
            if float(b["low"]) < stop:
                exit_bar, exit_price, reason = b, stop, "STOP LOSS"
                break
            if float(b["high"]) > target:
                exit_bar, exit_price, reason = b, target, "MÅL NÅTT"
                break

        if exit_bar:
            proceeds = exit_price * shares
            comm_out = commission(proceeds, market)
            pnl = proceeds - comm_out - (entry * shares) - float(p["commission_paid"])
            days = (date.fromisoformat(exit_bar["date"])
                    - date.fromisoformat(p["entry_date"])).days
            with connect(market) as c:
                c.execute("UPDATE account SET cash = cash + ? WHERE id = 1",
                          (proceeds - comm_out,))
                c.execute(
                    "UPDATE positions SET status = 'closed', exit_price = ?, "
                    "exit_date = ?, exit_reason = ?, realized_pnl = ?, mae_pct = ?, "
                    "days_held = ?, commission_paid = ? WHERE id = ?",
                    (exit_price, exit_bar["date"], reason, pnl, mae, days,
                     float(p["commission_paid"]) + comm_out, p["id"]),
                )
            exits.append({"ticker": p["ticker"], "price": exit_price,
                          "reason": reason, "pnl": round(pnl, 2),
                          "days": days, "mae_pct": round(mae, 2)})
        else:
            with connect(market) as c:
                c.execute("UPDATE positions SET mae_pct = ? WHERE id = ?",
                          (mae, p["id"]))

    return {"fills": fills, "exits": exits, "cancels": cancels}


def _cancel(order_id: int, reason: str, market: str = "se"):
    with connect(market) as c:
        c.execute("UPDATE orders SET status = 'cancelled', cancel_reason = ? "
                  "WHERE id = ?", (reason, order_id))


def performance(market: str = "se") -> dict:
    """
    Resultat, med fokus på det som avslöjar om strategin fungerar.

    Tre fält är viktigare än avkastningen:

      fill_rate_pct — andelen ordrar som blev affärer. Hon säger "de
                      flesta ordrar blir aldrig affärer", så en låg
                      siffra är NORMALT, inte ett fel.

      avg_mae_pct   — hur långt ner positionerna gick innan de stängdes.
                      Detta är måttet på adverse selection.

      avg_gap_pct   — hur stort gap som fanns vid fyllnad i snitt.
                      Ett stigande snitt över tid kan tyda på att
                      screenern allt oftare fångar fallande knivar
                      snarare än sunda studsar.
    """
    cfg = config.get_config(market)
    pf = portfolio(market)

    with connect(market) as c:
        closed = c.execute(
            "SELECT realized_pnl, days_held, exit_reason, mae_pct, gap_pct "
            "FROM positions WHERE status = 'closed'"
        ).fetchall()
        counts = {
            s: c.execute("SELECT COUNT(*) n FROM orders WHERE status = ?",
                         (s,)).fetchone()["n"]
            for s in ("open", "filled", "cancelled")
        }
        gap_rows = c.execute(
            "SELECT gap_pct FROM orders WHERE status = 'filled' AND gap_pct IS NOT NULL"
        ).fetchall()

    resolved = counts["filled"] + counts["cancelled"]
    fill_rate = round(counts["filled"] / resolved * 100, 1) if resolved else None

    gaps = [float(r["gap_pct"]) for r in gap_rows]
    avg_gap = round(sum(gaps) / len(gaps), 2) if gaps else None
    large_gaps = sum(1 for g in gaps if g > cfg.fill_gap_warning_pct)

    if not closed:
        return {"portfolio": pf, "orders": counts, "fill_rate_pct": fill_rate,
                "closed_trades": 0, "avg_gap_pct": avg_gap,
                "large_gap_fills": large_gaps,
                "note": "Inga avslutade affärer än."}

    pnls = [float(r["realized_pnl"]) for r in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    maes = [float(r["mae_pct"]) for r in closed if r["mae_pct"] is not None]
    days = [r["days_held"] for r in closed if r["days_held"] is not None]

    reasons = {}
    for r in closed:
        reasons[r["exit_reason"]] = reasons.get(r["exit_reason"], 0) + 1

    return {
        "portfolio": pf,
        "orders": counts,
        "fill_rate_pct": fill_rate,
        "closed_trades": len(closed),
        "total_pnl": round(sum(pnls), 2),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 1),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "profit_factor": (round(sum(wins) / abs(sum(losses)), 2)
                          if losses and sum(losses) else None),
        "avg_days_held": round(sum(days) / len(days), 1) if days else None,
        "avg_mae_pct": round(sum(maes) / len(maes), 2) if maes else None,
        "worst_mae_pct": round(min(maes), 2) if maes else None,
        "avg_gap_pct": avg_gap,
        "large_gap_fills": large_gaps,
        "exit_reasons": reasons,
        "note": _note(len(closed), reasons, maes),
    }


def _note(n: int, reasons: dict, maes: list) -> str:
    parts = []
    if n < 30:
        parts.append(f"Bara {n} avslutade affärer — för tidigt för slutsatser.")

    stops = reasons.get("STOP LOSS", 0)
    if n and stops / n > 0.3:
        parts.append(
            f"{stops} av {n} affärer stoppades ut. Hög andel tyder på adverse "
            "selection: du blir fylld när någon säljer av ett skäl du inte känner till."
        )

    if maes:
        avg = sum(maes) / len(maes)
        if avg < -8:
            parts.append(
                f"Genomsnittlig maximal motgång {avg:.1f}% — positionerna går djupt "
                "back innan de vänder. Det är market makings grundproblem."
            )

    return " ".join(parts) if parts else "Inget särskilt att notera."
