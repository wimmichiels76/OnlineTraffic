# Online SUMO-model E314 Aarschot – Leuven

Prototype, gestart op 24/11/2026. De vraag: kan een SUMO-model van een snelweg, gevoed door de MIV-minuutfeed van AWV (dezelfde feed die ANYWAYS gebruikt), de files reproduceren?

## Opbouw

| Stap | Script | Resultaat |
| --- | --- | --- |
| 1. Meetpunten | `maak_meetpuntenlijst.py` | `data/meetpunten_e314.csv`: 188 MIV-lussen (A0020001 = richting Leuven, A0020002 = richting Aarschot, A002xxxx = takken) |
| 2. Live data | `miv_logger.py --tot HH:MM` | `data/live/miv_YYYY-MM-DD.csv`. De feed geeft alleen de laatste minuut, dus de logger bouwt zelf de historiek op. |
| 2b. Verkeerscentrum | `vc_logger.py --tot HH:MM` | `data/live/rss_*.csv`: rijstrooksignalisatie per bord per minuut (snelheid, kruis, pijl), uit `rss-opendata.belfla.be` (geen auth). `data/live/datex_*.csv`: DATEX II v3-situaties (ongeval, file, werken, strookbeheer) binnen 400 m van een corridorlus. De geometrie staat in Lambert72; wegnamen staan niet in de feed. |
| 3. Netwerk | `bouw_osm.py`, netconvert, `bouw_net.py` | `net/e314.net.xml`: OSM motorway + motorway_link. De spitsstrook richting Leuven is toegevoegd als strook 0, omdat OSM die niet meetelt. |
| 4. Koppeling | `koppel_detectoren.py`, `bouw_corridor.py` | `data/corridor.json`: per richting de hoofdbaanroute, de meetdoorsneden (MIV-strook → SUMO-strook) en de op- en afritten |
| 5. Simulatie | `sim_online.py` | TraCI-loop per minuut. Uitvoer in `uit/` (e1, edgedata, tripinfo, log) |
| 6. Validatie | `vergelijk.py --tag …` | `uit/vergelijking_<tag>.png/.md`: tijd-ruimtediagrammen van de snelheid (gemeten en SUMO), reistijd, debiet, trefkans files |
| 6b. Radiotekst | `radiotekst.py --tag … [--tijd HH:MM] [--bron gemeten\|model]` | Voorleesbaar bericht: files (< 60 km/u over ≥ 1 km, tussen complexen), verliestijd t.o.v. 115 km/u, oorzaak uit DATEX, trend t.o.v. 10 min eerder. Staat ook in de viewer, met een kopieerknop. |
| 7. Viewer | `maak_viewer.py --tag …` | `uit/viewer_<tag>.html` (bovenop `viewer_sjabloon.html`): GRB-kaart met per wegvak de gemeten snelheid (brede rand) en de SUMO-snelheid (kern), een tijdschuif met afspelen (spatie, ←/→), klikbare tijd-ruimtediagrammen, de reistijd en de spitsstrookstatus. Het bestand staat op zichzelf; Leaflet en de kaarttegels komen van internet. |

## Modelprincipe

- **Invoer:** de gemeten telling op de eerste hoofdbaandoorsnede en op elke oprit (auto/vracht), per minuut.
- **Afritkeuze:** sequentiële afsplitsing. Per afrit geldt p = afrit / balans hoofdbaan, berekend over een venster van 5 min.
- **Spitsstrook:** strook 0 gaat open of dicht volgens de S09-lussen van die richting. Alleen op stukken zonder in- of uitvoegende tak.
- **Rijstrooksignalisatie** (`rss_model.py`): elk portaal geldt tot het volgende portaal. SNELH_x wordt de vmax per strook (× `--rss-naleving`, standaard 1,0). Kruis en gele pijl sluiten de strook, behalve op een edge met een tak; daar wordt het 30 km/u. Uitzetten kan met `--zonder-rss`.
- **Stroomafwaartse rand:** de gemeten snelheid op de laatste doorsnede wordt de vmax van de laatste edge. Zo kan een file die van buiten het model komt (E40, Leuven) terugslaan.
- **Validatie:** alle tussenliggende hoofdbaanlussen (±25 per richting) worden *niet* als invoer gebruikt. Ze dienen alleen als controle.

## Beperkingen en open punten

