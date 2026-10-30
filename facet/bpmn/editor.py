"""Перемещение геометрии и аккуратное сохранение BPMN DI.

DOM сохраняет namespace-префиксы, комментарии и расширения редактора.
Смысл процесса, условия, роли и sourceRef/targetRef не меняются.
"""

import math
import os
from pathlib import Path
import stat
import tempfile
from xml.dom import minidom

from facet.bpmn.checker import BPMN, MAX_BYTES
from facet.bpmn.diagram import COORDINATES, DIAGRAM, DRAWING, CONTAINERS


class EditError(ValueError):
    pass


def move_shape(diagram, identifier, dx, dy):
    """Сдвинуть элемент и пересчитать затронутые стрелки. Возвращает сдвинутые ID."""
    shapes = {shape.element_id: shape for shape in diagram.shapes}
    shape = shapes.get(identifier)
    if shape is None or not all(math.isfinite(n) for n in (dx, dy)):
        return set()
    # Граничное событие движется вместе с действием, к которому прикреплено.
    if shape.attached_to:
        return set()
    group = {identifier}
    if shape.kind in CONTAINERS or shape.expanded:
        group |= {other.element_id for other in diagram.shapes
                  if shape.x <= other.x and shape.y <= other.y
                  and other.x + other.width <= shape.x + shape.width
                  and other.y + other.height <= shape.y + shape.height}
    else:
        lane = shapes.get(shape.lane_id)
        if lane:
            # Не меняем роль случайным переносом блока в чужую дорожку.
            dx = max(lane.x + 38 - shape.x, min(dx, lane.x + lane.width - shape.width - 8 - shape.x))
            dy = max(lane.y + 10 - shape.y, min(dy, lane.y + lane.height - shape.height - 28 - shape.y))
    group |= {other.element_id for other in diagram.shapes if other.attached_to in group}
    if abs(dx) + abs(dy) < 0.01:
        return set()
    for moved_id in group:
        moved = shapes[moved_id]
        moved.x += dx
        moved.y += dy
        if moved.label:
            x, y, w, h = moved.label
            moved.label = x + dx, y + dy, w, h
    for edge in diagram.edges:
        if edge.source_id not in group and edge.target_id not in group:
            continue
        if edge.source_id in group and edge.target_id in group:
            edge.points = [(x + dx, y + dy) for x, y in edge.points]
            if edge.label:
                x, y, w, h = edge.label
                edge.label = x + dx, y + dy, w, h
        else:
            source, target = shapes.get(edge.source_id), shapes.get(edge.target_id)
            if source and target:
                edge.points = route(source, target)
            else:
                # У сломанной ссылки сохраняем отсутствующий конец стрелки.
                edge.points = list(edge.points)
                if edge.source_id in group:
                    x, y = edge.points[0]
                    edge.points[0] = x + dx, y + dy
                if edge.target_id in group:
                    x, y = edge.points[-1]
                    edge.points[-1] = x + dx, y + dy
            if edge.label:
                a, b = max(zip(edge.points, edge.points[1:]), key=lambda pair: math.dist(*pair))
                _, _, w, h = edge.label
                edge.label = (a[0] + b[0] - w) / 2, (a[1] + b[1]) / 2 - h - 6, w, h
    return group


def route(source, target):
    """Ортогональная связь с точками на границах блоков, без обхода препятствий."""
    sx, sy = source.x + source.width / 2, source.y + source.height / 2
    tx, ty = target.x + target.width / 2, target.y + target.height / 2
    if source.element_id == target.element_id:
        return [(source.x + source.width, sy), (source.x + source.width + 35, sy),
                (source.x + source.width + 35, source.y - 35), (sx, source.y - 35), (sx, source.y)]
    if abs(tx - sx) >= abs(ty - sy):
        direction = 1 if tx >= sx else -1
        a, b = (sx + direction * source.width / 2, sy), (tx - direction * target.width / 2, ty)
        mid = (a[0] + b[0]) / 2
        points = [a, (mid, a[1]), (mid, b[1]), b]
    else:
        direction = 1 if ty >= sy else -1
        a, b = (sx, sy + direction * source.height / 2), (tx, ty - direction * target.height / 2)
        mid = (a[1] + b[1]) / 2
        points = [a, (a[0], mid), (b[0], mid), b]
    return [point for index, point in enumerate(points) if index == 0 or point != points[index - 1]]


