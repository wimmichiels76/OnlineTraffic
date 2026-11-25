"""Vertrekvertraging per ingang (hoofdbaan, oprit) uit de tripinfo van een of meer runs.

    python opritten.py live_2026-11-24 oprit_2026-11-24 coop_2026-11-24

Een oprit waar voertuigen minuten wachten om in te voegen, verliest vraag: die voertuigen komen te laat of niet
op de hoofdbaan (zie bouw_net.py, invoegstroken).
"""
import json, os, sys
import xml.etree.ElementTree as ET
import pandas as pd

HIER = os.path.dirname(os.path.abspath(__file__))


def ingangen():
    c = json.load(open(os.path.join(HIER, 'data', 'corridor.json')))
    naam = {}
    for n, cc in c.items():
        naam[cc['route'][0]] = f'{n} | hoofdbaan'
        for o in cc['opritten']:
            naam[o['pad'][0]] = f"{n} | {o['ident'][:8]} {o['naam']}"
    return naam


def vertraging(tag):
    rijen = [(t.get('departLane').rsplit('_', 1)[0], float(t.get('departDelay')))
             for t in ET.parse(os.path.join(HIER, 'uit', f'tripinfo_{tag}.xml')).getroot().iter('tripinfo')]
    d = pd.DataFrame(rijen, columns=['edge', 'vertraging'])
    d['ingang'] = d.edge.map(ingangen()).fillna(d.edge)
    return d.groupby('ingang').vertraging.agg(['count', 'mean', 'max'])


if __name__ == '__main__':
    tags = sys.argv[1:]
    T = pd.concat({t: vertraging(t) for t in tags}, axis=1)
    T = T.loc[:, (slice(None), ['count', 'mean', 'max'])].round(0).astype('Int64')
    print(T.to_string())
