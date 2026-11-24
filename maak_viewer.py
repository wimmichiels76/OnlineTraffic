"""Maakt een zelfstandige HTML-viewer van een simulatierun: kaart (GRB) met snelheid per wegvak, gemeten en SUMO
naast elkaar, tijdschuif met afspelen, tijd-ruimtediagrammen en reistijd.

    python maak_viewer.py --tag live_2026-11-24        ->  uit/viewer_live_2026-11-24.html
"""
import argparse, json, math, os, sys, time
import numpy as np
import pandas as pd

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
import miv_data  # noqa: E402
from vergelijk import lees_e1, doorsnede_tabel, reistijd  # noqa: E402
import rss_model  # noqa: E402
import datex_model  # noqa: E402
import radiotekst  # noqa: E402
from pyproj import Transformer  # noqa: E402

LAMBERT = Transformer.from_crs('EPSG:31370', 'EPSG:4326', always_xy=True)
TEKEN = {'DOVEN': '', 'GROENE_PIJL': '↓', 'KRUIS': '✕', 'PIJL_RECHTS': '↘', 'PIJL_LINKS': '↙', 'EINDE': '⊘'}


def teken_kort(t):
    if not isinstance(t, str):
        return '?'
    if t.startswith('SNELH_'):
        return t[6:]
    if t.startswith('EINDE_'):
        return '⊘' + t[6:]
    return TEKEN.get(t, t[:3])


_MELD = {}


def meldingen_corridor(datum, t):
    """Actieve DATEX-meldingen op minuut t, geprojecteerd op de corridor: [{type, richting, x0, x1}]."""
    if 'm' not in _MELD:
        net = sumolib.net.readNet(os.path.join(HIER, 'net', 'e314.net.xml'))
        _MELD['m'] = datex_model.Meldingen(net, json.load(open(os.path.join(HIER, 'data', 'corridor.json'))), None)
    if _MELD.get('datum') != datum or _MELD.get('geladen', 0) < pd.Timestamp.now().timestamp() - 25:
        _MELD['d'], _MELD['A'] = datex_model.lees(datum)
        _MELD['datum'], _MELD['geladen'] = datum, pd.Timestamp.now().timestamp()
    uit = []
    for r in datex_model.actief(_MELD['d'], _MELD['A'], t):
        lig = _MELD['m'].projecteer(r)
        if lig:
            uit.append(dict(type=r.type, richting=lig[0], x0=lig[1], x1=lig[2]))
    return uit


def rss_viewer(datum, idx):
    """Portalen (per richting en km) met per minuut het beeld per strook, links -> rechts."""
    borden = json.load(open('data/rss_borden_e314.json'))
    d = rss_model.lees(datum)
    portalen = {}
    for bid, b in borden.items():
        p = portalen.setdefault((b['ident8'], b['km']), dict(richting='Aarschot' if b['ident8'] == 'A0020002' else 'Leuven',
                                                             km=b['km'], borden=[], lat=[], lon=[]))
        p['borden'].append((b['strook'], bid)); p['lat'].append(b['lat']); p['lon'].append(b['lon'])
    uit = []
    for p in sorted(portalen.values(), key=lambda p: (p['richting'], -float(p['km'] or 0))):
        p['borden'].sort(reverse=True)  # R11 (links) eerst
        beeld = []
        for t in idx:
            if d is None:
                beeld.append(None); continue
            sel = d[d.tijd < t + pd.Timedelta(seconds=60)]
            if sel.empty:
                beeld.append(None); continue
            laatste = sel.groupby('bord_id').tail(1).set_index('bord_id')
            beeld.append([teken_kort(laatste.teken.get(bid) if laatste.teken.get(bid) != 'DOVEN' else laatste.pijl.get(bid))
                          for _, bid in p['borden']])
        uit.append(dict(richting=p['richting'], km=p['km'], stroken=[s for s, _ in p['borden']],
                        ll=[round(sum(p['lat']) / len(p['lat']), 6), round(sum(p['lon']) / len(p['lon']), 6)], beeld=beeld))
    return uit


SOORT = {'Accident': 'ongeval', 'AbnormalTraffic': 'file', 'MaintenanceWorks': 'werken',
         'RoadOrCarriagewayOrLaneManagement': 'strookbeheer', 'EnvironmentalObstruction': 'obstakel'}


