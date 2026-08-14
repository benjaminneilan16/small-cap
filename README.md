# Småbolagsstrategi — paper trading

Testar en spread-strategi på svenska småbolag med låtsaspengar.
Körs automatiskt en gång per dag via GitHub Actions. Ingen server,
ingen databas, inga kostnader.

## Vad strategin gör

Letar efter småbolag med **breda spreadar och spretiga kurser** —
alltså precis det konventionell analys kallar dåligt. Lägger sedan
köpordrar under marknaden och säljordrar 5–10 % upp.

De flesta ordrar blir aldrig affärer. Med många ute samtidigt blir det
ändå avslut regelbundet.

## Kom igång

### 1. Lägg upp på GitHub

Skapa ett nytt repo och ladda upp alla filer. Actions aktiveras automatiskt.

### 2. Testa direkt med backtest

Gå till **Actions** → **Daglig körning** → **Run workflow**.

Eller lokalt om du har Python:

```bash
pip install -r requirements.txt
python run_daily.py --backtest
```

Backtestet spelar upp två års historik dag för dag och ger dig ett
första svar på minuter istället för månader.

### 3. Byt ut bolagen

`universe.txt` innehåller en startlista för att testa att allt fungerar.
Byt ut den mot riktiga kandidater:

1. Öppna Avanza → aktielistan
2. Filtrera på First North
3. Sortera på omsättning
4. Kopiera in tickers i `universe.txt`, en per rad

Suffixet `.ST` läggs till automatiskt. Bolag utan data markeras i
rapporten — byt ut dem.

### 4. Läs resultatet

Rapporten hamnar i `reports/latest.md` och uppdateras varje körning.
Öppna den på GitHub. Positioner och ordrar finns även som CSV.

### 5. Telegram-notiser (valfritt)

Repo → **Settings** → **Secrets and variables** → **Actions** →
lägg till `TELEGRAM_BOT_TOKEN` och `TELEGRAM_CHAT_ID`.

## Vad du ska titta på

Inte avkastningen först. Dessa två säger mer:

**Fyllnadsgrad** — andelen ordrar som blev affärer. Låg siffra är
normalt för den här strategin, inte ett fel.

**Genomsnittlig maximal motgång (MAE)** — hur långt ner positionerna
gick innan de stängdes. Detta är måttet på *adverse selection*: blir du
systematiskt fylld precis innan det fortsätter ner? Det är strategins
verkliga risk.

**Slår den buy & hold?** Gör den inte det är komplexiteten inte värd
risken.

## Varför resultatet är konservativt

| Antagande | Varför |
|---|---|
| Fill kräver **genombrott**, inte beröring | Att priset nådde 10,00 betyder inte att din order fylldes — du kan ha legat sist i kön |
| Ingen rundtur samma dag | Med dagliga staplar vet vi inte om lägsta kom före högsta |
| Vid tveksamhet antas stop loss | Nåddes både mål och stop samma dag vet vi inte ordningen |
| Fill till limitpris, inte bättre | Gapar aktien ner får du egentligen bättre pris — vi antar det sämre |

Modellen ska hellre underskatta än överskatta.

## Vad den inte kan fånga

**Om din order faktiskt hade fyllts.** I ett bolag som omsätter
100 000 kr om dagen är det en verklig osäkerhet.

**Överlevnadsbias i backtestet.** Universum består av bolag som finns
idag. De som avnoterats saknas — och det är precis de som hade skadat
strategin mest.

## Inställningar

Ändra i `smallcap/config.py` eller via miljövariabler:

| Variabel | Standard | Betydelse |
|---|---|---|
| `STARTING_CAPITAL` | 50000 | Låtsaskapital |
| `TARGET_PROFIT_PCT` | 7.0 | Vinstmål per affär |
| `POSITION_SIZE_PCT` | 2.0 | Andel av kapitalet per position |
| `MAX_EXPOSURE_PCT` | 30.0 | Tak för hur mycket som får vara investerat |
| `BUY_BELOW_PCT` | 4.0 | Hur långt under marknaden köpordern läggs |
| `STOP_LOSS_PCT` | -15.0 | Stop loss |
| `MIN_DAILY_RANGE_PCT` | 3.0 | Minsta dagliga spann för att godkännas |
| `MAX_EFFICIENCY_RATIO` | 0.30 | Över detta trendar aktien för mycket |

## Kommandon

```bash
python run_daily.py              # normal körning
python run_daily.py --backtest   # spela upp historiken
python run_daily.py --reset      # nollställ kontot
python run_daily.py --no-orders  # uppdatera utan att lägga nya ordrar
```