def updated_xml(original: bytes, diagram) -> bytes:
    if len(original) > MAX_BYTES:
        raise EditError("Файл больше 5 МБ.")
    text = original.decode("utf-8-sig")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise EditError("Документы с DTD не редактируются.")
    doc = minidom.parseString(original)
    root = doc.documentElement
    if root.namespaceURI != BPMN or root.localName != "definitions":
        raise EditError("Это не документ BPMN 2.0.")
    ids = [el.getAttribute("id") for el in doc.getElementsByTagName("*") if el.hasAttribute("id")]
    if len(ids) != len(set(ids)):
        raise EditError("Сначала исправьте повторяющиеся ID: однозначное сохранение невозможно.")

    def make(namespace, local):
        prefix = next((attr.localName for attr in root.attributes.values()
                       if attr.prefix == "xmlns" and attr.value == namespace), None)
        if prefix is None:
            prefix = {DIAGRAM: "bpmndi", COORDINATES: "dc", DRAWING: "di"}[namespace]
            while root.hasAttribute("xmlns:" + prefix):
                prefix += "_"
            root.setAttributeNS("http://www.w3.org/2000/xmlns/", "xmlns:" + prefix, namespace)
        return doc.createElementNS(namespace, prefix + ":" + local)

    def children(parent, namespace, local):
        return [el for el in parent.childNodes if el.nodeType == el.ELEMENT_NODE
                and el.namespaceURI == namespace and el.localName == local]

    def set_bounds(parent, bounds):
        candidates = children(parent, COORDINATES, "Bounds")
        element = candidates[0] if candidates else make(COORDINATES, "Bounds")
        if not candidates:
            parent.insertBefore(element, parent.firstChild)
        for key, value in zip(("x", "y", "width", "height"), bounds):
            if not math.isfinite(value) or abs(value) > 1_000_000:
                raise EditError("Координаты выходят за допустимый диапазон.")
            element.setAttribute(key, f"{value:.3f}".rstrip("0").rstrip("."))

    def set_label(parent, bounds):
        if bounds is None:
            return
        candidates = children(parent, DIAGRAM, "BPMNLabel")
        label = candidates[0] if candidates else make(DIAGRAM, "BPMNLabel")
        if not candidates:
            parent.appendChild(label)
        set_bounds(label, bounds)

    all_ids = set(ids)
    def unique_id(base):
        while base in all_ids:
            base += "_"
        all_ids.add(base)
        return base

    planes = doc.getElementsByTagNameNS(DIAGRAM, "BPMNPlane")
    if planes:
        plane = planes[0]
    else:
        scopes = doc.getElementsByTagNameNS(BPMN, "collaboration") or doc.getElementsByTagNameNS(BPMN, "process")
        if not scopes or not scopes[0].getAttribute("id"):
            raise EditError("Не найден процесс с ID для сохранения раскладки.")
        drawing = make(DIAGRAM, "BPMNDiagram")
        drawing.setAttribute("id", unique_id("Diagram_Check"))
        root.appendChild(drawing)
        plane = make(DIAGRAM, "BPMNPlane")
        plane.setAttribute("id", unique_id("Plane_Check"))
        plane.setAttribute("bpmnElement", scopes[0].getAttribute("id"))
        drawing.appendChild(plane)
    visuals = {el.getAttribute("bpmnElement"): el for el in plane.childNodes
               if el.nodeType == el.ELEMENT_NODE and el.namespaceURI == DIAGRAM}
    for shape in diagram.shapes:
        visual = visuals.get(shape.element_id)
        if visual is None:
            visual = make(DIAGRAM, "BPMNShape")
            visual.setAttribute("id", unique_id(shape.element_id + "_di"))
            visual.setAttribute("bpmnElement", shape.element_id)
            plane.appendChild(visual)
        if shape.kind in {"subProcess", "transaction", "adHocSubProcess"}:
            visual.setAttribute("isExpanded", "true" if shape.expanded else "false")
        set_bounds(visual, (shape.x, shape.y, shape.width, shape.height))
        set_label(visual, shape.label)
    for edge in diagram.edges:
        visual = visuals.get(edge.element_id)
        if visual is None:
            visual = make(DIAGRAM, "BPMNEdge")
            visual.setAttribute("id", unique_id(edge.element_id + "_di"))
            visual.setAttribute("bpmnElement", edge.element_id)
            plane.appendChild(visual)
        existing = children(visual, DRAWING, "waypoint")
        for element in existing:
            visual.removeChild(element)
        anchor = visual.firstChild
        for x, y in edge.points:
            element = make(DRAWING, "waypoint")
            for key, value in (("x", x), ("y", y)):
                if not math.isfinite(value) or abs(value) > 1_000_000:
                    raise EditError("Координаты стрелки выходят за допустимый диапазон.")
                element.setAttribute(key, f"{value:.3f}".rstrip("0").rstrip("."))
            visual.insertBefore(element, anchor)
        set_label(visual, edge.label)
    result = doc.toxml(encoding="utf-8")
    if len(result) > MAX_BYTES:
        raise EditError("После изменения файл превысил 5 МБ.")
    return result


def save_document(path, expected: bytes, updated: bytes):
    """Проверка внешних изменений, резервная копия и атомарная замена файла."""
    path = Path(path).resolve()
    if path.read_bytes() != expected:
        raise EditError("Файл изменён в другом редакторе. Загружена новая версия; повторите перенос.")
    backup = path.with_name(path.name + ".bak")
    try:
        with backup.open("xb") as file:
            file.write(expected)
    except FileExistsError:
        pass
    fd, temporary = tempfile.mkstemp(prefix=".bpmn-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(updated)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        if path.read_bytes() != expected:
            raise EditError("Файл изменился во время сохранения. Повторите перенос после обновления.")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
