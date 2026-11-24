"""Vergelijkt een simulatierun met de MIV-metingen: tijd-ruimtediagram snelheid, debieten, reistijd, filedetectie.

    python vergelijk.py --tag live_2026-11-24 [--van 15:00 --tot 20:00]
"""
import argparse, json, os, sys
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
import miv_data  # noqa: E402

FILE = 60  # km/u: grens voor "file"-cel
CMAP = LinearSegmentedColormap.from_list('v', ['#7a0019', '#d7301f', '#fc8d59', '#fee08b', '#d9ef8b', '#1a9850'])


def lees_e1(pad, t0):
    rows = []
    for _, el in ET.iterparse(pad):
        if el.tag == 'interval':
            rows.append((float(el.get('begin')), el.get('id'), int(float(el.get('nVehContrib'))),
                         float(el.get('harmonicMeanSpeed'))))
            el.clear()
    d = pd.DataFrame(rows, columns=['t', 'unieke_id', 'q', 'v'])
    d['tijd'] = pd.Timestamp(t0) + pd.to_timedelta(d.t, unit='s')
    d['v'] = np.where(d.v > 0, d.v * 3.6, np.nan)
    return d


def doorsnede_tabel(D, corr, naam):
    """(tijd x doorsnede) tabellen met q (vtg/u) en v (km/u, stroomgewogen harmonisch over de stroken)."""
    ds = corr[naam]['doorsneden']
    Q, V = {}, {}
    for k, d in enumerate(ds):
        sel = D[D.unieke_id.isin(list(d['lanes']))].copy()
        sel['q_over_v'] = np.where(sel.v > 0, sel.q / sel.v, 0)
        sel['qv'] = np.where(sel.v > 0, sel.q, 0)
        g = sel.groupby('tijd')
        Q[k] = g.q.sum() * 60
        V[k] = g.qv.sum() / g.q_over_v.sum().replace(0, np.nan)
    return pd.DataFrame(Q), pd.DataFrame(V)


