"""Logt de feeds van het Verkeerscentrum voor de E314-corridor:

  * rijstrooksignalisatie (RSS): https://rss-opendata.belfla.be/rss/verkeersdata (elke 2-3 s geactualiseerd)
    -> data/live/rss_YYYY-MM-DD.csv: per minuut en per bord het bevestigde beeld (snelheid, kruis, pijl, ...)
  * DATEX II v3: https://www.verkeerscentrum.be/uitwisseling/datex2v3 (ongevallen, files, werken, strookbeheer)
    -> data/live/datex_YYYY-MM-DD.csv: elke nieuwe versie van een situatie binnen 400 m van een corridorlus

Gebruik: python vc_logger.py --tot 20:30
"""
import argparse, csv, datetime as dt, io, json, math, os, re, sys, time, urllib.request
import xml.etree.ElementTree as ET

HIER = os.path.dirname(os.path.abspath(__file__))
RSS_CONF = 'https://rss-opendata.belfla.be/rss/configuratie/xml'
RSS_DATA = 'https://rss-opendata.belfla.be/rss/verkeersdata'
DATEX = 'https://www.verkeerscentrum.be/uitwisseling/datex2v3'
XSI = '{http://www.w3.org/2001/XMLSchema-instance}type'
AFSTAND = 400  # m: situatie hoort bij de corridor als een punt binnen deze afstand van een MIV-lus ligt


def haal(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'research-script/0.1'})
    with urllib.request.urlopen(req, timeout=50) as r:
        return r.read()


def f(s):
    return float(s.replace(',', '.'))


def corridor_punten():
    """Lambert72-coördinaten van de MIV-lussen van de corridor (uit de MIV-configuratie)."""
    ids = {r['unieke_id'] for r in csv.DictReader(open(os.path.join(HIER, 'data', 'meetpunten_e314.csv'), encoding='utf-8'))}
    pts = []
    for m in ET.parse(os.path.join(HIER, 'data', 'miv_config.xml')).getroot().findall('meetpunt'):
        if m.get('unieke_id') in ids:
            try:
                pts.append((f(m.findtext('X_coord_EPSG_31370')), f(m.findtext('Y_coord_EPSG_31370'))))
            except Exception:
                pass
    return pts


def rss_borden():
    """Borden op de E314 tussen Aarschot en Leuven (zelfde kader als de meetpunten)."""
    root = ET.fromstring(haal(RSS_CONF))
    borden = {}
    for b in root.findall('rss_bord'):
        if not (b.findtext('ident_8') or '').startswith('A002'):
            continue
        lon, lat = f(b.findtext('lengtegraad_EPSG_4326')), f(b.findtext('breedtegraad_EPSG_4326'))
        if 4.64 < lon < 4.86 and 50.855 < lat < 50.975:
            km = re.match(r'A2X([\d.]+)', b.findtext('abbameldanaam') or '')
            borden[b.get('unieke_id')] = dict(ident8=b.findtext('ident_8'), naam=b.findtext('abbameldanaam'),
                                              strook=b.findtext('rijstrook'), km=km.group(1) if km else '',
                                              lon=lon, lat=lat)
    json.dump(borden, open(os.path.join(HIER, 'data', 'rss_borden_e314.json'), 'w'), indent=1)
    return borden


def log_rss(borden, pad):
    root = ET.fromstring(haal(RSS_DATA))
    tijd = root.findtext('tijd_publicatie')
    rijen = []
    for b in root.findall('rss_bord'):
        uid = b.get('unieke_id')
        if uid not in borden:
            continue
        bb, tt = b.find('bevestigde_boodschap'), b.find('technische_toestand')
        rijen.append([tijd, uid, borden[uid]['ident8'], borden[uid]['km'], borden[uid]['strook'],
                      bb.findtext('verkeersteken_status'), bb.findtext('onderbord_status'),
                      bb.findtext('pijl_status'), bb.findtext('knipperlicht_status'),
                      tt.findtext('inDienst'), tt.findtext('defect')])
    schrijf(pad, ['tijd', 'bord_id', 'ident8', 'km', 'strook', 'teken', 'onderbord', 'pijl', 'knipper', 'in_dienst', 'defect'], rijen)
    return len(rijen)


