"""Voorleesbaar verkeersbericht (radiostijl) voor de E314 Aarschot - Leuven.

    python radiotekst.py --tag live_2026-11-24                 # laatste minuut, op basis van de metingen
    python radiotekst.py --tag live_2026-11-24 --tijd 17:30
    python radiotekst.py --tag live_2026-11-24 --bron model    # op basis van de SUMO-simulatie

Regels:
  * file      = aaneengesloten stuk van minstens 1 km waar de snelheid (3 min gemiddeld) onder 60 km/u ligt;
                kop en staart krijgen de naam van het dichtstbijzijnde complex;
  * verliestijd = momentane reistijd over de corridor min de reistijd aan 115 km/u, afgerond op hele minuten;
                  vanaf 2 minuten wordt ze vermeld;
  * oorzaak   = actieve DATEX-melding (ongeval, werken, obstakel) in de file of tot 1 km vóór de kop;
  * trend     = verliestijd nu tegenover 10 minuten eerder (groeit/neemt af bij >= 2 min verschil).
"""
import argparse, json, os, sys
import numpy as np
import pandas as pd

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)

V_FILE, MIN_LENGTE, V_VRIJ, MIN_VERLIES, MAX_GAT = 60, 1000, 115, 2, 500
WOORDEN = ['nul', 'een', 'twee', 'drie', 'vier', 'vijf', 'zes', 'zeven', 'acht', 'negen', 'tien', 'elf', 'twaalf',
           'dertien', 'veertien', 'vijftien', 'zestien', 'zeventien', 'achttien', 'negentien', 'twintig']
PLAATS = {'A00213': 'Aarschot', 'A00294': 'Rotselaar', 'A00214': 'Holsbeek', 'A00215': 'Wilsele',
          'A00217': 'Herent', 'A00218': 'Winksele', 'A00219': 'Gasthuisberg', 'A00220': 'Leuven'}
OORZAAK = {'Accident': 'een ongeval', 'MaintenanceWorks': 'wegenwerken',
           'RoadOrCarriagewayOrLaneManagement': 'een werfinrichting', 'EnvironmentalObstruction': 'een verzakking'}


def getal(n):
    return WOORDEN[n] if 0 <= n < len(WOORDEN) else str(n)


def plaatsen(c):
    """(x, naam) van de complexen langs de rijbaan, plus begin en eind."""
    p = [(t['x'], PLAATS.get(t['ident'][:6])) for t in c['opritten'] + c['afritten']]
    return sorted((x, n) for x, n in p if n)


def dichtste(pl, x):
    return min(pl, key=lambda q: abs(q[0] - x))[1]


def files(v, xs):
    """Aaneengesloten stukken met v < V_FILE -> [(x_staart, x_kop)] (x stijgt stroomafwaarts)."""
    stukken, start = [], None
    grenzen = np.r_[xs[0], (xs[1:] + xs[:-1]) / 2, xs[-1]]
    for k, val in enumerate(list(v) + [np.nan]):
        traag = val == val and val < V_FILE
        if traag and start is None:
            start = k
        if not traag and start is not None:
            stukken.append([grenzen[start], grenzen[k]])
            start = None
    samen = []  # stukken met een kort vlot gat (één snellere lus) samenvoegen
    for a, b in stukken:
        if samen and a - samen[-1][1] < MAX_GAT:
            samen[-1][1] = b
        else:
            samen.append([a, b])
    return [(a, b) for a, b in samen if b - a >= MIN_LENGTE]


