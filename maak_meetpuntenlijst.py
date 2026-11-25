"""Selecteert alle MIV-meetpunten op de E314 (A2) en zijn complexen tussen Aarschot en Leuven."""
import csv, xml.etree.ElementTree as ET
def f(s):
    try: return float(s.replace(',', '.'))
    except Exception: return None
r = ET.parse('data/miv_config.xml').getroot()
uit = []
for m in r.findall('meetpunt'):
    g = lambda t: (m.findtext(t) or '').strip()
    lon, lat = f(g('lengtegraad_EPSG_4326')), f(g('breedtegraad_EPSG_4326'))
    if lon and 4.64 < lon < 4.86 and 50.855 < lat < 50.975 and g('Ident_8').startswith('A002'):
        uit.append(dict(unieke_id=m.get('unieke_id'), beschrijvende_id=g('beschrijvende_id'), naam=g('volledige_naam'),
                        ident8=g('Ident_8'), kmp=f(g('Kmp_Rsys')), strook=g('Rijstrook'), lon=lon, lat=lat))
uit.sort(key=lambda d: (d['ident8'], d['kmp'], d['strook']))
with open('data/meetpunten_e314.csv', 'w', newline='', encoding='utf-8') as fh:
    w = csv.DictWriter(fh, fieldnames=list(uit[0])); w.writeheader(); w.writerows(uit)
print(len(uit), 'meetpunten')

# ---- Knooppunt Heverlee (E40 x E314): instroom richting Aarschot van vóór de file op km 86,7.
# Alle meetpunten binnen STRAAL m van het knooppunt die niet al in de E314-lijst staan (E40-hoofdbaan A003*,
# verbindingsbogen A0035*/A0039*, takken A00221*). Apart bestand, zodat netwerk en koppeling ongewijzigd blijven.
import math
KNOOPPUNT, STRAAL = (4.6453, 50.8605), 3000
e314 = {d['unieke_id'] for d in uit}
hev = []
for m in r.findall('meetpunt'):
    g = lambda t: (m.findtext(t) or '').strip()
    lon, lat = f(g('lengtegraad_EPSG_4326')), f(g('breedtegraad_EPSG_4326'))
    if lon is None or lat is None or m.get('unieke_id') in e314:
        continue
    afstand = math.hypot((lon - KNOOPPUNT[0]) * 70300, (lat - KNOOPPUNT[1]) * 111200)
    if afstand <= STRAAL:
        hev.append(dict(unieke_id=m.get('unieke_id'), beschrijvende_id=g('beschrijvende_id'), naam=g('volledige_naam'),
                        ident8=g('Ident_8'), kmp=f(g('Kmp_Rsys')), strook=g('Rijstrook'), lon=lon, lat=lat,
                        afstand_m=round(afstand)))
hev.sort(key=lambda d: (d['ident8'], d['kmp'] or 0, d['strook']))
with open('data/meetpunten_heverlee.csv', 'w', newline='', encoding='utf-8') as fh:
    w = csv.DictWriter(fh, fieldnames=list(hev[0])); w.writeheader(); w.writerows(hev)
print(len(hev), 'meetpunten Knooppunt Heverlee')
