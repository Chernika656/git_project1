"""Отрисовка базовых BPMN-символов средствами Tkinter Canvas, целиком на Python."""

import tkinter as tk
from copy import deepcopy
from tkinter import font as tkfont, ttk

from facet.bpmn.diagram import CONTAINERS, Diagram, severity_by_element
from facet.bpmn.editor import move_shape


COLORS = {
    "error": ("#c43142", "#fff0f1"),
    "warning": ("#ad7012", "#fff7dc"),
    "normal": ("#72709d", "#f4f1ff"),
}


class DiagramView(ttk.Frame):
    def __init__(self, parent, on_select, on_move=None, on_fullscreen=None):
        super().__init__(parent)
        self.on_select = on_select
        self.on_move = on_move
        self.move_id = None
        self.move_snapshot = None
        self.editable = True
        self.on_fullscreen = on_fullscreen
        self.diagram = Diagram()
        self.severities = {}
        self.selected = None
        self.scale = 1.0
        self.item_elements = {}
        self.element_items = {}
        self.offset = (35, 35)
        self.note = tk.StringVar(value="Откройте файл, чтобы увидеть схему.")
        tools = ttk.Frame(self)
        tools.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(tools, text="Схема", font=("Helvetica", 13, "bold")).pack(side="left")
        ttk.Label(tools, text="● Ошибка", foreground="#be394b", font=("Helvetica", 10)).pack(side="left", padx=(18, 10))
        ttk.Label(tools, text="● Рекомендация", foreground="#996912", font=("Helvetica", 10)).pack(side="left")
        if on_fullscreen:
            self.fullscreen_button = ttk.Button(tools, text="На весь экран", command=on_fullscreen)
            self.fullscreen_button.pack(side="right", padx=(8, 0))
        self.zoom_label = tk.StringVar(value="100%")
        ttk.Label(tools, textvariable=self.zoom_label, style="Muted.TLabel", width=5, anchor="center").pack(side="right", padx=6)
        ttk.Button(tools, text="Вместить", command=self.fit, width=9).pack(side="right")
        ttk.Button(tools, text="+", command=lambda: self.zoom(1.2), width=3).pack(side="right", padx=3)
        ttk.Button(tools, text="−", command=lambda: self.zoom(1 / 1.2), width=3).pack(side="right")
        self.canvas = tk.Canvas(self, background="#ffffff", highlightthickness=1, highlightbackground="#dce4ec", height=310)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        vertical.grid(row=1, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        horizontal.grid(row=2, column=0, sticky="ew")
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        ttk.Label(self, textvariable=self.note, wraplength=1050, style="Muted.TLabel").grid(row=3, column=0, columnspan=2, sticky="w", pady=(5, 0))
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<B1-Motion>", self.pan)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<Double-Button-1>", self.double_click)
        self.canvas.bind("<Escape>", self.cancel_move)
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<Button-4>", lambda _event: self.zoom(1.1))
        self.canvas.bind("<Button-5>", lambda _event: self.zoom(1 / 1.1))
        self.dragging = False

    def show(self, diagram, report):
        self.diagram = diagram
        self.severities = severity_by_element(report)
        self.selected = None
        self.editable = not any(issue.code in {"DUPLICATE_ID", "MISSING_ID"} for issue in report.issues)
        self.note.set(diagram.note or "Двойной клик — приблизить · Потяните блок — переместить и сохранить")
        self.fit()

    def bounds(self):
        points = []
        for shape in self.diagram.shapes:
            points.extend([(shape.x, shape.y), (shape.x + shape.width, shape.y + shape.height + 36)])
            if shape.label:
                x, y, w, h = shape.label
                points.extend([(x, y), (x + w, y + h)])
        for edge in self.diagram.edges:
            points.extend(edge.points)
            if edge.label:
                x, y, w, h = edge.label
                points.extend([(x, y), (x + w, y + h)])
        if not points:
            return 0, 0, 500, 240
        return (min(p[0] for p in points), min(p[1] for p in points),
                max(p[0] for p in points), max(p[1] for p in points))

    def fit(self):
        self.update_idletasks()
        x1, y1, x2, y2 = self.bounds()
        width, height = max(self.canvas.winfo_width(), 200), max(self.canvas.winfo_height(), 150)
        self.scale = max(0.02, min(1.6, (width - 80) / max(1, x2 - x1), (height - 75) / max(1, y2 - y1)))
        self.redraw()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def zoom(self, factor):
        self.scale = max(0.02, min(4.0, self.scale * factor))
        self.redraw()
        if self.selected:
            self.select(self.selected, center=True)

    def wheel(self, event):
        if event.delta:
            self.zoom(1.1 if event.delta > 0 else 1 / 1.1)
        return "break"

    def xy(self, x, y):
        return x * self.scale + self.offset[0], y * self.scale + self.offset[1]

    def register(self, item, identifier):
        self.item_elements[item] = identifier
        self.element_items.setdefault(identifier, []).append(item)
        return item

    def text(self, identifier, x, y, text, width=120, color="#273e52", anchor="center", bold=False):
        # Отрицательный размер — пиксели, поэтому текст масштабируется вместе с геометрией.
        font = ("Helvetica", -max(6, round(14 * self.scale)), "bold" if bold else "normal")
        metrics = tkfont.Font(self.canvas, font=font)
        # Не переносим последнюю букву длинного слова на отдельную строку.
        longest_word = max((metrics.measure(word) for word in text.split()), default=0)
        return self.register(self.canvas.create_text(*self.xy(x, y), text=text, width=max(25, width * self.scale, longest_word + 4),
                             font=font,
                             fill=color, anchor=anchor), identifier)

    def redraw(self, keep_origin=False):
        self.canvas.delete("all")
        self.item_elements.clear()
        self.element_items.clear()
        x1, y1, x2, y2 = self.bounds()
        if not keep_origin:
            self.offset = (max(40, (self.canvas.winfo_width()-(x2-x1)*self.scale)/2) - x1*self.scale,
                           max(35, (self.canvas.winfo_height()-(y2-y1)*self.scale)/2) - y1*self.scale)
        self.zoom_label.set(f"{round(self.scale*100)}%")
        if not self.diagram.shapes:
            self.canvas.create_text(32, 45, anchor="nw", text="Схема появится здесь", fill="#718394", font=("Helvetica", 18))
        # Контейнеры под стрелками; обычные блоки над стрелками.
        containers = [shape for shape in self.diagram.shapes if shape.kind in CONTAINERS or shape.expanded]
        normal = [shape for shape in self.diagram.shapes if shape not in containers]
        for shape in sorted(containers, key=lambda item: -item.width * item.height):
            self.draw_shape(shape)
        for edge in self.diagram.edges:
            self.draw_edge(edge)
        for shape in normal:
            self.draw_shape(shape)
        box = self.canvas.bbox("all")
        width = max(self.canvas.winfo_width() - 2, (x2 - x1) * self.scale + 90, box[2] + 20 if box else 0)
        height = max(self.canvas.winfo_height() - 2, (y2 - y1) * self.scale + 90, box[3] + 20 if box else 0)
        self.canvas.configure(scrollregion=(0, 0, width, height))
        if self.selected:
            self.select(self.selected)

    def draw_edge(self, edge):
        color, _ = COLORS[self.severities.get(edge.element_id, "normal")]
        points = [value for point in edge.points for value in self.xy(*point)]
        dash = (6, 4) if edge.kind in {"messageFlow", "association"} else ()
        width = (3 if edge.element_id in self.severities else 1.6) * max(0.7, self.scale)
        self.register(self.canvas.create_line(*points, fill=color, width=width,
                                             arrow=tk.LAST if edge.kind != "association" else tk.NONE,
                                             arrowshape=(10 * max(.7, self.scale), 12 * max(.7, self.scale), 4 * max(.7, self.scale)),
                                             dash=dash, joinstyle=tk.ROUND), edge.element_id)
        if edge.name:
            if edge.label:
                x, y, w, h = edge.label
                x, y = x + w / 2, y + h / 2
            else:
                # Подпись размещается над самым длинным сегментом.
                a, b = max(zip(edge.points, edge.points[1:]), key=lambda pair: (pair[0][0]-pair[1][0])**2 + (pair[0][1]-pair[1][1])**2)
                x, y, w = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 6, 160
            self.text(edge.element_id, x, y, edge.name, width=w, color=color, anchor="center" if edge.label else "s")

    def draw_shape(self, shape):
        identifier = shape.element_id
        color, fill = COLORS[self.severities.get(identifier, "normal")]
        if identifier not in self.severities:
            if shape.kind.endswith("Gateway"):
                color, fill = "#ab8645", "#fff5df"
            elif shape.kind.endswith("Event"):
                color, fill = "#6788b3", "#edf4ff"
        border = (3 if identifier in self.severities else 1.7) * max(.7, self.scale)
        x, y = self.xy(shape.x, shape.y)
        right, bottom = self.xy(shape.x + shape.width, shape.y + shape.height)
        cx, cy = (x + right) / 2, (y + bottom) / 2
        label_outside = False
        if shape.kind.endswith("Event"):
            width = max(border, 3.5 * self.scale) if shape.kind == "endEvent" else border
            self.register(self.canvas.create_oval(x, y, right, bottom, outline=color, fill=fill, width=width), identifier)
            if shape.kind in {"intermediateCatchEvent", "intermediateThrowEvent", "boundaryEvent"}:
                pad = 4 * self.scale
                self.register(self.canvas.create_oval(x+pad, y+pad, right-pad, bottom-pad, outline=color, width=max(1, self.scale)), identifier)
            label_outside = True
        elif shape.kind.endswith("Gateway"):
            self.register(self.canvas.create_polygon(cx, y, right, cy, cx, bottom, x, cy, outline=color, fill=fill, width=border), identifier)
            marker = {"exclusiveGateway": "×", "parallelGateway": "+", "inclusiveGateway": "○", "complexGateway": "*", "eventBasedGateway": "◇"}.get(shape.kind, "")
            self.register(self.canvas.create_text(cx, cy, text=marker, fill=color,
                                                 font=("Helvetica", max(11, round(26 * self.scale)), "bold")), identifier)
            label_outside = True
        elif shape.kind in CONTAINERS or shape.expanded:
            self.register(self.canvas.create_rectangle(x, y, right, bottom, outline=color if identifier in self.severities else "#d4d3e5",
                                                       fill=fill if identifier in self.severities else "#faf9fe", width=border), identifier)
            if shape.kind in CONTAINERS:
                self.register(self.canvas.create_line(x+28*self.scale, y, x+28*self.scale, bottom, fill=color), identifier)
                self.register(self.canvas.create_text(x+14*self.scale, cy, text=shape.name or identifier, angle=90,
                                                     width=max(30, (shape.height-12)*self.scale), fill=color,
                                                     font=("Helvetica", max(8, round(11*self.scale)))), identifier)
            else:
                self.text(identifier, shape.x+10, shape.y+8, shape.name or identifier, width=shape.width-20, anchor="nw")
        else:
            r = min(10*self.scale, (right-x)/4, (bottom-y)/4)
            points = [x+r,y, right-r,y, right,y, right,y+r, right,bottom-r, right,bottom,
                      right-r,bottom, x+r,bottom, x,bottom, x,bottom-r, x,y+r, x,y]
            self.register(self.canvas.create_polygon(points, smooth=True, splinesteps=16, outline=color, fill=fill, width=border), identifier)
            self.text(identifier, shape.x+shape.width/2, shape.y+shape.height/2,
                      shape.name or identifier, width=shape.width-16)
            if shape.kind in {"subProcess", "transaction", "adHocSubProcess"}:
                self.text(identifier, shape.x+shape.width/2, shape.y+shape.height-10, "⊞", width=20)
        if label_outside:
            if shape.label:
                lx, ly, lw, lh = shape.label
                self.text(identifier, lx+lw/2, ly+lh/2, shape.name or identifier, width=lw)
            else:
                self.text(identifier, shape.x+shape.width/2, shape.y+shape.height+10,
                          shape.name or identifier, width=max(100, shape.width+60), anchor="n")

    def element_bbox(self, identifier):
        items = self.element_items.get(identifier, [])
        return self.canvas.bbox(*items) if items else None

    def select(self, identifier, center=False):
        self.selected = identifier
        self.canvas.delete("selection")
        box = self.element_bbox(identifier)
        if not box:
            return False
        x1, y1, x2, y2 = box
        self.canvas.create_rectangle(x1-7, y1-7, x2+7, y2+7, outline="#8860d0", width=2, tags="selection")
        if center:
            region = tuple(float(value) for value in self.canvas.cget("scrollregion").split())
            self.canvas.xview_moveto(max(0, ((x1+x2)/2-self.canvas.winfo_width()/2)/max(1, region[2])))
            self.canvas.yview_moveto(max(0, ((y1+y2)/2-self.canvas.winfo_height()/2)/max(1, region[3])))
        return True

    def click(self, event):
        self.canvas.focus_set()
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        hits = self.canvas.find_overlapping(x-4, y-4, x+4, y+4)
        identifier = next((self.item_elements[item] for item in reversed(hits) if item in self.item_elements), None)
        if identifier:
            self.dragging = False
            self.select(identifier)
            self.on_select(identifier)
            shape = next((item for item in self.diagram.shapes if item.element_id == identifier), None)
            if shape and self.on_move and self.editable and not shape.attached_to:
                self.move_id = identifier
                self.move_start = (event.x, event.y)
                self.move_snapshot = None
                self.move_origin = self.offset
        else:
            self.dragging = True
            self.canvas.scan_mark(event.x, event.y)

    def pan(self, event):
        if self.move_id:
            dx, dy = event.x-self.move_start[0], event.y-self.move_start[1]
            if abs(dx)+abs(dy) < 5 and self.move_snapshot is None:
                return
            if self.move_snapshot is None:
                self.move_snapshot = deepcopy(self.diagram)
            self.diagram = deepcopy(self.move_snapshot)
            move_shape(self.diagram, self.move_id, dx/self.scale, dy/self.scale)
            self.offset = self.move_origin
            self.redraw(keep_origin=True)
            self.canvas.configure(cursor="fleur")
        elif self.dragging:
            self.canvas.scan_dragto(event.x, event.y, gain=1)

    def release(self, _event=None):
        changed = self.move_snapshot is not None and self.diagram != self.move_snapshot
        self.move_id = None
        self.move_snapshot = None
        self.dragging = False
        self.canvas.configure(cursor="")
        if changed and self.on_move:
            self.on_move(self.diagram)

    def cancel_move(self, _event=None):
        if self.move_snapshot is not None:
            self.diagram = self.move_snapshot
            self.redraw()
        self.move_id = None
        self.move_snapshot = None
        self.dragging = False
        self.canvas.configure(cursor="")

    def focus_element(self, identifier):
        self.update_idletasks()
        box = self.element_bbox(identifier)
        if box is None:
            return False
        width, height = (box[2]-box[0])/self.scale, (box[3]-box[1])/self.scale
        # Масштаб определяется новым объектом: после маленького блока большой
        # должен уменьшиться до размеров области просмотра, а не наследовать зум.
        self.scale = max(.02, min(2.2, max(200, self.canvas.winfo_width())*.6/max(width, 1),
                                 max(150, self.canvas.winfo_height())*.6/max(height, 1)))
        self.selected = identifier
        self.redraw()
        return self.select(identifier, center=True)

    def double_click(self, event):
        self.cancel_move()
        self.click(event)
        identifier = self.selected
        self.move_id = None
        if identifier:
            self.focus_element(identifier)
        return "break"
