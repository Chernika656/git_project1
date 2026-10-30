"""Создать учебную закупку: смешанный и исправленный варианты BPMN.

Запуск: python3 examples/generate_purchase.py
Координаты заданы явно, чтобы схема открывалась одинаково в разных редакторах.
"""

from pathlib import Path
import xml.etree.ElementTree as ET

B = "http://www.omg.org/spec/BPMN/20100524/MODEL"
D = "http://www.omg.org/spec/BPMN/20100524/DI"
C = "http://www.omg.org/spec/DD/20100524/DC"
I = "http://www.omg.org/spec/DD/20100524/DI"
for prefix, namespace in (("bpmn", B), ("bpmndi", D), ("dc", C), ("di", I)):
    ET.register_namespace(prefix, namespace)

# Тип, ID, подпись, роль, x, y, ширина, высота.
NODES = [
    ("startEvent", "Start_Request", "Нужна покупка", "initiator", 150, 192, 36, 36),
    ("userTask", "Task_Request", "Подготовить заявку", "initiator", 250, 170, 150, 80),
    ("userTask", "Task_Clarify", "Уточнить обоснование", "initiator", 530, 170, 150, 80),
    ("userTask", "Task_Documents", "Собрать документы", "initiator", 980, 170, 150, 80),
    ("userTask", "Task_NoFunds", "Сообщить о нехватке средств", "initiator", 1550, 170, 160, 80),
    ("endEvent", "End_NoFunds", "Покупка отложена", "initiator", 1810, 192, 36, 36),
    ("userTask", "Task_Review", "Рассмотреть заявку", "manager", 450, 420, 150, 80),
    ("exclusiveGateway", "Gateway_Approval", "Решение руководителя", "manager", 700, 435, 50, 50),
    ("parallelGateway", "Gateway_Fork", "Подготовка", "manager", 900, 435, 50, 50),
    ("parallelGateway", "Gateway_Join", "Всё готово", "manager", 1240, 435, 50, 50),
    ("exclusiveGateway", "Gateway_Funds", "Средств достаточно?", "manager", 1380, 435, 50, 50),
    ("userTask", "Task_Reject", "Оформить отказ", "manager", 820, 545, 150, 65),
    ("endEvent", "End_Rejected", "Заявка отклонена", "manager", 1070, 560, 36, 36),
    ("serviceTask", "Task_Budget", "Рассчитать доступный бюджет", "accountant", 980, 750, 160, 80),
    ("userTask", "Task_Pay", "Оплатить счёт", "accountant", 1550, 750, 150, 80),
    ("task", "Task_Archive", "Сохранить платёжные документы", "accountant", 1780, 750, 160, 80),
    ("userTask", "Task_Audit", "Сверить реквизиты", "accountant", 2010, 750, 150, 80),
    ("endEvent", "End_Paid", "Покупка оплачена", "accountant", 2260, 772, 36, 36),
]

# ID, источник, получатель, подпись, формальное условие, точки стрелки.
FLOWS = [
    ("Flow_Start", "Start_Request", "Task_Request", "", None, [(186,210),(250,210)]),
    ("Flow_Submit", "Task_Request", "Task_Review", "", None, [(400,210),(425,210),(425,460),(450,460)]),
    ("Flow_Reviewed", "Task_Review", "Gateway_Approval", "", None, [(600,460),(700,460)]),
    ("Flow_Approved", "Gateway_Approval", "Gateway_Fork", "Одобрено", 'decision = "approved"', [(750,460),(900,460)]),
    ("Flow_Rejected", "Gateway_Approval", "Task_Reject", "Отказ", None, [(725,485),(725,578),(820,578)]),
    ("Flow_RejectEnd", "Task_Reject", "End_Rejected", "", None, [(970,578),(1070,578)]),
    ("Flow_Clarify", "Gateway_Approval", "Task_Clarify", "На доработку", 'decision = "clarify"', [(725,435),(725,210),(680,210)]),
    ("Flow_Documents", "Gateway_Fork", "Task_Documents", "", None, [(925,435),(925,210),(980,210)]),
    ("Flow_Budget", "Gateway_Fork", "Task_Budget", "", None, [(925,485),(925,790),(980,790)]),
    ("Flow_DocumentsReady", "Task_Documents", "Gateway_Join", "", None, [(1130,210),(1265,210),(1265,435)]),
    ("Flow_BudgetReady", "Task_Budget", "Gateway_Join", "", None, [(1140,790),(1265,790),(1265,485)]),
    ("Flow_Prepared", "Gateway_Join", "Gateway_Funds", "", None, [(1290,460),(1380,460)]),
    ("Flow_HasFunds", "Gateway_Funds", "Task_Pay", "Да", "available >= amount", [(1405,485),(1405,790),(1550,790)]),
    ("Flow_NoFunds", "Gateway_Funds", "Task_NoFunds", "Нет", None, [(1405,435),(1405,210),(1550,210)]),
    ("Flow_NoFundsEnd", "Task_NoFunds", "End_NoFunds", "", None, [(1710,210),(1810,210)]),
    ("Flow_Payment", "Task_Pay", "Task_Archive", "", None, [(1700,790),(1780,790)]),
]