def bericht_richting(naam, c, V, TT, i, meldingen, spits):
    """Eén zin (of enkele) voor één rijrichting op minuut-index i."""
    xs = np.array([d['x'] for d in c['doorsneden']])
    pl = plaatsen(c)
    v = V.iloc[max(0, i - 2): i + 1].mean()  # 3 minuten
    if v.notna().sum() < 0.5 * len(v):
        return f'Richting {naam}: geen betrouwbare meetgegevens.'
    lengte = c['doorsneden'][-1]['x'] - c['doorsneden'][0]['x']
    tt_vrij = lengte / 1000 / V_VRIJ * 60
    verlies = TT.iloc[i] - tt_vrij if pd.notna(TT.iloc[i]) else np.nan
    eerder = TT.iloc[i - 10] - tt_vrij if i >= 10 and pd.notna(TT.iloc[i - 10]) else np.nan
    F = files(v.values, xs)
    zinnen = []
    if not F and not (verlies >= MIN_VERLIES):
        zin = f'Richting {naam} rijdt het verkeer vlot'
        if spits:
            zin += ', de spitsstrook is open'
        return zin + '.'
    for j, (a, b) in enumerate(sorted(F, key=lambda f: f[0] - f[1])):  # langste eerst
        km = max(1, round((b - a) / 1000))
        staart, kop = dichtste(pl, a), dichtste(pl, b)
        waar = f'ter hoogte van {kop}' if staart == kop else f'tussen {staart} en {kop}'
        aantal = 'een' if km == 1 else getal(km)
        zin = (f'Richting {naam} staat {aantal} kilometer file {waar}' if j == 0
               else f'Verder staat er nog {aantal} kilometer file {waar}')
        oorzaken = {}
        for m in meldingen:
            if m['richting'] == naam and m['type'] in OORZAAK and a - 500 <= m['x1'] and m['x0'] <= b + 1000:
                oorzaken.setdefault(dichtste(pl, (m['x0'] + m['x1']) / 2), set()).add(OORZAAK[m['type']])
        if oorzaken:
            zin += ', door ' + ' en '.join(f"{' en '.join(sorted(o))} in {p}" for p, o in oorzaken.items())
        zinnen.append(zin + '.')
    if not F:
        zinnen.append(f'Richting {naam} rijdt het verkeer traag.')
    if verlies >= MIN_VERLIES:
        min_ = int(round(verlies))
        zin = f'U verliest er ongeveer {getal(min_)} {"minuut" if min_ == 1 else "minuten"}'
        if eerder == eerder:
            if verlies - eerder >= 2:
                zin += ', en de file groeit'
            elif eerder - verlies >= 2:
                zin += ', maar het wordt rustiger'
        zinnen.append(zin + '.')
    return ' '.join(zinnen)


def bericht(tabel, corr, i, tijd, meldingen):
    """tabel: {richting: (V, TT, spits[])}; meldingen: [{type, richting, x0, x1}] actief op minuut i."""
    delen = [bericht_richting(n, corr[n], *tabel[n][:2], i, meldingen, tabel[n][2][i] if tabel[n][2] else 0)
             for n in ['Leuven', 'Aarschot']]
    if all('vlot' in d for d in delen):
        return f'{tijd}, de E314 tussen Aarschot en Leuven: het verkeer rijdt vlot in beide richtingen.'
    return f'{tijd}, de E314 tussen Aarschot en Leuven. ' + ' '.join(delen)


def main():
    import miv_data, maak_viewer  # noqa: E401
    from vergelijk import doorsnede_tabel, reistijd
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', required=True)
    ap.add_argument('--tijd', help='HH:MM (standaard: laatste minuut)')
    ap.add_argument('--bron', choices=['gemeten', 'model'], default='gemeten')
    a = ap.parse_args()
    os.chdir(HIER)
    meta = json.load(open(f'uit/meta_{a.tag}.json'))
    corr = json.load(open('data/corridor.json'))
    if a.bron == 'gemeten':
        D = miv_data.per_minuut(miv_data.lees(meta['datum']))
        D = D[D.ok]
    else:
        D = maak_viewer.lees_sim(a.tag, meta)
    if a.tijd:
        t1 = pd.Timestamp(f"{meta['datum']} {a.tijd}")
    else:  # laatste minuut waarvoor minstens 80 % van de lussen data heeft
        n = D.groupby('tijd').unieke_id.nunique()
        t1 = n[n >= 0.8 * n.max()].index.max()
    idx = pd.date_range(t1 - pd.Timedelta(minutes=15), t1, freq='1min')
    log = pd.read_csv(f'uit/log_{a.tag}.csv') if os.path.exists(f'uit/log_{a.tag}.csv') else None
    tabel = {}
    for n in ['Leuven', 'Aarschot']:
        _, V = doorsnede_tabel(D, corr, n)
        V = V.reindex(idx)
        spits = []
        if log is not None:
            l = log[log.richting == n].drop_duplicates('tijd', keep='last').set_index('tijd').spitsstrook
            spits = [int(l.get(f'{t:%H:%M}', 0)) for t in idx]
        tabel[n] = (V, reistijd(V, corr, n), spits)
    print(bericht(tabel, corr, len(idx) - 1, f'{t1:%H.%M} uur', maak_viewer.meldingen_corridor(meta['datum'], t1)))


if __name__ == '__main__':
    main()