def incidenten_viewer(datum, idx):
    pad, pad_a = f'data/live/datex_{datum}.csv', f'data/live/datex_actief_{datum}.csv'
    if not os.path.exists(pad):
        return []
    d = pd.read_csv(pad).drop_duplicates(['record', 'versie']).sort_values('versie').groupby('record').tail(1)
    A = pd.read_csv(pad_a) if os.path.exists(pad_a) else None
    if A is not None:
        A['tijd'] = pd.to_datetime(A.tijd.str[:19])
    uit = []
    for r in d.itertuples():
        det = json.loads(r.details)
        xy = json.loads(r.lambert72_xy)
        lon, lat = LAMBERT.transform([p[0] for p in xy], [p[1] for p in xy])
        start = pd.Timestamp(det.get('overallStartTime', '')[:19]) if det.get('overallStartTime') else None
        eind = pd.Timestamp(det.get('overallEndTime', '')[:19]) if det.get('overallEndTime') else None
        actief = []
        for t in idx:
            if A is not None and (A.tijd <= t + pd.Timedelta(seconds=60)).any():
                rij = A[A.tijd <= t + pd.Timedelta(seconds=60)].iloc[-1]
                actief.append(int(r.record in str(rij.records).split()))
            else:  # vóór de momentopnames: op begin- en eindtijd
                actief.append(int((start is None or start <= t) and (eind is None or t <= eind)))
        if not any(actief):
            continue
        tekst = ', '.join(f'{k}: {v}' for k, v in det.items() if k not in ('validityStatus', 'specificLocation', 'alertCDirectionCoded'))
        uit.append(dict(soort=SOORT.get(r.type, r.type), id=r.record, tekst=tekst,
                        ll=[[round(b, 6), round(a, 6)] for a, b in zip(lon, lat)], actief=actief))
    return uit




if 'SUMO_HOME' in os.environ:
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))
import sumolib  # noqa: E402


def segmenten(net, c):
    """Lijngeometrie (lon/lat) per meetdoorsnede: van halverwege de vorige tot halverwege de volgende."""
    pts, cum = [], []
    for e in c['route']:
        shp = net.getEdge(e).getShape()
        for p in (shp if not pts else shp[1:]):
            if pts:
                cum.append(cum[-1] + math.dist(pts[-1], p))
            else:
                cum.append(0.0)
            pts.append(p)
    # cum is geometrische afstand; schaal naar edge-lengtes (x in corridor.json)
    schaal = c['lengte'] / cum[-1]
    cum = [v * schaal for v in cum]
    xs = [d['x'] for d in c['doorsneden']]
    grenzen = [max(0, xs[0] - 300)] + [(a + b) / 2 for a, b in zip(xs, xs[1:])] + [min(c['lengte'], xs[-1] + 300)]
    out = []
    for a, b in zip(grenzen, grenzen[1:]):
        lijn = []
        for i in range(len(pts)):
            if a <= cum[i] <= b:
                lijn.append(pts[i])
        # begin- en eindpunt interpoleren
        def op(x):
            i = max(0, min(len(cum) - 2, np.searchsorted(cum, x) - 1))
            f = (x - cum[i]) / max(1e-9, cum[i + 1] - cum[i])
            return (pts[i][0] + f * (pts[i + 1][0] - pts[i][0]), pts[i][1] + f * (pts[i + 1][1] - pts[i][1]))
        lijn = [op(a)] + lijn + [op(b)]
        out.append([[round(v, 6) for v in net.convertXY2LonLat(*p)[::-1]] for p in lijn])
    return out


COMPLEX = {'A00213': 'Aarschot', 'A00214': 'Holsbeek', 'A00215': 'Wilsele', 'A00217': 'Herent', 'A00218': 'Winksele',
           'A00219': 'Gasthuisberg', 'A00220': 'Leuven', 'A00294': 'Parking Rotselaar'}


def complexnaam(t):
    return COMPLEX.get(t['ident'][:6], t['naam'])


def r(v, n=0):
    return None if v is None or not np.isfinite(v) else round(float(v), n)


def lees_sim(tag, meta):
    """Afgeronde run: e1-xml (harmonische snelheid). Lopende run: de minuutlog uit TraCI."""
    e1, csv = f'uit/e1_{tag}.xml', f'uit/sim_minuut_{tag}.csv'
    if meta.get('klaar', True) and os.path.exists(e1) and os.path.getsize(e1) > 2000:
        return lees_e1(e1, meta['t0'])
    S = pd.read_csv(csv, dtype={'unieke_id': str})
    S['tijd'] = pd.to_datetime(S.tijd)
    return S


