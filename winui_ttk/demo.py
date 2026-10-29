"""WinUI controls gallery: python3 -m winui_ttk.demo

Plain tkinter/ttk code. The only theme-specific parts are the style names
for variants (Accent.TButton, Switch.TCheckbutton, Title.TLabel, ...) and
``ttk.Frame(class_="Card")`` for cards.
"""

import random
import tkinter as tk
from tkinter import colorchooser, ttk

from . import WINDOWS_ACCENTS, create_root, tokens
from .svg import Svg, rrect


class Gallery:
    def __init__(self):
        self.root, self.theme = create_root("WinUI for ttk", mode="light")
        root, theme = self.root, self.theme
        self.s = theme.scale
        self._vars = []
        root.geometry("%dx%d" % (self.px(1180), self.px(860)))
        root.minsize(self.px(900), self.px(640))

        outer = ttk.Frame(root, padding=self.px(28, 24, 28, 24))
        outer.pack(fill="both", expand=True)

        self._header(outer)
        self._accent_picker(outer)

        tabs = ttk.Notebook(outer)
        tabs.pack(fill="both", expand=True, pady=(self.px(20), 0))
        tabs.add(self._controls_page(tabs), text="Controls")
        tabs.add(self._list_page(tabs), text="ListView")
        tabs.add(self._typography_page(tabs), text="Typography")

        theme.on_change(lambda t: self._update_status())
        self._update_status()

    def var(self, kind, value):
        # Tk variables are deleted when Python collects them; keep them alive.
        v = kind(master=self.root, value=value)
        self._vars.append(v)
        return v

    def px(self, *values):
        out = tuple(round(v * self.s) for v in values)
        return out[0] if len(out) == 1 else out

    # -- top --------------------------------------------------------------------

    def _header(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill="x")
        text = ttk.Frame(row)
        text.pack(side="left")
        ttk.Label(text, text="WinUI for ttk", style="Title.TLabel").pack(anchor="w")
        self.status = ttk.Label(text, style="Secondary.TLabel")
        self.status.pack(anchor="w")

        self.dark = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Dark theme", style="Switch.TCheckbutton", variable=self.dark,
                        command=lambda: self.theme.set_mode("dark" if self.dark.get() else "light")
                        ).pack(side="right", anchor="n")

    def _update_status(self):
        t = self.theme
        self.status.configure(text="%s · %d%% scale · %d images drawn in %d ms · %s"
                              % (t.font_family, round(t.scale * 100), len(t.images),
                                 t.last_render_ms, t.accent))

    def _accent_picker(self, parent):
        card = ttk.Frame(parent, class_="Card")
        card.pack(fill="x", pady=(self.px(16), 0))
        top = ttk.Frame(card)
        top.pack(fill="x")
        ttk.Label(top, text="Accent color", style="BodyStrong.TLabel").pack(side="left")
        ttk.Button(top, text="Custom…", command=self._custom_accent).pack(side="right")
        ttk.Label(top, text="Windows' accent palette; click to repaint the theme live.",
                  style="Secondary.TLabel").pack(side="left", padx=self.px(12))

        grid = ttk.Frame(card)
        grid.pack(fill="x", pady=(self.px(12), 0))
        self.swatches = {}
        size = self.px(28)
        for i, color in enumerate(WINDOWS_ACCENTS):
            label = ttk.Label(grid, cursor="hand2")
            label.grid(row=i // 24, column=i % 24, padx=(0, self.px(6)), pady=(0, self.px(6)))
            label.bind("<Button-1>", lambda e, c=color: self.theme.set_accent(c))
            self.swatches[color] = label
        self.theme.on_change(lambda t: self._paint_swatches(size))
        self._paint_swatches(size)

    def _paint_swatches(self, size):
        ring = self.theme.colors.on("TextFillColorPrimary", self.theme.colors.surface)
        surface = self.theme.colors.surface
        self._swatch_images = {}
        for color, label in self.swatches.items():
            fill = tokens.parse(color)
            img = Svg(size, size, surface)
            r = 4 * self.s
            if color == self.theme.accent:
                w = max(2, round(2 * self.s))
                img.draw(rrect(0, 0, size, size, r), ring)
                img.draw(rrect(w, w, size - w, size - w, r - w / 2), surface)
                img.draw(rrect(2 * w, 2 * w, size - 2 * w, size - 2 * w, r - w), fill)
            else:
                img.draw(rrect(0, 0, size, size, r), fill)
            photo = tk.PhotoImage(master=self.root, data=img.data(), format="svg")
            self._swatch_images[color] = photo
            label.configure(image=photo)

    def _custom_accent(self):
        _, color = colorchooser.askcolor(self.theme.accent, parent=self.root, title="Accent color")
        if color:
            self.theme.set_accent(color)

    # -- pages --------------------------------------------------------------------

    def _card(self, parent, title, row, column, description=None):
        card = ttk.Frame(parent, class_="Card")
        card.grid(row=row, column=column, sticky="nsew", padx=self.px(8), pady=self.px(8))
        ttk.Label(card, text=title, style="BodyStrong.TLabel").pack(anchor="w")
        if description:
            ttk.Label(card, text=description, style="Secondary.TLabel").pack(anchor="w")
        body = ttk.Frame(card)
        body.pack(fill="both", expand=True, pady=(self.px(12), 0))
        return body

    def _controls_page(self, notebook):
        page = ttk.Frame(notebook, padding=self.px(12))
        for c in range(3):
            page.columnconfigure(c, weight=1, uniform="cards")
        gap = self.px(8)

        # 1. Button
        body = self._card(page, "Button", 0, 0, "Standard, accent and disabled")
        ttk.Button(body, text="Standard").pack(anchor="w")
        ttk.Button(body, text="Accent button", style="Accent.TButton").pack(anchor="w", pady=gap)
        ttk.Button(body, text="Disabled", state="disabled").pack(anchor="w")

        # 2. TextBox + 3. ComboBox
        body = self._card(page, "TextBox & ComboBox", 0, 1, "Click a field to see the accent underline")
        e = ttk.Entry(body)
        e.insert(0, "Hello, WinUI")
        e.pack(fill="x")
        e2 = ttk.Entry(body)
        e2.insert(0, "Disabled")
        e2.state(["disabled"])
        e2.pack(fill="x", pady=gap)
        combo = ttk.Combobox(body, state="readonly",
                             values=["Blue", "Green", "Orange", "Purple", "Red"])
        combo.current(0)
        combo.pack(fill="x")
        editable = ttk.Combobox(body, values=["Small", "Medium", "Large"])
        editable.set("Editable")
        editable.pack(fill="x", pady=(gap, 0))

        # 4. CheckBox
        body = self._card(page, "CheckBox", 0, 2, "Two-state, three-state and disabled")
        for text, value in (("Unchecked", 0), ("Checked", 1)):
            ttk.Checkbutton(body, text=text, variable=self.var(tk.IntVar, value)).pack(anchor="w")
        tri = self.var(tk.IntVar, 2)
        mixed = ttk.Checkbutton(body, text="Indeterminate", variable=tri, onvalue=1, offvalue=0)
        mixed.pack(anchor="w")
        self.root.globalunsetvar(str(tri))   # an unset variable = indeterminate; a click sets it
        dis = self.var(tk.IntVar, 1)
        ttk.Checkbutton(body, text="Disabled", variable=dis, state="disabled").pack(anchor="w")

        # 5. RadioButton
        body = self._card(page, "RadioButton", 1, 0, "One choice from a group")
        choice = self.var(tk.StringVar, "b")
        for text, value in (("Option 1", "a"), ("Option 2", "b"), ("Option 3", "c")):
            ttk.Radiobutton(body, text=text, value=value, variable=choice).pack(anchor="w")
        ttk.Radiobutton(body, text="Disabled", value="d", variable=choice, state="disabled").pack(anchor="w")

        # 6. ToggleSwitch
        body = self._card(page, "ToggleSwitch", 1, 1, "On/off settings")
        for text, on, state in (("Wi-Fi", True, "normal"), ("Bluetooth", False, "normal"),
                                ("Airplane mode", True, "disabled"), ("Location", False, "disabled")):
            ttk.Checkbutton(body, text=text, variable=self.var(tk.BooleanVar, on), style="Switch.TCheckbutton",
                            state=state).pack(anchor="w")

        # 7. Slider + 8. ProgressBar
        body = self._card(page, "Slider & ProgressBar", 1, 2, "The slider drives the bar")
        value = self.var(tk.DoubleVar, 40)
        readout = ttk.Label(body, text="40", style="Secondary.TLabel")
        ttk.Scale(body, from_=0, to=100, variable=value,
                  command=lambda v: readout.configure(text="%d" % float(v))).pack(fill="x")
        readout.pack(anchor="e")
        ttk.Progressbar(body, variable=value, maximum=100).pack(fill="x", pady=(gap, gap * 2))
        busy = ttk.Progressbar(body, mode="indeterminate", maximum=60)
        busy.pack(fill="x")
        busy.start(16)
        disabled = ttk.Scale(body, from_=0, to=100, value=70)
        disabled.state(["disabled"])
        disabled.pack(fill="x", pady=(gap * 2, 0))
        return page

    def _list_page(self, notebook):
        page = ttk.Frame(notebook, padding=self.px(16))
        page.rowconfigure(1, weight=1)
        page.columnconfigure(0, weight=1)
        ttk.Label(page, text="ListView with a ScrollBar — hover the scrollbar to expand it",
                  style="Secondary.TLabel").grid(row=0, column=0, sticky="w", pady=(0, self.px(8)))
        tree = ttk.Treeview(page, columns=("name", "kind", "size", "modified"), show="headings")
        for key, title, width, anchor in (("name", "Name", 280, "w"), ("kind", "Type", 140, "w"),
                                          ("size", "Size", 100, "e"), ("modified", "Modified", 160, "w")):
            tree.heading(key, text=title, anchor=anchor)
            tree.column(key, width=self.px(width), anchor=anchor)
        rng = random.Random(4)
        kinds = [("Document", ".docx"), ("Spreadsheet", ".xlsx"), ("Picture", ".png"),
                 ("Presentation", ".pptx"), ("Text", ".txt")]
        words = ["Budget", "Roadmap", "Notes", "Invoice", "Holiday", "Design", "Report", "Draft"]
        for i in range(60):
            kind, ext = rng.choice(kinds)
            tree.insert("", "end", values=("%s %d%s" % (rng.choice(words), i + 1, ext), kind,
                                           "%d KB" % rng.randint(4, 4000),
                                           "2026-%02d-%02d" % (rng.randint(1, 10), rng.randint(1, 28))))
        tree.selection_set(tree.get_children()[2])
        bar = ttk.Scrollbar(page, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        tree.grid(row=1, column=0, sticky="nsew")
        bar.grid(row=1, column=1, sticky="ns")
        return page

    def _typography_page(self, notebook):
        page = ttk.Frame(notebook, padding=self.px(24))
        for name, sample in (("Display", "Display"), ("TitleLarge", "Title large"),
                             ("Title", "Title"), ("Subtitle", "Subtitle"),
                             ("BodyLarge", "Body large"), ("BodyStrong", "Body strong"),
                             ("Body", "Body"), ("Caption", "Caption")):
            row = ttk.Frame(page)
            row.pack(fill="x", anchor="w")
            size, strong = tokens.TYPE_RAMP[name]
            ttk.Label(row, text="%s · %dpx%s" % (name, size, " semibold" if strong else ""),
                      style="Secondary.TLabel", width=26).pack(side="left", anchor="s")
            ttk.Label(row, text=sample, style="%s.TLabel" % name).pack(side="left", anchor="s")
        ttk.Label(page, text="Accent text uses AccentTextFillColorPrimary", style="Accent.TLabel"
                  ).pack(anchor="w", pady=(self.px(16), 0))
        return page


def main():
    Gallery().root.mainloop()


if __name__ == "__main__":
    main()
