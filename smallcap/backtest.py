"""
Backtest — spelar upp historiken dag för dag.

VARFÖR: utan detta skulle du behöva vänta månader på att få veta om
strategin överhuvudtaget fungerar. Med två års historik får du ett
första svar på några sekunder.

VARFÖR DET ÄR TROVÄRDIGT HÄR, till skillnad från de flesta backtest:

  Samma kod. Fill-logiken, exit-reglerna och courtaget är exakt samma
  funktioner som paper.py använder live. Bygger man en separat
  "backtest-version" testar man något annat än det som faktiskt körs.

  Ingen lookahead. Loopen ger strategin bara staplar fram till och med
  dagens datum. Screenern kan aldrig se framtida kurser.

  Konservativ fyllnad. Priset måste gå IGENOM limitnivån, inte nudda
  den. Rundtur samma dag är omöjlig.

VAD DET FORTFARANDE INTE KAN FÅNGA:

  Om DIN order faktiskt hade blivit fylld. Vi vet att priset var där,
  inte att det fanns en motpart för just dig. I ett bolag som omsätter
  100 000 kr om dagen är det en verklig osäkerhet.

  Överlevnadsbias. Universum består av bolag som finns idag. Bolag som
  avnoterats eller gått i konkurs saknas — och det är precis de som
  hade skadat strategin mest.

Läs alltså resultatet som ett OVRE TAK, inte som en prognos.

MARKNADSPARAMETER: samma backtest-motor används för SE och US — bara
databasen och konfigurationen som läses av bytes ut.
"""
import logging
from datetime import date

from .store import connect, get_bars
from . import config, screener, paper

logger = logging.getLogger("backtest")


def _bars_until(ticker: str, until: str, limit: int = 400, market: str = "se") -> list[dict]:
    with connect(market) as c:
        rows = c.execute(
