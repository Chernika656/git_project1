"""Оконные тесты: BPMN_GUI_TESTS=1 python3 -m unittest discover -s tests -v.

На macOS выполнять вне песочницы: Tk требует доступа к оконному серверу.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@unittest.skipUnless(os.environ.get("BPMN_GUI_TESTS") == "1", "Для тестов Tk включите BPMN_GUI_TESTS=1")
class GuiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from facet.desktop.app import BpmnApp
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = BpmnApp(self.root)
        self.app.demo()
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def test_error_and_warning_colors(self):
        view = self.app.diagram_view
        for identifier, expected in (("approved", "#c43142"), ("forgotten", "#ad7012")):
            outline = [view.canvas.itemcget(item, "outline") for item in view.element_items[identifier]
                       if view.canvas.type(item) in {"oval", "polygon", "rectangle"}]
            self.assertIn(expected, outline)

    def test_list_selection_marks_shape_and_edge(self):
        view = self.app.diagram_view
        for identifier in ("approved", "yes"):
            index = next(index for index, issue in enumerate(self.app.report.issues) if issue.element_id == identifier)
            self.app.table.selection_set(str(index))
            self.app.describe()
            self.assertEqual(view.selected, identifier)
            self.assertTrue(view.canvas.find_withtag("selection"))

    def test_click_on_shape_selects_its_issue(self):
        from types import SimpleNamespace
        view = self.app.diagram_view
        # Fit tiny hidden canvas; event coordinates still refer to the actual drawn shape.
        shape = next(shape for shape in view.diagram.shapes if shape.element_id == "forgotten")
        x, y = view.xy(shape.x+shape.width/2, shape.y+shape.height/2)
        event = SimpleNamespace(x=x-view.canvas.canvasx(0), y=y-view.canvas.canvasy(0))
        view.click(event)
        self.assertEqual(view.selected, "forgotten")
        chosen = int(self.app.table.selection()[0])
        self.assertEqual(self.app.report.issues[chosen].element_id, "forgotten")

    def test_clean_element_selection_and_zoom(self):
        app = self.app
        app.select_element("review")
        self.assertFalse(app.table.selection())
        self.assertIn("замечаний не найдено", app.detail.get("1.0", "end"))
        app.diagram_view.select("review")
        app.diagram_view.zoom(1.2)
        self.assertEqual(app.diagram_view.selected, "review")
        self.assertTrue(app.diagram_view.canvas.find_withtag("selection"))

    def test_reload_clears_stale_highlights_and_bad_xml_clears_canvas(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "watched.bpmn"
            examples = Path(__file__).resolve().parents[1] / "examples"
            file.write_bytes((examples / "broken.bpmn").read_bytes())
            self.app.load(file)
            file.write_bytes((examples / "simple.bpmn").read_bytes())
            self.app.watch()
            self.app.watch()
            self.assertFalse(self.app.diagram_view.severities)
            self.assertEqual(len(self.app.diagram_view.diagram.shapes), 3)
            file.write_bytes(b"invalid")
            self.app.watch()
            self.app.watch()
            self.assertFalse(self.app.diagram_view.diagram.shapes)
            self.assertEqual(self.app.report.issues[0].code, "INVALID_XML")

    def test_detail_is_readable_in_small_window(self):
        from tkinter import font
        self.root.deiconify()
        self.root.geometry("900x680")
        self.root.update()
        line_height = font.Font(self.app.detail, font=self.app.detail.cget("font")).metrics("linespace")
        self.assertGreaterEqual(self.app.detail.winfo_height(), line_height * 4)
        self.assertGreaterEqual(self.app.table.winfo_height(), 70)

    def test_double_click_zooms_to_problem(self):
        from types import SimpleNamespace
        view = self.app.diagram_view
        item = next(shape for shape in view.diagram.shapes if shape.element_id == "forgotten")
        x, y = view.xy(item.x+item.width/2, item.y+item.height/2)
        scale = view.scale
        view.double_click(SimpleNamespace(x=x-view.canvas.canvasx(0), y=y-view.canvas.canvasy(0)))
        self.assertEqual(view.selected, "forgotten")
        self.assertGreater(view.scale, scale)
        self.assertIsNone(view.move_id)

    def test_double_click_switches_from_old_selection_to_clicked_row(self):
        from types import SimpleNamespace
        self.root.deiconify()
        self.root.update()
        table = self.app.table
        for identifier in ("approved", "forgotten", "start", "approved"):
            row = str(next(i for i, issue in enumerate(self.app.report.issues) if issue.element_id == identifier))
            table.see(row)
            self.root.update()
            x, y, width, height = table.bbox(row)
            # На входе обработчика выделение может ещё относиться к прошлой строке.
            self.app.zoom_issue(SimpleNamespace(widget=table, x=x+20, y=y+height//2))
            self.root.update()
            self.assertEqual(table.selection(), (row,))
            self.assertEqual(self.app.active_view.selected, identifier)
            box = self.app.active_view.element_bbox(identifier)
            canvas = self.app.active_view.canvas
            self.assertLess(box[0], canvas.canvasx(canvas.winfo_width()))
            self.assertGreater(box[2], canvas.canvasx(0))
            self.assertLess(box[1], canvas.canvasy(canvas.winfo_height()))
            self.assertGreater(box[3], canvas.canvasy(0))

    def test_double_click_in_floating_list_uses_its_clicked_row(self):
        from types import SimpleNamespace
        self.app.toggle_fullscreen()
        self.root.update()
        table = self.app.floating_list
        for identifier in ("approved", "forgotten", "start"):
            row = str(next(i for i, issue in enumerate(self.app.report.issues) if issue.element_id == identifier))
            table.see(row)
            self.root.update()
            x, y, width, height = table.bbox(row)
            self.app.zoom_issue(SimpleNamespace(widget=table, x=x+20, y=y+height//2))
            self.root.update()
            self.assertEqual(self.app.table.selection(), (row,))
            self.assertEqual(table.selection(), (row,))
            self.assertEqual(self.app.fullscreen_view.selected, identifier)
        self.app.close_fullscreen()

    def test_focus_large_element_reduces_previous_zoom(self):
        from facet.bpmn.checker import Report
        from facet.bpmn.diagram import Diagram, Shape
        self.root.deiconify()
        self.root.update()
        view = self.app.diagram_view
        view.show(Diagram(shapes=[Shape("small", "startEvent", "Старт", 0, 0, 36, 36),
                                 Shape("large", "subProcess", "Большой процесс", 200, 0, 900, 500, expanded=True)]), Report("test"))
        view.focus_element("small")
        zoom_small = view.scale
        view.focus_element("large")
        self.assertLess(view.scale, zoom_small)
        box = view.element_bbox("large")
        self.assertLess(box[2]-box[0], view.canvas.winfo_width())
        self.assertLess(box[3]-box[1], view.canvas.winfo_height())

    def test_fullscreen_double_click_dispatches_through_tk_bindings(self):
        from unittest.mock import patch
        self.app.toggle_fullscreen()
        self.root.update()
        table = self.app.floating_list
        clock = 10000
        for identifier in ("approved", "forgotten", "start"):
            row = str(next(i for i, issue in enumerate(self.app.report.issues) if issue.element_id == identifier))
            table.see(row)
            self.root.update()
            x, y, width, height = table.bbox(row)
            with patch.object(self.app.fullscreen_view, "focus_element", wraps=self.app.fullscreen_view.focus_element) as focus:
                for phase, offset in (("ButtonPress", 0), ("ButtonRelease", 35), ("ButtonPress", 110), ("ButtonRelease", 145)):
                    table.event_generate(f"<{phase}-1>", x=x+30, y=y+height//2, time=clock+offset)
                    self.root.update()
                focus.assert_called_with(identifier)
            self.assertEqual(self.app.fullscreen_view.selected, identifier)
            clock += 2000
        self.app.close_fullscreen()

    def test_fullscreen_double_click_in_row_space_outside_columns(self):
        from types import SimpleNamespace
        self.app.toggle_fullscreen()
        self.root.update()
        table = self.app.floating_list
        # Узкие колонки оставляют свободную часть строки — она тоже кликабельна.
        table.column("kind", width=40, minwidth=20, stretch=False)
        table.column("name", width=80, minwidth=20, stretch=False)
        self.root.update()
        row = str(next(i for i, issue in enumerate(self.app.report.issues) if issue.element_id == "forgotten"))
        table.see(row)
        self.root.update()
        _, y, _, height = table.bbox(row)
        self.app.zoom_issue(SimpleNamespace(widget=table, x=table.winfo_width()-8, y=y+height//2), table)
        self.root.update()
        self.assertEqual(self.app.fullscreen_view.selected, "forgotten")
        self.app.close_fullscreen()

    def test_fullscreen_canvas_double_click_dispatches_through_tk_bindings(self):
        from unittest.mock import patch
        self.app.toggle_fullscreen()
        self.root.update()
        view = self.app.fullscreen_view
        clock = 20000
        for identifier in ("approved", "forgotten", "start"):
            view.fit()
            shape = next(s for s in view.diagram.shapes if s.element_id == identifier)
            x, y = view.xy(shape.x+shape.width/2, shape.y+shape.height/2)
            x, y = x-view.canvas.canvasx(0), y-view.canvas.canvasy(0)
            with patch.object(view, "focus_element", wraps=view.focus_element) as focus:
                for phase, offset in (("ButtonPress", 0), ("ButtonRelease", 35), ("ButtonPress", 110), ("ButtonRelease", 145)):
                    view.canvas.event_generate(f"<{phase}-1>", x=int(x), y=int(y), time=clock+offset)
                    self.root.update()
                focus.assert_called_with(identifier)
            self.assertEqual(view.selected, identifier)
            clock += 2000
        self.app.close_fullscreen()

    def test_drag_saves_and_undo_restores_exact_file(self):
        from types import SimpleNamespace
        from facet.bpmn.diagram import load_diagram
        examples = Path(__file__).resolve().parents[1] / "examples"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.bpmn"
            original = (examples / "simple.bpmn").read_bytes()
            path.write_bytes(original)
            self.app.load(path)
            self.root.update()
            view = self.app.diagram_view
            task = next(shape for shape in view.diagram.shapes if shape.element_id == "Check_Request")
            x, y = view.xy(task.x+task.width/2, task.y+task.height/2)
            event = SimpleNamespace(x=x-view.canvas.canvasx(0), y=y-view.canvas.canvasy(0))
            scale = view.scale
            view.click(event)
            self.root.update()
            view.pan(SimpleNamespace(x=event.x+30, y=event.y+20))
            view.release()
            moved = next(shape for shape in load_diagram(path.read_bytes()).shapes if shape.element_id == "Check_Request")
            self.assertAlmostEqual(moved.x, task.x+30/scale, places=2)
            self.assertAlmostEqual(moved.y, task.y+20/scale, places=2)
            self.assertEqual(path.with_suffix(".bpmn.bak").read_bytes(), original)
            self.app.undo_move()
            self.assertEqual(path.read_bytes(), original)

    def test_fullscreen_panel_links_and_closes(self):
        import time
        self.app.toggle_fullscreen()
        # macOS подтверждает переход в fullscreen асинхронно, после анимации окна.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.root.update()
            if self.app.fullscreen_window.attributes("-fullscreen"):
                break
            time.sleep(.05)
        self.assertTrue(self.app.fullscreen_window.attributes("-fullscreen"))
        self.assertEqual(len(self.app.floating_list.get_children()), len(self.app.report.issues))
        row = str(next(i for i, issue in enumerate(self.app.report.issues) if issue.element_id == "forgotten"))
        self.app.floating_list.selection_set(row)
        self.app.floating_select()
        self.root.update()
        self.assertEqual(self.app.fullscreen_view.selected, "forgotten")
        self.assertIn("недостижим", self.app.floating_detail.get("1.0", "end"))
        self.app.collapse_floating()
        self.assertFalse(self.app.floating_body.winfo_manager())
        self.app.close_fullscreen()
        self.assertIsNone(self.app.fullscreen_window)

    def test_cancel_drag_does_not_write_file(self):
        from types import SimpleNamespace
        view = self.app.diagram_view
        original = view.diagram
        view.move_id = "review"
        view.move_start = (0, 0)
        view.move_origin = view.offset
        view.pan(SimpleNamespace(x=30, y=20))
        view.cancel_move()
        self.assertEqual(view.diagram, original)
        self.assertFalse(self.app.undo_history)

    def test_external_save_during_drag_is_not_overwritten(self):
        from copy import deepcopy
        from facet.bpmn.editor import move_shape
        from unittest.mock import patch
        examples = Path(__file__).resolve().parents[1] / "examples"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.bpmn"
            path.write_bytes((examples / "simple.bpmn").read_bytes())
            self.app.load(path)
            moving = deepcopy(self.app.diagram_view.diagram)
            move_shape(moving, "Check_Request", 20, 30)
            external = (examples / "valid.bpmn").read_bytes()
            path.write_bytes(external)
            with patch("facet.desktop.app.messagebox.showerror") as notify:
                self.app.commit_move(moving)
                notify.assert_called_once()
            self.assertEqual(path.read_bytes(), external)
            self.assertEqual(self.app.source_data, external)
            self.assertFalse(self.app.undo_history)


if __name__ == "__main__":
    unittest.main()
