"""Оконное приложение на Python. Проверки находятся отдельно в checker.py."""

from pathlib import Path
from copy import deepcopy
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from checker import MAX_BYTES, Report, check_bytes, check_file, write_html
from canvas_view import DiagramView
from diagram import Diagram, load_diagram
from editor import EditError, save_document, updated_xml


class BpmnApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.path: Path | None = None
        self.report: Report | None = None
        self.last_signature = None
        self.pending_signature = None
        self.source_data = None
        self.undo_history = []
        self.fullscreen_window = None
        self.fullscreen_view = None
        self._canvas_selection = None
        # Единая светлая тема: цвета замечаний читаются и при тёмной теме macOS.
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", background="#f5f3fa", foreground="#38344d", font=("Helvetica", 11))
        style.configure("TButton", padding=(12, 7), relief="flat", borderwidth=0,
                        background="#eae5f5", foreground="#534770")
        style.map("TButton", background=[("active", "#e0d7ef"), ("pressed", "#d4c7e9")],
                  foreground=[("disabled", "#94a1ad")])
        style.configure("Primary.TButton", background="#8463be", foreground="#ffffff", font=("Helvetica", 11, "bold"))
        style.map("Primary.TButton", background=[("active", "#7453ae"), ("pressed", "#644399")], foreground=[("disabled", "#d4c6e5")])
        style.configure("Muted.TLabel", foreground="#65768a", font=("Helvetica", 10))
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", rowheight=31,
                        borderwidth=0, relief="flat", font=("Helvetica", 11))
        style.configure("Treeview.Heading", background="#eaf0f5", foreground="#617287",
                        relief="flat", padding=(8, 7), font=("Helvetica", 10, "bold"))
        style.map("Treeview", background=[("selected", "#ebe1fc")], foreground=[("selected", "#55398a")])
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("TScrollbar", background="#c7d3df", troughcolor="#edf1f5", borderwidth=0,
                        arrowsize=12, relief="flat")
        root.title("BPMN Check — помощник аналитика")
        root.geometry(f"{min(1180, root.winfo_screenwidth()-80)}x{min(900, root.winfo_screenheight()-90)}")
        root.minsize(900, 680)
        frame = ttk.Frame(root, padding=(24, 18))
        frame.pack(fill="both", expand=True)
        heading = ttk.Frame(frame)
        heading.pack(fill="x")
        ttk.Label(heading, text="BPMN Check", font=("Helvetica", 24, "bold")).pack(side="left")
        toolbar = ttk.Frame(heading)
        toolbar.pack(side="right")
        ttk.Button(toolbar, text="Открыть схему", command=self.choose, style="Primary.TButton").pack(side="left")
        examples = ttk.Menubutton(toolbar, text="Примеры", padding=(10, 7))
        examples.pack(side="left", padx=10)
        menu = tk.Menu(examples, tearoff=False)
        for title, filename in (("Простая схема", "simple.bpmn"), ("Пример с ошибками", "broken.bpmn"),
                                ("Закупка: с ошибками", "purchase-mixed.bpmn"), ("Закупка: исправленная", "purchase-fixed.bpmn")):
            menu.add_command(label=title, command=lambda name=filename: self.load(Path(__file__).parent / "examples" / name))
        examples.configure(menu=menu)
        self.undo_button = ttk.Button(toolbar, text="Отменить перенос", command=self.undo_move, state="disabled")
        self.undo_button.pack(side="left", padx=(0, 10))
        self.export_button = ttk.Button(toolbar, text="Отчёт", command=self.export, state="disabled")
        self.export_button.pack(side="right")
        self.filename = tk.StringVar(value="Файл ещё не выбран")
        self.summary = tk.StringVar(value="Можно начать с готового примера.")
        metadata = ttk.Frame(frame)
        metadata.pack(fill="x", pady=(14, 14))
        ttk.Label(metadata, textvariable=self.filename, style="Muted.TLabel", wraplength=450).pack(side="left")
        ttk.Label(metadata, textvariable=self.summary, font=("Helvetica", 11, "bold")).pack(side="right")
        panes = ttk.Panedwindow(frame, orient="vertical")
        panes.pack(fill="both", expand=True)
        self.diagram_view = DiagramView(panes, on_select=self.select_element, on_move=self.commit_move,
                                         on_fullscreen=self.toggle_fullscreen)
        panes.add(self.diagram_view, weight=3)
        bottom = ttk.Frame(panes, padding=(0, 10, 0, 0))
        panes.add(bottom, weight=2)
        self.panes = panes
        self._resize_job = None
        panes.bind("<Configure>", self.resize_panes)
        list_heading = ttk.Frame(bottom)
        list_heading.pack(fill="x", pady=(0, 8))
        ttk.Label(list_heading, text="Замечания", font=("Helvetica", 13, "bold")).pack(side="left")
        table_frame = ttk.Frame(bottom)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_frame, columns=("level", "element", "message"), show="headings", selectmode="browse", height=4)
        for column, label, width in (("level", "Тип", 95), ("element", "Элемент", 220), ("message", "Замечание", 620)):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, minwidth=80)
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.table.tag_configure("error", foreground="#a32932")
        self.table.tag_configure("warning", foreground="#8b5b0a")
        self.table.tag_configure("stripe", background="#f7f9fb")
        self.table.bind("<<TreeviewSelect>>", self.describe)
        self.table.bind("<Button-1>", self.table_click)
        self.table.bind("<Double-Button-1>", self.zoom_issue)
        self.detail = tk.Text(bottom, height=4, wrap="word", font=("Helvetica", 11), padx=14, pady=10,
                              background="#ffffff", foreground="#23384c", relief="flat", highlightthickness=1,
                              highlightbackground="#d6dfe7")
        # Сначала резервируем место пояснению, затем отдаём остаток таблице.
        self.detail.pack(side="bottom", fill="x", pady=(8, 4), before=table_frame)
        self.detail.tag_configure("title", font=("Helvetica", 11, "bold"), foreground="#243449")
        self.detail.tag_configure("muted", foreground="#728194", font=("Helvetica", 10))
        self.set_detail("Здесь появятся пояснение и подсказка для выбранного замечания.")
        self.status = tk.StringVar(value="Переносы сохраняются автоматически · Двойной клик приближает элемент")
        ttk.Label(frame, textvariable=self.status, style="Muted.TLabel", wraplength=1050).pack(side="bottom", anchor="w", pady=(8, 0), before=panes)
        root.bind("<Command-z>", lambda _event: self.undo_move())
        root.bind("<Control-z>", lambda _event: self.undo_move())
        root.bind("<F11>", lambda _event: self.toggle_fullscreen())
        root.after(700, self.watch)

    def resize_panes(self, _event=None):
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after_idle(self.arrange_panes)

    def arrange_panes(self):
        self._resize_job = None
        height = self.panes.winfo_height()
        # Пояснение и хотя бы две строки списка остаются видимыми при уменьшении окна.
        self.panes.sashpos(0, max(100, min(round(height * .58), height - 250)))
        self.diagram_view.fit()

    def choose(self):
        selected = filedialog.askopenfilename(title="Выберите BPMN-схему", filetypes=[("BPMN / XML", "*.bpmn *.xml"), ("Все файлы", "*")])
        if selected:
            self.load(Path(selected))

    def demo(self):
        self.load(Path(__file__).parent / "examples" / "broken.bpmn")

    def signature(self):
        try:
            stat = self.path.stat() if self.path else None
            return (stat.st_mtime_ns, stat.st_size) if stat else None
        except OSError:
            return None

    def load(self, path: Path):
        self.undo_history.clear()
        self.undo_button.configure(state="disabled")
        self._canvas_selection = None
        self.path = path
        self.filename.set(path.name)
        self.analyze()

    def analyze(self, preserve=False):
        if self.path is None:
            return
        self.last_signature = self.signature()
        self.pending_signature = self.last_signature
        # Один снимок файла для анализа и отрисовки: они не расходятся при сохранении.
        try:
            with self.path.open("rb") as source:
                data = source.read(MAX_BYTES + 1)
        except OSError:
            self.source_data = None
            self.report = check_file(self.path)
            diagram = Diagram(note="Файл недоступен. Подробности в списке замечаний.")
        else:
            self.source_data = data
            self.report = check_bytes(data, self.path.name)
            diagram = load_diagram(data)
        for view in self.views():
            old_scale, old_selection = view.scale, view.selected
            view.show(deepcopy(diagram), self.report)
            if preserve:
                view.scale = old_scale
                view.redraw()
                if old_selection:
                    view.select(old_selection, center=True)
        self.summary.set(f"Ошибки: {self.report.errors}    Рекомендации: {self.report.warnings}    Элементы: {self.report.nodes}")
        for row in self.table.get_children():
            self.table.delete(row)
        for index, issue in enumerate(self.report.issues):
            self.table.insert("", "end", iid=str(index), values=(
                "Ошибка" if issue.severity == "error" else "Проверить",
                issue.element_name or issue.element_id or "Документ", issue.message,
            ), tags=(issue.severity, "stripe" if index % 2 else "plain"))
        if self.report.issues:
            self.table.selection_set("0")
            self.describe()
        else:
            self.set_detail("В рамках доступных проверок замечаний нет. Это не гарантирует корректность бизнес-процесса.")
        self.export_button.configure(state="normal")
        if self.fullscreen_window:
            self.populate_floating()

    def watch(self):
        if self.path and not any(view.move_id for view in self.views()):
            current = self.signature()
            if current != self.last_signature:
                if current == self.pending_signature:
                    self.analyze()
                else:
                    self.pending_signature = current
        self.root.after(700, self.watch)

    def set_detail(self, text: str):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.tag_add("title", "1.0", "1.end")
        for index, line in enumerate(text.splitlines(), start=1):
            if line.startswith("ID:"):
                self.detail.tag_add("muted", f"{index}.0", f"{index}.end")
        self.detail.configure(state="disabled")

    def describe(self, _event=None):
        selected = self.table.selection()
        if self.report and selected and int(selected[0]) < len(self.report.issues):
            issue = self.report.issues[int(selected[0])]
            visible = self.active_view.select(issue.element_id, center=self._canvas_selection != issue.element_id)
            location = "" if visible else "\nЭлемент не показан на текущей схеме; замечание относится к документу или другой области."
            self.set_detail(f"{issue.message}\nЧто сделать: {issue.hint}\nID: {issue.element_id or '—'} · Правило: {issue.code}{location}")
            if self.fullscreen_window:
                if self.floating_list.selection() != selected:
                    self.floating_list.selection_set(selected[0])
                    self.floating_list.see(selected[0])
                self.floating_detail.configure(state="normal")
                self.floating_detail.delete("1.0", "end")
                self.floating_detail.insert("1.0", f"{issue.message}\n\n{issue.hint}")
                self.floating_detail.configure(state="disabled")

    def select_element(self, identifier):
        self._canvas_selection = identifier
        if self.report is None:
            return
        matching = [index for index, issue in enumerate(self.report.issues) if issue.element_id == identifier]
        if matching:
            row = str(matching[0])
            self.table.selection_set(row)
            self.table.see(row)
            self.describe()
        else:
            self.table.selection_remove(*self.table.selection())
            element = next((item for item in self.diagram_view.diagram.shapes + self.diagram_view.diagram.edges
                            if item.element_id == identifier), None)
            label = element.name or identifier if element else identifier
            self.set_detail(f"{label}\nДля этого элемента замечаний не найдено.\nID: {identifier}")
            if self.fullscreen_window:
                self.floating_list.selection_remove(*self.floating_list.selection())
                self.floating_detail.configure(state="normal")
                self.floating_detail.delete("1.0", "end")
                self.floating_detail.insert("1.0", f"{label}\nЗамечаний не найдено.")
                self.floating_detail.configure(state="disabled")

    @property
    def active_view(self):
        return self.fullscreen_view or self.diagram_view

    def views(self):
        return [self.diagram_view] + ([self.fullscreen_view] if self.fullscreen_view else [])

    def table_click(self, _event=None):
        self._canvas_selection = None

    def zoom_issue(self, event=None, source_table=None):
        if self.report is None:
            return "break"
        if event is not None:
            # Событие двойного клика приходит раньше стандартной обработки
            # Treeview. Берём строку под курсором, а не устаревшее selection().
            table = source_table if source_table is not None else event.widget
            # Вся строка кликабельна, в том числе свободная область справа от колонок.
            # identify_row возвращает пустую строку для заголовка и пустого списка.
            row = table.identify_row(event.y)
        else:
            row = next(iter(self.table.selection()), "")
        if not row or not row.isdigit() or int(row) >= len(self.report.issues):
            return "break"
        self._canvas_selection = None
        self.table.selection_set(row)
        self.table.focus(row)
        self.table.see(row)
        if self.fullscreen_window:
            self.floating_list.selection_set(row)
            self.floating_list.focus(row)
            self.floating_list.see(row)
        self.describe()
        self.active_view.focus_element(self.report.issues[int(row)].element_id)
        return "break"

    def commit_move(self, diagram):
        if self.path is None or self.source_data is None:
            self.analyze(preserve=True)
            return
        previous = self.source_data
        selected = self.active_view.selected
        try:
            updated = updated_xml(previous, diagram)
            save_document(self.path, previous, updated)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Перенос не сохранён", str(exc), parent=self.fullscreen_window or self.root)
            self.analyze(preserve=True)
            return
        self.undo_history.append((previous, updated))
        self.undo_history = self.undo_history[-20:]
        self.undo_button.configure(state="normal")
        self.analyze(preserve=True)
        if selected:
            self.active_view.select(selected)
            self.select_element(selected)
        self.status.set(f"Сохранено в {self.path.name} · Отмена: ⌘Z / Ctrl+Z")

    def undo_move(self):
        if not self.undo_history or self.path is None:
            return
        previous, expected = self.undo_history[-1]
        try:
            save_document(self.path, expected, previous)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Не удалось отменить", str(exc), parent=self.fullscreen_window or self.root)
            self.analyze(preserve=True)
            return
        self.undo_history.pop()
        self.undo_button.configure(state="normal" if self.undo_history else "disabled")
        self.analyze(preserve=True)
        self.status.set("Последний перенос отменён")

    def toggle_fullscreen(self):
        if self.fullscreen_window:
            self.close_fullscreen()
            return
        window = tk.Toplevel(self.root)
        self.fullscreen_window = window
        window.title("BPMN Check · Схема")
        window.protocol("WM_DELETE_WINDOW", self.close_fullscreen)
        window.bind("<Escape>", lambda _event: self.close_fullscreen())
        window.bind("<F11>", lambda _event: self.close_fullscreen())
        window.bind("<Command-z>", lambda _event: self.undo_move())
        window.bind("<Control-z>", lambda _event: self.undo_move())
        view = DiagramView(window, self.select_element, self.commit_move, self.close_fullscreen)
        view.fullscreen_button.configure(text="Выйти · Esc")
        self.fullscreen_view = view
        view.pack(fill="both", expand=True, padx=16, pady=16)
        self.floating = ttk.Frame(window, padding=12, relief="solid", borderwidth=1)
        self.floating.place(relx=1, x=-26, y=70, anchor="ne", width=350)
        bar = ttk.Frame(self.floating)
        bar.pack(fill="x", pady=(0, 8))
        handle = ttk.Label(bar, text="⠿  Замечания", font=("Helvetica", 12, "bold"), cursor="fleur")
        handle.pack(side="left")
        ttk.Button(bar, text="−", width=2, command=self.collapse_floating).pack(side="right")
        self.floating_body = ttk.Frame(self.floating)
        self.floating_body.pack(fill="both")
        self.floating_list = ttk.Treeview(self.floating_body, columns=("kind", "name"), show="headings", height=5, selectmode="browse")
        self.floating_list.heading("kind", text="Тип")
        self.floating_list.heading("name", text="Элемент")
        self.floating_list.column("kind", width=82, stretch=False)
        self.floating_list.column("name", width=210)
        scrollbar = ttk.Scrollbar(self.floating_body, orient="vertical", command=self.floating_list.yview)
        self.floating_list.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.floating_list.pack(fill="x")
        self.floating_list.tag_configure("error", foreground="#b33b55")
        self.floating_list.tag_configure("warning", foreground="#936e26")
        self.floating_list.bind("<<TreeviewSelect>>", self.floating_select)
        self.floating_list.bind("<Double-Button-1>", lambda event: self.zoom_issue(event, self.floating_list))
        self.floating_detail = tk.Text(self.floating_body, height=5, wrap="word", background="#ffffff", foreground="#4c4265",
                                       relief="flat", padx=8, pady=8, font=("Helvetica", 11))
        self.floating_detail.pack(fill="x", pady=(8, 0))
        ttk.Label(self.floating, text="Esc — вернуться · ⌘Z — отменить перенос", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        handle.bind("<Button-1>", lambda event: setattr(self, "_panel_drag", (event.x_root-self.floating.winfo_x(), event.y_root-self.floating.winfo_y())))
        handle.bind("<B1-Motion>", self.drag_floating)
        window.update_idletasks()
        if self.report:
            view.show(deepcopy(self.diagram_view.diagram), self.report)
        self.populate_floating()
        # На macOS запрос fullscreen до показа окна иногда игнорируется.
        # Сначала даём Tk отобразить полностью созданное окно, затем разворачиваем.
        window.update()
        window.lift()
        window.focus_set()
        window.attributes("-fullscreen", True)

    def populate_floating(self):
        for row in self.floating_list.get_children():
            self.floating_list.delete(row)
        if self.report:
            for index, issue in enumerate(self.report.issues):
                self.floating_list.insert("", "end", iid=str(index), values=("Ошибка" if issue.severity == "error" else "Совет",
                    issue.element_name or issue.element_id or "Документ"), tags=(issue.severity,))
        self.floating_detail.configure(state="normal")
        self.floating_detail.delete("1.0", "end")
        self.floating_detail.insert("1.0", "Выберите замечание из списка." if self.report and self.report.issues else "Замечаний не найдено.")
        self.floating_detail.configure(state="disabled")

    def floating_select(self, _event=None):
        selected = self.floating_list.selection()
        if selected and selected != self.table.selection():
            self._canvas_selection = None
            self.table.selection_set(selected[0])
            self.describe()

    def collapse_floating(self):
        if self.floating_body.winfo_manager():
            self.floating_body.pack_forget()
        else:
            self.floating_body.pack(fill="both", after=self.floating.winfo_children()[0])

    def drag_floating(self, event):
        x = max(0, min(event.x_root-self._panel_drag[0], self.fullscreen_window.winfo_width()-350))
        y = max(45, min(event.y_root-self._panel_drag[1], self.fullscreen_window.winfo_height()-self.floating.winfo_height()))
        self.floating.place(relx=0, x=x, y=y, anchor="nw")

    def close_fullscreen(self):
        if not self.fullscreen_window:
            return
        self.fullscreen_view.cancel_move()
        self.fullscreen_window.destroy()
        self.fullscreen_window = None
        self.fullscreen_view = None
        self.root.focus_set()

    def export(self):
        if self.report is None:
            return
        selected = filedialog.asksaveasfilename(title="Сохранить отчёт", defaultextension=".html", initialfile="bpmn-report.html", filetypes=[("HTML", "*.html")])
        if selected:
            if self.path and Path(selected).resolve() == self.path.resolve():
                messagebox.showerror("Выберите другое имя", "Нельзя сохранять отчёт поверх исходной схемы.")
                return
            try:
                write_html(self.report, selected)
            except OSError as exc:
                messagebox.showerror("Отчёт не сохранён", str(exc))
                return
            messagebox.showinfo("Готово", "HTML-отчёт сохранён. Его можно открыть в браузере.")


if __name__ == "__main__":
    window = tk.Tk()
    app = BpmnApp(window)
    if len(sys.argv) > 1:
        window.after(100, lambda: app.load(Path(sys.argv[1])))
    window.mainloop()
