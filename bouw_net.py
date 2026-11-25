"""Bouwt net/e314.net.xml uit net/e314_ruw.net.xml (OSM):
  * de spitsstrook richting Leuven wordt strook 0 op de lange 2-strookse edges;
  * hoofdbaan-edges langer dan SPLITS_VANAF worden in stukken van ~STUK m geknipt, zodat rijstrooksignalisatie en
    meldingen (werken, ongeval) op ~250 m nauwkeurig kunnen ingrijpen (TraCI stuurt per volledige strook van een edge).
  * de twee opritten binnen de spitsstrookzone (Rotselaar, km 76) krijgen een invoegstrook: de samenvoeg-edge heeft
    4 stroken (invoegstrook + 2 rijstroken + spitsstrook) in plaats van 3.
Verbindingen: die van OSM blijven behouden waar het aantal stroken niet verandert. Alleen verbindingen van/naar een
edge met een ander aantal stroken worden expliciet gezet. Verbindingen vanuit een geknipte edge vertrekken voortaan
van het laatste stuk (nieuwe id), met dezelfde stroken. Vroeger liet het script netconvert die verbindingen gokken;
netconvert deed dat zo dat strook 0 van de hoofdbaan rechtdoor liep op de invoegstrook. Opritvoertuigen moesten
dan voorrang geven en bleven tot uren staan (live-run 24/11/2026)."""
import subprocess, xml.etree.ElementTree as ET
import sumolib

SPLITS_VANAF, STUK = 400, 250
SPITS_LEUVEN = ['345078863', '39965901', '26435873', '474453521', '474453518']
# samenvoeg-edge: (voorganger, oprit, opvolger), alle drie met de hoofdbaan in de spitsstrookzone
INVOEG_SPITS = {'474453524': ('39965901', '472676824', '26435873'),   # parking Rotselaar
                '474453516': ('474453521', '14099964', '474453518')}  # oprit km 76,0
subprocess.run(['netconvert', '-s', 'net/e314_ruw.net.xml', '--plain-output-prefix', 'net/plain'], check=True)
edg = ET.parse('net/plain.edg.xml')
for e in edg.getroot().findall('edge'):
    if e.get('id') in SPITS_LEUVEN or e.get('id') in INVOEG_SPITS:
        e.set('numLanes', '4' if e.get('id') in INVOEG_SPITS else '3')
        for l in e.findall('lane'):
            e.remove(l)
ruw = sumolib.net.readNet('net/e314_ruw.net.xml')
GESPLITST = []
for e in edg.getroot().findall('edge'):
    E = ruw.getEdge(e.get('id'))
    if not E.getType().endswith('.motorway') or E.getLength() < SPLITS_VANAF:
        continue
    n = round(E.getLength() / STUK)
    for k in range(1, n):
        ET.SubElement(e, 'split', pos=f'{k * E.getLength() / n:.1f}')
    GESPLITST.append(e.get('id'))
print(len(GESPLITST), 'hoofdbaan-edges gesplitst')
edg.write('net/plain_patch.edg.xml')
con = ET.parse('net/plain.con.xml')
r = con.getroot()
# ander aantal stroken: alle verbindingen van en naar die edges weg (expliciet of door netconvert opnieuw);
# geknipte edges: enkel de uitgaande (het laatste stuk heeft een nieuwe id), de inkomende blijven zoals in OSM
def laatste(eid):
    """id van het laatste stuk van een geknipte edge (netconvert: id.<int(pos)>)."""
    e = edg.getroot().find(f"edge[@id='{eid}']")
    pos = [float(s.get('pos')) for s in e.findall('split')]
    return f'{eid}.{int(max(pos))}' if pos else eid


stroken = set(SPITS_LEUVEN) | set(INVOEG_SPITS)
# een edge met nog maar een deel van zijn verbindingen wordt door netconvert niet aangevuld: daarom van elke
# voorganger van zo'n edge alle verbindingen weg (dit zijn splitsingen hoofdbaan/afrit, geen invoegingen)
voorgangers = {c.get('from') for c in r if c.get('to') in stroken} - set(v for v, _, _ in INVOEG_SPITS.values())
for c in list(r):
    if c.get('from') in stroken | voorgangers or c.get('to') in stroken:
        r.remove(c)
    elif c.get('from') in GESPLITST:  # zelfde stroken, maar vanuit het laatste stuk
        c.set('from', laatste(c.get('from')))
for m, (voor, oprit, na) in INVOEG_SPITS.items():
    voor = laatste(voor)
    ET.SubElement(r, 'connection', {'from': oprit, 'to': m, 'fromLane': '0', 'toLane': '0'})
    for k in range(3):
        ET.SubElement(r, 'connection', {'from': voor, 'to': m, 'fromLane': str(k), 'toLane': str(k + 1)})
        ET.SubElement(r, 'connection', {'from': m, 'to': na, 'fromLane': str(k + 1), 'toLane': str(k)})
con.write('net/plain_patch.con.xml')
subprocess.run(['netconvert', '-n', 'net/plain.nod.xml', '-e', 'net/plain_patch.edg.xml', '-x', 'net/plain_patch.con.xml',
                '-t', 'net/plain.typ.xml', '--offset.disable-normalization', '-o', 'net/e314.net.xml'], check=True)
