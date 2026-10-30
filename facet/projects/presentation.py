"""Safe text extraction from a small PPTX for mapping slides to project blocks."""
import base64
import binascii
import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET


DRAWING = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
PRESENTATION = '{http://schemas.openxmlformats.org/presentationml/2006/main}'
RELATIONSHIP = '{http://schemas.openxmlformats.org/package/2006/relationships}'
OFFICE_RELATIONSHIP = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
SLIDE_NAME = re.compile(r'^ppt/slides/slide([1-9][0-9]*)\.xml$')
MAX_IMAGE = 300_000
MAX_IMAGES_TOTAL = 3_000_000


def image_type(raw):
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if raw.startswith(b'\xff\xd8\xff'):
        return 'jpeg'
    if raw.startswith(b'RIFF') and raw[8:12] == b'WEBP':
        return 'webp'
    return None


def extract_pptx(encoded):
    if not isinstance(encoded, str) or len(encoded) > 10_000_000:
        raise ValueError('Презентация слишком большая. Максимум 7 МБ.')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('Не удалось прочитать PPTX.') from None
    if len(raw) > 7 * 1024 * 1024:
        raise ValueError('Презентация слишком большая. Максимум 7 МБ.')
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        slides = sorted(((int(match.group(1)), info) for info in archive.infolist()
                         if (match := SLIDE_NAME.fullmatch(info.filename))), key=lambda item: item[0])
        if not slides or len(slides) > 40:
            raise ValueError('В PPTX должно быть от 1 до 40 слайдов.')
        if any(info.file_size > 500_000 for _, info in slides) or sum(info.file_size for _, info in slides) > 5_000_000:
            raise ValueError('Текст слайдов превышает допустимый размер.')
        # File names are not the presentation order after a user rearranges slides.
        if 'ppt/presentation.xml' in archive.namelist() and 'ppt/_rels/presentation.xml.rels' in archive.namelist():
            presentation_info = archive.getinfo('ppt/presentation.xml')
            rels_info = archive.getinfo('ppt/_rels/presentation.xml.rels')
            if presentation_info.file_size <= 100_000 and rels_info.file_size <= 100_000:
                presentation = ET.fromstring(archive.read(presentation_info))
                relationships = ET.fromstring(archive.read(rels_info))
                slide_targets = {node.get('Id'): posixpath.normpath(posixpath.join('ppt', node.get('Target', '')))
                                 for node in relationships.iter(RELATIONSHIP + 'Relationship')
                                 if node.get('Type', '').endswith('/slide') and node.get('TargetMode') != 'External'}
                available = {info.filename: (number, info) for number, info in slides}
                ordered = []
                for node in presentation.iter(PRESENTATION + 'sldId'):
                    path = slide_targets.get(node.get(OFFICE_RELATIONSHIP + 'id'))
                    if path in available and available[path] not in ordered:
                        ordered.append(available[path])
                slides = ordered + [item for item in slides if item not in ordered]
        result = []
        image_bytes = 0
        for position, (file_number, info) in enumerate(slides, 1):
            with archive.open(info) as source:
                xml = source.read(500_001)
            if len(xml) > 500_000:
                raise ValueError('Текст слайда превышает допустимый размер.')
            root = ET.fromstring(xml)
            shapes = []
            for shape in root.iter(PRESENTATION + 'sp'):
                paragraphs = []
                for paragraph in shape.iter(DRAWING + 'p'):
                    line = ''.join(node.text or '' for node in paragraph.iter(DRAWING + 't')).strip()[:500]
                    if line:
                        paragraphs.append(line)
                if paragraphs:
                    shapes.append(paragraphs)
            title = (shapes[0][0] if shapes else f'Слайд {position}')[:200]
            lines = [line for shape in shapes for line in shape]
            if lines and lines[0] == title:
                lines.pop(0)
            slide = {'number': position, 'title': title, 'lines': lines[:15]}
            pictures = [node.get(OFFICE_RELATIONSHIP + 'embed') for picture in root.iter(PRESENTATION + 'pic')
                        for node in picture.iter(DRAWING + 'blip') if node.get(OFFICE_RELATIONSHIP + 'embed')]
            if pictures:
                rels_name = f'ppt/slides/_rels/slide{file_number}.xml.rels'
                if rels_name in archive.namelist():
                    rels_info = archive.getinfo(rels_name)
                    if rels_info.file_size <= 100_000:
                        relationships = ET.fromstring(archive.read(rels_info))
                        images = {node.get('Id'): node.get('Target') for node in relationships.iter(RELATIONSHIP + 'Relationship')
                                  if node.get('Type', '').endswith('/image') and node.get('TargetMode') != 'External'}
                        for picture_id in pictures:
                            target = images.get(picture_id)
                            if not target:
                                continue
                            media_path = posixpath.normpath(posixpath.join('ppt/slides', target))
                            if not media_path.startswith('ppt/media/') or media_path not in archive.namelist():
                                continue
                            media_info = archive.getinfo(media_path)
                            if media_info.file_size > MAX_IMAGE or image_bytes + media_info.file_size > MAX_IMAGES_TOTAL:
                                continue
                            with archive.open(media_info) as source:
                                raw_image = source.read(MAX_IMAGE + 1)
                            mime = image_type(raw_image)
                            if mime and len(raw_image) <= MAX_IMAGE:
                                slide['image'] = f'data:image/{mime};base64,' + base64.b64encode(raw_image).decode('ascii')
                                image_bytes += len(raw_image)
                                break
                if not slide.get('image') or len(pictures) > 1:
                    slide['image_note'] = 'В PPTX есть изображения, которые не перенесены. Поддерживается одно PNG, JPEG или WebP до 300 КБ на слайд.'
            result.append(slide)
        return result
    except (zipfile.BadZipFile, RuntimeError, ET.ParseError, OSError):
        raise ValueError('Файл не является читаемой презентацией PPTX.') from None
