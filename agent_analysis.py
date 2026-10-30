"""Контекст проекта и проверка ссылок в аналитическом ответе агента."""
import json
import xml.etree.ElementTree as ET
from checker import check_bytes, kind, NODES


def object_schema(properties):
    return dict(type='object', additionalProperties=False, properties=properties, required=list(properties))


TEXT = {'type': 'string'}
SCHEMA = object_schema({
    'summary': TEXT,
    'findings': {'type': 'array', 'items': object_schema({
        'severity': {'type': 'string', 'enum': ['error', 'warning', 'suggestion']},
        'block_id': TEXT, 'element_id': TEXT, 'title': TEXT, 'explanation': TEXT,
        'recommendation': TEXT,
    })},
    'questions': {'type': 'array', 'items': TEXT},
    'next_steps': {'type': 'array', 'items': TEXT},
})


def project_context(project, scope, block_id=None, layer='all'):
    if scope not in ('project', 'block', 'bpmn'):
        raise ValueError('Выберите анализ проекта или BPMN.')
    blocks = project['blocks']
    if scope in ('block', 'bpmn'):
        blocks = [b for b in blocks if b['id'] == block_id]
        if not blocks:
            raise ValueError('Блок не найден.')
    if scope == 'bpmn':
        layer = 'bpmn'
        if not blocks[0].get('bpmn'):
            raise ValueError('В выбранном блоке пока нет BPMN-схемы.')
    if layer not in ('all','overview','requirements','bpmn','uml','technical','slides'):
        raise ValueError('Неизвестный слой контекста.')
    context = {k: project.get(k) for k in ('id', 'name', 'goal', 'revision')}
    context['links']=[link for link in project.get('links',[]) if scope=='project' or block_id in (link.get('source'),link.get('target'))]
    if layer in ('all','overview','requirements'):
        context['glossary']=[term for term in project.get('glossary',[]) if scope=='project' or block_id in term.get('blocks',[])]
    context['block_index'] = [{'id': b['id'], 'name': b['name']} for b in project['blocks']]
    context['scope'] = scope
    context['layer'] = layer
    context['blocks'] = []
    references = {}
    for b in blocks:
        item = {k: b.get(k) for k in ('id', 'name', 'description', 'owner', 'status')}
        if layer in ('all','requirements','bpmn','slides'):
            item.update({k:b.get(k) for k in ('requirements','requirement_items')})
        if layer in ('all','uml'): item['uml']=b.get('uml')
        if layer in ('all','technical'): item['technical']=b.get('technical')
        if layer in ('all','bpmn','uml'): item['element_details']=b.get('element_details')
        references[b['id']] = set()
        if layer in ('all','bpmn') and b.get('bpmn'):
            report = check_bytes(b['bpmn'].encode()).to_dict()
            item['checker'] = {key:report[key] for key in ('processes','nodes','flows','errors','warnings')}
            item['checker']['issues']=[{key:issue.get(key,'') for key in ('severity','code','element_id','message')} for issue in report['issues']]
            if not any(i['code'] in ('INVALID_XML', 'FILE_TOO_LARGE', 'NOT_BPMN') for i in report['issues']):
                root = ET.fromstring(b['bpmn'])
                processes=[element for element in root.iter() if kind(element)=='process']
                split_process=max(processes,key=lambda element:sum(kind(child) in NODES for child in element)) if processes else None
                item['bpmn_split_candidates']=[child.get('id') for child in split_process if kind(child) in NODES and child.get('id')] if split_process is not None else []
                # Только семантика BPMN: без координат, DI и расширений редакторов.
                item['bpmn_elements'] = []
                for parent in root.iter():
                    if not kind(parent):
                        continue
                    for el in parent:
                        if not kind(el):
                            continue
                        item['bpmn_elements'].append({'type': kind(el), 'parent': parent.get('id', ''),
                            'attributes': dict(el.attrib), 'text': (el.text or '').strip()})
                        if el.get('id'):
                            references[b['id']].add(el.get('id'))
        if layer == 'all' and b.get('html_prototype'):
            item['prototype_pages'] = b['html_prototype']['pages']
        context['blocks'].append(item)
    content = json.dumps(context, ensure_ascii=False, separators=(',',':'))
    if len(content) > 180000:
        raise ValueError('Проект слишком большой для одного запроса. Выберите анализ BPMN отдельного блока.')
    return content, references


def validate_analysis(value, references):
    if not isinstance(value, dict):
        raise ValueError('Некорректный отчёт.')
    def text(value, limit=8000):
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError('Некорректный текст отчёта.')
        return value
    summary = text(value.get('summary'))
    findings = value.get('findings')
    if not isinstance(findings, list) or len(findings) > 60:
        raise ValueError('Слишком много замечаний.')
    clean = []
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError('Некорректное замечание.')
        f = {key: text(finding.get(key)) for key in SCHEMA['properties']['findings']['items']['properties']}
        if f['severity'] not in ('error', 'warning', 'suggestion'):
            raise ValueError('Некорректная важность.')
        if f['block_id'] and f['block_id'] not in references:
            raise ValueError('Агент сослался на отсутствующий блок.')
        if f['element_id'] and f['element_id'] not in references.get(f['block_id'], set()):
            raise ValueError('Агент сослался на отсутствующий элемент.')
        clean.append(f)
    result = {'summary': summary, 'findings': clean}
    for key in ('questions', 'next_steps'):
        items = value.get(key)
        if not isinstance(items, list) or len(items) > 30:
            raise ValueError('Некорректный список рекомендаций.')
        result[key] = [text(item) for item in items]
    return result
