# Småbolagsstrategi — paper trading

Testar en spread-strategi på svenska och amerikanska småbolag med
låtsaspengar. Körs automatiskt varje dag via GitHub Actions. Ingen
server, ingen molndatabas, inga kostnader.

## Vad strategin gör

Letar efter småbolag med **breda spreadar och spretiga kurser** —
alltså precis det konventionell analys kallar dåligt. Lägger sedan
köpordrar under marknaden och säljordrar 5–10 % upp.

De flesta ordrar blir aldrig affärer. Med många ute samtidigt blir det
ändå avslut regelbundet.

## Två marknader, helt separata

Sverige (First North, `.ST`) och USA (Nasdaq/NYSE small cap) körs som
två parallella, helt isolerade instanser:

| | Sverige | USA |
|---|---|---|
| Bolagslista | `universe.txt` | `universe_us.txt` |
| Databas | `data/market_se.db` | `data/market_us.db` |
| Rapport | `reports/latest.md` | `reports/latest_us.md` |
| Valuta | kr | $ |
| Stängning (UTC) | 15:30/16:30 (sommar/vinter) | 20:00/21:00 (sommar/vinter) |

Kapital, positioner och ordrar blandas aldrig mellan marknaderna —
de ligger i separata SQLite-filer, inte bara filtrerade rader i samma
fil. Se `smallcap/config.py` för alla marknadsspecifika värden.

**Varför Nasdaq/NYSE och inte OTC/Pink Sheets för USA:** OTC-noteringar
matchar strategins profil bättre (mer illikvida, bredare spreadar),
men har generellt sämre datakvalitet i Yahoo Finance. Nasdaq/NYSE small
cap ($300M–$2B) valdes först för att verifiera att hela rörledningen
(screener, fill-logik, rapport) håller för en ny marknad, innan OTC
läggs till som nästa steg.

## Kom igång

### 1. Lägg upp på GitHub

Skapa ett nytt repo och ladda upp alla filer. Actions aktiveras automatiskt.

### 2. Testa direkt med backtest

Gå till **Actions** → **Daglig körning — Sverige** (eller **USA**) →
**Run workflow**.

Eller lokalt om du har Python:

```bash
pip install -r requirements.txt
python run_daily.py --backtest                # Sverige
python run_daily.py --backtest --market us     # USA
```

Backtestet spelar upp två års historik dag för dag och ger dig ett
första svar på minuter istället för månader.

### 3. Byt ut bolagen

`universe.txt` (Sverige) och `universe_us.txt` (USA) innehåller
startlistor. `universe_us.txt` har redan 400+ riktiga Nasdaq/NYSE
small-cap-tickers och går att använda direkt.

Vill du bygga om listorna från grunden (t.ex. när bolagslistan
ändrats), kör:

```bash
python build_universe.py              # Sverige — läser company_names.txt
python build_universe.py --market us  # USA — läser company_names_us.txt
```

Det slår upp varje bolagsnamn mot Yahoo Finance sök-API och behåller
bara träffar på rätt marknad. Bolag som inte gick att matcha hamnar i
`unresolved.txt` / `unresolved_us.txt`.

Suffixet `.ST` läggs på automatiskt för svenska tickers. Bolag utan
data markeras i rapporten — byt ut dem.

### 4. Läs resultatet

Rapporterna hamnar i `reports/latest.md` (SE) och `reports/latest_us.md`
(US), och uppdateras varje körning. Öppna dem på GitHub. Positioner och
ordrar finns även som CSV.

### 5. Telegram-notiser (valfritt)

Repo → **Settings** → **Secrets and variables** → **Actions** →
lägg till `TELEGRAM_BOT_TOKEN` och `TELEGRAM_CHAT_ID`. Delas mellan
båda marknaderna och morgonkollen.

## Morgonkoll (öppningsauktionen)

Utöver den fulla dagliga körningen (som sker efter stängning) finns en
lätt morgonkoll som körs strax efter öppning:

```bash
python run_morning.py              # Sverige, ~09:15 svensk tid
python run_morning.py --market us  # USA, ~09:45 ET (sommartid)
```

Den lägger **inga nya ordrar** och ändrar ingen strategi — den kollar
bara om något fyllts i öppningsauktionen och skickar en kort
Telegram-status. Tanken: öppningsauktionen kan skapa prisrörelser som
avviker kraftigt från gårdagens stängning (övernattnyheter, andra
marknaders utveckling), så det är värt att veta snabbt om något hände
innan resten av dagen — utan att göra om hela den dagliga analysen.

