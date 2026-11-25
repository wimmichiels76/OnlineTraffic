"""Online SUMO-model E314 Aarschot-Leuven, gevoed door de MIV-minuutdata.

    python sim_online.py --datum 2026-11-24 --van 16:00 --tot 19:00            (herspelen)
    python sim_online.py --datum 2026-11-24 --van 16:00 --tot 19:00 --live     (volgt de logger)

Werking per minuut m:
  * instroom = gemeten telling op de eerste meetdoorsnede (hoofdbaan) + elke oprit, per auto/vracht,
    gelijkmatig gespreid over de minuut;
  * elk voertuig krijgt een afrit via sequentiële afsplitsing: p_afrit = afrit / (balans hoofdbaan op dat punt),
    berekend op een voortschrijdend venster van 5 minuten;
  * spitsstrook (strook 0) open/dicht volgens de S09-lussen van die richting (5 min venster);
  * stroomafwaartse rand: gemeten snelheid van de laatste meetdoorsnede als maximumsnelheid op de laatste edge
    (file die van buiten het model terugslaat);
  * de binnenste meetdoorsneden worden NIET gebruikt als invoer: ze dienen enkel om te valideren.
"""
import argparse, datetime as dt, json, os, random, sys, time
import numpy as np
import pandas as pd

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
import miv_data  # noqa: E402
import rss_model  # noqa: E402
import datex_model  # noqa: E402

if 'SUMO_HOME' in os.environ:
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))
import sumolib  # noqa: E402
import traci  # noqa: E402

VENSTER = 5  # minuten voor afrit-aandelen en spitsstrookstatus
DICHT = ['passenger', 'truck', 'trailer', 'delivery', 'motorcycle', 'bus', 'coach']


def schrijf_additionals(corr, pad, tag, lc=''):
    """e1-lussen op alle meetdoorsneden (enkel validatie) + voertuigtypes."""
    with open(pad, 'w', encoding='utf-8') as f:
        f.write('<additional>\n')
        f.write('  <vType id="auto" vClass="passenger" length="4.6" maxSpeed="42" speedDev="0.1" tau="1.0" '
                f'lcSpeedGain="1.0" lcKeepRight="1.0" {lc}/>\n')
        f.write('  <vType id="vracht" vClass="truck" length="15" maxSpeed="25" speedDev="0.05" accel="0.6" decel="3.5" '
                f'tau="1.2" {lc}/>\n')
        f.write('  <vType id="ongeval" vClass="authority" length="10" maxSpeed="1" color="1,0,1"/>\n')
        for naam, c in corr.items():
            for d in c['doorsneden']:
                for uid, lane in d['lanes'].items():
                    f.write(f'  <inductionLoop id="{uid}" lane="{d["edge"]}_{lane}" pos="{d["pos"]:.1f}" '
                            f'period="60" file="../uit/e1_{tag}.xml"/>\n')
        f.write('</additional>\n')


def routes_bouwen(net, corr):
    """Per richting: lijst van ingangen en uitgangen met hun edge-pad."""
    R = {}
    for naam, c in corr.items():
        route = c['route']
        idx = {e: i for i, e in enumerate(route)}
        eind_pos = c['doorsneden'][-1]['pos'] + 30
        ing = [dict(soort='hoofd', ids=list(c['doorsneden'][0]['lanes']), x=c['doorsneden'][0]['x'], pad=[], i=0,
                    naam='begin ' + c['doorsneden'][0]['naam'])]
        for t in c['opritten']:
            ing.append(dict(soort='oprit', ids=t['ids'], x=t['x'], pad=t['pad'], i=idx[t['hoofd_edge']], naam=t['naam']))
        uit = [dict(soort='afrit', ids=t['ids'], x=t['x'], pad=t['pad'], i=idx[t['hoofd_edge']], naam=t['naam'])
               for t in c['afritten']]
        uit.sort(key=lambda u: u['x'])
        events = sorted([('op', k, g) for k, g in enumerate(ing[1:], 1)] + [('af', k, u) for k, u in enumerate(uit)],
                        key=lambda e: e[2]['x'])
        R[naam] = dict(ing=ing, uit=uit, route=route, eind_pos=min(eind_pos, net.getEdge(route[-1]).getLength() - 1),
                       events=events)
        # controle op connectiviteit
        for g in ing:
            for u in uit + [None]:
                if u is not None and u['x'] <= g['x']:
                    continue
                edges = pad_voor(R[naam], g, u)
                for a, b in zip(edges, edges[1:]):
                    if net.getEdge(b) not in net.getEdge(a).getOutgoing():
                        raise SystemExit(f'route niet verbonden {naam}: {a}->{b} ({g["naam"]} -> {u and u["naam"]})')
    return R


def pad_voor(r, g, u):
    route = r['route']
    eind = (u['i'] + 1) if u else len(route)
    return g['pad'] + route[g['i']:eind] + (u['pad'] if u else [])


