"""Haalt OSM-snelwegdata (motorway + motorway_link) langs de E314 Aarschot-Leuven op via de OSM-API.
Overpass werkt niet vanaf deze machine (406), dus kleine bbox-tegels langs de corridor en zelf filteren."""
import csv, time, urllib.request, xml.etree.ElementTree as ET
pts = [(float(r['lon']), float(r['lat'])) for r in csv.DictReader(open('data/meetpunten_e314.csv', encoding='utf-8'))]
# tegels van 0.02 x 0.015 graden die minstens één meetpunt bevatten (+ buren)
dx, dy = 0.02, 0.015
tegels = set()
for lon, lat in pts:
    i, j = int(lon // dx), int(lat // dy)
    for a in (-1, 0, 1):
        for b in (-1, 0, 1):
            tegels.add((i + a, j + b))
nodes, ways = {}, {}
for n, (i, j) in enumerate(sorted(tegels)):
    bbox = f"{i*dx:.4f},{j*dy:.4f},{(i+1)*dx:.4f},{(j+1)*dy:.4f}"
    req = urllib.request.Request(f"https://api.openstreetmap.org/api/0.6/map?bbox={bbox}", headers={'User-Agent': 'sumo-research-script/0.1'})
    for poging in range(3):
        try:
            root = ET.fromstring(urllib.request.urlopen(req, timeout=120).read()); break
        except Exception as e:
            print('retry', bbox, e); time.sleep(5)
    for nd in root.findall('node'):
        nodes[nd.get('id')] = nd
    for w in root.findall('way'):
        tags = {t.get('k'): t.get('v') for t in w.findall('tag')}
        if tags.get('highway') in ('motorway', 'motorway_link'):
            ways[w.get('id')] = w
    print(n + 1, '/', len(tegels), bbox, len(ways), flush=True)
nodig = {nd.get('ref') for w in ways.values() for nd in w.findall('nd')}
osm = ET.Element('osm', version='0.6', generator='bouw_osm.py')
for nid in nodig:
    if nid in nodes:
        osm.append(nodes[nid])
for w in ways.values():
    osm.append(w)
ET.ElementTree(osm).write('net/e314.osm.xml', encoding='utf-8', xml_declaration=True)
print('klaar', len(ways), 'ways', len(nodig), 'nodes')
