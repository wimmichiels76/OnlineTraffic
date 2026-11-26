"""Replay van een run, om in sumo-gui te bekijken.

sim_online.py neemt tijdens de run elke TraCI-ingreep op (snelheden per strook, gesloten stroken, ongevallen) en
laat SUMO de gereden voertuigen wegschrijven. Bij het afsluiten maakt schrijf() daarvan:

    uit/replay_<tag>/e314.sumocfg       openen met:  sumo-gui -c uit/replay_<tag>/e314.sumocfg
                     routes.rou.xml     alle voertuigen met hun route en vertrektijd
                     regeling.add.xml   voertuigtypes, variabele snelheidsborden (RSS, meldingen, stroomafwaartse
                                        rand), strookafsluitingen (rerouter) en stilstaande ongevalsvoertuigen
                     gui.xml            kleur volgens snelheid
                     werfzones.json     per minuut de edges met een grotere volgafstand (tau-factor)

Twee manieren om te kijken:
    python replay.py uit/replay_<tag>              sumo-gui via TraCI, MET de werfzones (zoals de run)
    sumo-gui -c uit/replay_<tag>/e314.sumocfg      zonder Python, ZONDER de werfzones

De grotere volgafstand in werfzones (tau x 2) bestaat niet als SUMO-additional: TraCI moet ze per voertuig zetten.
Zonder de speler is de file aan de werfzone in Herent daarom kleiner dan in de run.
"""
import argparse, json, os, sys
import xml.etree.ElementTree as ET

DICHT = 'passenger truck trailer delivery motorcycle bus coach'


class Opname:
    """Onderschept de TraCI-oproepen die de verkeersregeling veranderen."""

    def __init__(self, traci):
        self.traci, self.rij = traci, []
        for dom, fn in ((traci.lane, 'setMaxSpeed'), (traci.lane, 'setDisallowed'), (traci.edge, 'setMaxSpeed')):
            self._wikkel(dom, fn, 'edge' if dom is traci.edge else 'lane')
        orig_add, orig_rem = traci.vehicle.add, traci.vehicle.remove

        def add(vid, rid, *x, **k):
            if k.get('typeID') == 'ongeval':
                self.rij.append((traci.simulation.getTime(), 'ongeval+', vid, (traci.route.getEdges(rid)[0], k)))
            return orig_add(vid, rid, *x, **k)

        def rem(vid, *x, **k):
            if vid.startswith('ongeval_'):
                self.rij.append((traci.simulation.getTime(), 'ongeval-', vid, None))
            return orig_rem(vid, *x, **k)
        traci.vehicle.add, traci.vehicle.remove = add, rem

    def _wikkel(self, dom, fn, soort):
        orig = getattr(dom, fn)

        def w(i, v, *x, **k):
            self.rij.append((self.traci.simulation.getTime(), f'{soort}.{fn}', i, v))
            return orig(i, v, *x, **k)
        setattr(dom, fn, w)


