"""Generate two editable BPMN 2.0 diagrams for the Patient pathway pitch.

The diagrams describe the target business process. Real integrations and clinical
rules remain subject to partner contracts and medical approval.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
DI = "http://www.omg.org/spec/DD/20100524/DI"
XSI = "http://www.w3.org/2001/XMLSchema-instance"

for prefix, uri in (("bpmn", BPMN), ("bpmndi", BPMNDI), ("dc", DC), ("di", DI), ("xsi", XSI)):
    ET.register_namespace(prefix, uri)


def q(uri: str, name: str) -> str:
    return f"{{{uri}}}{name}"


class Diagram:
    def __init__(self, root: ET.Element, name: str, key: str) -> None:
        self.key = key
        self.collab = ET.SubElement(root, q(BPMN, "collaboration"), id=f"{key}_collaboration", name=name)
        self.diagram = ET.SubElement(root, q(BPMNDI, "BPMNDiagram"), id=f"{key}_diagram")
        self.plane = ET.SubElement(
            self.diagram, q(BPMNDI, "BPMNPlane"),
            id=f"{key}_plane", bpmnElement=f"{key}_collaboration",
        )
        self.processes: dict[str, ET.Element] = {}
        self.coords: dict[str, tuple[float, float, float, float]] = {}

    def pool(self, root: ET.Element, key: str, label: str, x: int, y: int, w: int, h: int) -> None:
        process_id = f"{self.key}_{key}_process"
        process = ET.SubElement(root, q(BPMN, "process"), id=process_id, isExecutable="false")
        self.processes[key] = process
        participant_id = f"{self.key}_{key}_participant"
        ET.SubElement(self.collab, q(BPMN, "participant"), id=participant_id, name=label, processRef=process_id)
        self.shape(participant_id, x, y, w, h, is_horizontal="true")

    def shape(self, element_id: str, x: float, y: float, w: float, h: float, *, is_horizontal: str | None = None) -> None:
        attrs = {"id": f"{element_id}_di", "bpmnElement": element_id}
        if is_horizontal is not None:
            attrs["isHorizontal"] = is_horizontal
        shape = ET.SubElement(self.plane, q(BPMNDI, "BPMNShape"), attrs)
        ET.SubElement(shape, q(DC, "Bounds"), x=str(x), y=str(y), width=str(w), height=str(h))
        self.coords[element_id] = (x, y, w, h)

    def node(self, pool: str, tag: str, key: str, name: str, x: int, y: int, w: int = 110, h: int = 70,
             event: str | None = None, gateway_default: str | None = None) -> str:
        element_id = f"{self.key}_{key}"
        attrs = {"id": element_id, "name": name}
        if gateway_default:
            attrs["default"] = f"{self.key}_{gateway_default}"
        node = ET.SubElement(self.processes[pool], q(BPMN, tag), attrs)
        if event:
            ET.SubElement(node, q(BPMN, f"{event}EventDefinition"), id=f"{element_id}_{event}")
        self.shape(element_id, x, y, w, h)
        return element_id

    def flow(self, pool: str, key: str, source: str, target: str, *, name: str = "", condition: str | None = None,
             points: list[tuple[float, float]] | None = None) -> None:
        flow_id = f"{self.key}_{key}"
        attrs = {"id": flow_id, "sourceRef": f"{self.key}_{source}", "targetRef": f"{self.key}_{target}"}
        if name:
            attrs["name"] = name
        flow = ET.SubElement(self.processes[pool], q(BPMN, "sequenceFlow"), attrs)
        if condition:
            ET.SubElement(flow, q(BPMN, "conditionExpression"), {q(XSI, "type"): "bpmn:tFormalExpression"}).text = condition
        self.edge(flow_id, source, target, points)

    def message(self, key: str, source: str, target: str, name: str, points: list[tuple[float, float]] | None = None) -> None:
        flow_id = f"{self.key}_{key}"
        ET.SubElement(self.collab, q(BPMN, "messageFlow"),
                      id=flow_id, sourceRef=f"{self.key}_{source}", targetRef=f"{self.key}_{target}", name=name)
        self.edge(flow_id, source, target, points)

    def edge(self, element_id: str, source: str, target: str, points: list[tuple[float, float]] | None) -> None:
        edge = ET.SubElement(self.plane, q(BPMNDI, "BPMNEdge"), id=f"{element_id}_di", bpmnElement=element_id)
        if points is None:
            sx, sy, sw, sh = self.coords[f"{self.key}_{source}"]
            tx, ty, tw, th = self.coords[f"{self.key}_{target}"]
            if abs((sy + sh / 2) - (ty + th / 2)) > abs((sx + sw / 2) - (tx + tw / 2)):
                points = [(sx + sw / 2, sy + sh if sy < ty else sy), (tx + tw / 2, ty if sy < ty else ty + th)]
            else:
                points = [(sx + sw if sx < tx else sx, sy + sh / 2), (tx if sx < tx else tx + tw, ty + th / 2)]
        for x, y in points:
            ET.SubElement(edge, q(DI, "waypoint"), x=str(x), y=str(y))


root = ET.Element(q(BPMN, "definitions"), {
    "id": "patient_pathway_pitch_bpmn", "name": "Patient pathway — путь пациента",
    "targetNamespace": "https://patient-pathway.example/pitch/bpmn",
    "exporter": "Patient pathway project", "exporterVersion": "1.0",
})

# Diagram 1: the route is proposed and approved during the encounter.
d = Diagram(root, "01 · Формирование и утверждение во время приёма", "visit")
d.pool(root, "ai", "ИИ / источник заключения", 80, 70, 1940, 130)
d.pool(root, "core", "Patient pathway · маршрут", 80, 230, 1940, 250)
d.pool(root, "reviewer", "Уполномоченный специалист", 80, 510, 1940, 190)

d.node("ai", "startEvent", "ai_start", "SR готов", 190, 115, 36, 36)
d.node("ai", "sendTask", "send_report", "Передать JSON / SR", 300, 98)
d.node("ai", "endEvent", "ai_end", "Передано", 485, 115, 36, 36)
d.flow("ai", "ai_f1", "ai_start", "send_report")
d.flow("ai", "ai_f2", "send_report", "ai_end")

d.node("core", "startEvent", "report_received", "Заключение получено", 190, 335, 36, 36, event="message")
d.node("core", "serviceTask", "parse", "Разобрать по профилю", 300, 318)
d.node("core", "exclusiveGateway", "complete", "Фактов достаточно?", 465, 335, 50, 50)
d.node("core", "serviceTask", "propose", "CatBoost: проект + поля влияния", 620, 270)
d.node("core", "userTask", "manual", "Ручной проект", 620, 385)
d.node("core", "exclusiveGateway", "merge", "", 800, 335, 50, 50)
d.node("core", "sendTask", "send_proposal", "Показать специалисту", 910, 318)
d.node("core", "receiveTask", "receive_decision", "Получить решение", 1070, 318)
d.node("core", "exclusiveGateway", "approved", "Утверждено?", 1230, 335, 50, 50)
d.node("core", "serviceTask", "save_revision", "Новая ручная версия", 1385, 395)
d.node("core", "serviceTask", "publish", "Опубликовать версию", 1385, 270)
d.node("core", "sendTask", "notify", "Передать в кабинет", 1545, 270)
d.node("core", "endEvent", "core_end", "Путь доступен", 1730, 287, 36, 36)

for key, source, target in (
    ("c1", "report_received", "parse"), ("c2", "parse", "complete"),
    ("c3", "complete", "propose"), ("c4", "complete", "manual"),
    ("c5", "propose", "merge"), ("c6", "manual", "merge"),
    ("c7", "merge", "send_proposal"), ("c8", "send_proposal", "receive_decision"),
    ("c9", "receive_decision", "approved"), ("c10", "approved", "publish"),
    ("c11", "approved", "save_revision"), ("c12", "publish", "notify"),
    ("c13", "notify", "core_end"),
):
    label = {"c3": "да", "c4": "нет", "c10": "да", "c11": "правка / отклонение"}.get(key, "")
    d.flow("core", key, source, target, name=label)
d.flow("core", "c14", "save_revision", "send_proposal", name="повторная проверка",
       points=[(1385, 430), (1340, 430), (1340, 465), (965, 465), (965, 388)])

d.node("reviewer", "startEvent", "proposal_received", "Проект показан", 900, 580, 36, 36, event="message")
d.node("reviewer", "userTask", "review", "Проверить основания", 1020, 563)
d.node("reviewer", "exclusiveGateway", "review_choice", "Принять?", 1180, 580, 50, 50)
d.node("reviewer", "userTask", "approve_route", "Подтвердить версию", 1325, 530)
d.node("reviewer", "userTask", "edit_route", "Исправить + причина", 1325, 625)
d.node("reviewer", "exclusiveGateway", "review_merge", "", 1480, 580, 50, 50)
d.node("reviewer", "sendTask", "send_decision", "Передать решение", 1595, 563)
d.node("reviewer", "endEvent", "review_end", "Решение сохранено", 1780, 580, 36, 36)
for key, source, target in (
    ("r1", "proposal_received", "review"), ("r2", "review", "review_choice"),
    ("r3", "review_choice", "approve_route"), ("r4", "review_choice", "edit_route"),
    ("r5", "approve_route", "review_merge"), ("r6", "edit_route", "review_merge"),
    ("r7", "review_merge", "send_decision"), ("r8", "send_decision", "review_end"),
):
    d.flow("reviewer", key, source, target, name={"r3": "да", "r4": "нет"}.get(key, ""))
d.message("m_report", "send_report", "report_received", "Заключение + технический ID")
d.message("m_proposal", "send_proposal", "proposal_received", "Версия маршрута + trace")
d.message("m_decision", "send_decision", "receive_decision", "Утверждение или правка")

# Diagram 2: one published step; a later step requires a new approved version.
d = Diagram(root, "02 · Показ, подготовка и новый цикл после результата", "follow")
d.pool(root, "core", "Patient pathway · исполнение", 80, 70, 2780, 225)
d.pool(root, "patient", "Пациент · кабинет", 80, 325, 2780, 225)
d.pool(root, "booking", "Система записи / МИС", 80, 580, 2780, 200)

d.node("core", "startEvent", "approved_start", "Версия утверждена", 185, 163, 36, 36)
d.node("core", "sendTask", "show_route", "Показать доступный шаг", 300, 145)
d.node("core", "receiveTask", "receive_request", "Получить запрос записи", 700, 145)
d.node("core", "sendTask", "book", "Запросить слот", 860, 145)
d.node("core", "receiveTask", "booking_status", "Получить статус", 1040, 145)
d.node("core", "exclusiveGateway", "is_confirmed", "Подтверждено?", 1210, 155, 50, 50)
d.node("core", "sendTask", "no_slots", "Сообщить: нет слота", 1360, 225)
d.node("core", "sendTask", "confirm", "Показать подтверждение", 1360, 110)
d.node("core", "receiveTask", "result", "Результат услуги и подготовки", 1540, 110)
d.node("core", "exclusiveGateway", "condition", "Нужен ещё шаг?", 1720, 120, 50, 50)
d.node("core", "serviceTask", "next", "Создать проект одного шага", 1870, 95)
d.node("core", "endEvent", "core_continue", "Ждёт решения", 2055, 112, 36, 36)
d.node("core", "endEvent", "core_finish", "Маршрут завершён", 1870, 255, 36, 36)
for key, source, target in (
    ("c1", "approved_start", "show_route"), ("c2", "show_route", "receive_request"),
    ("c3", "receive_request", "book"), ("c4", "book", "booking_status"),
    ("c5", "booking_status", "is_confirmed"), ("c6", "is_confirmed", "confirm"),
    ("c7", "is_confirmed", "no_slots"), ("c8", "no_slots", "receive_request"),
    ("c9", "confirm", "result"), ("c10", "result", "condition"),
    ("c11", "condition", "next"), ("c12", "condition", "core_finish"),
    ("c13", "next", "core_continue"),
):
    d.flow("core", key, source, target,
           name={"c6": "да", "c7": "нет", "c11": "да", "c12": "нет"}.get(key, ""),
           points=[(1360, 260), (755, 260), (755, 215)] if key == "c8" else None)

d.node("patient", "startEvent", "route_seen", "Путь показан", 185, 420, 36, 36, event="message")
d.node("patient", "userTask", "view", "Изучить доступный шаг", 300, 403)
d.node("patient", "exclusiveGateway", "choice", "Записаться?", 470, 413, 50, 50)
d.node("patient", "userTask", "decline", "Отказ + категория причины", 580, 475)
d.node("patient", "userTask", "resume", "Вернуться к записи", 760, 475)
d.node("patient", "sendTask", "request", "Выбрать время", 700, 375)
d.node("patient", "receiveTask", "status", "Получить статус", 1040, 375)
d.node("patient", "exclusiveGateway", "status_choice", "Подтверждено?", 1210, 385, 50, 50)
d.node("patient", "endEvent", "patient_end", "Ожидать визит", 1390, 395, 36, 36)
for key, source, target in (
    ("p1", "route_seen", "view"), ("p2", "view", "choice"),
    ("p3", "choice", "request"), ("p4", "choice", "decline"),
    ("p5", "decline", "resume"), ("p6", "resume", "request"),
    ("p7", "request", "status"), ("p8", "status", "status_choice"),
    ("p9", "status_choice", "patient_end"), ("p10", "status_choice", "request"),
):
    d.flow("patient", key, source, target,
           name={"p3": "да", "p4": "нет", "p9": "да", "p10": "нет слота"}.get(key, ""),
           points=[(1210, 430), (1170, 430), (1170, 535), (755, 535), (755, 445)] if key == "p10" else None)

d.node("booking", "startEvent", "booking_request", "Запрос получен", 845, 665, 36, 36, event="message")
d.node("booking", "serviceTask", "reserve", "Проверить / занять слот", 960, 648)
d.node("booking", "sendTask", "send_status", "Отдать статус записи", 1270, 648)
d.node("booking", "exclusiveGateway", "after_status", "Подтверждено?", 1440, 658, 50, 50)
d.node("booking", "receiveTask", "performed", "Результат услуги", 1590, 625)
d.node("booking", "sendTask", "send_result", "Передать результат", 1770, 625)
d.node("booking", "endEvent", "booking_end", "Готово", 1960, 642, 36, 36)
d.node("booking", "endEvent", "no_slot_end", "Нет слота", 1590, 720, 36, 36)
for key, source, target in (
    ("b1", "booking_request", "reserve"), ("b2", "reserve", "send_status"),
    ("b4", "send_status", "after_status"),
    ("b5", "after_status", "performed"), ("b6", "performed", "send_result"),
    ("b7", "send_result", "booking_end"), ("b8", "after_status", "no_slot_end"),
):
    d.flow("booking", key, source, target, name={"b5": "да", "b8": "нет"}.get(key, ""))

d.message("m_route", "show_route", "route_seen", "Утверждённый маршрут")
d.message("m_patient_request", "request", "receive_request", "Запрос записи")
d.message("m_booking_request", "book", "booking_request", "Бронь слота")
d.message("m_booking_status", "send_status", "booking_status", "Статус")
d.message("m_patient_status", "confirm", "status", "Подтверждение")
d.message("m_patient_no_slots", "no_slots", "status", "Нет слота")
d.message("m_result", "send_result", "result", "Результат выполненного шага")

out = Path(__file__).with_name("workflow.bpmn")
# BPMN definitions expects all root elements before BPMNDiagram children.
for visual in root.findall(q(BPMNDI, "BPMNDiagram")):
    root.remove(visual)
    root.append(visual)
ET.indent(root, space="  ")
out.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
print(out)
