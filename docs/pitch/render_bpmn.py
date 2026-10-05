"""Render the editable BPMN file to lightweight SVG previews."""

from __future__ import annotations

import textwrap
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

B = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BD = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
DI = "http://www.omg.org/spec/DD/20100524/DI"


def tag(elem: ET.Element) -> str:
    return elem.tag.rsplit("}", 1)[-1]


src = Path(__file__).with_name("workflow.bpmn")
root = ET.parse(src).getroot()
by_id = {e.get("id"): e for e in root.iter() if e.get("id")}

for diagram in root.findall(f"{{{BD}}}BPMNDiagram"):
    plane = diagram.find(f"{{{BD}}}BPMNPlane")
    if plane is None:
        continue
    shapes = plane.findall(f"{{{BD}}}BPMNShape")
    edges = plane.findall(f"{{{BD}}}BPMNEdge")
    boxes = []
    for shape in shapes:
        b = shape.find(f"{{{DC}}}Bounds")
        if b is None:
            continue
        boxes.append((shape.get("bpmnElement"), *(float(b.get(k)) for k in ("x", "y", "width", "height"))))
    width = max(x+w for _, x, y, w, h in boxes) + 60
    height = max(y+h for _, x, y, w, h in boxes) + 60
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height:g}" width="{width:g}" height="{height:g}">',
           '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#246653"/></marker></defs>',
           '<rect width="100%" height="100%" fill="#F7F8F4"/>']
    # Pools first, then edges, then nodes, matching conventional BPMN stacking.
    for element_id,x,y,w,h in boxes:
        el=by_id.get(element_id)
        if el is None or tag(el)!="participant":continue
        out.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="8" fill="#FFFFFF" stroke="#B6CEC0" stroke-width="2"/>')
        out.append(f'<rect x="{x:g}" y="{y:g}" width="100" height="{h:g}" rx="8" fill="#EAF5ED"/>')
        out.append(f'<line x1="{x+100:g}" y1="{y:g}" x2="{x+100:g}" y2="{y+h:g}" stroke="#B6CEC0" stroke-width="2"/>')
        label=el.get("name", "")
        for i,line in enumerate(textwrap.wrap(label,width=11,break_long_words=False)):
            out.append(f'<text x="{x+9:g}" y="{y+28+i*20:g}" font-family="Arial,sans-serif" font-size="15" font-weight="700" fill="#173B34">{escape(line)}</text>')
    for edge in edges:
        el=by_id.get(edge.get("bpmnElement"))
        if el is None:continue
        coords=[(float(p.get("x")),float(p.get("y"))) for p in edge.findall(f"{{{DI}}}waypoint")]
        if len(coords)<2:continue
        pts=" ".join(f"{x:g},{y:g}" for x,y in coords)
        dashed=' stroke-dasharray="8 6"' if tag(el)=="messageFlow" else ""
        out.append(f'<polyline points="{pts}" fill="none" stroke="#246653" stroke-width="2" marker-end="url(#arrow)"{dashed}/>')
        label=el.get("name", "")
        if label and tag(el)=="sequenceFlow" and len(label)<22:
            x=(coords[0][0]+coords[-1][0])/2;y=(coords[0][1]+coords[-1][1])/2
            out.append(f'<text x="{x:g}" y="{y-7:g}" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" fill="#637E73">{escape(label)}</text>')
    for element_id,x,y,w,h in boxes:
        el=by_id.get(element_id)
        if el is None or tag(el)=="participant":continue
        typ=tag(el);name=el.get("name", "")
        if typ.endswith("Event"):
            out.append(f'<circle cx="{x+w/2:g}" cy="{y+h/2:g}" r="{min(w,h)/2:g}" fill="#FFFFFF" stroke="#246653" stroke-width="{3 if typ=="endEvent" else 2}"/>')
        elif typ.endswith("Gateway"):
            out.append(f'<polygon points="{x+w/2:g},{y:g} {x+w:g},{y+h/2:g} {x+w/2:g},{y+h:g} {x:g},{y+h/2:g}" fill="#FFF3DA" stroke="#D6A352" stroke-width="2"/>')
            if name:out.append(f'<text x="{x+w/2:g}" y="{y+h/2+5:g}" text-anchor="middle" font-family="Arial,sans-serif" font-size="15" font-weight="700" fill="#925D20">×</text>')
        else:
            out.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="10" fill="#FFFFFF" stroke="#246653" stroke-width="2"/>')
        if name:
            if typ.endswith("Gateway"):
                tx=x+w/2;ty=y+h+17
                out.append(f'<text x="{tx:g}" y="{ty:g}" text-anchor="middle" font-family="Arial,sans-serif" font-size="13" fill="#173B34">{escape(name)}</text>')
            elif typ.endswith("Event"):
                tx=x+w/2;ty=y+h+17
                out.append(f'<text x="{tx:g}" y="{ty:g}" text-anchor="middle" font-family="Arial,sans-serif" font-size="13" fill="#173B34">{escape(name)}</text>')
            else:
                lines=textwrap.wrap(name,width=max(10,int(w/9)),break_long_words=False)
                start=y+h/2-(len(lines)-1)*9+5
                for i,line in enumerate(lines):
                    out.append(f'<text x="{x+w/2:g}" y="{start+i*18:g}" text-anchor="middle" font-family="Arial,sans-serif" font-size="14" font-weight="600" fill="#173B34">{escape(line)}</text>')
    out.append('</svg>')
    target=src.with_name("bpmn-visit.svg" if "visit" in diagram.get("id","") else "bpmn-followup.svg")
    target.write_text("\n".join(out),encoding="utf-8")
    print(target)
