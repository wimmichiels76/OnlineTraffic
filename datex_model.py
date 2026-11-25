"""DATEX II-meldingen van het Verkeerscentrum in het SUMO-model.

De feed geeft per melding enkel type, geldigheid en ligging (Lambert72): geen strook, geen restcapaciteit.
De vertaling naar het model is dus een AANNAME per type (EFFECT hieronder, aanpasbaar):

  Accident                          -> stilstaand voertuig op de rechterrijstrook (blokkeert die lokaal)
                                       + vmax 70 km/u binnen ±300 m (afremmen, kijkfile)
  MaintenanceWorks                  -> vmax 90 km/u over de lengte van de melding
  RoadOrCarriagewayOrLaneManagement -> vmax 70 km/u (ook laneClosures: geen strook dicht, zie SLUIT_UIT_DATEX)
  EnvironmentalObstruction          -> vmax 70 km/u
  Werfinrichting en obstakel krijgen bovendien een capaciteitsverlies: voertuigen in de zone volgen met
  tau x 1,75 (smalle stroken, meer afstand). Afgesteld op de avondspits van 24/11 (25/11/2026): 1,6 geeft een
  te korte reistijd, 1,9 en 2,0 laten de file tot aan de modelrand terugslaan. Het effect kantelt scherp
  rond 1,8; met `sim_online.py --werf-tau` te overschrijven.
  AbnormalTraffic (file)            -> GEEN invoer: een file is een gevolg, het model moet die zelf maken.
                                       Deze meldingen dienen als controle.

Richting: via de Alert-C-richting (positive = richting Aarschot); zonder Alert-C de dichtstbijzijnde rijbaan.
"""
import json, os
import pandas as pd
from pyproj import Transformer

HIER = os.path.dirname(os.path.abspath(__file__))
LAMBERT = Transformer.from_crs('EPSG:31370', 'EPSG:4326', always_xy=True)
EFFECT = {
    'Accident': dict(blokkeer=True, vmax=70, buffer=300),
    'MaintenanceWorks': dict(vmax=90, buffer=0),
    'RoadOrCarriagewayOrLaneManagement': dict(vmax=70, buffer=0, tau=1.75),
    'EnvironmentalObstruction': dict(vmax=70, buffer=0, tau=1.75),
}
# Een laneClosures-melding sluit in het model GEEN strook. Sinds 25/11/2026 publiceert de feed bij elke lopende
# werf extra deelrecords (-M-LC1, -A-LO1, -A-LCA ...) van het type laneClosures, terwijl de rijstroken open blijven:
# op km 4,9 richting Aarschot telde de rechterstrook die avond 996 vtg/u (53 %), en de RSS toonden geen rood kruis.
# Strookafsluitingen komen daarom uit de RSS (rss_model) en uit ongevallen; laneClosures krijgt vmax en tau.
SLUIT_UIT_DATEX = False
MAX_AFSTAND = 60  # m tot de rijbaan; verder = andere weg (bv. E40, op- of afrit)
ALERTC = {'positive': 'Aarschot', 'negative': 'Leuven'}  # E314 (A2), zie projecteer()


def lees(datum):
    """Alle meldingen (laatste versie per record) + momentopnames van wat actief was."""
    pad, pad_a = f'{HIER}/data/live/datex_{datum}.csv', f'{HIER}/data/live/datex_actief_{datum}.csv'
    if not os.path.exists(pad):
        return None, None
    d = pd.read_csv(pad).drop_duplicates(['record', 'versie']).sort_values('versie').groupby('record').tail(1)
    A = pd.read_csv(pad_a) if os.path.exists(pad_a) else None
    if A is not None:
        A['tijd'] = pd.to_datetime(A.tijd.str[:19])
    return d, A


