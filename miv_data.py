"""Inlezen en aggregeren van de gelogde MIV-minuutdata (zie miv_logger.py)."""
import glob, os
import numpy as np
import pandas as pd

HIER = os.path.dirname(os.path.abspath(__file__))
AUTO, VRACHT = (1, 2, 3), (4, 5)  # klasse 1 moto, 2 auto, 3 bestelwagen, 4 vrachtwagen, 5 vrachtwagen+aanhanger


def lees(datum):
    pad = os.path.join(HIER, 'data', 'live', f'miv_{datum}.csv')
    d = pd.read_csv(pad, dtype={'unieke_id': str})
    d['tijd'] = pd.to_datetime(d['tijd'].str[:19])
    return d


def per_minuut(d):
    """Eén rij per (tijd, unieke_id): q_auto, q_vracht, v (harmonisch, stroom-gewogen), bezetting, ok."""
    d = d.copy()
    d['ok'] = (d.beschikbaar == 1) & (d.defect == 0)
    geldig_v = (d.q > 0) & (d.v_harm > 0) & (d.v_harm < 250)
    d['q_over_v'] = np.where(geldig_v, d.q / d.v_harm.clip(lower=1), 0.0)
    d['q_v'] = np.where(geldig_v, d.q, 0)
    d['is_auto'] = d.klasse.isin(AUTO)
    g = d.groupby(['tijd', 'unieke_id'])
    out = pd.DataFrame({
        'q_auto': d[d.is_auto].groupby(['tijd', 'unieke_id']).q.sum(),
        'q_vracht': d[~d.is_auto].groupby(['tijd', 'unieke_id']).q.sum(),
        'som_q_over_v': g.q_over_v.sum(), 'som_qv': g.q_v.sum(),
        'bezetting': g.bezetting.first(), 'ok': g.ok.first(),
    }).fillna({'q_auto': 0, 'q_vracht': 0})
    out['q'] = out.q_auto + out.q_vracht
    out['v'] = np.where(out.som_qv > 0, out.som_qv / out.som_q_over_v.replace(0, np.nan), np.nan)  # km/u
    return out.reset_index()