def generate(mixed: bool) -> Path:
    root = ET.Element(f"{{{B}}}definitions", id="Definitions_Purchase", targetNamespace="urn:bpmn-check:purchase")
    process = ET.SubElement(root, f"{{{B}}}process", id="Process_Purchase", name="Согласование и оплата покупки", isExecutable="false")
    ET.SubElement(process, f"{{{B}}}documentation").text = (
        "Учебный процесс с намеренными ошибками; не использовать для исполнения."
        if mixed else "Учебный процесс с исправленными структурными замечаниями."
    )
    lanes = ET.SubElement(process, f"{{{B}}}laneSet", id="LaneSet_Roles")
    roles = [("initiator", "Инициатор", 80, 240), ("manager", "Руководитель", 320, 320), ("accountant", "Бухгалтер", 640, 280)]
    for identifier, name, _, _ in roles:
        lane = ET.SubElement(lanes, f"{{{B}}}lane", id="Lane_"+identifier, name=name)
        for _, node_id, _, role, *_ in NODES:
            if role == identifier:
                ET.SubElement(lane, f"{{{B}}}flowNodeRef").text = node_id
    elements = {}
    for tag, identifier, name, _, *_ in NODES:
        attrs = {"id": identifier}
        if not (mixed and identifier == "Task_Archive"):
            attrs["name"] = name
        elements[identifier] = ET.SubElement(process, f"{{{B}}}{tag}", attrs)
    elements["Gateway_Approval"].set("default", "Flow_Rejected")
    elements["Gateway_Funds"].set("default", "Flow_Submit" if mixed else "Flow_NoFunds")
    flows = list(FLOWS)
    if mixed:
        flows += [
            ("Flow_ClarifyLoop", "Task_Clarify", "Task_Clarify", "Повторить", None, [(605,170),(605,125),(485,125),(485,210),(530,210)]),
            ("Flow_ArchiveEnd", "Task_Archive", "End_Paid", "", None, [(1860,750),(1860,690),(2278,690),(2278,772)]),
            ("Flow_BadRestart", "End_Paid", "Start_Request", "Ошибочный возврат в начало", None, [(2296,790),(2335,790),(2335,105),(168,105),(168,192)]),
        ]
    else:
        flows += [
            ("Flow_ClarifyReturn", "Task_Clarify", "Task_Request", "Доработано", None, [(605,170),(605,125),(325,125),(325,170)]),
            ("Flow_Audit", "Task_Archive", "Task_Audit", "", None, [(1940,790),(2010,790)]),
            ("Flow_AuditEnd", "Task_Audit", "End_Paid", "", None, [(2160,790),(2260,790)]),
        ]
    for identifier, source, target, name, condition, _ in flows:
        attrs = {"id": identifier, "sourceRef": source, "targetRef": target}
        if name:
            attrs["name"] = name
        flow = ET.SubElement(process, f"{{{B}}}sequenceFlow", attrs)
        if mixed and identifier == "Flow_Approved":
            condition = None
        if mixed and identifier == "Flow_NoFunds":
            # Отдельная смысловая ошибка: при равенстве истинны обе ветки.
            # Текущий анализатор выражения не вычисляет; это ручной контроль.
            condition = "available <= amount"
        if condition:
            ET.SubElement(flow, f"{{{B}}}conditionExpression").text = condition
        ET.SubElement(elements[source], f"{{{B}}}outgoing").text = identifier
        ET.SubElement(elements[target], f"{{{B}}}incoming").text = identifier

    collaboration = ET.SubElement(root, f"{{{B}}}collaboration", id="Collaboration_Purchase")
    ET.SubElement(collaboration, f"{{{B}}}participant", id="Pool_Company", name="Компания · закупка", processRef="Process_Purchase")
    diagram = ET.SubElement(root, f"{{{D}}}BPMNDiagram", id="Diagram_Purchase")
    plane = ET.SubElement(diagram, f"{{{D}}}BPMNPlane", id="Plane_Purchase", bpmnElement="Collaboration_Purchase")

    def shape(identifier, x, y, w, h, label=False):
        visual = ET.SubElement(plane, f"{{{D}}}BPMNShape", id=identifier+"_di", bpmnElement=identifier)
        ET.SubElement(visual, f"{{{C}}}Bounds", x=str(x), y=str(y), width=str(w), height=str(h))
        if label:
            label_element = ET.SubElement(visual, f"{{{D}}}BPMNLabel")
            ET.SubElement(label_element, f"{{{C}}}Bounds", x=str(x+w/2-75), y=str(y+h+8), width="150", height="34")
        return visual

    shape("Pool_Company", 40, 80, 2340, 840).set("isHorizontal", "true")
    for identifier, _, y, height in roles:
        shape("Lane_"+identifier, 70, y, 2310, height).set("isHorizontal", "true")
    for tag, identifier, _, _, x, y, w, h in NODES:
        shape(identifier, x, y, w, h, tag.endswith("Event") or tag.endswith("Gateway"))
    for identifier, _, _, _, _, points in flows:
        edge = ET.SubElement(plane, f"{{{D}}}BPMNEdge", id=identifier+"_di", bpmnElement=identifier)
        for x, y in points:
            ET.SubElement(edge, f"{{{I}}}waypoint", x=str(x), y=str(y))
    ET.indent(root)
    path = Path(__file__).parent / ("purchase-mixed.bpmn" if mixed else "purchase-fixed.bpmn")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


if __name__ == "__main__":
    for mixed in (True, False):
        print(generate(mixed).name)
