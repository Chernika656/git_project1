"""Локальные проекты: SQLite, проверка данных и защита от потери правок."""
import base64
import binascii
import json
import math
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from facet.paths import PROJECT_ROOT, EXAMPLES_DIR
SLIDE_IMAGE = re.compile(r'^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$')


class Conflict(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def new_block(name='Новый блок', index=0):
    return dict(id=uuid.uuid4().hex, name=name, description='', requirements='',
                owner='', status='draft', x=80 + (index % 3) * 310, y=110 + (index // 3) * 230,
                bpmn='', uml={'participants': [], 'messages': []}, technical='')


def new_project(name='Новый проект', demo=False):
    blocks, links = [], []
    if demo:
        for i, (title, desc, owner) in enumerate([
            ('Оформление заказа', 'Помочь покупателю оформить заказ без лишних действий.', 'Бизнес-аналитик'),
            ('Оплата', 'Проверить заявку и провести оплату. Предусмотреть отказ.', 'Системный аналитик'),
            ('Доставка', 'Передать оплаченный заказ в доставку и сообщить статус.', 'Разработчик'),
            ('Возврат платежа', 'Вернуть деньги при отмене заказа.', 'Бизнес-аналитик'),
        ]):
            b = new_block(title, i)
            b.update(description=desc, owner=owner, requirements='• Пользователь видит текущий статус.\n• Ошибка не должна приводить к потере данных.',
                     status='review' if i == 1 else 'draft', x=70 + min(i, 2)*310, y=100 if i < 3 else 340)
            b['bpmn'] = (EXAMPLES_DIR/('broken.bpmn' if i == 1 else 'simple.bpmn')).read_text()
            b['uml'] = {'participants': [{'id': 'client', 'name': 'Клиент'}, {'id': 'app', 'name': 'Система'}, {'id': 'service', 'name': 'Сервис'}],
                        'messages': [{'id': 'm1', 'from': 'client', 'to': 'app', 'text': title, 'kind': 'call'},
                                     {'id': 'm2', 'from': 'app', 'to': 'service', 'text': 'Проверить запрос', 'kind': 'call'},
                                     {'id': 'm3', 'from': 'service', 'to': 'app', 'text': 'Результат', 'kind': 'return'}]}
            b['technical'] = '{\n  "method": "POST",\n  "path": "/payments",\n  "request": {"order_id": "string", "amount": "number"},\n  "responses": [201, 400, 409]\n}' if i == 1 else ''
            blocks.append(b)
        links = [{'id': uuid.uuid4().hex, 'source': blocks[a]['id'], 'target': blocks[b]['id']} for a, b in [(0, 1), (1, 2), (1, 3)]]
    return dict(id=uuid.uuid4().hex, name=name, goal='Упростить покупку и сделать процесс прозрачным.' if demo else '',
                blocks=blocks, links=links, revision=1, updated=now())


def validate_project(p):
    """Не допускаем битые ссылки и чрезмерные документы при импорте/сохранении."""
    def string(value, limit=20000):
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError('Некорректное текстовое поле или превышен размер.')
    if not isinstance(p, dict):
        raise ValueError('Ожидается объект проекта.')
    for key in ('id', 'name', 'goal'):
        string(p.get(key), 20000 if key == 'goal' else 200)
    if not p['name'].strip():
        raise ValueError('Укажите название проекта.')
    blocks, links = p.get('blocks'), p.get('links')
    if not isinstance(blocks, list) or len(blocks) > 200 or not isinstance(links, list) or len(links) > 1000:
        raise ValueError('Максимум 200 блоков и 1000 связей.')
    ids = set()
    glossary = p.get('glossary', [])
    if not isinstance(glossary, list) or len(glossary) > 500:
        raise ValueError('Максимум 500 терминов в словаре проекта.')
    term_ids, term_names = set(), set()
    for term in glossary:
        if not isinstance(term, dict):
            raise ValueError('Некорректный термин.')
        for key, limit in (('id', 200), ('name', 200), ('definition', 20000)):
            string(term.get(key), limit)
        normalized = term['name'].strip().casefold()
        if not term['id'] or term['id'] in term_ids or not normalized or normalized in term_names:
            raise ValueError('Терминам нужны уникальные ID и названия.')
        if not term['definition'].strip():
            raise ValueError('Добавьте определение термина.')
        term_ids.add(term['id']); term_names.add(normalized)
        targets = term.get('blocks')
        if not isinstance(targets, list) or len(targets) > 200:
            raise ValueError('Некорректные связи термина.')
        for target in targets:
            string(target, 200)
            if not target:
                raise ValueError('Пустая ссылка термина.')
        if len(set(targets)) != len(targets):
            raise ValueError('Повторная ссылка термина.')
        elements = term.get('elements', [])
        if not isinstance(elements, list) or len(elements) > 200:
            raise ValueError('Некорректные связи термина с BPMN.')
        element_keys = set()
        for element in elements:
            if not isinstance(element, dict):
                raise ValueError('Некорректная ссылка термина на BPMN.')
            block_id, element_id = element.get('block_id'), element.get('element_id')
            string(block_id, 200); string(element_id, 200)
            if not block_id or not element_id or (block_id, element_id) in element_keys:
                raise ValueError('Ссылка термина на BPMN должна быть уникальной.')
            element_keys.add((block_id, element_id))
    image_bytes = 0
    def validate_slide(slide):
        nonlocal image_bytes
        if not isinstance(slide, dict) or slide.get('layout') not in ('summary', 'bullets', 'decision', 'section'):
            raise ValueError('Некорректный макет слайда.')
        string(slide.get('title'), 200)
        string(slide.get('message'), 4000)
        if 'notes' in slide:
            string(slide['notes'], 5000)
        bullets = slide.get('bullets')
        if not isinstance(bullets, list) or len(bullets) > 6:
            raise ValueError('На слайде допускается до 6 пунктов.')
        for bullet in bullets:
            string(bullet, 240)
        if 'image' in slide:
            image = slide['image']
            if not isinstance(image, str) or len(image) > 400_100 or not (match := SLIDE_IMAGE.fullmatch(image)):
                raise ValueError('Некорректное изображение слайда.')
            try:
                raw_image = base64.b64decode(match.group(2), validate=True)
            except (ValueError, binascii.Error):
                raise ValueError('Некорректное изображение слайда.') from None
            signature = {'png': raw_image.startswith(b'\x89PNG\r\n\x1a\n'),
                         'jpeg': raw_image.startswith(b'\xff\xd8\xff'),
                         'webp': raw_image.startswith(b'RIFF') and raw_image[8:12] == b'WEBP'}[match.group(1)]
            if not signature or len(raw_image) > 300_000:
                raise ValueError('Изображение слайда должно быть PNG, JPEG или WebP до 300 КБ.')
            image_bytes += len(raw_image)
    for b in blocks:
        if not isinstance(b, dict):
            raise ValueError('Некорректный блок.')
        if b.get('html_prototype') is not None:
            from facet.ai.agent import validate_prototype
            b['html_prototype'] = validate_prototype(b['html_prototype'])
        for key in ('id', 'name', 'owner', 'status', 'description', 'requirements', 'technical', 'bpmn'):
            string(b.get(key), 5*1024*1024 if key == 'bpmn' else 20000)
        if not b['id'] or b['id'] in ids or not b['name'].strip():
            raise ValueError('Блоки должны иметь уникальные ID и названия.')
        ids.add(b['id'])
        if b['status'] not in ('draft', 'review', 'approved'):
            raise ValueError('Неизвестный статус блока.')
        slide = b.get('slide')
        if slide is not None:
            validate_slide(slide)
        for key in ('x', 'y'):
            if type(b.get(key)) not in (float, int) or not math.isfinite(b[key]) or abs(b[key]) > 100000:
                raise ValueError('Некорректные координаты блока.')
        requirements = b.get('requirement_items', [])
        if not isinstance(requirements, list) or len(requirements) > 300:
            raise ValueError('Максимум 300 требований в блоке.')
        requirement_ids = set()
        for item in requirements:
            if not isinstance(item, dict):
                raise ValueError('Некорректное требование.')
            for key, limit in (('id', 200), ('title', 200), ('text', 20000)):
                string(item.get(key), limit)
            if not item['id'] or item['id'] in requirement_ids or not item['title'].strip():
                raise ValueError('Требованию нужны название и уникальный ID.')
            requirement_ids.add(item['id'])
            if item.get('status') not in ('draft', 'review', 'approved'):
                raise ValueError('Неизвестный статус требования.')
            elements = item.get('elements')
            if not isinstance(elements, list) or len(elements) > 500:
                raise ValueError('Некорректные связи требования.')
            for element in elements:
                string(element, 200)
                if not element:
                    raise ValueError('Пустая ссылка требования.')
            if len(set(elements)) != len(elements):
                raise ValueError('Повторная ссылка требования.')
        details = b.get('element_details', [])
        if not isinstance(details, list) or len(details) > 500:
            raise ValueError('Максимум 500 детализаций BPMN в блоке.')
        detail_ids = set()
        uml_models = [b.get('uml')]
        for detail in details:
            if not isinstance(detail, dict):
                raise ValueError('Некорректная детализация BPMN.')
            string(detail.get('element_id'), 200)
            string(detail.get('description'))
            string(detail.get('requirements', ''))
            string(detail.get('acceptance', ''))
            if 'screen' in detail:
                screen = detail['screen']
                if not isinstance(screen, dict):
                    raise ValueError('Некорректный экран прототипа.')
                for key, limit in (('title', 200), ('text', 10000), ('button', 100)):
                    string(screen.get(key), limit)
                if not screen['title'].strip() or not screen['button'].strip():
                    raise ValueError('Экрану нужны заголовок и название кнопки.')
                fields = screen.get('fields')
                if not isinstance(fields, list) or len(fields) > 12:
                    raise ValueError('На экране допускается до 12 полей.')
                field_ids = set()
                for field in fields:
                    if not isinstance(field, dict):
                        raise ValueError('Некорректное поле экрана.')
                    string(field.get('id'), 200); string(field.get('label'), 200)
                    if not field['id'] or field['id'] in field_ids or not field['label'].strip():
                        raise ValueError('Полям нужны подписи и уникальные ID.')
                    if field.get('type') not in ('text', 'email', 'number', 'textarea') or type(field.get('required')) is not bool:
                        raise ValueError('Некорректный тип или обязательность поля.')
                    field_ids.add(field['id'])
            if 'uml_review' in detail:
                review = detail['uml_review']
                if not isinstance(review, dict):
                    raise ValueError('Некорректная отметка актуальности UML.')
                for key in ('description', 'requirements', 'acceptance'):
                    string(review.get(key))
            if not detail['element_id'] or detail['element_id'] in detail_ids:
                raise ValueError('Повторная или пустая привязка BPMN.')
            detail_ids.add(detail['element_id'])
            uml_models.append(detail.get('uml'))
        for uml in uml_models:
            if not isinstance(uml, dict) or not isinstance(uml.get('participants'), list) or not isinstance(uml.get('messages'), list):
                raise ValueError('Некорректная UML-схема.')
            if len(uml['participants']) > 30 or len(uml['messages']) > 200:
                raise ValueError('Максимум 30 участников и 200 сообщений UML.')
            actors = set()
            for a in uml['participants']:
                if not isinstance(a, dict):
                    raise ValueError('Некорректный участник UML.')
                string(a.get('id'), 200); string(a.get('name'), 200)
                if not a['id'] or a['id'] in actors or not a['name'].strip():
                    raise ValueError('Участникам UML нужны имена и уникальные ID.')
                actors.add(a['id'])
            msg_ids = set()
            for m in uml['messages']:
                if not isinstance(m, dict):
                    raise ValueError('Некорректное сообщение UML.')
                for key in ('id', 'from', 'to', 'text', 'kind'):
                    string(m.get(key), 2000)
                if m['id'] in msg_ids or not m['id'] or m['from'] not in actors or m['to'] not in actors or m['kind'] not in ('call', 'return'):
                    raise ValueError('Некорректная ссылка или тип сообщения UML.')
                msg_ids.add(m['id'])
    extra_slides = p.get('presentation_extra_slides', [])
    if not isinstance(extra_slides, list) or len(extra_slides) + len(blocks) > 200:
        raise ValueError('В презентации допускается до 200 слайдов.')
    extra_ids = set()
    for entry in extra_slides:
        if not isinstance(entry, dict):
            raise ValueError('Некорректный дополнительный слайд.')
        slide_id, block_id = entry.get('id'), entry.get('block_id')
        string(slide_id, 200); string(block_id, 200)
        if not slide_id or slide_id in ids or slide_id in extra_ids or block_id not in ids:
            raise ValueError('Дополнительному слайду нужен уникальный ID и существующий блок.')
        extra_ids.add(slide_id)
        validate_slide(entry.get('slide'))
    if image_bytes > 3_000_000:
        raise ValueError('Изображения презентации превышают 3 МБ.')
    slide_order = p.get('presentation_order', [])
    if not isinstance(slide_order, list) or len(slide_order) > 200:
        raise ValueError('Некорректный порядок слайдов.')
    for block_id in slide_order:
        string(block_id, 200)
    if len(set(slide_order)) != len(slide_order):
        raise ValueError('Слайд не может повторяться в презентации.')
    link_ids = set()
    pairs = set()
    for link in links:
        if not isinstance(link, dict):
            raise ValueError('Некорректная связь.')
        for key in ('id', 'source', 'target'):
            string(link.get(key), 200)
        pair = link['source'], link['target']
        if link['id'] in link_ids or not link['id'] or any(x not in ids for x in pair) or pair[0] == pair[1] or pair in pairs:
            raise ValueError('Некорректная или повторная связь блоков.')
        link_ids.add(link['id']); pairs.add(pair)
    return p


class ClosingConnection(sqlite3.Connection):
    """Контекст транзакции также освобождает соединение после запроса."""
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, document TEXT NOT NULL)')
            if not db.execute('SELECT 1 FROM projects LIMIT 1').fetchone():
                p = new_project('Интернет-магазин', demo=True)
                db.execute('INSERT INTO projects VALUES (?,?)', (p['id'], json.dumps(p, ensure_ascii=False)))

    def connect(self):
        db=sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=10000')
        return db

    def list(self):
        with self.connect() as db:
            projects = [json.loads(r[0]) for r in db.execute('SELECT document FROM projects')]
        return sorted([dict(id=p['id'], name=p['name'], updated=p['updated'], blocks=len(p['blocks'])) for p in projects], key=lambda p:p['updated'], reverse=True)

    def get(self, identifier):
        with self.connect() as db:
            row = db.execute('SELECT document FROM projects WHERE id=?', (identifier,)).fetchone()
        if not row:
            raise KeyError('Проект не найден.')
        return json.loads(row[0])

    def create(self, name, imported=None):
        p = validate_project(imported) if imported is not None else new_project(name)
        p.update(id=uuid.uuid4().hex, revision=1, updated=now())
        validate_project(p)
        with self.connect() as db:
            db.execute('INSERT INTO projects VALUES (?,?)', (p['id'], json.dumps(p, ensure_ascii=False)))
        return p

    def save(self, identifier, p, revision):
        validate_project(p)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT document FROM projects WHERE id=?', (identifier,)).fetchone()
            if not row:
                raise KeyError('Проект не найден.')
            old = json.loads(row[0])
            if type(revision) is not int or old['revision'] != revision:
                raise Conflict('Проект изменён в другой вкладке. Скачайте свои правки и перезагрузите страницу.')
            p.update(id=identifier, revision=revision+1, updated=now())
            db.execute('UPDATE projects SET document=? WHERE id=?', (json.dumps(p, ensure_ascii=False), identifier))
        return p
