from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checker import check_file
from diagram import load_diagram

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class PurchaseExampleTests(unittest.TestCase):
    def test_mixed_has_exactly_the_planted_findings(self):
        report = check_file(EXAMPLES / "purchase-mixed.bpmn")
        self.assertEqual((report.nodes, report.flows, report.errors, report.warnings), (18, 19, 3, 4))
        self.assertEqual({(issue.code, issue.element_id) for issue in report.issues}, {
            ("END_OUTGOING", "End_Paid"), ("START_INCOMING", "Start_Request"),
            ("INVALID_DEFAULT", "Gateway_Funds"), ("BRANCH_CONDITION", "Flow_Approved"),
            ("UNNAMED_ACTIVITY", "Task_Archive"), ("UNREACHABLE", "Task_Audit"),
            ("NO_PATH_TO_END", "Task_Clarify"),
        })

    def test_fixed_has_no_findings(self):
        self.assertEqual(check_file(EXAMPLES / "purchase-fixed.bpmn").issues, [])

    def test_both_diagrams_have_roles_and_all_connections(self):
        for filename in ("purchase-mixed.bpmn", "purchase-fixed.bpmn"):
            with self.subTest(filename=filename):
                diagram = load_diagram((EXAMPLES / filename).read_bytes())
                self.assertEqual(len(diagram.shapes), 22)
                self.assertEqual(len(diagram.edges), 19)
                self.assertEqual({shape.name for shape in diagram.shapes if shape.kind == "lane"},
                                 {"Инициатор", "Руководитель", "Бухгалтер"})
                self.assertFalse(diagram.note)


if __name__ == "__main__":
    unittest.main()