def venster_som(M, ids, t, kol='q'):
    sel = M[(M.tijd > t - pd.Timedelta(minutes=VENSTER)) & (M.tijd <= t) & M.unieke_id.isin(ids)]
    return sel[kol].sum(), sel.tijd.nunique()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datum', default=str(dt.date.today()))
    ap.add_argument('--van', required=True)
    ap.add_argument('--tot', required=True)
    ap.add_argument('--opwarm', type=int, default=15, help='minuten opwarmtijd voor --van')
    ap.add_argument('--live', action='store_true')
    ap.add_argument('--gui', action='store_true')
    ap.add_argument('--tag', default='run')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--zonder-rss', action='store_true', help='rijstrooksignalisatie niet toepassen')
    ap.add_argument('--zonder-datex', action='store_true', help='DATEX-meldingen (ongeval, werken) niet toepassen')
    ap.add_argument('--rss-naleving', type=float, default=1.0, help='gereden snelheid = factor x bordsnelheid')
    ap.add_argument('--lc', default='', help='extra strookwisselparameters voor auto en vracht, bv. '
                    '"lcCooperative=1 lcCooperativeSpeed=1 lcAssertive=1.5"')
    a = ap.parse_args()
    random.seed(a.seed)
    os.chdir(HIER)
    os.makedirs('uit', exist_ok=True)

    corr = json.load(open('data/corridor.json'))
    net = sumolib.net.readNet('net/e314.net.xml')
    R = routes_bouwen(net, corr)
    add = f'net/e314_{a.tag}.add.xml'
    lc = ' '.join(f'{k}="{v}"' for k, v in (p.split('=') for p in a.lc.split())) if a.lc else ''
    schrijf_additionals(corr, add, a.tag, lc)

    t0 = pd.Timestamp(f'{a.datum} {a.van}') - pd.Timedelta(minutes=a.opwarm)
    t1 = pd.Timestamp(f'{a.datum} {a.tot}')
    spitsstrook = {}
    for naam, c in corr.items():
        edges = {d['edge'] for d in c['doorsneden'] if any(s == 'S09' for s in d['strook'].values())}
        edges |= {e for e in c['route'] if e.split('.')[0] in {'345078863', '39965901', '26435873', '474453521', '474453518'}}
        # enkel 'zuivere' hoofdbaanstukken sluiten: geen in- of uitvoegende tak (anders blokkeert strook 0 een afrit)
        edges = {e for e in edges if len(net.getEdge(e).getOutgoing()) == 1 and len(net.getEdge(e).getIncoming()) == 1}
        s09 = [u for d in c['doorsneden'] for u, s in d['strook'].items() if s == 'S09']
        spitsstrook[naam] = dict(edges=sorted(edges), s09=s09, open=None)

    sumo = sumolib.checkBinary('sumo-gui' if a.gui else 'sumo')
    traci.start([sumo, '-n', 'net/e314.net.xml', '-a', add, '--begin', '0',
                 '--step-length', '0.5', '--no-step-log', '--time-to-teleport', '300', '--seed', str(a.seed),
                 '--edgedata-output', f'uit/edgedata_{a.tag}.xml',
                 '--tripinfo-output', f'uit/tripinfo_{a.tag}.xml', '--device.tripinfo.probability', '1',
                 '--statistic-output', f'uit/stat_{a.tag}.xml', '--duration-log.statistics',
                 '--lateral-resolution', '0'])
    meta = dict(t0=str(t0), van=a.van, tot=a.tot, datum=a.datum, live=a.live, klaar=False)
    json.dump(meta, open(f'uit/meta_{a.tag}.json', 'w'))
    log = open(f'uit/log_{a.tag}.csv', 'w')
    log.write('tijd,richting,instroom,ingevoegd_wacht,spitsstrook,v_rand,rss,meldingen\n')
    rss = None if a.zonder_rss else rss_model.RSS(net, corr, traci, a.rss_naleving)
    mel = None if a.zonder_datex else datex_model.Meldingen(net, corr, traci)
    regelaar = datex_model.Regelaar(traci)
    rss_data, datex_d, datex_a = None, None, None
    # per minuut de lussen uitlezen (de e1-xml schrijft SUMO pas weg bij het afsluiten);
    # let op: TraCI geeft de rekenkundige gemiddelde snelheid, de e1-xml de harmonische
    simlus = open(f'uit/sim_minuut_{a.tag}.csv', 'w')
    simlus.write('tijd,unieke_id,q,v\n')
    lussen = traci.inductionloop.getIDList()

    n_veh = 0
    m = t0
    while m < t1:
        # ---- data voor minuut m ophalen (live: wachten tot de logger ze heeft)
        while True:
            if a.live or m == t0:
                M_alles = miv_data.per_minuut(miv_data.lees(a.datum))
            if (M_alles.tijd >= m).any() or not a.live:
                break
            time.sleep(15)
        M = M_alles[M_alles.ok]
        rss_tekst, w_rss, w_mel, mel_tekst = {}, {}, {}, []
        if rss is not None:
            if a.live or rss_data is None:
                rss_data = rss_model.lees(a.datum)
            w_rss, rss_tekst = rss.gewenst(rss_model.toestand(rss_data, m))
        if mel is not None:
            if a.live or datex_d is None:
                datex_d, datex_a = datex_model.lees(a.datum)
            w_mel, blok, mel_tekst = mel.gewenst(datex_model.actief(datex_d, datex_a, m))
            mel.blokkeer(blok)
        regelaar.pas_toe(datex_model.Regelaar.samen(w_rss, w_mel), a.rss_naleving)
        sim_t = (m - t0).total_seconds()
        for naam, r in R.items():
            # afrit-aandelen via balans
            F, _ = venster_som(M, r['ing'][0]['ids'], m)
            p = {}
            for soort, k, obj in r['events']:
                q, _ = venster_som(M, obj['ids'], m)
                if soort == 'op':
                    F += q
                else:
                    p[k] = min(0.95, q / F) if F > 0 else 0.0
                    F -= min(q, F)
            # instroom deze minuut
            Mm = M[M.tijd == m]
            totaal = 0
            for g in r['ing']:
                sel = Mm[Mm.unieke_id.isin(g['ids'])]
                n_a, n_v = int(sel.q_auto.sum()), int(sel.q_vracht.sum())
                v_in = sel.v.mean() if g['soort'] == 'hoofd' else np.nan
                v_in = 'max' if not np.isfinite(v_in) else f'{max(v_in, 10) / 3.6:.1f}'
                types = ['auto'] * n_a + ['vracht'] * n_v
                random.shuffle(types)
                for j, typ in enumerate(types):
                    u = None
                    for k, uu in enumerate(r['uit']):
                        if uu['x'] > g['x'] and random.random() < p.get(k, 0):
                            u = uu
                            break
                    rid = f'r_{naam}_{r["ing"].index(g)}_{r["uit"].index(u) if u else "eind"}'
                    if rid not in traci.route.getIDList():
                        traci.route.add(rid, pad_voor(r, g, u))
                    vid = f'{naam[0]}{n_veh}'
                    n_veh += 1
                    traci.vehicle.add(vid, rid, typeID=typ, depart=f'{sim_t + (j + random.random()) * 60 / max(1, len(types)):.1f}',
                                      departLane='best', departSpeed=(v_in if typ == 'auto' or v_in == 'max' else f'{min(float(v_in), 24.5):.1f}') if g['soort'] == 'hoofd' else 'max',
                                      arrivalPos=f'{r["eind_pos"]:.1f}' if u is None else 'max')
                totaal += len(types)
            # spitsstrook
            s = spitsstrook[naam]
            q09, nmin = venster_som(M, s['s09'], m)
            is_open = nmin > 0 and q09 / max(1, len(s['s09'])) / nmin >= 0.5  # >= 0.5 vtg/min per lus
            if is_open != s['open']:
                for e in s['edges']:
                    traci.lane.setDisallowed(f'{e}_0', [] if is_open else DICHT)
                s['open'] = is_open
            # stroomafwaartse rand
            laatste = corr[naam]['doorsneden'][-1]
            sel = M[(M.tijd > m - pd.Timedelta(minutes=3)) & (M.tijd <= m) & M.unieke_id.isin(list(laatste['lanes']))]
            v_rand = (sel.q.sum() / (sel.q / sel.v).sum()) if sel.q.sum() > 0 and sel.v.notna().all() else np.nan
            vmax = 120 if not np.isfinite(v_rand) or v_rand > 90 else max(v_rand, 10)
            traci.edge.setMaxSpeed(r['route'][-1], vmax / 3.6)
            log.write(f'{m:%H:%M},{naam},{totaal},{traci.simulation.getMinExpectedNumber()},{int(is_open)},{v_rand:.0f},{rss_tekst.get(naam, '')},{' '.join(t for t in mel_tekst if '@' + naam in t)}\n')
        if mel is not None and mel.zone_tau:
            for k in range(1, 13):  # in stappen van 5 s, zodat voertuigen in een werfzone hun tau krijgen
                traci.simulationStep(sim_t + 5 * k)
                mel.pas_tau_toe()
        else:
            traci.simulationStep(sim_t + 60)
        for lid in lussen:
            v = traci.inductionloop.getLastIntervalMeanSpeed(lid)
            n = traci.inductionloop.getLastIntervalVehicleNumber(lid)
            simlus.write(f'{m:%Y-%m-%d %H:%M},{lid},{n},{v * 3.6:.1f}\n' if v >= 0 and n > 0
                         else f'{m:%Y-%m-%d %H:%M},{lid},{n},\n')
        simlus.flush()
        log.flush()
        if m.minute % 10 == 0:
            print(f'{m:%H:%M}  in netwerk {traci.vehicle.getIDCount():5d}  spits L/A '
                  f'{int(spitsstrook["Leuven"]["open"])}/{int(spitsstrook["Aarschot"]["open"])}', flush=True)
        m += pd.Timedelta(minutes=1)
    traci.close()
    log.close()
    simlus.close()
    meta['klaar'] = True
    json.dump(meta, open(f'uit/meta_{a.tag}.json', 'w'))


if __name__ == '__main__':
    main()
