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
fylld i ett litet bolag är det ofta för att
