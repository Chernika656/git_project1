"""Небольшой статический анализатор BPMN 2.0 на стандартной библиотеке Python.

Он проверяет структуру графа, но не исполняет процесс и не заменяет BPMN XSD.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from html import escape
import json
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET


BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
MAX_BYTES = 5 * 1024 * 1024
ACTIVITIES = {
    "task", "userTask", "serviceTask", "manualTask", "scriptTask",
    "businessRuleTask", "sendTask", "receiveTask", "callActivity",
    "subProcess", "transaction", "adHocSubProcess",
}
GATEWAYS = {
    "exclusiveGateway", "inclusiveGateway", "parallelGateway",
    "eventBasedGateway", "complexGateway",
}
NODES = ACTIVITIES | GATEWAYS | {
    "startEvent", "endEvent", "intermediateCatchEvent",
    "intermediateThrowEvent", "boundaryEvent",
}
SCOPES = {"process", "subProcess", "transaction", "adHocSubProcess"}


def kind(element: ET.Element | None) -> str:
    """Учитываем только элементы BPMN, не расширения редакторов."""
    if element is None:
        return ""
    prefix = "{" + BPMN + "}"
    return element.tag[len(prefix):] if element.tag.startswith(prefix) else ""


@dataclass
class Issue:
    severity: str
    code: str
    element_id: str
    element_name: str
    message: str
    hint: str


@dataclass
class Report:
    filename: str
    issues: list[Issue] = field(default_factory=list)
    processes: int = 0
    nodes: int = 0
    flows: int = 0

    @property
    def errors(self) -> int:
        return sum(issue.severity == "error" for issue in self.issues)

    @property
    def warnings(self) -> int:
        return sum(issue.severity == "warning" for issue in self.issues)

    def add(self, severity, code, element, message, hint):
        self.issues.append(Issue(
            severity, code,
            element.get("id", "") if element is not None else "",
            element.get("name", "") if element is not None else "",
            message, hint,
        ))

    def to_dict(self) -> dict:
        return {**asdict(self), "errors": self.errors, "warnings": self.warnings}


def reachable(seeds: set[str], edges: dict[str, list[str]]) -> set[str]:
    """Обход графа без рекурсии: безопасен для циклов и длинных процессов."""
    seen = set(seeds)
    pending = list(seeds)
    while pending:
        current = pending.pop()
        for target in edges.get(current, []):
            if target not in seen:
                seen.add(target)
                pending.append(target)
    return seen


def check_bytes(data: bytes, filename: str = "Схема") -> Report:
    report = Report(filename)
    if len(data) > MAX_BYTES:
        report.add("error", "FILE_TOO_LARGE", None, "Файл больше 5 МБ.", "Выберите меньшую схему.")
        return report
    try:
        # Явное ограничение UTF-8 позволяет отклонить DTD до XML-парсинга,
        # в том числе избежать обхода проверки через UTF-16.
        text = data.decode("utf-8-sig")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise ValueError("Объявления DTD и ENTITY не поддерживаются.")
        root = ET.fromstring(text)
    except (UnicodeError, ET.ParseError, ValueError) as exc:
        report.add("error", "INVALID_XML", None, f"Не удалось прочитать XML: {exc}",
                   "Экспортируйте BPMN 2.0 в кодировке UTF-8 из редактора.")
        return report
    if kind(root) != "definitions":
        report.add("error", "NOT_BPMN", root, "Это не документ BPMN 2.0 definitions.",
                   "Нужен файл .bpmn или .xml, а не картинка схемы.")
        return report

    elements = list(root.iter())
    report.processes = sum(kind(el) == "process" for el in elements)
    report.nodes = sum(kind(el) in NODES for el in elements)
    report.flows = sum(kind(el) == "sequenceFlow" for el in elements)
    ids: dict[str, ET.Element] = {}
    for element in elements:
        identifier = element.get("id")
        if identifier:
            if identifier in ids:
                report.add("error", "DUPLICATE_ID", element, "Идентификатор повторяется в документе.",
                           "Задайте каждому элементу уникальный id.")
            ids[identifier] = element
        elif kind(element) in NODES | SCOPES | {"sequenceFlow", "messageFlow", "participant", "collaboration"}:
            report.add("error", "MISSING_ID", element, "У элемента отсутствует id.",
                       "Назначьте идентификатор в редакторе или XML.")
    if not report.processes:
        report.add("warning", "NO_PROCESS", root, "В документе нет процесса для проверки.",
                   "Экспортируйте схему с внутренним процессом участника.")
    if any(issue.code in {"MISSING_ID", "DUPLICATE_ID"} for issue in report.issues):
        # Не строим неоднозначный граф и не выдаём каскад ложных сообщений.
        return report

    check_collaborations(elements, ids, report)
    for scope in elements:
        if kind(scope) not in SCOPES:
            continue
        if scope.get("triggeredByEvent") == "true" or kind(scope) in {"adHocSubProcess", "transaction"}:
            report.add("warning", "ADVANCED_SCOPE", scope,
                       "Специальная семантика этого подпроцесса проверяется не полностью.",
                       "В этой области проверены ссылки и базовые ограничения; пути требуют ручной проверки.")
            check_scope(scope, report, paths=False)
        else:
            check_scope(scope, report, paths=True)
    report.issues.sort(key=lambda issue: (issue.severity != "error", issue.element_id, issue.code))
    return report


def check_collaborations(elements: list[ET.Element], ids: dict[str, ET.Element], report: Report) -> None:
    parents = {child: parent for parent in elements for child in parent}
    local_ref = lambda value: value.rsplit(":", 1)[-1] if value else ""
    endpoints = ACTIVITIES | {"participant", "startEvent", "endEvent",
                              "intermediateCatchEvent", "intermediateThrowEvent", "boundaryEvent"}

    def process_of(element: ET.Element) -> ET.Element | None:
        while element is not None and kind(element) != "process":
            element = parents.get(element)
        return element

    for collaboration in (element for element in elements if kind(element) == "collaboration"):
        participants = [child for child in collaboration if kind(child) == "participant"]
        by_process = {}
        for participant in participants:
            process_ref = participant.get("processRef")
            if process_ref:
                process_id = local_ref(process_ref)
                if kind(ids.get(process_id)) != "process":
                    report.add("error", "PARTICIPANT_PROCESS", participant,
                               "Пул ссылается на отсутствующий процесс.",
                               "Укажите существующий process в processRef или оставьте пул без внутреннего процесса.")
                else:
                    by_process[process_id] = participant
        for flow in (child for child in collaboration if kind(child) == "messageFlow"):
            source, target = ids.get(local_ref(flow.get("sourceRef"))), ids.get(local_ref(flow.get("targetRef")))
            if source is None or target is None:
                report.add("error", "MESSAGE_FLOW_REFERENCE", flow,
                           "Сообщение ссылается на отсутствующий элемент.",
                           "Соедините существующие действия, события или границы двух пулов.")
                continue
            if kind(source) not in endpoints or kind(target) not in endpoints:
                report.add("error", "MESSAGE_FLOW_ENDPOINT", flow,
                           "Сообщение соединено с элементом неподходящего типа.",
                           "Используйте действие, событие или границу пула; шлюз и артефакт не подходят.")
                continue
            def pool_for(element):
                if kind(element) == "participant":
                    return element if element in participants else None
                process = process_of(element)
                return by_process.get(process.get("id")) if process is not None else None
            source_pool, target_pool = pool_for(source), pool_for(target)
            if source_pool is None or target_pool is None:
                report.add("error", "MESSAGE_FLOW_POOL", flow,
                           "Концы сообщения не принадлежат двум пулам этого сотрудничества.",
                           "Добавьте участников с processRef и соедините элементы внутри их процессов.")
            elif source_pool is target_pool:
                report.add("error", "MESSAGE_FLOW_SAME_POOL", flow,
                           "Сообщение соединяет элементы одного пула.",
                           "Внутри пула используйте поток последовательности; сообщение направьте другому участнику.")
    for flow in (element for element in elements if kind(element) == "messageFlow"):
        if kind(parents.get(flow)) != "collaboration":
            report.add("error", "MESSAGE_FLOW_SCOPE", flow,
                       "Связь сообщений должна находиться внутри collaboration.",
                       "Перенесите messageFlow в collaboration двух участников.")


def check_scope(scope: ET.Element, report: Report, paths: bool) -> None:
    # Только непосредственные дети: поток не может пересекать границы подпроцесса.
    nodes = {el.get("id"): el for el in scope if kind(el) in NODES}
    flows = [el for el in scope if kind(el) == "sequenceFlow"]
    if kind(scope) == "adHocSubProcess":
        if not any(kind(el) in ACTIVITIES for el in nodes.values()):
            report.add("error", "AD_HOC_EMPTY", scope,
                       "В свободном подпроцессе нет действий.",
                       "Добавьте хотя бы одно действие внутрь подпроцесса.")
        if any(kind(el) in {"startEvent", "endEvent"} for el in nodes.values()):
            report.add("error", "AD_HOC_BOUNDARY_EVENT", scope,
                       "Свободный подпроцесс не должен содержать начальное или конечное событие.",
                       "Удалите начальное и конечное события внутри свободного подпроцесса.")
        if scope.get("ordering", "Parallel") not in {"Parallel", "Sequential"}:
            report.add("error", "AD_HOC_ORDERING", scope,
                       "Неизвестный порядок действий свободного подпроцесса.",
                       "Укажите Parallel или Sequential.")
    if not nodes:
        if kind(scope) == "process":
            report.add("warning", "EMPTY_PROCESS", scope, "В процессе нет действий или событий.",
                       "Добавьте шаги процесса или проверьте экспорт.")
    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)
    outgoing_flows: dict[str, list[ET.Element]] = defaultdict(list)
    damaged = False
    for flow in flows:
        source, target = flow.get("sourceRef"), flow.get("targetRef")
        if source not in nodes or target not in nodes:
            report.add("error", "BROKEN_REFERENCE", flow,
                       "Поток ссылается на отсутствующий элемент или другую область процесса.",
                       "Соедините два существующих элемента внутри одного процесса или подпроцесса.")
            damaged = True
            continue
        outgoing[source].append(target)
        incoming[target].append(source)
        outgoing_flows[source].append(flow)

    starts = {identifier for identifier, el in nodes.items() if kind(el) == "startEvent"}
    ends = {identifier for identifier, el in nodes.items() if kind(el) == "endEvent"}
    if kind(scope) == "subProcess" and scope.get("triggeredByEvent") == "true":
        if len(starts) != 1:
            report.add("error", "EVENT_SUBPROCESS_START_COUNT", scope,
                       "У событийного подпроцесса должно быть ровно одно стартовое событие.",
                       "Оставьте одно startEvent внутри событийного подпроцесса.")
        else:
            start = nodes[next(iter(starts))]
            if not any(kind(child).endswith("EventDefinition") or kind(child) == "eventDefinitionRef"
                       for child in start):
                report.add("error", "EVENT_SUBPROCESS_TRIGGER", start,
                           "Стартовое событие событийного подпроцесса не имеет триггера.",
                           "Добавьте определение события, например messageEventDefinition.")
    excluded = {
        identifier for identifier, el in nodes.items()
        if el.get("isForCompensation") == "true" or el.get("triggeredByEvent") == "true"
    }
    boundaries: dict[str, list[str]] = defaultdict(list)
    for identifier, node in nodes.items():
        node_kind = kind(node)
        for loop in (child for child in node if kind(child) == "multiInstanceLoopCharacteristics"):
            cardinality = next((child for child in loop if kind(child) == "loopCardinality"), None)
            data_input = next((child for child in loop if kind(child) == "loopDataInputRef"), None)
            if (cardinality is None or not "".join(cardinality.itertext()).strip()) and data_input is None:
                report.add("error", "MULTI_INSTANCE_COUNT", node,
                           "У повторяющегося действия не задано число экземпляров или входная коллекция.",
                           "Укажите loopCardinality либо loopDataInputRef.")
            elif cardinality is not None:
                value = "".join(cardinality.itertext()).strip()
                if value.lstrip("-").isdigit() and int(value) < 0:
                    report.add("error", "MULTI_INSTANCE_COUNT", node,
                               "Число экземпляров действия отрицательное.",
                               "Укажите неотрицательное loopCardinality.")
        if node_kind == "subProcess" and node.get("triggeredByEvent") == "true" and (
                incoming[identifier] or outgoing[identifier]):
            report.add("error", "EVENT_SUBPROCESS_FLOW", node,
                       "Событийный подпроцесс соединён внешним потоком последовательности.",
                       "Удалите входящие и исходящие sequenceFlow у событийного подпроцесса.")
        if node_kind == "startEvent" and incoming[identifier]:
            report.add("error", "START_INCOMING", node, "Во входное событие начала входит поток последовательности.",
                       "Уберите входящий поток или используйте подходящее промежуточное событие.")
        if node_kind == "endEvent" and outgoing[identifier]:
            report.add("error", "END_OUTGOING", node, "Из события завершения выходит поток последовательности.",
                       "Уберите исходящий поток или замените событие завершения.")
        if node_kind == "boundaryEvent":
            attached = node.get("attachedToRef")
            if attached not in nodes or kind(nodes[attached]) not in ACTIVITIES:
                report.add("error", "BOUNDARY_ATTACHMENT", node, "Граничное событие не прикреплено к действию в этой области.",
                           "Укажите существующее действие в attachedToRef.")
                damaged = True
            else:
                boundaries[attached].append(identifier)
            if incoming[identifier]:
                report.add("error", "BOUNDARY_INCOMING", node, "У граничного события есть входящий поток последовательности.",
                           "Событие запускается у прикреплённого действия, а не входящим потоком.")
            if any(kind(child) == "compensateEventDefinition" for child in node):
                excluded.add(identifier)
        if node_kind == "receiveTask" and node.get("instantiate") == "true" and incoming[identifier]:
            report.add("error", "RECEIVE_INSTANTIATE_INCOMING", node,
                       "Задача получения, запускающая процесс, имеет входящий поток.",
                       "Удалите входящий поток последовательности или отключите запуск процесса.")
        if node_kind == "eventBasedGateway":
            gateway_flows = outgoing_flows[identifier]
            if node.get("instantiate") == "true" and incoming[identifier]:
                report.add("error", "EVENT_GATEWAY_INSTANTIATE_INCOMING", node,
                           "Запускающий процесс шлюз по событию имеет входящий поток.",
                           "Удалите входящий поток у запускающего шлюза.")
            if node.get("eventGatewayType") == "Parallel" and node.get("instantiate") != "true":
                report.add("error", "EVENT_GATEWAY_PARALLEL_INSTANTIATE", node,
                           "Параллельный событийный шлюз не настроен на запуск процесса.",
                           "Для Parallel установите instantiate=true или используйте обычный параллельный шлюз.")
            if len(gateway_flows) < 2:
                report.add("error", "EVENT_GATEWAY_BRANCHES", node,
                           "У шлюза по событию должно быть не меньше двух исходящих потоков.",
                           "Добавьте альтернативные ожидаемые события или задачи получения сообщения.")
            targets = [nodes[flow.get("targetRef")] for flow in gateway_flows]
            has_receive = any(kind(target) == "receiveTask" for target in targets)
            has_message = False
            for flow, target in zip(gateway_flows, targets):
                if any(kind(child) == "conditionExpression" for child in flow):
                    report.add("error", "EVENT_GATEWAY_CONDITION", flow,
                               "У потока после шлюза по событию задано условие.",
                               "Перенесите условие в ожидаемое событие или используйте другой шлюз.")
                target_kind = kind(target)
                if target_kind not in {"intermediateCatchEvent", "receiveTask"}:
                    report.add("error", "EVENT_GATEWAY_TARGET", flow,
                               "Поток шлюза по событию ведёт не к ожидающему событию или задаче получения.",
                               "Соедините шлюз с intermediateCatchEvent или receiveTask.")
                    continue
                target_id = target.get("id")
                if len(incoming[target_id]) != 1:
                    report.add("error", "EVENT_GATEWAY_TARGET_INCOMING", target,
                               "К варианту шлюза по событию ведёт ещё один поток.",
                               "Оставьте у этого события только входящий поток от шлюза.")
                if target_kind == "receiveTask":
                    if any(kind(other) == "boundaryEvent" and other.get("attachedToRef") == target_id
                           for other in nodes.values()):
                        report.add("error", "EVENT_GATEWAY_RECEIVE_BOUNDARY", target,
                                   "У задачи получения после шлюза есть граничное событие.",
                                   "Удалите граничное событие или вынесите задачу за шлюз.")
                    continue
                triggers = {kind(child) for child in target}
                has_message |= "messageEventDefinition" in triggers
                if not triggers.intersection({"messageEventDefinition", "signalEventDefinition",
                                              "timerEventDefinition", "conditionalEventDefinition",
                                              "multipleEventDefinition", "eventDefinitionRef"}):
                    report.add("error", "EVENT_GATEWAY_TRIGGER", target,
                               "После шлюза указано событие без допустимого триггера.",
                               "Используйте сообщение, сигнал, таймер, условие или множественное событие.")
            if has_receive and has_message:
                report.add("error", "EVENT_GATEWAY_MIXED_MESSAGE", node,
                           "Шлюз одновременно ожидает событие сообщения и задачу получения сообщения.",
                           "Используйте для сообщений только один из этих способов ожидания.")
        if node_kind in ACTIVITIES and not node.get("name", "").strip():
            report.add("warning", "UNNAMED_ACTIVITY", node, "Действие не подписано.",
                       "Назовите результат или действие, например «Проверить заявку».")
        default = node.get("default")
        if default and default not in {flow.get("id") for flow in outgoing_flows[identifier]}:
            report.add("error", "INVALID_DEFAULT", node, "Путь по умолчанию не является исходящим потоком элемента.",
                       "Выберите один из исходящих потоков как default.")
        if node_kind in {"exclusiveGateway", "inclusiveGateway"} and len(outgoing_flows[identifier]) > 1:
            for flow in outgoing_flows[identifier]:
                condition = flow.find("{" + BPMN + "}conditionExpression")
                if flow.get("id") != default and (condition is None or not "".join(condition.itertext()).strip()):
                    report.add("warning", "BRANCH_CONDITION", flow,
                               "Для ветки не задано формальное условие выбора.",
                               "Уточните правило перехода; в описательной схеме подписи может быть достаточно.")

    if not paths or damaged:
        return
    active = set(nodes) - excluded
    # Отсутствие явных start/end допустимо в BPMN: используем неявные точки.
    seeds = starts or {identifier for identifier in active
                      if not incoming[identifier] and kind(nodes[identifier]) != "boundaryEvent"}
    graph = {identifier: outgoing[identifier] + boundaries.get(identifier, []) for identifier in nodes}
    seen = reachable(seeds, graph)
    for identifier in sorted(active - seen):
        report.add("warning", "UNREACHABLE", nodes[identifier],
                   "По потокам графа элемент недостижим от начала процесса.",
                   "Проверьте входящие связи. Условия и события исполнения анализатор не моделирует.")
    # Только обычные процессы: обработка прерываний и компенсаций требует движка.
    if boundaries or excluded or any(kind(el) in {"transaction", "adHocSubProcess", "complexGateway"}
                                      for el in nodes.values()):
        report.add("warning", "PATH_CHECK_LIMITED", scope,
                   "Проверка путей до завершения пропущена из-за специальных элементов.",
                   "Вручную проверьте прерывания, компенсации и завершение ветвей.")
        return
    terminals = ends or {identifier for identifier in active if not outgoing[identifier]}
    can_finish = reachable(terminals, incoming)
    for identifier in sorted((active & seen) - can_finish):
        report.add("warning", "NO_PATH_TO_END", nodes[identifier],
                   "В графе нет пути от элемента к завершению.",
                   "Проверьте замкнутый цикл или незавершённую ветку. Это не анализ токенов BPMN.")


def check_file(path: str | Path) -> Report:
    path = Path(path)
    try:
        with path.open("rb") as source:
            data = source.read(MAX_BYTES + 1)
    except OSError as exc:
        report = Report(path.name)
        report.add("error", "FILE_READ", None, f"Не удалось открыть файл: {exc.strerror or exc}",
                   "Проверьте путь и права на чтение.")
        return report
    return check_bytes(data, path.name)


def format_text(report: Report) -> str:
    lines = [f"BPMN Check · {report.filename}",
             f"Элементов: {report.nodes} · Потоков: {report.flows}",
             f"Ошибок: {report.errors} · Рекомендаций: {report.warnings}"]
    for issue in report.issues:
        label = "ОШИБКА" if issue.severity == "error" else "ПРОВЕРИТЬ"
        element = issue.element_name or issue.element_id or "Документ"
        lines.extend([f"\n[{label}] {element} ({issue.code})", issue.message, f"  → {issue.hint}"])
    if not report.issues:
        lines.append("В рамках доступных проверок замечаний нет.")
    return "\n".join(lines)


def write_html(report: Report, path: str | Path) -> None:
    """Автономный отчёт: без сервера, скриптов, шрифтов и внешних запросов."""
    cards = []
    for issue in report.issues:
        label = "Ошибка" if issue.severity == "error" else "Проверить"
        cards.append(f'<article class="{issue.severity}"><div class="issue-top"><span class="badge">{label}</span><span class="rule">{escape(issue.code)}</span></div>'
                     f'<h2>{escape(issue.element_name or issue.element_id or "Документ")}</h2>'
                     f'<p>{escape(issue.message)}</p><div class="hint"><b>Что сделать</b><br>{escape(issue.hint)}</div>'
                     f'<code class="element-id">Элемент: {escape(issue.element_id) or "документ"}</code></article>')
    content = "\n".join(cards) or '<article class="success"><h2>Замечаний не найдено</h2><p>Схема прошла доступные структурные проверки.</p></article>'
    css = Path(__file__).with_name("report.css").read_text(encoding="utf-8")
    html = f'''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BPMN Check — {escape(report.filename)}</title>
<style>{css}</style><main><div class="brand"><strong>BPMN Check</strong><span>Локальный отчёт · без облака</span></div>
<header><small>АНАЛИЗ СХЕМЫ ПРОЦЕССА</small><h1>Всё по шагам.</h1>
<p class="filename">{escape(report.filename)}</p></header><div class="stats">
<div class="stat errors"><strong>{report.errors}</strong><span>Ошибки структуры</span></div>
<div class="stat warnings"><strong>{report.warnings}</strong><span>Рекомендации</span></div>
<div class="stat"><strong>{report.nodes}</strong><span>Элементы процесса</span></div></div>
<div class="section-heading"><h2>Результаты проверки</h2><span>Найдено замечаний: {len(report.issues)} · Потоков: {report.flows}</span></div>{content}
<footer>Проверка помогает найти проблемы в структуре схемы. Она не исполняет процесс,
не оценивает бизнес-смысл и не заменяет полную валидацию BPMN.</footer></main></html>'''
    Path(path).write_text(html, encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Проверка структуры BPMN 2.0")
    parser.add_argument("file", type=Path, help="Файл .bpmn или .xml")
    parser.add_argument("--json", action="store_true", help="Машиночитаемый отчёт")
    parser.add_argument("--html", type=Path, help="Сохранить HTML-отчёт")
    parser.add_argument("--watch", action="store_true", help="Проверять после сохранения файла")
    args = parser.parse_args(argv)
    if args.html and args.html.resolve() == args.file.resolve():
        parser.error("HTML-отчёт нельзя сохранять поверх исходной схемы")
    last = object()
    try:
        while True:
            try:
                stat = args.file.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                signature = None
            if signature != last:
                # Небольшая задержка сглаживает запись файла редактором.
                if args.watch:
                    time.sleep(0.25)
                report = check_file(args.file)
                print(json.dumps(report.to_dict(), ensure_ascii=False) if args.json else format_text(report), flush=True)
                if args.html:
                    try:
                        write_html(report, args.html)
                    except OSError as exc:
                        print(f"Не удалось сохранить отчёт: {exc}", file=sys.stderr)
                        return 2
                last = signature
                if not args.watch:
                    return 1 if report.errors else 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