def bouw_data(tag, van_arg=None, tot_arg=None, cache={}):
    meta = json.load(open(f'uit/meta_{tag}.json'))
    corr = json.load(open('data/corridor.json'))
    if 'segmenten' not in cache:
        net = sumolib.net.readNet('net/e314.net.xml')
        cache['segmenten'] = {naam: segmenten(net, corr[naam]) for naam in corr}
    van = pd.Timestamp(f"{meta['datum']} {van_arg or meta['van']}")
    tot = pd.Timestamp(f"{meta['datum']} {tot_arg or meta['tot']}")
    M = miv_data.per_minuut(miv_data.lees(meta['datum']))
    M = M[M.ok][['tijd', 'unieke_id', 'q', 'v']]
    S = lees_sim(tag, meta)
    laatste = min(M.tijd.max(), S.tijd.max()) if len(S) else M.tijd.max()
    tot = min(tot, laatste + pd.Timedelta(minutes=1))
    idx = pd.date_range(van, tot - pd.Timedelta(minutes=1), freq='1min')
    log = pd.read_csv(f'uit/log_{tag}.csv') if os.path.exists(f'uit/log_{tag}.csv') else None

    data = dict(titel=f"E314 Aarschot – Leuven · {van:%d/%m/%Y}", tijden=[f'{t:%H:%M}' for t in idx], richtingen=[],
                live=bool(meta.get('live')) and not meta.get('klaar', True),
                bijgewerkt=pd.Timestamp.now().strftime('%H:%M:%S'))
    for naam in ['Leuven', 'Aarschot']:
        c = corr[naam]
        Qm, Vm = (t.reindex(idx) for t in doorsnede_tabel(M, corr, naam))
        Qs, Vs = (t.reindex(idx) for t in doorsnede_tabel(S, corr, naam))
        spits = []
        if log is not None and len(log):
            l = log[log.richting == naam].drop_duplicates('tijd', keep='last').set_index('tijd').spitsstrook
            spits = [int(l.get(f'{t:%H:%M}', 0)) for t in idx]
        data['richtingen'].append(dict(
            naam=naam,
            doorsneden=[dict(naam=d['naam'], kmp=d['kmp'], x=round(d['x'] / 1000, 2)) for d in c['doorsneden']],
            segmenten=cache['segmenten'][naam],
            vm=[[r(v) for v in rij] for rij in Vm.values], vs=[[r(v) for v in rij] for rij in Vs.values],
            qm=[[r(v) for v in rij] for rij in Qm.values], qs=[[r(v) for v in rij] for rij in Qs.values],
            ttm=[r(v, 2) for v in reistijd(Vm, corr, naam).rolling(3, min_periods=1).mean()],
            tts=[r(v, 2) for v in reistijd(Vs, corr, naam).rolling(3, min_periods=1).mean()],
            spits=spits,
            ramps=[dict(naam=complexnaam(t), soort='op', x=round(t['x'] / 1000, 2)) for t in c['opritten']] +
                  [dict(naam=complexnaam(t), soort='af', x=round(t['x'] / 1000, 2)) for t in c['afritten']],
        ))
    data['rss'] = rss_viewer(meta['datum'], idx)
    # radiobericht per minuut, op basis van de metingen (de 'waarheid' van dat moment)
    tabel = {}
    for R in data['richtingen']:
        _, Vm = doorsnede_tabel(M, corr, R['naam'])
        Vm = Vm.reindex(idx)
        tabel[R['naam']] = (Vm, reistijd(Vm, corr, R['naam']), R['spits'])
    data['radio'] = [radiotekst.bericht(tabel, corr, i, f'{t:%H.%M} uur', meldingen_corridor(meta['datum'], t))
                     for i, t in enumerate(idx)]
    data['incidenten'] = incidenten_viewer(meta['datum'], idx)
    return data, meta


def schrijf_atomair(pad, tekst):
    tmp = pad + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(tekst)
    os.replace(tmp, pad)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', required=True)
    ap.add_argument('--van'); ap.add_argument('--tot')
    ap.add_argument('--live', action='store_true',
                    help='HTML laadt uit/viewer_<tag>_data.js en ververst; dit script werkt dat bestand bij tot de run klaar is')
    ap.add_argument('--interval', type=int, default=30, help='seconden tussen updates (--live)')
    a = ap.parse_args()
    os.chdir(HIER)
    sjabloon = open(os.path.join(HIER, 'viewer_sjabloon.html'), encoding='utf-8').read()
    pad = f'uit/viewer_{a.tag}.html'
    if not a.live:
        data, _ = bouw_data(a.tag, a.van, a.tot)
        schrijf_atomair(pad, sjabloon.replace('/*DATA*/null', json.dumps(data, separators=(',', ':'))))
        print(pad, f'{os.path.getsize(pad) / 1e6:.1f} MB', len(data['tijden']), 'minuten')
        return
    datajs = f'viewer_{a.tag}_data.js'
    schrijf_atomair(pad, sjabloon.replace('/*LIVE*/null', json.dumps(datajs)))
    print('open', os.path.abspath(pad), flush=True)
    while True:
        try:
            data, meta = bouw_data(a.tag, a.van, a.tot)
            schrijf_atomair('uit/' + datajs, 'window.VIEWER_DATA=' + json.dumps(data, separators=(',', ':')) + ';')
            print(data['bijgewerkt'], 'laatste minuut', data['tijden'][-1] if data['tijden'] else '-', flush=True)
            if meta.get('klaar'):
                break
        except Exception as e:  # bestand half geschreven of nog geen data: volgende keer opnieuw
            print('fout:', e, flush=True)
        time.sleep(a.interval)


if __name__ == '__main__':
    main()
