"""Экраны задач переживают сохранение и копирование; некорректные формы отклоняются."""
import copy
import tempfile
import unittest
from pathlib import Path

from facet.projects.templates import Templates
from facet.projects.workspace import Store, new_project, validate_project


class PrototypeTests(unittest.TestCase):
    def setUp(self):
        self.project = new_project(demo=True)
        self.screen = {'title':'Оформить заказ', 'text':'Укажите адрес доставки.', 'button':'Продолжить',
                       'fields':[{'id':'address','label':'Адрес','type':'text','required':True}]}
        self.project['blocks'][0]['element_details'] = [
            {'element_id':'Check_Request','description':'', 'screen':self.screen,
             'uml':{'participants':[], 'messages':[]}}]

    def test_roundtrip_and_template_preserve_screen(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/'test.sqlite3')
            saved = store.create('Тест', self.project)
            self.assertEqual(store.get(saved['id'])['blocks'][0]['element_details'][0]['screen'], self.screen)
            library = Templates(store)
            library.save('test-user', 'Экран заказа', saved['blocks'][0])
            self.assertEqual(library.list('test-user')[-1]['block']['element_details'][0]['screen'], self.screen)

    def test_invalid_controls_are_rejected(self):
        for change in [dict(type='password'),dict(required='true'),dict(label=''),dict(id='')]:
            with self.subTest(change=change):
                p = copy.deepcopy(self.project)
                p['blocks'][0]['element_details'][0]['screen']['fields'][0].update(change)
                with self.assertRaises(ValueError): validate_project(p)

    def test_duplicate_fields_and_oversized_form_are_rejected(self):
        for count in [2,13]:
            p=copy.deepcopy(self.project)
            p['blocks'][0]['element_details'][0]['screen']['fields'] *= count
            with self.assertRaises(ValueError): validate_project(p)

    def test_old_projects_and_all_supported_field_types(self):
        validate_project(new_project(demo=True))
        self.screen['fields']=[dict(id=t,label=t,type=t,required=False) for t in ('text','email','number','textarea')]
        validate_project(self.project)


if __name__ == '__main__': unittest.main()
