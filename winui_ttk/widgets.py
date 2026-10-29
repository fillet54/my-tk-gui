"""Widgets that ttk lacks, built from themed parts."""

import tkinter as tk
from tkinter import ttk

from .elements import TEXTBOX_STATES, stroke
from .tokens import to_hex


def theme_of(widget):
    """The ``Theme`` applied to ``widget``'s application."""
    theme = getattr(widget._root(), "_winui_theme", None)
    if theme is None:
        raise RuntimeError("no winui_ttk Theme on this Tk root; create one first")
    return theme


class TextBox(ttk.Frame):
    """A multi-line WinUI TextBox: a ``tk.Text`` (``.text``) inside the
    TextBox border, with the accent underline when focused.

        box = TextBox(parent, height=5, wrap="word")
        box.text.insert("end", "Hello")
        box.set_enabled(False)

    Extra keyword arguments go to the ``tk.Text``.
    """

    def __init__(self, master, **text_options):
        self.theme = theme_of(master)
        s = self.theme.scale
        st = stroke(s)
        underline = max(2, round(2 * s))
        super().__init__(master, style="TextBox.TFrame", padding=(st, st, st, underline))

        text_options.setdefault("height", 4)
        self.text = tk.Text(self, borderwidth=0, highlightthickness=0, relief="flat",
                            font="WinUI.Body", padx=round(10 * s), pady=round(5 * s), **text_options)
        self.text.pack(fill="both", expand=True)

        self.text.bind("<FocusIn>", lambda e: self._set("focus", True), add="+")
        self.text.bind("<FocusOut>", lambda e: self._set("focus", False), add="+")
        for widget in (self, self.text):
            widget.bind("<Enter>", lambda e: self._set("hover", True), add="+")
            widget.bind("<Leave>", self._leave, add="+")
        # The theme moves widgets on cards to "Surface." styles when shown.
        self.bind("<Map>", lambda e: self.after_idle(self._recolor), add="+")
        self._listener = self.theme.on_change(lambda theme: self._recolor())
        self.bind("<Destroy>", self._destroyed, add="+")
        self._recolor()

    def set_enabled(self, enabled):
        self.text.configure(state="normal" if enabled else "disabled")
        self._set("disabled", not enabled)

    def _set(self, flag, on):
        self.state([flag if on else "!" + flag])
        self._recolor()

    def _leave(self, event):
        # Moving from the border onto the Text is a Leave on the frame; only
        # clear hover once the pointer is outside both.
        def check():
            if not self.winfo_exists():
                return
            inside = self.winfo_containing(*self.winfo_pointerxy())
            if inside not in (self, self.text):
                self._set("hover", False)
        self.after_idle(check)

    def _recolor(self):
        if not self.winfo_exists():
            return
        c = self.theme.colors
        under = c.surface if str(self.cget("style")).startswith("Surface.") else c.base
        fill_name = next(fill for spec, fill, *_ in TEXTBOX_STATES
                         if spec == "" or self.instate(list(spec)))
        fill = c.on(fill_name, under)
        text = "TextFillColorDisabled" if self.instate(["disabled"]) else "TextFillColorPrimary"
        self.text.configure(
            background=to_hex(fill), foreground=to_hex(c.on(text, fill)),
            insertbackground=to_hex(c.on("TextFillColorPrimary", fill)),
            selectbackground=to_hex(c.on("AccentFillColorSelectedTextBackground", fill)),
            selectforeground="#ffffff",
            inactiveselectbackground=to_hex(c.on("SubtleFillColorTertiary", fill)))

    def _destroyed(self, event):
        if event.widget is self:
            self.theme.remove_listener(self._listener)
