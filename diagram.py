"""Данные для отрисовки BPMN. Не зависит от оконного интерфейса.

BPMN DI хранит прямоугольники элементов и точки линий прямо в XML.
Если координат нет, используем простую раскладку, не меняя исходный файл.
"""

from dataclasses import dataclass, field
import math
import xml.etree.ElementTree as ET

from checker import MAX_BYTES, NODES, Report, kind


DIAGRAM = "http://www.omg.org/spec/BPMN/20100524/DI"
DRAWING = "http://www.omg.org/spec/DD/20100524/DI"
COORDINATES = "http://www.omg.org/spec/DD/20100524/DC"
CONTAINERS = {"participant", "lane"}
LINKS = {"sequenceFlow", "messageFlow", "association"}
ARTIFACTS = {"dataObject", "dataObjectReference", "textAnnotation"}


def display_name(element):
    if kind(element) == "textAnnotation":
        text = next((child for child in element if kind(child) == "text"), None)
        return "".join(text.itertext()) if text is not None else ""
    return element.get("name", "")


@dataclass
class Shape:
    element_id: str
    kind: str
    name: str
    x: float
    y: float
    width: float
    height: float
    expanded: bool = False
    label: tuple[float, float, float, float] | None = None
    attached_to: str = ""
    lane_id: str = ""


@dataclass
class Edge:
    element_id: str
    kind: str
    name: str
    points: list[tuple[float, float]]
    label: tuple[float, float, float, float] | None = None
    source_id: str = ""
    target_id: str = ""


@dataclass
class Diagram:
    shapes: list[Shape] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    note: str = ""


def read_bounds(element):
    if element is None:
        return None
    try:
        values = tuple(float(element.get(key, "")) for key in ("x", "y", "width", "height"))
        x, y, width, height = values
        if not all(math.isfinite(value) and abs(value) <= 1_000_000 for value in values):
            return None
        if width <= 0 or height <= 0:
            return None
        return x, y, width, height
    except ValueError:
        return None


def read_label(element):
    return read_bounds(element.find(f"{{{DIAGRAM}}}BPMNLabel/{{{COORDINATES}}}Bounds"))


def severity_by_element(report: Report) -> dict[str, str]:
    """Красный имеет приоритет, если у элемента есть ещё и рекомендации."""
    result = {}
    for issue in report.issues:
        if issue.element_id and result.get(issue.element_id) != "error":
            result[issue.element_id] = issue.severity
    return result


def load_diagram(data: bytes) -> Diagram:
    if len(data) > MAX_BYTES:
        return Diagram(note="Файл слишком большой для просмотра.")
    try:
        text = data.decode("utf-8-sig")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise ValueError("DTD")
        root = ET.fromstring(text)
    except (UnicodeError, ValueError, ET.ParseError):
        return Diagram(note="Невозможно отрисовать повреждённый XML. Подробности в списке ниже.")
    if kind(root) != "definitions":
        return Diagram(note="Для просмотра нужен документ BPMN 2.0.")
    semantic = {}
    duplicate = False
    for element in root.iter():
        identifier = element.get("id")
        if kind(element) and identifier:
            duplicate |= identifier in semantic
            semantic.setdefault(identifier, element)
    planes = root.findall(f".//{{{DIAGRAM}}}BPMNPlane")
    lane_ids = {ref.text: lane.get("id", "") for lane in root.iter() if kind(lane) == "lane"
                for ref in lane if kind(ref) == "flowNodeRef"}
    if not planes:
        return automatic_layout(semantic)
    diagram = Diagram()
    omitted = 0
    # Первая страница BPMNDiagram. Остальные страницы явно отмечаем в интерфейсе.
    for visual in planes[0]:
        identifier = visual.get("bpmnElement", "")
        element = semantic.get(identifier)
        if element is None:
            omitted += 1
            continue
        if visual.tag == f"{{{DIAGRAM}}}BPMNShape":
            bounds = read_bounds(visual.find(f"{{{COORDINATES}}}Bounds"))
            if bounds is None:
                omitted += 1
                continue
            diagram.shapes.append(Shape(identifier, kind(element), display_name(element), *bounds,
                                        expanded=visual.get("isExpanded") == "true", label=read_label(visual),
                                        attached_to=element.get("attachedToRef", ""), lane_id=lane_ids.get(identifier, "")))
        elif visual.tag == f"{{{DIAGRAM}}}BPMNEdge":
            try:
                points = [(float(point.get("x", "")), float(point.get("y", "")))
                          for point in visual.findall(f"{{{DRAWING}}}waypoint")]
                if len(points) < 2 or not all(math.isfinite(value) and abs(value) <= 1_000_000
                                              for point in points for value in point):
                    raise ValueError("Неверные координаты")
            except ValueError:
                omitted += 1
                continue
            diagram.edges.append(Edge(identifier, kind(element), element.get("name", ""), points, read_label(visual),
                                      element.get("sourceRef", ""), element.get("targetRef", "")))
    if not diagram.shapes:
        return automatic_layout(semantic)
    notes = []
    if len(planes) > 1:
        notes.append(f"Показана первая из {len(planes)} страниц; замечания относятся ко всему файлу.")
    if omitted:
        notes.append(f"Не показано элементов с некорректными координатами или ссылками: {omitted}.")
    if duplicate:
        notes.append("Повторяющиеся ID: отображение привязано к первому элементу с этим ID.")
    diagram.note = " ".join(notes)
    return diagram


def automatic_layout(semantic: dict) -> Diagram:
    """Упрощённая сетка для XML без DI; вложенность здесь не изображается."""
    diagram = Diagram(note="Нет пригодной раскладки BPMN DI: показана упрощённая сетка без пулов и вложенности.")
    nodes = {identifier: element for identifier, element in semantic.items() if kind(element) in NODES | ARTIFACTS}
    # Стабильный порядок из XML делает просмотр воспроизводимым.
    for index, (identifier, element) in enumerate(nodes.items()):
        node_kind = kind(element)
        width, height = (44, 44) if node_kind.endswith("Event") else (140, 80)
        if node_kind.endswith("Gateway"):
            width, height = 54, 54
        diagram.shapes.append(Shape(identifier, node_kind, display_name(element),
                                    80 + (index % 5) * 210, 80 + (index // 5) * 160, width, height))
    positions = {shape.element_id: shape for shape in diagram.shapes}
    for identifier, element in semantic.items():
        if kind(element) not in LINKS:
            continue
        source = positions.get(element.get("sourceRef"))
        target = positions.get(element.get("targetRef"))
        if source is None or target is None:
            continue
        start = (source.x + source.width, source.y + source.height / 2)
        finish = (target.x, target.y + target.height / 2)
        if source is target:
            points = [start, (start[0] + 30, start[1]), (start[0] + 30, source.y - 30),
                      (source.x + source.width / 2, source.y - 30), (source.x + source.width / 2, source.y)]
        else:
            points = [start, ((start[0] + finish[0]) / 2, start[1]),
                      ((start[0] + finish[0]) / 2, finish[1]), finish]
        diagram.edges.append(Edge(identifier, kind(element), element.get("name", ""), points,
                                  source_id=element.get("sourceRef", ""), target_id=element.get("targetRef", "")))
    if not nodes:
        diagram.note = "В документе нет элементов процесса для отображения."
    return diagram