Körs automatiskt via `morning_se.yml` / `morning_us.yml`.

## Vad du ska titta på

Inte avkastningen först. Dessa mått säger mer:

**Fyllnadsgrad** — andelen ordrar som blev affärer. Låg siffra är
normalt för den här strategin, inte ett fel.

**Genomsnittlig maximal motgång (MAE)** — hur långt ner positionerna
gick innan de stängdes. Detta är måttet på *adverse selection*: blir du
systematiskt fylld precis innan det fortsätter ner?

**Genomsnittligt gap vid fyllnad** (nytt) — hur stort avstånd som fanns
mellan limitpriset och dagens faktiska lägsta när ordern fylldes. Ett
litet gap är en sund studs. Ett stort gap (flaggas med ⚠️ i rapporten
när det överstiger `FILL_GAP_WARNING_PCT`, standard 5 %) kan betyda att
aktien gappade ner kraftigt — t.ex. vid öppning på dåliga nyheter — och
att du blev fylld mitt i ett fall snarare än vid en naturlig nivå.

**Kapital i vila** (nytt) — andelen av portföljen som inte är
investerad just nu. Enligt Folcke är detta en medveten del av
strategin, inte spillo: en stor del av kapitalet ligger alltid still i
väntande ordrar, vilket fungerade som en krockkudde vid tidigare
börsfall.

**Slår den buy & hold?** Gör den inte det är komplexiteten inte värd
risken.

## Varför resultatet är konservativt

| Antagande | Varför |
|---|---|
| Fill kräver **genombrott**, inte beröring | Att priset nådde 10,00 betyder inte att din order fylldes — du kan ha legat sist i kön |
| Ingen rundtur samma dag | Med dagliga staplar vet vi inte om lägsta kom före högsta |
| Vid tveksamhet antas stop loss | Nåddes både mål och stop samma dag vet vi inte ordningen |
| Fill till limitpris, inte bättre | Gapar aktien ner får du egentligen bättre pris — vi antar det sämre |
| Exponeringstaket kollas strikt per order | Flera ordrar i samma körning kan inte tillsammans bryta taket, även om alla skulle fyllas direkt |

Modellen ska hellre underskatta än överskatta.

## Vad den inte kan fånga

**Om din order faktiskt hade fyllts.** I ett bolag som omsätter
100 000 kr (eller motsvarande i dollar) om dagen är det en verklig
osäkerhet.

**Överlevnadsbias i backtestet.** Universum består av bolag som finns
idag. De som avnoterats saknas — och det är precis de som hade skadat
strategin mest.

## Inställningar

Marknadsoberoende värden ändras i `smallcap/config.py` (modulnivå) eller
via miljövariabler. Marknadsspecifika värden (valuta, courtage,
omsättningströskel, handelstider) ligger i `MARKETS`-dictionaryn i
samma fil.

| Variabel | Standard | Betydelse |
|---|---|---|
| `STARTING_CAPITAL` | 50000 | Låtsaskapital (delas som startvärde för båda marknaderna) |
| `TARGET_PROFIT_PCT` | 7.0 | Vinstmål per affär |
| `POSITION_SIZE_PCT` | 2.0 | Andel av kapitalet per position |
| `MAX_EXPOSURE_PCT` | 30.0 | Tak för hur mycket som får vara investerat |
| `BUY_BELOW_PCT` | 4.0 | Hur långt under marknaden köpordern läggs |
| `STOP_LOSS_PCT` | -15.0 | Stop loss |
| `MIN_DAILY_RANGE_PCT` | 3.0 | Minsta dagliga spann för att godkännas |
| `MAX_EFFICIENCY_RATIO` | 0.30 | Över detta trendar aktien för mycket |
| `FILL_GAP_WARNING_PCT` | 5.0 | Gap vid fyllnad över detta flaggas i rapporten |

## Kommandon

```bash
# Daglig körning (efter stängning)
python run_daily.py                    # Sverige
python run_daily.py --market us        # USA
python run_daily.py --backtest         # spela upp historiken
python run_daily.py --reset            # nollställ kontot
python run_daily.py --no-orders        # uppdatera utan att lägga nya ordrar

# Morgonkoll (öppningsauktionen, inga nya ordrar)
python run_morning.py
python run_morning.py --market us

# Bygg om bolagslistan från namn
python build_universe.py
python build_universe.py --market us
```
