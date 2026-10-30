from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from facet.bpmn.checker import BPMN, Report
from facet.bpmn.diagram import load_diagram, severity_by_element


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class DiagramTests(unittest.TestCase):
    def test_simple_keeps_bpmn_coordinates(self):
        diagram = load_diagram((EXAMPLES / "simple.bpmn").read_bytes())
        self.assertEqual(len(diagram.shapes), 3)
        self.assertEqual(len(diagram.edges), 2)
        task = next(shape for shape in diagram.shapes if shape.element_id == "Check_Request")
        self.assertEqual((task.x, task.y, task.width, task.height), (220, 100, 140, 80))
        self.assertEqual(diagram.edges[0].points, [(136, 140), (220, 140)])

    def test_missing_di_generates_visible_shapes_and_edges(self):
        data = f'''<definitions xmlns="{BPMN}"><process id="p"><task id="a" name="Шаг"/>
            <endEvent id="b"/><sequenceFlow id="f" sourceRef="a" targetRef="b"/></process></definitions>'''.encode()
        diagram = load_diagram(data)
        self.assertEqual(len(diagram.shapes), 2)
        self.assertEqual(len(diagram.edges), 1)
        self.assertIn("упрощённая", diagram.note)

    def test_malformed_and_entities_do_not_reach_renderer(self):
        for data in (b"broken", b'<!DOCTYPE x [<!ENTITY x "x">]><x/>', b"<other/>"):
            with self.subTest(data=data):
                diagram = load_diagram(data)
                self.assertFalse(diagram.shapes)
                self.assertTrue(diagram.note)

    def test_non_finite_coordinates_are_omitted(self):
        data = (EXAMPLES / "simple.bpmn").read_bytes().replace(b'x="100"', b'x="NaN"')
        diagram = load_diagram(data)
        self.assertEqual(len(diagram.shapes), 2)
        self.assertIn("Не показано", diagram.note)

    def test_broken_edge_coordinates_are_omitted(self):
        data = (EXAMPLES / "simple.bpmn").read_bytes().replace(b'x="136"', b'x="Infinity"')
        diagram = load_diagram(data)
        self.assertEqual(len(diagram.edges), 1)
        self.assertIn("Не показано", diagram.note)

    def test_error_has_priority_over_warning(self):
        import xml.etree.ElementTree as ET
        report = Report("sample")
        element = ET.fromstring('<task id="a"/>')
        report.add("warning", "W", element, "", "")
        report.add("error", "E", element, "", "")
        report.add("warning", "W2", element, "", "")
        self.assertEqual(severity_by_element(report), {"a": "error"})

    def test_self_loop_has_visible_route(self):
        data = f'''<definitions xmlns="{BPMN}"><process id="p"><task id="a"/>
            <sequenceFlow id="f" sourceRef="a" targetRef="a"/></process></definitions>'''.encode()
        diagram = load_diagram(data)
        self.assertGreater(len(set(diagram.edges[0].points)), 2)


if __name__ == "__main__":
    unittest.main()
