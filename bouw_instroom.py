"""Instroom richting Aarschot vanaf het Knooppunt Heverlee (E40 x E314), vóór de file.

De eerste meetdoorsnede richting Aarschot (km 86,7) staat in de avondspits zelf in de file en telt dan de afvoer,
niet de vraag. De file loopt terug over beide verbindingsbogen tot op de rechterstroken van de E40 bij Bertem.
De vraag wordt daarom gemeten waar het verkeer nog vlot rijdt:

  * uit Brussel: E40 Bertem km 15,7 (alle stroken) + oprit Bertem - afrit Bertem - E40 doorgaand Heverlee West km 18,1
    (balans over de E40; ingevoegd op de eerste E40-edge van het netwerk bij Bertem, ±km 17,2, met route naar de
    E314; staat de file nog verder terug, dan wacht het verkeer vóór het netwerk als vertrekvertraging);
  * uit Luik:    de verbindingsboog zelf (lus 3675), die vlot rijdt.

Schrijft per ingang {naam, plus, min, pad} in data/corridor.json onder corridor['Aarschot']['instroom'].
sim_online.py gebruikt die dan in plaats van de doorsnede op km 86,7 (die blijft als controle).
De meetpunten van het Knooppunt Heverlee worden gelogd sinds 25/11/2026 17:12 (miv_logger.py).
"""
import json, os, sys

HIER = os.path.dirname(os.path.abspath(__file__))
if 'SUMO_HOME' in os.environ:
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))
import sumolib  # noqa: E402

INSTROOM = [
    dict(naam='E40 uit Brussel', start='369061439',
         plus=['3324', '3325', '3326', '3327',   # E40 Snede Bertem - RSS km 15,7 (S09, R10-R12)
               '1097'],                          # oprit complex Bertem (22), A0030851
         min=['1096',                            # afrit complex Bertem (22), A0030811
              '3051', '3052', '3053']),          # E40 doorgaand, Verkeerswisselaar Heverlee West km 18,1
    dict(naam='E40 uit Luik', start='3989605', plus=['3675'], min=[]),  # verbindingsboog, Knooppunt Heverlee Oostkant
]


def main():
    os.chdir(HIER)
    net = sumolib.net.readNet('net/e314.net.xml')
    corr = json.load(open('data/corridor.json'))
    c = corr['Aarschot']
    doel = net.getEdge(c['route'][0])
    uit = []
    for g in INSTROOM:
        pad, _ = net.getShortestPath(net.getEdge(g['start']), doel)
        if not pad:
            raise SystemExit(f"geen pad van {g['start']} naar {doel.getID()}")
        pad = [e.getID() for e in pad[:-1]]  # tot vóór de eerste corridor-edge
        L = sum(net.getEdge(e).getLength() for e in pad)
        uit.append(dict(naam=g['naam'], plus=g['plus'], min=g['min'], pad=pad, lengte=round(L)))
        print(f"{g['naam']:<16} {len(pad)} edges, {L:5.0f} m vóór km 86,7: {' '.join(pad)}")
    c['instroom'] = uit
    json.dump(corr, open('data/corridor.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
