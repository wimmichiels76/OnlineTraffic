"""Bouwt data/corridor.json: per rijrichting de hoofdbaanroute, de meetdoorsneden (met SUMO-strook per MIV-strook)
en de op- en afritten (topologisch bepaald) met hun ligging langs de hoofdbaan."""
import csv, json, collections, sumolib
net = sumolib.net.readNet('net/e314.net.xml')
det = [r for r in csv.DictReader(open('data/detectoren_sumo.csv', encoding='utf-8')) if r['edge']]
RICHTING = {'A0020001': 'Leuven', 'A0020002': 'Aarschot'}
STROOKORDE = lambda s: (0 if s.startswith('S') else 1, s)  # S09 rechts van R09 < R10 < R11 ...

GRENZEN = {'A0020001': ('345078862', '19787339'), 'A0020002': ('340093653', '345078859')}

def hoofd_route(ident):
    """Volgt de hoofdbaan (type motorway, niet de takken) van begin- tot eind-edge."""
    a, b = GRENZEN[ident]
    e, route = net.getEdge(a), [a]
    while e.getID() != b:
        mw = [o for o in e.getOutgoing() if o.getType().endswith('.motorway')]
        e = max(mw, key=lambda o: o.getLaneNumber())
        route.append(e.getID())
    return route

corr = {}
for ident, naam in RICHTING.items():
    route = hoofd_route(ident)
    idx = {e: i for i, e in enumerate(route)}
    km = {}; acc = 0
    for e in route: km[e] = acc; acc += net.getEdge(e).getLength()
    doorsneden = collections.defaultdict(list)
    for r in det:
        if r['ident8'] == ident and r['edge'] in idx:
            if r['strook'].startswith('P'): continue  # pechstrook
            doorsneden[(r['naam'], r['kmp'])].append(r)
    ds = []
    for _, rs in doorsneden.items():
        e = max(set(r['edge'] for r in rs), key=[r['edge'] for r in rs].count)
        rs = [r for r in rs if r['edge'] == e]
        n = net.getEdge(e).getLaneNumber()
        rs.sort(key=lambda r: STROOKORDE(r['strook']))
        pos = sum(float(r['pos']) for r in rs) / len(rs)
        lanes = {r['unieke_id']: n - len(rs) + i for i, r in enumerate(rs)}
        lanes = {k: max(0, v) for k, v in lanes.items()}
        ds.append(dict(naam=rs[0]['naam'], kmp=rs[0]['kmp'], edge=e, pos=min(pos, net.getEdge(e).getLength() - 1),
                       x=km[e] + pos, lanes=lanes, strook={r['unieke_id']: r['strook'] for r in rs}))
    ds.sort(key=lambda d: d['x'])
    corr[naam] = dict(ident=ident, route=route, doorsneden=ds, opritten=[], afritten=[], lengte=acc)

def zoek(e0, richting, maxd=8):
    """BFS stroomaf (richting='af') of stroomop ('op') tot een hoofdbaan-edge."""
    seen, q = {e0.getID()}, [(e0, 0, 0.0, [e0.getID()])]
    while q:
        e, d, L, pad = q.pop(0)
        nb = e.getOutgoing() if richting == 'af' else e.getIncoming()
        for o in nb:
            if o.getID() in seen: continue
            seen.add(o.getID())
            for naam, c in corr.items():
                if o.getID() in c['route']:
                    return naam, o.getID(), L, pad if richting == 'af' else pad[::-1]
            if d < maxd and not o.getType().endswith('.motorway'):
                q.append((o, d + 1, L + o.getLength(), pad + [o.getID()]))
    return None

for r in det:
    if r['ident8'] in RICHTING: continue
    e = net.getEdge(r['edge'])
    af, op = zoek(e, 'af'), zoek(e, 'op')
    kand = []
    if af: kand.append(('oprit',) + af)
    if op: kand.append(('afrit',) + op)
    if not kand: print('niet gekoppeld', r['ident8'], r['naam']); continue
    soort, naam, hedge, L, pad = min(kand, key=lambda k: k[3])
    c = corr[naam]
    x = sum(net.getEdge(z).getLength() for z in c['route'][:c['route'].index(hedge)])
    if soort == 'afrit':
        x += net.getEdge(hedge).getLength()  # afrit splitst aan het einde van de hoofdbaan-edge
    elif x < c['doorsneden'][0]['x']:
        print('oprit voor eerste meetdoorsnede (zit al in de instroom):', r['naam']); continue
    lijst = c['opritten' if soort == 'oprit' else 'afritten']
    bestaand = [t for t in lijst if t['edge'] == r['edge']]
    if bestaand: bestaand[0]['ids'].append(r['unieke_id']); continue
    lijst.append(dict(naam=r['naam'], ident=r['ident8'], edge=r['edge'], pos=float(r['pos']), hoofd_edge=hedge, x=x, ids=[r['unieke_id']], pad=pad))

for naam, c in corr.items():
    c['opritten'].sort(key=lambda t: t['x']); c['afritten'].sort(key=lambda t: t['x'])
    print(f"\n== richting {naam}: {len(c['route'])} edges, {c['lengte']/1000:.1f} km")
    for d in c['doorsneden']: print(f"  meet  {d['x']/1000:5.2f} km  {d['naam'][:30]:30} {d['strook']}  -> lanes {list(d['lanes'].values())}")
    for t in c['opritten']: print(f"  OP    {t['x']/1000:5.2f} km  {t['naam'][:30]:30} {t['ident']} {t['edge']}")
    for t in c['afritten']: print(f"  AF    {t['x']/1000:5.2f} km  {t['naam'][:30]:30} {t['ident']} {t['edge']}")
json.dump(corr, open('data/corridor.json', 'w'), indent=1)