def log_datex(pts, pad, gezien):
    root = ET.fromstring(haal(DATEX))
    rijen, actief = [], []
    for sit in root:
        if not sit.tag.endswith('situation'):
            continue
        for rec in sit:
            if not rec.tag.endswith('situationRecord'):
                continue
            xy = []
            for e in rec.iter():
                tag = e.tag.split('}')[-1]
                if tag == 'posList':
                    v = list(map(float, e.text.split()))
                    xy += list(zip(v[0::2], v[1::2]))
            lat = [float(e.text) for e in rec.iter() if e.tag.endswith('}latitude')]
            lon = [float(e.text) for e in rec.iter() if e.tag.endswith('}longitude')]
            xy += list(zip(lon, lat))  # Lambert72: 'longitude' = x, 'latitude' = y
            if not xy:
                continue
            dmin = min(math.hypot(x - a, y - b) for x, y in xy[::3] or xy for a, b in pts)
            if dmin > AFSTAND:
                continue
            actief.append(rec.get('id'))
            versie = rec.findtext('{http://datex2.eu/schema/3/situation}situationRecordVersionTime')
            sleutel = (rec.get('id'), versie)
            if sleutel in gezien:
                continue
            gezien.add(sleutel)
            det = {e.tag.split('}')[-1]: e.text for e in rec.iter()
                   if e.tag.split('}')[-1] in ('abnormalTrafficType', 'queueLength', 'accidentType', 'roadMaintenanceType',
                                               'roadOrCarriagewayOrLaneManagementType', 'alertCDirectionCoded',
                                               'overallStartTime', 'overallEndTime', 'validityStatus',
                                               'environmentalObstructionType', 'specificLocation')}
            rijen.append([dt.datetime.now().isoformat(timespec='seconds'), sit.get('id'), rec.get('id'), versie,
                          (rec.get(XSI) or '').split(':')[-1], round(dmin), json.dumps(det, ensure_ascii=False),
                          json.dumps([[round(x), round(y)] for x, y in xy])])
    schrijf(pad, ['gelogd', 'situatie', 'record', 'versie', 'type', 'afstand_m', 'details', 'lambert72_xy'], rijen)
    # momentopname: welke corridorsituaties staan er nu in de feed (zo weet de viewer wanneer iets voorbij is)
    schrijf(pad.replace('datex_', 'datex_actief_'), ['tijd', 'records'],
            [[root.findtext('{http://datex2.eu/schema/3/common}publicationTime') or dt.datetime.now().isoformat(),
              ' '.join(actief)]])
    return len(rijen)


def schrijf(pad, kop, rijen):
    if not rijen:
        return
    nieuw = not os.path.exists(pad)
    with open(pad, 'a', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        if nieuw:
            w.writerow(kop)
        w.writerows(rijen)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tot', default='23:59')
    a = ap.parse_args()
    stop = dt.datetime.combine(dt.date.today(), dt.time.fromisoformat(a.tot))
    os.makedirs(os.path.join(HIER, 'data', 'live'), exist_ok=True)
    borden, pts, gezien = rss_borden(), corridor_punten(), set()
    print(len(borden), 'RSS-borden,', len(pts), 'corridorlussen', flush=True)
    while dt.datetime.now() < stop:
        start = time.time()
        dag = dt.date.today()
        for naam, fn in (('rss', lambda: log_rss(borden, os.path.join(HIER, 'data', 'live', f'rss_{dag}.csv'))),
                         ('datex', lambda: log_datex(pts, os.path.join(HIER, 'data', 'live', f'datex_{dag}.csv'), gezien))):
            try:
                n = fn()
                print(dt.datetime.now().strftime('%H:%M:%S'), naam, n, flush=True)
            except Exception as e:
                print('fout', naam, e, file=sys.stderr, flush=True)
        time.sleep(max(5, 60 - (time.time() - start)))


if __name__ == '__main__':
    main()