def reistijd(V, corr, naam):
    x = np.array([d['x'] for d in corr[naam]['doorsneden']]) / 1000
    dx = np.diff(np.r_[x[0], (x[1:] + x[:-1]) / 2, x[-1]])  # elke doorsnede vertegenwoordigt zijn halve afstanden
    leeg = V.notna().sum(axis=1) < 0.5 * V.shape[1]  # minder dan de helft van de lussen: geen reistijd
    v = V.clip(lower=5).ffill(axis=1).bfill(axis=1).fillna(110)
    tt = (v.rdiv(1).mul(dx, axis=1)).sum(axis=1) * 60  # minuten
    return tt.mask(leeg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', required=True)
    ap.add_argument('--van'); ap.add_argument('--tot')
    a = ap.parse_args()
    os.chdir(HIER)
    meta = json.load(open(f'uit/meta_{a.tag}.json'))
    corr = json.load(open('data/corridor.json'))
    van = pd.Timestamp(f"{meta['datum']} {a.van or meta['van']}")
    tot = pd.Timestamp(f"{meta['datum']} {a.tot or meta['tot']}")

    M = miv_data.per_minuut(miv_data.lees(meta['datum']))
    M = M[M.ok][['tijd', 'unieke_id', 'q', 'v']]
    S = lea = lees_e1(f'uit/e1_{a.tag}.xml', meta['t0'])
    rapport = [f'# Vergelijking {a.tag}  ({van:%d/%m %H:%M} - {tot:%H:%M})\n']

    fig, axs = plt.subplots(4, 2, figsize=(16, 17), gridspec_kw=dict(height_ratios=[3, 3, 1.6, 1.6]))
    for kol, naam in enumerate(['Leuven', 'Aarschot']):
        ds = corr[naam]['doorsneden']
        x = np.array([d['x'] for d in ds]) / 1000
        Qm, Vm = doorsnede_tabel(M, corr, naam)
        Qs, Vs = doorsnede_tabel(S, corr, naam)
        idx = pd.date_range(van, tot - pd.Timedelta(minutes=1), freq='1min')
        Qm, Vm, Qs, Vs = (t.reindex(idx) for t in (Qm, Vm, Qs, Vs))
        # tijd-ruimtediagrammen
        for rij, (V, titel) in enumerate([(Vm, 'gemeten'), (Vs, 'SUMO')]):
            ax = axs[rij, kol]
            t_num = (idx - idx[0]).total_seconds() / 60
            pc = ax.pcolormesh(idx, x, V.T.values, cmap=CMAP, vmin=0, vmax=120, shading='nearest')
            ax.set_title(f'Richting {naam} – snelheid {titel}')
            ax.set_ylabel('km stroomafwaarts →')
            gezien = set()
            for d, xx in zip(ds, x):
                kort = d['naam'].replace('Complex nr ', 'nr ').replace('complex nr', 'nr ').replace('complex ', '')
                if d['naam'].lower().startswith(('complex', 'parking')) and kort not in gezien:
                    gezien.add(kort)
                    ax.axhline(xx, color='k', lw=0.4, alpha=0.4)
                    ax.text(idx[0], xx, ' ' + kort[:18], fontsize=7, va='bottom', alpha=0.8)
            fig.colorbar(pc, ax=ax, label='km/u')
        # reistijd
        ax = axs[2, kol]
        TTm, TTs = reistijd(Vm, corr, naam), reistijd(Vs, corr, naam)
        ax.plot(idx, TTm.rolling(3, min_periods=1).mean(), label='gemeten (lussen)', color='k')
        ax.plot(idx, TTs.rolling(3, min_periods=1).mean(), label='SUMO', color='#d7301f')
        ax.set_ylabel('reistijd (min)'); ax.legend(); ax.set_title(f'Reistijd {x[0]:.1f}–{x[-1]:.1f} km (momentaan)')
        # debiet op een paar doorsneden (15 min)
        ax = axs[3, kol]
        for k, kleur in zip([0, len(ds) // 2, len(ds) - 1], ['#1b9e77', '#7570b3', '#d95f02']):
            ax.plot(idx, Qm[k].rolling(15, min_periods=5).mean(), color=kleur, label=f'{ds[k]["naam"][:22]} gemeten')
            ax.plot(idx, Qs[k].rolling(15, min_periods=5).mean(), color=kleur, ls='--', label='… SUMO')
        ax.set_ylabel('vtg/u (15 min)'); ax.legend(fontsize=7, ncol=2)

        # kengetallen
        geldig = Vm.notna() & Vs.notna()
        fm, fs = (Vm < FILE) & geldig, (Vs < FILE) & geldig
        hit = (fm & fs).sum().sum() / max(1, fm.sum().sum())
        vals = (fs & ~fm).sum().sum() / max(1, fs.sum().sum())
        rmse = np.sqrt(((Vm - Vs)[geldig] ** 2).mean().mean())
        Qm15, Qs15 = Qm.resample('15min').mean(), Qs.resample('15min').mean()
        geh = np.sqrt(2 * (Qm15 - Qs15) ** 2 / (Qm15 + Qs15)).stack()
        rapport += [f'## Richting {naam}',
                    f'- filecellen gemeten (v<{FILE}): {fm.sum().sum()} van {geldig.sum().sum()} doorsnede-minuten',
                    f'- filecellen SUMO: {fs.sum().sum()}  | trefkans {hit:.0%}  | vals alarm {vals:.0%}',
                    f'- RMSE snelheid: {rmse:.1f} km/u',
                    f'- debiet 15 min: GEH<5 voor {(geh < 5).mean():.0%} van de doorsnede-kwartieren',
                    f'- reistijd gemeten gem/max {TTm.mean():.1f}/{TTm.max():.1f} min, SUMO {TTs.mean():.1f}/{TTs.max():.1f} min', '']
    fig.tight_layout()
    fig.savefig(f'uit/vergelijking_{a.tag}.png', dpi=110)
    open(f'uit/vergelijking_{a.tag}.md', 'w', encoding='utf-8').write('\n'.join(rapport))
    print('\n'.join(rapport))


if __name__ == '__main__':
    main()