def actief(d, A, m):
    """Records die tijdens minuut m actief zijn."""
    if d is None:
        return []
    t = m + pd.Timedelta(seconds=60)
    if A is not None and (A.tijd <= t).any():
        ids = set(str(A[A.tijd <= t].iloc[-1].records).split())
        return [r for r in d.itertuples() if r.record in ids]
    uit = []
    for r in d.itertuples():  # vóór de momentopnames: op begin- en eindtijd
        det = json.loads(r.details)
        s, e = det.get('overallStartTime'), det.get('overallEndTime')
        if (not s or pd.Timestamp(s[:19]) <= m) and (not e or m <= pd.Timestamp(e[:19])):
            uit.append(r)
    return uit


class Meldingen:
    def __init__(self, net, corr, traci):
        self.net, self.corr, self.traci = net, corr, traci
        self.cum = {}
        for naam, c in corr.items():
            acc, cum = 0.0, {}
            for e in c['route']:
                cum[e] = acc
                acc += net.getEdge(e).getLength()
            self.cum[naam] = cum
        self.ligging = {}      # record -> (richting, x0, x1, afstand) of None
        self.blokkades = {}    # record -> voertuig-id
        self.zone_tau = {}     # edge -> tau-factor (capaciteitsverlies)
        self.aangepast = {}    # voertuig -> oorspronkelijke tau

    def projecteer(self, r):
        if r.record in self.ligging:
            return self.ligging[r.record]
        xy = json.loads(r.lambert72_xy)
        if len(xy) > 40:
            xy = xy[::len(xy) // 40] + [xy[-1]]
        lon, lat = LAMBERT.transform([p[0] for p in xy], [p[1] for p in xy])
        pts = [self.net.convertLonLat2XY(a, b) for a, b in zip(lon, lat)]
        best = None
        for naam, c in self.corr.items():
            proj = []
            for p in pts:
                kand = []
                for e in c['route']:
                    pos, dist = self.net.getEdge(e).getLanes()[0].getClosestLanePosAndDist(p)
                    kand.append((dist, self.cum[naam][e] + pos))
                proj.append(min(kand))
            gem = sum(d for d, _ in proj) / len(proj)
            xs = [x for _, x in proj]
            score = gem
            # De DATEX-lijn volgt de wegas: beide rijbanen liggen even dicht. De Alert-C-richting beslist dan.
            # Empirisch (24/11/2026): filemeldingen 'positive' vallen samen met de gemeten file richting Aarschot,
            # en de RSS-werfzone (alleen richting Aarschot) ligt op dezelfde plek -> positive = richting Aarschot.
            richting = json.loads(r.details).get('alertCDirectionCoded')
            if richting in ALERTC:
                score += 0 if ALERTC[richting] == naam else 500
            if best is None or score < best[0]:
                best = (score, naam, min(xs), max(xs), gem)
        res = None if best[4] > MAX_AFSTAND else (best[1], best[2], best[3], round(best[4]))
        self.ligging[r.record] = res
        return res

    def gewenst(self, actieve):
        """-> ({lane: ('v', kmh) | ('dicht',)}, [blokkade-specs], [beschrijving])"""
        lanes, blok, tekst = {}, [], []
        self.zone_tau = {}
        for r in actieve:
            eff = EFFECT.get(r.type)
            if eff is None:
                continue
            lig = self.projecteer(r)
            if lig is None:
                continue
            naam, x0, x1, _ = lig
            det = json.loads(r.details)
            sluit = (SLUIT_UIT_DATEX and r.type == 'RoadOrCarriagewayOrLaneManagement'
                     and 'Closure' in det.get('roadOrCarriagewayOrLaneManagementType', ''))
            a, b = x0 - eff['buffer'], x1 + eff['buffer']
            for e in self.corr[naam]['route']:
                E = self.net.getEdge(e)
                mid = self.cum[naam][e] + E.getLength() / 2
                if not (a <= mid <= b or (self.cum[naam][e] <= x0 <= self.cum[naam][e] + E.getLength())):
                    continue
                if eff.get('tau'):
                    self.zone_tau[e] = max(self.zone_tau.get(e, 1.0), eff['tau'])
                for k in range(E.getLaneNumber()):
                    lid = f'{e}_{k}'
                    if sluit and k == 0:
                        lanes[lid] = ('dicht',)
                    elif lanes.get(lid) != ('dicht',):
                        oud = lanes.get(lid, ('v', 999))
                        lanes[lid] = ('v', min(oud[1], eff['vmax']))
            if eff.get('blokkeer'):
                blok.append((r.record, naam, x0))
            tekst.append(f"{r.type}@{naam}:{x0 / 1000:.1f}-{x1 / 1000:.1f}km")
        return lanes, blok, tekst

    def pas_tau_toe(self):
        """Na elke korte simulatiestap: tau verhogen voor voertuigen in een werfzone, terugzetten erbuiten."""
        nu = {}
        for e, f in self.zone_tau.items():
            for v in self.traci.edge.getLastStepVehicleIDs(e):
                nu[v] = f
        for v in list(self.aangepast):
            if v not in nu:
                tau = self.aangepast.pop(v)
                try:
                    self.traci.vehicle.setTau(v, tau)
                except Exception:
                    pass  # voertuig is het netwerk al uit
        for v, f in nu.items():
            if v not in self.aangepast and not v.startswith('ongeval_'):
                tau = self.traci.vehicle.getTau(v)
                self.aangepast[v] = tau
                self.traci.vehicle.setTau(v, tau * f)

    def blokkeer(self, blok):
        """Stilstaande voertuigen voor ongevallen plaatsen of weghalen."""
        nu = {rec for rec, _, _ in blok}
        for rec in list(self.blokkades):
            if rec not in nu:
                vid = self.blokkades.pop(rec)
                if vid in self.traci.vehicle.getIDList():
                    self.traci.vehicle.remove(vid)
        for rec, naam, x in blok:
            if rec in self.blokkades:
                continue
            for e in self.corr[naam]['route']:
                L = self.net.getEdge(e).getLength()
                if self.cum[naam][e] <= x < self.cum[naam][e] + L:
                    pos = max(10.0, min(L - 5, x - self.cum[naam][e]))
                    vid = f'ongeval_{rec}'
                    rid = f'r_{vid}'
                    self.traci.route.add(rid, [e])
                    self.traci.vehicle.add(vid, rid, typeID='ongeval', departPos=f'{pos:.1f}', departLane='0', departSpeed='0')
                    self.traci.vehicle.setStop(vid, e, pos=pos + 1, laneIndex=0, duration=86400)
                    self.blokkades[rec] = vid
                    break


class Regelaar:
    """Voegt de wensen van RSS en meldingen samen (dicht wint, anders laagste snelheid) en zet ze via TraCI."""
    DICHT = ['passenger', 'truck', 'trailer', 'delivery', 'motorcycle', 'bus', 'coach']

    def __init__(self, traci):
        self.traci, self.orig, self.toegepast = traci, {}, {}
        self.orig_dis = {}  # oorspronkelijke verboden voertuigklassen (bv. vrachtverbod links), hersteld na heropenen

    @staticmethod
    def samen(*wensen):
        uit = {}
        for w in wensen:
            for lid, v in w.items():
                o = uit.get(lid)
                if o == ('dicht',) or v == ('dicht',):
                    uit[lid] = ('dicht',)
                else:
                    uit[lid] = v if o is None else ('v', min(o[1], v[1]))
        return uit

    def pas_toe(self, gewenst, naleving=1.0):
        for lid in set(self.toegepast) | set(gewenst):
            nieuw, oud = gewenst.get(lid), self.toegepast.get(lid)
            if nieuw == oud:
                continue
            if lid not in self.orig:
                self.orig[lid] = self.traci.lane.getMaxSpeed(lid)
                self.orig_dis[lid] = list(self.traci.lane.getDisallowed(lid))
            if oud == ('dicht',):
                self.traci.lane.setDisallowed(lid, self.orig_dis[lid])
            if nieuw is None:
                self.traci.lane.setMaxSpeed(lid, self.orig[lid])
            elif nieuw[0] == 'v':
                self.traci.lane.setMaxSpeed(lid, min(self.orig[lid], nieuw[1] * naleving / 3.6))
            else:
                self.traci.lane.setDisallowed(lid, self.DICHT)
            self.toegepast[lid] = nieuw