def schrijf(tag, opname, net, begin, einde, vehroutes, offset=0, datum=None, corr=None):
    """offset (s): tel bij alle tijden op, zodat sumo-gui de kloktijd toont (sim-tijd 0 = t0 van de run)."""
    map_ = os.path.join('uit', f'replay_{tag}')
    os.makedirs(map_, exist_ok=True)
    # ---- snelheden per strook -> variabele snelheidsborden
    snel, dicht, ongeval, vracht = {}, {}, {}, {}
    for t, wat, i, v in opname.rij:
        if wat == 'lane.setMaxSpeed':
            snel.setdefault(i, []).append((t, v))
        elif wat == 'edge.setMaxSpeed':
            for L in net.getEdge(i).getLanes():
                snel.setdefault(L.getID(), []).append((t, v))
        elif wat == 'lane.setDisallowed':
            # drie toestanden: dicht (alles geweerd), vrachtverbod (enkel vrachtwagens), open
            dicht.setdefault(i, []).append((t, 'passenger' in v))
            vracht.setdefault(i, []).append((t, bool(v) and 'passenger' not in v))
        elif wat == 'ongeval+':
            ongeval[i] = [t, None, v]
        elif wat == 'ongeval-' and i in ongeval:
            ongeval[i][1] = t
    add = ET.Element('additional')
    for vt in ET.parse(f'net/e314_{tag}.add.xml').getroot().iter('vType'):
        add.append(vt)
    for k, (lid, stappen) in enumerate(sorted(snel.items())):
        vss = ET.SubElement(add, 'variableSpeedSign', id=f'vss{k}', lanes=lid)
        vorige = None
        for t, v in sorted(stappen, key=lambda s: s[0]):
            if v != vorige:
                ET.SubElement(vss, 'step', time=f'{t + offset:.0f}', speed=f'{v:.2f}')
                vorige = v
    # ---- gesloten stroken -> rerouter met closingLaneReroute per interval
    def intervallen(stappen):
        uit, start = [], None
        for t, d in sorted(stappen, key=lambda s: s[0]) + [(einde, False)]:
            if d and start is None:
                start = max(t, begin)
            elif not d and start is not None:
                uit.append((start, t))
                start = None
        return [(b, e) for b, e in uit if e > b]

    for soort, tabel, weer in (('dicht', dicht, DICHT), ('vracht', vracht, 'truck trailer')):
        for k, (lid, stappen) in enumerate(sorted(tabel.items())):
            iv_lijst = intervallen(stappen)
            if not iv_lijst:
                continue
            rr = ET.SubElement(add, 'rerouter', id=f'{soort}{k}', edges=lid.rsplit('_', 1)[0])
            for b, e in iv_lijst:
                iv = ET.SubElement(rr, 'interval', begin=f'{b + offset:.0f}', end=f'{e + offset:.0f}')
                ET.SubElement(iv, 'closingLaneReroute', id=lid, disallow=weer)
    ET.indent(add)
    ET.ElementTree(add).write(os.path.join(map_, 'regeling.add.xml'), encoding='utf-8', xml_declaration=True)
    # ---- voertuigen: de door SUMO weggeschreven routes, zonder ongevalsvoertuigen, + ongevallen met een stop
    rou = ET.Element('routes')
    vtypes = {vt.get('id') for vt in add.iter('vType')}
    voertuigen = []
    for el in ET.parse(vehroutes).getroot():
        if el.tag == 'vType' and el.get('id') in vtypes:
            continue
        if el.tag == 'vehicle':
            if el.get('id').startswith('ongeval_'):
                continue
            for a in ('arrival', 'routeLength'):
                el.attrib.pop(a, None)
            el.set('depart', f"{float(el.get('depart')) + offset:.2f}")
            el.set('type', el.get('type', 'auto').split('@')[0])  # 'auto@A80' = per voertuig aangepast (tau)
            el.set('departLane', 'best')  # zoals in de run; de weggeschreven vaste strook gaf veel vertrekvertraging
            voertuigen.append(el)
        else:
            rou.append(el)
    for vid, (b, e, (edge, k)) in ongeval.items():
        v = ET.Element('vehicle', id=vid, type='ongeval', depart=f'{b + offset:.0f}', departPos=k['departPos'],
                       departLane='0', departSpeed='0')
        ET.SubElement(v, 'route', edges=edge)
        ET.SubElement(v, 'stop', lane=f'{edge}_0', endPos=f'{float(k["departPos"]) + 1:.1f}',
                      until=f'{(e if e is not None else einde) + offset:.0f}')
        voertuigen.append(v)
    voertuigen.sort(key=lambda v: float(v.get('depart')))
    rou.extend(voertuigen)
    ET.indent(rou)
    ET.ElementTree(rou).write(os.path.join(map_, 'routes.rou.xml'), encoding='utf-8', xml_declaration=True)
    # ---- gui-instellingen en sumocfg
    open(os.path.join(map_, 'gui.xml'), 'w', encoding='utf-8').write(
        '<viewsettings>\n  <scheme name="real world"/>\n  <delay value="20"/>\n'
        '  <vehicles vehicleMode="8" vehicleQuality="2" vehicle_minSize="2" vehicle_exaggeration="4"/>\n'
        '</viewsettings>\n')
    open(os.path.join(map_, 'e314.sumocfg'), 'w', encoding='utf-8').write(f'''<configuration>
    <input>
        <net-file value="../../net/e314.net.xml"/>
        <route-files value="routes.rou.xml"/>
        <additional-files value="regeling.add.xml"/>
    </input>
    <time>
        <begin value="{begin + offset:.0f}"/>
        <end value="{einde + offset:.0f}"/>
        <step-length value="0.5"/>
    </time>
    <processing>
        <time-to-teleport value="300"/>
        <lateral-resolution value="0"/>
    </processing>
    <report>
        <human-readable-time value="true"/>
    </report>
    <gui_only>
        <gui-settings-file value="gui.xml"/>
    </gui_only>
</configuration>
''')
    if datum is not None:
        json.dump(werfzones(net, corr, datum, offset, begin, einde), open(os.path.join(map_, 'werfzones.json'), 'w'))
    return map_


def werfzones(net, corr, datum, offset, begin, einde):
    """[[kloktijd_s, {edge: tau-factor}], ...] bij elke wijziging; zelfde logica als de run (datex_model)."""
    import pandas as pd
    import datex_model
    mel = datex_model.Meldingen(net, corr, None)
    d, A = datex_model.lees(datum)
    t0 = pd.Timestamp(datum) + pd.Timedelta(seconds=offset)
    uit, vorige = [], None
    for s in range(int(begin), int(einde), 60):
        m = t0 + pd.Timedelta(seconds=s)
        mel.gewenst(datex_model.actief(d, A, m))
        if mel.zone_tau != vorige:
            uit.append([s + offset, dict(mel.zone_tau)])
            vorige = dict(mel.zone_tau)
    return uit


def speel(map_, gui=True):
    """Speelt de replay af via TraCI en zet tau in de werfzones, zoals sim_online.py dat doet."""
    hier = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, hier)
    if 'SUMO_HOME' in os.environ:
        sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))
    import sumolib, traci
    import datex_model
    zones = json.load(open(os.path.join(map_, 'werfzones.json')))
    net = sumolib.net.readNet(os.path.join(hier, 'net', 'e314.net.xml'))
    corr = json.load(open(os.path.join(hier, 'data', 'corridor.json')))
    traci.start([sumolib.checkBinary('sumo-gui' if gui else 'sumo'), '-c', os.path.join(map_, 'e314.sumocfg')]
                + ([] if gui else ['--no-step-log', '--duration-log.statistics']))
    mel = datex_model.Meldingen(net, corr, traci)
    k = 0
    while traci.simulation.getMinExpectedNumber() > 0:
        t = traci.simulation.getTime()
        while k < len(zones) and zones[k][0] <= t:
            mel.zone_tau = zones[k][1]
            k += 1
        traci.simulationStep(t + 5)
        if mel.zone_tau or mel.aangepast:
            mel.pas_tau_toe()
    traci.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Replay van een run afspelen in sumo-gui, met de werfzones.')
    ap.add_argument('map', help='uit/replay_<tag>')
    ap.add_argument('--zonder-gui', action='store_true')
    a = ap.parse_args()
    speel(a.map, not a.zonder_gui)