- Er is geen historisch archief met snelheden publiek beschikbaar. De MIV-historiek staat bij ANYWAYS op data1 (`/var/services/files/verkeerscentrum/`); de traffic-counts-api bewaart wel tellingen, maar geen snelheden.
- De configuratie-endpoint van MIV is sinds 05/12/2025 niet meer bijgewerkt (zie de Issue Tracker), maar voor de E314 zijn alle lussen aanwezig.
- De rijstrooksignalisatie (RSS) zit sinds 24/11 in het model. Op de E314 hangen alleen in richting Aarschot borden, tussen km 86,7 en 80,8. Op 24/11 stond daar een zone van 50 km/u met de weefstrook dicht. DATEX meldde een werfinrichting (08/11 tot 30/11) en een verzakking bij Herent.
- Test 24/11, 14:55-15:09, richting Aarschot: zonder RSS kwam de reistijd op 11,0 min tegen 14,7 gemeten en werd geen enkele filecel getroffen. Met RSS was het 14,0 min (gemeten 14,6) en werden alle filecellen getroffen, met 38 % vals alarm. In SUMO rijdt iedereen 50 in de zone, in werkelijkheid 75-90. De echte file staat bij km 4-5,5 (vóór Herent), op een plek die het model nog niet als knelpunt heeft. Naleving 1,3 geeft een lagere RMSE (13,7) maar een te korte reistijd (12,5 min).
- DATEX-meldingen zitten in het model (`datex_model.py`, uitzetten met `--zonder-datex`). De feed geeft geen stroken, dus het effect per type is een aanname:
  - ongeval: een stilstaand voertuig op de rechterstrook, plus 70 km/u op ±300 m;
  - werken: 90 km/u;
  - werfinrichting of verzakking: 70 km/u, plus tau × 2 in de zone, wat de capaciteit verlaagt;
  - filemeldingen dienen alleen als controle.
- Richting: Alert-C 'positive' = richting Aarschot. Dat is afgeleid op 24/11 uit filemeldingen die samenvielen met de gemeten file.
- De hoofdbaan is in stukken van ±250 m geknipt (`bouw_net.py`), zodat RSS en meldingen lokaal ingrijpen.
- Test 24/11, 14:55-15:22, richting Aarschot: met RSS alleen was de reistijd gemiddeld 14,9 min (gemeten 17,1). Met RSS en meldingen 17,3 min; het maximum was 19,7 min tegen 23,9 gemeten. De filekop ligt juist, bij de werfzone in Herent.
- SUMO is nog niet gekalibreerd: standaard Krauss, tau 1,0 s voor auto's en 1,2 s voor vrachtwagens. Extra strookwisselparameters kunnen mee met `--lc "lcAssertive=1.5 …"`.
- **Invoegstroken (25/11):** het knippen in `bouw_net.py` liet netconvert de verbindingen vóór de opritten opnieuw gokken. Bij zes opritten liep strook 0 van de hoofdbaan dan rechtdoor op de invoegstrook, zodat opritverkeer voorrang moest geven en tot uren wachtte (de live-run van 24/11 verloor zo een groot deel van de vraag). De verbindingen van OSM blijven nu behouden; de twee opritten in de spitsstrookzone richting Leuven kregen een vierde strook als invoegstrook. `opritten.py <tag> …` toont de vertrekvertraging per ingang.
- Avondspits 24/11, 15:00-20:15, met RSS en DATEX, herspeeld op het hersteld netwerk:

  | | live-run (oud netwerk) | hersteld netwerk | + `lcAssertive=1.5` | gemeten |
  | --- | --- | --- | --- | --- |
  | reistijd richting Aarschot gem/max (min) | 15,6 / 29,4 | 25,8 / 47,6 | 26,5 / 51,5 | 25,5 / 53,3 |
  | trefkans file richting Aarschot | 99 % | 99 % (20 % vals alarm) | 99 % (21 %) | |
  | debiet GEH < 5, richting Leuven / Aarschot | 27 % / 10 % | 97 % / 22 % | 98 % / 22 % | |
  | gemiddelde vertrekvertraging | 403 s | 96 s | 101 s | |

- Coöperatief strookwisselen staat in SUMO standaard al op het maximum (`lcCooperative` = 1). Meer assertief invoegen veranderde weinig.
- Open punt: de oprit Gasthuisberg richting Aarschot wacht nog gemiddeld 40 min. Zijn strook loopt 420 m door en wordt de afrit Winksele (weefvak), midden in de file. Wie verder rijdt, moet daar in de file naar links; dat lukt SUMO slecht. Dat verklaart ook de lage GEH richting Aarschot.

## Installatie

1. Installeer [Eclipse SUMO](https://eclipse.dev/sumo/) 1.24 en zet `SUMO_HOME`. `sumo` en `netconvert` moeten op het PATH staan.
2. `pip install -r requirements.txt`
3. Het netwerk (`net/e314.net.xml`) en de corridor (`data/corridor.json`) staan in de repository. Stap 1, 3 en 4 hoeven dus niet opnieuw.
4. Start de loggers (`miv_logger.py`, `vc_logger.py`) en daarna `sim_online.py --live` en `maak_viewer.py --live`.

`data/live/` en `uit/` staan niet in git: de loggers en de simulatie vullen ze zelf.

## Bronnen en licenties

- **MIV-verkeersmetingen** (`miv.opendata.belfla.be`), **rijstrooksignalisatie** (`rss-opendata.belfla.be`) en **DATEX II-meldingen** (`verkeerscentrum.be/uitwisseling/datex2v3`): open data van het Vlaams Verkeerscentrum (Agentschap Wegen en Verkeer), onder de Modellicentie Gratis Hergebruik. `data/miv_config.xml` en `data/rss_borden_e314.json` zijn afgeleid van die feeds.
- **Wegennet** (`net/e314.osm.xml` en de afgeleide SUMO-netwerken): © OpenStreetMap-bijdragers, onder de [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/).
- **Kaartachtergrond in de viewer:** GRB-basiskaart van Digitaal Vlaanderen.
- De licentie van de code zelf ligt nog niet vast.
