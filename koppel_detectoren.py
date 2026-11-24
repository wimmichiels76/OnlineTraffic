"""Koppelt MIV-meetpunten aan SUMO-edges (afstand + rijrichting). Hoofdbaan A0020001 = richting Leuven
(km stijgend, rijdt naar het ZW), A0020002 = richting Aarschot (NO). Takken (A00213xx..A00229xx) = op/afritten."""
import csv, math, sys, sumolib
net = sumolib.net.readNet(sys.argv[1] if len(sys.argv) > 1 else 'net/e314.net.xml')
def bearing(e, pos):
    shp = e.getShape(); acc = 0
    for (x1, y1), (x2, y2) in zip(shp, shp[1:]):
        l = math.hypot(x2 - x1, y2 - y1)
        if acc + l >= pos or (x2, y2) == shp[-1]:
            return math.degrees(math.atan2(x2 - x1, y2 - y1)) % 360
        acc += l
uit = []
for r in csv.DictReader(open('data/meetpunten_e314.csv', encoding='utf-8')):
    x, y = net.convertLonLat2XY(float(r['lon']), float(r['lat']))
    kand = []
    for e, d in net.getNeighboringEdges(x, y, 40):
        hoofd = r['ident8'] in ('A0020001', 'A0020002')
        if hoofd != (e.getType().endswith('.motorway')):
            continue
        lane0 = e.getLanes()[0]
        pos, dist = lane0.getClosestLanePosAndDist((x, y))
        b = bearing(e, pos)
        if r['ident8'] == 'A0020001' and not (150 < b < 300): continue   # naar ZW/W
        if r['ident8'] == 'A0020002' and not (b < 120 or b > 330): continue  # naar NO/O
        kand.append((d, e, pos, b))
    if not kand:
        uit.append({**r, 'edge': '', 'pos': '', 'lanes': '', 'dist': ''}); continue
    d, e, pos, b = min(kand, key=lambda k: k[0])
    uit.append({**r, 'edge': e.getID(), 'pos': round(pos, 1), 'lanes': e.getLaneNumber(), 'dist': round(d, 1), 'bearing': round(b)})
velden = list(uit[0].keys()) + ['bearing']
velden = list(dict.fromkeys(velden))
with open('data/detectoren_sumo.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=velden); w.writeheader(); w.writerows(uit)
for u in uit:
    print(u['ident8'], u['kmp'], u['strook'], u['naam'][:28].ljust(28), u['edge'][:28].ljust(28), u['pos'], u['lanes'], u['dist'], u.get('bearing',''))
