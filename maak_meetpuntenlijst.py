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
