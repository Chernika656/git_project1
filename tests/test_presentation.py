"""PPTX text extraction without a real upload or AI request."""
import base64
import io
import unittest
import zipfile

from facet.projects.presentation import extract_pptx
from facet.projects.workspace import new_block, new_project, validate_project


class PresentationTests(unittest.TestCase):
    def test_multiple_slides_can_link_to_one_block(self):
        project = new_project()
        block = new_block('Оплата')
        project['blocks'] = [block]
        project['presentation_extra_slides'] = [
            {'id': 'slide-a', 'block_id': block['id'], 'slide': {'title': 'Риск', 'message': 'Ошибка оплаты', 'layout': 'summary', 'bullets': []}},
            {'id': 'slide-b', 'block_id': block['id'], 'slide': {'title': 'Решение', 'message': 'Повторить платёж', 'layout': 'bullets', 'bullets': ['Проверить статус']}}]
        project['presentation_order'] = [block['id'], 'slide-a', 'slide-b']
        validate_project(project)
        project['presentation_extra_slides'][1]['block_id'] = 'missing'
        with self.assertRaises(ValueError):
            validate_project(project)

    def test_imports_embedded_image_and_validates_saved_slide(self):
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/XhoAAAAASUVORK5CYII=')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('ppt/slides/slide1.xml',
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<p:sp><a:p><a:r><a:t>Доставка</a:t></a:r></a:p></p:sp>'
                '<p:pic><a:blip r:embed="rId1"/></p:pic></p:sld>')
            archive.writestr('ppt/slides/_rels/slide1.xml.rels',
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                'Target="../media/image1.png"/></Relationships>')
            archive.writestr('ppt/media/image1.png', png)
        slide = extract_pptx(base64.b64encode(buffer.getvalue()).decode())[0]
        self.assertEqual(base64.b64decode(slide['image'].split(',')[1]), png)
        project = new_project()
        block = new_block()
        block['slide'] = {'title': slide['title'], 'message': '', 'layout': 'summary',
                          'bullets': [], 'image': slide['image']}
        project['blocks'] = [block]
        validate_project(project)
        block['slide']['image'] = 'data:image/png;base64,' + base64.b64encode(b'<script>').decode()
        with self.assertRaises(ValueError):
            validate_project(project)

    def test_extracts_title_and_body_in_slide_order(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for number, title in ((2, 'Второй'), (1, 'Первый')):
                xml = ('<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                       'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                       f'<p:sp><a:p><a:r><a:t>{title}</a:t></a:r></a:p>'
                       '<a:p><a:r><a:t>Главный тезис</a:t></a:r></a:p></p:sp></p:sld>')
                archive.writestr(f'ppt/slides/slide{number}.xml', xml)
        slides = extract_pptx(base64.b64encode(buffer.getvalue()).decode())
        self.assertEqual([slide['title'] for slide in slides], ['Первый', 'Второй'])
        self.assertEqual(slides[0]['lines'], ['Главный тезис'])

    def test_follows_presentation_order_after_slides_are_rearranged(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for number in (1, 2):
                archive.writestr(f'ppt/slides/slide{number}.xml',
                    '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                    f'<p:sp><a:p><a:r><a:t>Слайд {number}</a:t></a:r></a:p></p:sp></p:sld>')
            archive.writestr('ppt/presentation.xml',
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId1"/></p:sldIdLst>'
                '</p:presentation>')
            archive.writestr('ppt/_rels/presentation.xml.rels',
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/>'
                '</Relationships>')
        slides = extract_pptx(base64.b64encode(buffer.getvalue()).decode())
        self.assertEqual([slide['title'] for slide in slides], ['Слайд 2', 'Слайд 1'])
        self.assertEqual([slide['number'] for slide in slides], [1, 2])

    def test_rejects_non_pptx(self):
        with self.assertRaises(ValueError):
            extract_pptx(base64.b64encode(b'not a zip').decode())
