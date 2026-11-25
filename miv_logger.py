"""Logt de MIV-minuutfeed (AWV/Verkeerscentrum) voor een set meetpunten.

Gebruik:  python miv_logger.py --tot 20:00 [--ids data/meetpunten_e314.csv,data/meetpunten_heverlee.csv]

Standaard: de E314-corridor plus het Knooppunt Heverlee (E40 x E314, instroom richting Aarschot).

Schrijft per dag data/live/miv_YYYY-MM-DD.csv met één rij per (minuut, meetpunt, klasse).
De feed geeft enkel de laatste minuut; dit script bouwt dus zelf de historiek op.
"""
import argparse, csv, datetime as dt, io, os, sys, time, urllib.request
import xml.etree.ElementTree as ET

URL = "http://miv.opendata.belfla.be/miv/verkeersdata"
HIER = os.path.dirname(os.path.abspath(__file__))


def lees_ids(paden):
    ids = set()
    for pad in paden.split(","):
        with open(pad, encoding="utf-8") as f:
            ids |= {r["unieke_id"] for r in csv.DictReader(f)}
    return ids


def haal(ids):
    with urllib.request.urlopen(URL, timeout=50) as r:
        data = r.read()
    rijen = []
    for _, el in ET.iterparse(io.BytesIO(data)):
        if el.tag != "meetpunt":
            continue
        uid = el.get("unieke_id")
        if uid in ids:
            t = el.findtext("tijd_waarneming")
            kop = [t, uid, el.findtext("beschikbaar"), el.findtext("defect"), el.findtext("geldig"),
                   el.findtext("rekendata/bezettingsgraad"), el.findtext("rekendata/beschikbaarheidsgraad")]
            for md in el.findall("meetdata"):
                rijen.append(kop + [md.get("klasse_id"), md.findtext("verkeersintensiteit"),
                                    md.findtext("voertuigsnelheid_harmonisch"),
                                    md.findtext("voertuigsnelheid_rekenkundig")])
        el.clear()
    return rijen


KOLOMMEN = ["tijd", "unieke_id", "beschikbaar", "defect", "geldig", "bezetting", "beschikbaarheid",
            "klasse", "q", "v_harm", "v_rek"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default=",".join(os.path.join(HIER, "data", f) for f in
                                              ("meetpunten_e314.csv", "meetpunten_heverlee.csv")))
    ap.add_argument("--tot", default="23:59", help="stoptijd HH:MM (lokale tijd)")
    a = ap.parse_args()
    ids = lees_ids(a.ids)
    stop = dt.datetime.combine(dt.date.today(), dt.time.fromisoformat(a.tot))
    os.makedirs(os.path.join(HIER, "data", "live"), exist_ok=True)
    gezien = set()
    while dt.datetime.now() < stop:
        start = time.time()
        try:
            rijen = haal(ids)
            nieuw = [r for r in rijen if (r[0], r[1]) not in gezien]
            if nieuw:
                pad = os.path.join(HIER, "data", "live", f"miv_{dt.date.today()}.csv")
                bestaat = os.path.exists(pad)
                with open(pad, "a", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    if not bestaat:
                        w.writerow(KOLOMMEN)
                    w.writerows(nieuw)
                gezien.update((r[0], r[1]) for r in nieuw)
                print(dt.datetime.now().strftime("%H:%M:%S"), "tijd", nieuw[0][0], "rijen", len(nieuw), flush=True)
        except Exception as e:  # feed hapert soms; gewoon volgende minuut opnieuw
            print("fout:", e, file=sys.stderr, flush=True)
        time.sleep(max(5, 30 - (time.time() - start)))  # 2x per minuut pollen, dedupe op tijd


if __name__ == "__main__":
    main()
