"""Zelfstandige SUMO-configuratie van een run, om in sumo-gui te bekijken (zonder TraCI of Python).

sim_online.py neemt tijdens de run elke TraCI-ingreep op (snelheden per strook, gesloten stroken, ongevallen) en
laat SUMO de gereden voertuigen wegschrijven. Bij het afsluiten maakt schrijf() daarvan:

    uit/replay_<tag>/e314.sumocfg       openen met:  sumo-gui -c uit/replay_<tag>/e314.sumocfg
                     routes.rou.xml     alle voertuigen met hun route en vertrektijd
                     regeling.add.xml   voertuigtypes, variabele snelheidsborden (RSS, meldingen, stroomafwaartse
                                        rand), strookafsluitingen (rerouter) en stilstaande ongevalsvoertuigen
                     gui.xml            kleur volgens snelheid

Wat er niet in zit: de grotere volgafstand (tau x 2) in werfzones. Die zet TraCI per voertuig en bestaat niet als
additional. De file aan de werfzone in Herent is in de replay daarom kleiner dan in de run zelf.
"""
import os
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


def schrijf(tag, opname, net, begin, einde, vehroutes, offset=0):
    """offset (s): tel bij alle tijden op, zodat sumo-gui de kloktijd toont (sim-tijd 0 = t0 van de run)."""
    map_ = os.path.join('uit', f'replay_{tag}')
    os.makedirs(map_, exist_ok=True)
    # ---- snelheden per strook -> variabele snelheidsborden
    snel, dicht, ongeval = {}, {}, {}
    for t, wat, i, v in opname.rij:
        if wat == 'lane.setMaxSpeed':
            snel.setdefault(i, []).append((t, v))
        elif wat == 'edge.setMaxSpeed':
            for L in net.getEdge(i).getLanes():
                snel.setdefault(L.getID(), []).append((t, v))
        elif wat == 'lane.setDisallowed':
            dicht.setdefault(i, []).append((t, bool(v)))
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
    for k, (lid, stappen) in enumerate(sorted(dicht.items())):
        intervallen, start = [], None
        for t, d in sorted(stappen, key=lambda s: s[0]) + [(einde, False)]:
            if d and start is None:
                start = t
            elif not d and start is not None:
                intervallen.append((start, t))
                start = None
        if not intervallen:
            continue
        rr = ET.SubElement(add, 'rerouter', id=f'dicht{k}', edges=lid.rsplit('_', 1)[0])
        for b, e in intervallen:
            iv = ET.SubElement(rr, 'interval', begin=f'{b + offset:.0f}', end=f'{e + offset:.0f}')
            ET.SubElement(iv, 'closingLaneReroute', id=lid, disallow=DICHT)
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
            el.set('type', el.get('type', 'auto').split('@')[0])  # 'auto@A80' = per voertuig aangepast (tau), niet weggeschreven
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
    return map_
