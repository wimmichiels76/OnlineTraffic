"""Verdeling over de rijstroken per meetdoorsnede: gemeten (MIV) tegenover het model (e1-lussen).

    python analyse/stroken.py --tag tau1.75_2026-11-24 [--richting Aarschot] [--van 16:00 --tot 19:00]

Per doorsnede en per strook: aandeel in het debiet en de harmonische snelheid. Stroken van rechts naar links
(S09 spitsstrook / R09 weefstrook eerst, dan R10, R11, ...).
"""
import argparse, json, os, sys
import numpy as np
import pandas as pd

HIER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HIER)
import miv_data  # noqa: E402
from vergelijk import lees_e1  # noqa: E402


def per_strook(D, ids):
    d = D[D.unieke_id.isin(ids)]
    q = d.groupby('unieke_id').q.sum()
    w = d[(d.v > 0) & (d.q > 0)]
    v = w.groupby('unieke_id').apply(lambda x: x.q.sum() / (x.q / x.v).sum(), include_groups=False)
    return q, v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', required=True)
    ap.add_argument('--richting', default='Aarschot')
    ap.add_argument('--van', default='16:00')
    ap.add_argument('--tot', default='19:00')
    a = ap.parse_args()
    os.chdir(HIER)
    meta = json.load(open(f'uit/meta_{a.tag}.json'))
    corr = json.load(open('data/corridor.json'))[a.richting]
    t0, t1 = pd.Timestamp(f"{meta['datum']} {a.van}"), pd.Timestamp(f"{meta['datum']} {a.tot}")
    G = miv_data.per_minuut(miv_data.lees(meta['datum']))
    G = G[G.ok & (G.tijd >= t0) & (G.tijd < t1)]
    S = lees_e1(f'uit/e1_{a.tag}.xml', meta['t0'])
    S = S[(S.tijd >= t0) & (S.tijd < t1)]
    uren = (t1 - t0).total_seconds() / 3600
    print(f"richting {a.richting}, {a.van}-{a.tot}: per strook debiet (vtg/u), aandeel en snelheid (km/u); gemeten | model")
    for d in corr['doorsneden']:
        ids = sorted(d['strook'], key=lambda u: (0 if d['strook'][u].startswith('S') else 1, d['strook'][u]))
        qg, vg = per_strook(G, ids)
        qs, vs = per_strook(S, ids)
        if qg.sum() == 0:
            continue
        print(f"\n{d['x'] / 1000:5.1f} km  {d['naam']}")
        for u in ids:
            print(f"   {d['strook'][u]:<4} {qg.get(u, 0) / uren:5.0f} {qg.get(u, 0) / qg.sum():4.0%} {vg.get(u, np.nan):4.0f}"
                  f"  |  {qs.get(u, 0) / uren:5.0f} {qs.get(u, 0) / max(1, qs.sum()):4.0%} {vs.get(u, np.nan):4.0f}")


if __name__ == '__main__':
    main()
