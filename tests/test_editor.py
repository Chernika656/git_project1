from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from xml.dom import minidom

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from facet.bpmn.checker import BPMN, check_bytes
from facet.bpmn.diagram import DIAGRAM, Diagram, Edge, Shape, load_diagram
from facet.bpmn.editor import EditError, move_shape, route, save_document, updated_xml

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class EditorTests(unittest.TestCase):
    def test_move_persists_bounds_and_connections_without_semantic_changes(self):
        data = (EXAMPLES / "simple.bpmn").read_bytes()
        diagram = load_diagram(data)
        move_shape(diagram, "Check_Request", 80, 110)
        saved = updated_xml(data, diagram)
        loaded = load_diagram(saved)
        task = next(shape for shape in loaded.shapes if shape.element_id == "Check_Request")
        self.assertEqual((task.x, task.y), (300, 210))
        self.assertEqual(loaded.edges, diagram.edges)
        self.assertFalse(check_bytes(saved).issues)
        for payload in (data, saved):
            root = minidom.parseString(payload)
            self.assertEqual([(flow.getAttribute("sourceRef"), flow.getAttribute("targetRef"))
                              for flow in root.getElementsByTagNameNS(BPMN, "sequenceFlow")],
                             [("Start", "Check_Request"), ("Check_Request", "End")])

    def test_extension_comments_and_namespace_prefixes_are_preserved(self):
        data = (EXAMPLES / "simple.bpmn").read_bytes().replace(
            b'id="Definitions_Simple"', b'xmlns:vendor="urn:vendor" id="Definitions_Simple"').replace(
            b'<bpmn:task id="Check_Request"', b'<!--keep this--><bpmn:task vendor:tag="keep" id="Check_Request"').replace(
            b'<bpmn:incoming>Flow_1</bpmn:incoming>',
            b'<bpmn:extensionElements><vendor:config><![CDATA[x < 3]]></vendor:config></bpmn:extensionElements><bpmn:incoming>Flow_1</bpmn:incoming>')
        diagram = load_diagram(data)
        move_shape(diagram, "Check_Request", 30, 40)
        saved = updated_xml(data, diagram)
        self.assertIn(b'xmlns:vendor="urn:vendor"', saved)
        self.assertIn(b'vendor:tag="keep"', saved)
        self.assertIn(b'<!--keep this-->', saved)
        self.assertIn(b'<![CDATA[x < 3]]>', saved)

    def test_backup_and_external_edit_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.bpmn"
            path.write_bytes(b"first")
            save_document(path, b"first", b"second")
            self.assertEqual(path.read_bytes(), b"second")
            self.assertEqual(path.with_suffix(".bpmn.bak").read_bytes(), b"first")
            path.write_bytes(b"external")
            with self.assertRaises(EditError):
                save_document(path, b"second", b"third")
            self.assertEqual(path.read_bytes(), b"external")
            self.assertFalse(list(Path(folder).glob(".bpmn-*")))

    def test_moving_pool_moves_roles_and_preserves_internal_routes(self):
        # Учебные файлы пользователь редактирует в приложении; геометрия теста независима.
        diagram = Diagram(shapes=[
            Shape("Pool_Company", "participant", "Компания", 0, 0, 600, 300),
            Shape("lane", "lane", "Роль", 30, 0, 570, 300),
            Shape("a", "task", "A", 80, 100, 120, 80),
            Shape("b", "task", "B", 350, 100, 120, 80),
        ], edges=[Edge("flow", "sequenceFlow", "", [(200, 140), (350, 140)], source_id="a", target_id="b")])
        before = deepcopy(diagram)
        move_shape(diagram, "Pool_Company", 70, 90)
        self.assertTrue(all((a.x, a.y) == (b.x+70, b.y+90) for a, b in zip(diagram.shapes, before.shapes)))
        for a, b in zip(diagram.edges, before.edges):
            self.assertEqual(a.points, [(x+70, y+90) for x, y in b.points])

    def test_task_stays_inside_its_role(self):
        diagram = load_diagram((EXAMPLES / "purchase-mixed.bpmn").read_bytes())
        move_shape(diagram, "Task_Pay", 0, -900)
        task = next(s for s in diagram.shapes if s.element_id == "Task_Pay")
        lane = next(s for s in diagram.shapes if s.element_id == "Lane_accountant")
        self.assertGreaterEqual(task.y, lane.y)
        self.assertLessEqual(task.y+task.height, lane.y+lane.height)

    def test_no_di_gets_saved_layout(self):
        data = f'<definitions xmlns="{BPMN}"><process id="p"><task id="t" name="Task"/></process></definitions>'.encode()
        diagram = load_diagram(data)
        move_shape(diagram, "t", 10, 20)
        saved = updated_xml(data, diagram)
        self.assertTrue(minidom.parseString(saved).getElementsByTagNameNS(DIAGRAM, "BPMNPlane"))
        self.assertFalse(load_diagram(saved).note)

    def test_routes_have_axis_aligned_segments_and_self_loop_is_not_zero(self):
        source = Shape("a", "task", "A", 0, 0, 100, 80)
        for target in [source, Shape("b", "task", "B", 300, 250, 100, 80), Shape("c", "task", "C", -100, 500, 100, 80)]:
            points = route(source, target)
            self.assertGreater(len(set(points)), 1)
            self.assertTrue(all(a[0] == b[0] or a[1] == b[1] for a, b in zip(points, points[1:])))

    def test_duplicate_ids_cannot_be_written(self):
        data = f'<definitions xmlns="{BPMN}"><process id="p"><task id="t"/><task id="t"/></process></definitions>'.encode()
        with self.assertRaises(EditError):
            updated_xml(data, load_diagram(data))

    def test_unrelated_edge_unchanged(self):
        diagram = load_diagram((EXAMPLES / "purchase-fixed.bpmn").read_bytes())
        before = deepcopy(next(edge for edge in diagram.edges if edge.element_id == "Flow_RejectEnd"))
        move_shape(diagram, "Task_Pay", 45, -30)
        self.assertEqual(before, next(edge for edge in diagram.edges if edge.element_id == "Flow_RejectEnd"))


if __name__ == "__main__":
    unittest.main()
