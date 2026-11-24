"""Rijstrooksignalisatie (RSS) in het SUMO-model.

Elk portaal (de borden van één rijrichting op één km) geldt voor de rijbaan tot het volgende portaal
(het laatste tot GELDIGHEID_LAATSTE m verder). Een edge hoort bij het portaal dat zijn midden dekt.
Per strook betekent het bevestigde beeld:
  SNELH_x            -> vmax x km/u op die strook
  EINDE_x, EINDE, DOVEN, GROENE_PIJL -> standaardsnelheid
  KRUIS, PIJL_LINKS, PIJL_RECHTS     -> strook dicht (alleen op edges zonder in-/uitvoegende tak;
                                        anders 30 km/u, zodat een afrit bereikbaar blijft)
MIV/RSS-strooknummers worden links uitgelijnd: R11 = meest linkse strook bij 2+ stroken, R10 daarnaast, R09, R08.
"""
import json, math, os, re
import pandas as pd

HIER = os.path.dirname(os.path.abspath(__file__))
GELDIGHEID_LAATSTE = 800  # m
DICHT = ['passenger', 'truck', 'trailer', 'delivery', 'motorcycle', 'bus', 'coach']
RICHTING = {'A0020001': 'Leuven', 'A0020002': 'Aarschot'}


def strook_naar_lane(strook, n_lanes):
    nr = int(re.sub(r'\D', '', strook))
    lane = n_lanes - 1 - (11 - nr)
    return lane if 0 <= lane < n_lanes else None


def bouw(net, corr):
    """-> {richting: dict(portalen=[{x, borden:{bord_id: strook}}], edges={edge: portaalindex})}"""
    borden = json.load(open(os.path.join(HIER, 'data', 'rss_borden_e314.json')))
    model = {}
    for ident, naam in RICHTING.items():
        c = corr[naam]
        cum, acc = {}, 0.0
        for e in c['route']:
            cum[e] = acc
            acc += net.getEdge(e).getLength()
        portalen = {}
        for bid, b in borden.items():
            if b['ident8'] != ident:
                continue
            x, y = net.convertLonLat2XY(b['lon'], b['lat'])
            best = None
            for e in c['route']:
                pos, d = net.getEdge(e).getLanes()[0].getClosestLanePosAndDist((x, y))
                if best is None or d < best[0]:
                    best = (d, e, pos)
            if best[0] > 40:
                continue
            xr = cum[best[1]] + best[2]
            portalen.setdefault(b['km'], dict(x=xr, km=b['km'], borden={}))['borden'][bid] = b['strook']
        P = sorted(portalen.values(), key=lambda p: p['x'])
        edges = {}
        for e in c['route']:
            mid = cum[e] + net.getEdge(e).getLength() / 2
            for k, p in enumerate(P):
                eind = P[k + 1]['x'] if k + 1 < len(P) else p['x'] + GELDIGHEID_LAATSTE
                if p['x'] <= mid < eind:
                    edges[e] = k
        model[naam] = dict(portalen=P, edges=edges)
    return model


def lees(datum):
    pad = os.path.join(HIER, 'data', 'live', f'rss_{datum}.csv')
    if not os.path.exists(pad):
        return None
    d = pd.read_csv(pad)
    d['tijd'] = pd.to_datetime(d.tijd.str[:19])
    return d


def toestand(d, m):
    """Laatst bekende beeld per bord binnen minuut m (tot m+60 s). None als er nog niets gelogd is."""
    if d is None:
        return None
    sel = d[d.tijd < m + pd.Timedelta(seconds=60)]
    if sel.empty:  # vóór de start van de RSS-logger: eerste bekende beeld (werfinrichtingen blijven dagen staan)
        sel = d[d.tijd == d.tijd.min()]
    laatste = sel.sort_values('tijd').groupby('bord_id').tail(1)
    return {r.bord_id: (r.teken if r.teken != 'DOVEN' else r.pijl) for r in laatste.itertuples()
            if r.in_dienst == 1 and r.defect == 0}


class RSS:
    def __init__(self, net, corr, traci, naleving=1.0):
        self.net, self.traci, self.naleving = net, traci, naleving  # naleving: gereden snelheid = factor x bordsnelheid
        self.model = bouw(net, corr)
        self.orig = {}
        self.toegepast = {}  # lane -> ('v', km/u) | ('dicht',) | None

    def zuiver(self, e):
        E = self.net.getEdge(e)
        return len(E.getOutgoing()) == 1 and len(E.getIncoming()) == 1

    def gewenst(self, beeld):
        """-> ({lane: ('v', km/u) | ('dicht',)}, {richting: samenvatting}); toepassen doet datex_model.Regelaar."""
        samenvatting = {}
        gewenst = {}
        for naam, M in self.model.items():
            if beeld is None:
                continue
            tekens = []
            for e, k in M['edges'].items():
                n = self.net.getEdge(e).getLaneNumber()
                for bid, strook in M['portalen'][k]['borden'].items():
                    lane = strook_naar_lane(strook, n)
                    t = beeld.get(bid)
                    if lane is None or t is None:
                        continue
                    lid = f'{e}_{lane}'
                    if t.startswith('SNELH_'):
                        gewenst[lid] = ('v', int(t.split('_')[1]))
                    elif t in ('KRUIS', 'PIJL_LINKS', 'PIJL_RECHTS'):
                        gewenst[lid] = ('dicht',) if self.zuiver(e) else ('v', 30)
            for p in M['portalen']:
                ts = sorted({beeld.get(b, '?') for b in p['borden']})
                tekens.append(f"{p['km']}:{'/'.join(t.replace('SNELH_', '') for t in ts)}")
            samenvatting[naam] = ' '.join(tekens)
        return gewenst, samenvatting

    def pas_toe(self, beeld):
        """Alleen RSS (zonder meldingen): wensen berekenen en zelf toepassen."""
        gewenst, samenvatting = self.gewenst(beeld)
        # wijzigingen doorvoeren (ook terugzetten van stroken die niet meer gestuurd worden)
        for lid in set(self.toegepast) | set(gewenst):
            nieuw, oud = gewenst.get(lid), self.toegepast.get(lid)
            if nieuw == oud:
                continue
            if lid not in self.orig:
                self.orig[lid] = self.traci.lane.getMaxSpeed(lid)
            if oud == ('dicht',):
                self.traci.lane.setDisallowed(lid, [])
            if nieuw is None:
                self.traci.lane.setMaxSpeed(lid, self.orig[lid])
            elif nieuw[0] == 'v':
                self.traci.lane.setMaxSpeed(lid, min(self.orig[lid], nieuw[1] * self.naleving / 3.6))
            else:
                self.traci.lane.setDisallowed(lid, DICHT)
            self.toegepast[lid] = nieuw
        return samenvatting
