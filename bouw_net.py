"""Bouwt net/e314.net.xml uit net/e314_ruw.net.xml (OSM):
  * de spitsstrook richting Leuven wordt strook 0 op de lange 2-strookse edges;
  * hoofdbaan-edges langer dan SPLITS_VANAF worden in stukken van ~STUK m geknipt, zodat rijstrooksignalisatie en
    meldingen (werken, ongeval) op ~250 m nauwkeurig kunnen ingrijpen (TraCI stuurt per volledige strook van een edge).
Van alle aangepaste edges laat netconvert de verbindingen opnieuw berekenen."""
import subprocess, xml.etree.ElementTree as ET
import sumolib

SPLITS_VANAF, STUK = 400, 250
SPITS_LEUVEN = ['345078863', '39965901', '26435873', '474453521', '474453518']
subprocess.run(['netconvert', '-s', 'net/e314_ruw.net.xml', '--plain-output-prefix', 'net/plain'], check=True)
edg = ET.parse('net/plain.edg.xml')
for e in edg.getroot().findall('edge'):
    if e.get('id') in SPITS_LEUVEN:
        e.set('numLanes', '3')
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
# alle verbindingen weg van edges die van/naar een aangepaste edge gaan (anders vult netconvert niet aan)
aangepast = set(SPITS_LEUVEN) | set(GESPLITST)
weg = aangepast | {c.get('from') for c in r if c.get('to') in aangepast}
for c in list(r):
    if c.get('from') in weg:
        r.remove(c)
con.write('net/plain_patch.con.xml')
subprocess.run(['netconvert', '-n', 'net/plain.nod.xml', '-e', 'net/plain_patch.edg.xml', '-x', 'net/plain_patch.con.xml',
                '-t', 'net/plain.typ.xml', '--offset.disable-normalization', '-o', 'net/e314.net.xml'], check=True)
