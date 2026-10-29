"""The WinUI ttk theme: images, elements, layouts, styles and fonts."""

import os
import re
import subprocess
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from . import elements, tokens
from .elements import Colors, stroke
from .tokens import TYPE_RAMP, to_hex

# Containers whose children sit on the card surface instead of the window.
SURFACE_CLASSES = ("Card", "TNotebook")

# ttk classes that get moved onto "Surface.<style>" inside those containers.
_THEMED_CLASSES = ("TFrame", "TLabel", "TButton", "TCheckbutton", "TRadiobutton",
                   "TEntry", "TCombobox", "TScale", "TProgressbar", "TScrollbar",
                   "Treeview", "TSeparator", "TSpinbox", "TNotebook", "Card")


class Theme:
    """A WinUI 3 look for every ttk widget in ``root``.

    ``mode`` is "light" or "dark"; ``accent`` a "#RRGGBB" color (default:
    the Windows accent on Windows, else Windows' default blue). Both can be
    changed later with ``set_mode`` / ``set_accent``; images are repainted
    in place and every widget updates.
    """

    def __init__(self, root, mode="light", accent=None, scale=None):
        require_tk9(root)
        self.root = root
        self.scale = float(scale or detect_scale(root))
        self.mode = mode
        self.palette = tokens.system_accent() or tokens.accent_palette(accent or tokens.DEFAULT_ACCENT)
        if accent:
            self.palette = tokens.accent_palette(accent)
        self.style = ttk.Style(root)
        self.name = "winui-%d" % round(self.scale * 100)
        self.images = {}            # image name -> PhotoImage
        self._surface_styles = set()
        self._element_names = set()
        self._listeners = []
        self.fonts = {}
        self.last_render_ms = 0.0

        root.tk.call("tk", "scaling", self.scale * 96 / 72)
        self._fonts()
        self.colors = self._resolve()
        self._elements = elements.build(self.scale)
        self._paint_all(create=True)
        self._create_theme()
        self._configure()
        self._install_surface_hook()

    # -- public ---------------------------------------------------------------

    @property
    def accent(self):
        return self.palette["Accent"]

    def set_mode(self, mode):
        if mode not in ("light", "dark"):
            raise ValueError("mode must be 'light' or 'dark'")
        self.mode = mode
        self._refresh()

    def set_accent(self, color=None, palette=None):
        """Set an accent color (Windows derives the shades), or a full palette."""
        self.palette = palette or tokens.accent_palette(color)
        self._refresh()

    def color(self, token, on_surface=False):
        """A WinUI color token as "#rrggbb", composited for this mode."""
        under = self.colors.surface if on_surface else self.colors.base
        return to_hex(self.colors.on(token, under))

    def on_change(self, callback):
        """Call ``callback(theme)`` after every mode/accent change."""
        self._listeners.append(callback)

    def font(self, name="Body"):
        return "WinUI.%s" % name

    # -- colors and images ------------------------------------------------------

    def _resolve(self):
        values = dict(tokens.DARK if self.mode == "dark" else tokens.LIGHT)
        values.update(tokens.accent_tokens(self.palette, self.mode == "dark"))
        return Colors(values)

    def _variants(self):
        """(element-name prefix, colors) for elements on the window and on cards."""
        return (("", self.colors), ("Surface.", self.colors.on_surface()))

    def _paint_all(self, create=False):
        start = time.perf_counter()
        for prefix, colors in self._variants():
            for element in self._elements:
                for index, (_, paint) in enumerate(element.states):
                    name = _image_name(prefix + element.name, index)
                    data = paint(colors).data()
                    if create:
                        self.images[name] = tk.PhotoImage(name=name, master=self.root, data=data, format="svg")
                    else:
                        self.images[name].configure(data=data, format="svg")
        self.last_render_ms = (time.perf_counter() - start) * 1000

    def _refresh(self):
        self.colors = self._resolve()
        self._paint_all()
        self._configure()
        for callback in self._listeners:
            callback(self)

    # -- theme structure (scale-dependent, built once) ---------------------------

    def _create_theme(self):
        style = self.style
        if self.name not in style.theme_names():
            style.theme_create(self.name, parent="clam")
        style.theme_use(self.name)

        for prefix, _ in self._variants():
            for element in self._elements:
                name = prefix + element.name
                default = None
                specs = []
                for index, (state, _) in enumerate(element.states):
                    image = _image_name(name, index)
                    if state == "":
                        default = image
                    else:
                        specs.append(tuple(state) + (image,))
                kw = {"sticky": element.sticky, "padding": element.padding,
                      "width": element.size[0], "height": element.size[1]}
                if element.border:
                    kw["border"] = element.border
                style.element_create(name, "image", default, *specs, **kw)
        self._element_names = {element.name for element in self._elements}

        style.layout("TButton", [("Button.border", {"sticky": "nsew", "children": [
            ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
        style.layout("Accent.TButton", [("AccentButton.border", {"sticky": "nsew", "children": [
            ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
        style.layout("TEntry", [("Entry.field", {"sticky": "nsew", "children": [
            ("Entry.padding", {"sticky": "nsew", "children": [("Entry.textarea", {"sticky": "nsew"})]})]})])
        for cls, indicator in (("TCheckbutton", "Checkbutton.indicator"),
                               ("TRadiobutton", "Radiobutton.indicator"),
                               ("Switch.TCheckbutton", "Switch.indicator")):
            style.layout(cls, [("Checkbutton.padding", {"sticky": "nsew", "children": [
                (indicator, {"side": "left", "sticky": ""}),
                ("Checkbutton.label", {"side": "left", "sticky": "nsew"})]})])
        style.layout("TCombobox", [("Combobox.field", {"sticky": "nsew", "children": [
            ("Combobox.downarrow", {"side": "right", "sticky": "ns"}),
            ("Combobox.padding", {"sticky": "nsew", "children": [
                ("Combobox.textarea", {"sticky": "nsew"})]})]})])
        style.layout("Horizontal.TScale", [("Scale.padding", {"sticky": "nsew", "children": [
            ("Horizontal.Scale.trough", {"sticky": "ew", "children": [
                ("Horizontal.Scale.slider", {"side": "left", "sticky": ""})]})]})])
        style.layout("Horizontal.TProgressbar", [("Horizontal.Progressbar.trough", {"sticky": "ew", "children": [
            ("Horizontal.Progressbar.pbar", {"side": "left", "sticky": "ns"})]})])
        style.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.uparrow", {"side": "top", "sticky": ""}),
            ("Vertical.Scrollbar.downarrow", {"side": "bottom", "sticky": ""}),
            ("Vertical.Scrollbar.thumb", {"sticky": "nsew"})]})])
        style.layout("Horizontal.TScrollbar", [("Horizontal.Scrollbar.trough", {"sticky": "ew", "children": [
            ("Horizontal.Scrollbar.leftarrow", {"side": "left", "sticky": ""}),
            ("Horizontal.Scrollbar.rightarrow", {"side": "right", "sticky": ""}),
            ("Horizontal.Scrollbar.thumb", {"sticky": "nsew"})]})])
        style.layout("Treeview", [("Treeview.padding", {"sticky": "nsew", "children": [
            ("Treeview.treearea", {"sticky": "nsew"})]})])
        style.layout("Treeview.Row", [("Treeitem.row", {"sticky": "nsew"})])
        style.layout("TNotebook", [("Notebook.client", {"sticky": "nsew"})])
        style.layout("TNotebook.Tab", [("Notebook.tab", {"sticky": "nsew", "children": [
            ("Notebook.padding", {"side": "top", "sticky": "nsew", "children": [
                ("Notebook.label", {"side": "top", "sticky": ""})]})]})])
        style.layout("Card", [("Card.border", {"sticky": "nsew"})])

    # -- colors, fonts, paddings (re-run on every change) ---------------------------

    def _configure(self):
        c, s, style = self.colors, self.scale, self.style
        hexc = lambda name, under=None: to_hex(c.on(name, under))
        base, surface = to_hex(c.base), to_hex(c.surface)
        primary = hexc("TextFillColorPrimary")
        secondary = hexc("TextFillColorSecondary")
        disabled = hexc("TextFillColorDisabled")
        accent_fill = c.on("AccentFillColorDefault")
        select_bg = hexc("AccentFillColorSelectedTextBackground")
        px = lambda *v: tuple(round(x * s) for x in v)
        st = stroke(s)

        style.configure(".", background=base, foreground=primary, font="WinUI.Body",
                        selectbackground=select_bg, selectforeground="#ffffff",
                        insertcolor=primary, fieldbackground=base, troughcolor=base,
                        bordercolor=hexc("ControlStrokeColorDefault"), lightcolor=base,
                        darkcolor=base, focuscolor=primary, insertwidth=st)
        style.map(".", foreground=[("disabled", disabled)])

        # Buttons: WinUI padding plus the 1px border.
        style.configure("TButton", padding=px(12, 6, 12, 7), anchor="center", foreground=primary)
        style.map("TButton", foreground=[("disabled", disabled), ("pressed", secondary)])
        style.configure("Accent.TButton", foreground=hexc("TextOnAccentFillColorPrimary", accent_fill))
        style.map("Accent.TButton", foreground=[
            ("disabled", hexc("TextOnAccentFillColorDisabled", c.on("AccentFillColorDisabled"))),
            ("pressed", hexc("TextOnAccentFillColorSecondary", c.on("AccentFillColorTertiary")))])

        style.configure("TEntry", padding=px(11, 6, 7, 7), foreground=primary)
        style.map("TEntry", foreground=[("disabled", disabled)])

        style.configure("TCombobox", padding=px(13, 6, 0, 7), foreground=primary,
                        arrowsize=round(12 * s))
        style.map("TCombobox", foreground=[("disabled", disabled)],
                  selectbackground=[("readonly", hexc("ControlFillColorDefault"))],
                  selectforeground=[("readonly", primary)],
                  fieldbackground=[("readonly", hexc("ControlFillColorDefault"))])

        for cls in ("TCheckbutton", "TRadiobutton", "Switch.TCheckbutton"):
            style.configure(cls, padding=px(0, 6, 0, 6), foreground=primary)
            style.map(cls, foreground=[("disabled", disabled)])

        style.configure("Horizontal.TScale", padding=px(0, 6, 0, 6))
        style.configure("Treeview", rowheight=elements.row_height(s), font="WinUI.Body",
                        foreground=primary, background=base, fieldbackground=base, borderwidth=0)
        style.map("Treeview", foreground=[("selected", primary)], background=[("selected", base)])
        style.configure("Treeview.Heading", font="WinUI.Caption", foreground=secondary,
                        background=base, padding=px(12, 8, 12, 8), relief="flat", borderwidth=0)
        style.map("Treeview.Heading", background=[("active", base)], foreground=[("active", primary)])
        style.configure("Treeview.Item", padding=px(12, 0, 12, 0))
        style.configure("Treeview.Cell", padding=px(12, 0, 12, 0))

        style.configure("TNotebook", background=base, padding=0, tabmargins=0)
        style.configure("TNotebook.Tab", padding=px(14, 8, 14, 8), font="WinUI.Body",
                        foreground=secondary, background=base)
        style.map("TNotebook.Tab", foreground=[("selected", primary)],
                  expand=[("selected", (0, 0, 0, st))])

        style.configure("TFrame", background=base)
        style.configure("Card", background=surface)
        # Frames take padding only from the widget option, so default it for the class.
        self.root.option_add("*Card.padding", round(tokens.METRICS["CardPadding"] * s), "widgetDefault")
        style.configure("TLabel", background=base, foreground=primary, font="WinUI.Body")
        for name in TYPE_RAMP:
            style.configure("%s.TLabel" % name, font="WinUI.%s" % name)
        style.configure("Secondary.TLabel", foreground=secondary)
        style.configure("Accent.TLabel", foreground=hexc("AccentTextFillColorPrimary"))
        style.configure("TSeparator", background=hexc("DividerStrokeColorDefault"))
        style.configure("Vertical.TScrollbar", troughcolor=base)

        for name in self._surface_styles:
            style.configure(name, background=surface, fieldbackground=surface)
        if self._surface_styles:
            style.map("Surface.Treeview", background=[("selected", surface)])
            style.map("Surface.TNotebook.Tab", background=[])

        self._window_colors(base, primary)

    def _window_colors(self, base, primary):
        c = self.colors
        flyout = to_hex(c.raw("AcrylicBackgroundFillColorDefault"))
        hover = to_hex(c.on("SubtleFillColorSecondary", c.raw("AcrylicBackgroundFillColorDefault")))
        root = self.root
        root.configure(background=base)
        for pattern, value in (("*Toplevel.background", base),
                               ("*TCombobox*Listbox.background", flyout),
                               ("*TCombobox*Listbox.foreground", primary),
                               ("*TCombobox*Listbox.selectBackground", hover),
                               ("*TCombobox*Listbox.selectForeground", primary),
                               ("*TCombobox*Listbox.font", "WinUI.Body"),
                               ("*TCombobox*Listbox.borderWidth", 0),
                               ("*TCombobox*Listbox.highlightThickness", 0),
                               ("*TCombobox*Listbox.relief", "flat")):
            root.option_add(pattern, value)
        self.style.configure("ComboboxPopdownFrame", background=flyout, relief="solid", borderwidth=1,
                             bordercolor=to_hex(c.on("CardStrokeColorDefault", c.raw("AcrylicBackgroundFillColorDefault"))))
        # Popdowns that already exist don't re-read the option database.
        for widget in _descendants(root):
            if widget.winfo_class() == "TCombobox":
                try:
                    popdown = root.tk.call("ttk::combobox::PopdownWindow", widget)
                    root.tk.call(str(popdown) + ".f.l", "configure", "-background", flyout,
                                 "-foreground", primary, "-selectbackground", hover,
                                 "-selectforeground", primary)
                except tk.TclError:
                    pass
        _dark_title_bar(root, self.mode == "dark")

    # -- fonts --------------------------------------------------------------------

    def _fonts(self):
        families = set(tkfont.families(self.root))
        text = _first(families, ["Segoe UI Variable Text", "Segoe UI", "Selawik", "Noto Sans",
                                 "Inter", "Cantarell", "Liberation Sans", "DejaVu Sans"]) or "TkDefaultFont"
        display = _first(families, ["Segoe UI Variable Display", "Segoe UI"]) or text
        semibold = _first(families, ["Segoe UI Variable Text Semibold", "Segoe UI Semibold"])
        semibold_display = _first(families, ["Segoe UI Variable Display Semibold", "Segoe UI Semibold"])

        for name, (size, strong) in TYPE_RAMP.items():
            big = size >= 20
            if strong:
                family = (semibold_display if big else semibold) or (display if big else text)
                weight = "normal" if (semibold_display if big else semibold) else "bold"
            else:
                family, weight = (display if big else text), "normal"
            px = -max(1, round(size * self.scale))     # negative = pixels
            fname = "WinUI.%s" % name
            if fname in tkfont.names(self.root):
                tkfont.nametofont(fname, root=self.root).configure(family=family, size=px, weight=weight)
            else:
                # Keep a reference: tkinter deletes a named font when its Font is collected.
                self.fonts[name] = tkfont.Font(root=self.root, name=fname, family=family,
                                               size=px, weight=weight)

        body = tkfont.nametofont("WinUI.Body", root=self.root).actual()
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
            try:
                tkfont.nametofont(name, root=self.root).configure(
                    family=body["family"], size=-max(1, round(14 * self.scale)))
            except tk.TclError:
                pass
        self.font_family = text

    # -- surfaces ---------------------------------------------------------------------

    def _install_surface_hook(self):
        for cls in _THEMED_CLASSES:
            self.root.bind_class(cls, "<Map>", self._on_map, add="+")

    def _on_map(self, event):
        widget = event.widget
        if isinstance(widget, str):
            return
        try:
            current = str(widget.cget("style"))
        except tk.TclError:
            return
        if current.startswith("Surface."):
            return
        if current.split(".")[-1] == "Card" and not str(widget.cget("padding")):
            widget.configure(padding=round(tokens.METRICS["CardPadding"] * self.scale))
        if not current:
            # ttk picks an unstyled widget's layout from its type ("TFrame"),
            # not its class, so a Frame(class_="Card") needs the style named.
            current = widget.winfo_class()
            if current in ("TScale", "TProgressbar", "TScrollbar"):
                # These look up "<Orient>.<class>" layouts.
                current = "%s.%s" % (str(widget.cget("orient")).title(), current)
        parent = widget.master
        while parent is not None and not _is_surface(parent):
            parent = parent.master
        if parent is not None:
            widget.configure(style=self.surface_style(current))
        elif current != str(widget.cget("style")) and current == "Card":
            widget.configure(style="Card")

    def surface_style(self, style_name):
        """The ``Surface.`` twin of a style, for widgets on a card: the same
        layout, using the element images painted on the card color."""
        name = "Surface." + style_name
        if name in self._surface_styles:
            return name
        self._surface_styles.add(name)
        # Sublayouts (Treeview rows/headings, notebook tabs) are looked up as
        # "<style>.<part>", so they need their own Surface. copies too.
        for suffix in ("", ".Row", ".Heading", ".Item", ".Cell", ".Tab"):
            try:
                layout = self.style.layout(style_name + suffix)
            except tk.TclError:
                continue
            if layout and (suffix == "" or self._uses_elements(layout)):
                self.style.layout(name + suffix, self._on_surface(layout))
        surface = to_hex(self.colors.surface)
        self.style.configure(name, background=surface, fieldbackground=surface)
        if style_name == "Treeview":
            self.style.map(name, background=[("selected", surface)])
        return name

    def _on_surface(self, layout):
        out = []
        for element, options in layout:
            options = dict(options or {})
            if "children" in options:
                options["children"] = self._on_surface(options["children"])
            out.append(("Surface." + element if element in self._element_names else element, options))
        return out

    def _uses_elements(self, layout):
        return any(element in self._element_names or self._uses_elements((options or {}).get("children", []))
                   for element, options in layout)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def require_tk9(root):
    version = root.tk.call("info", "patchlevel")
    if not root.tk.call("package", "vsatisfies", version, "9-"):
        raise RuntimeError(
            "winui_ttk needs Tk 9 (for its built-in SVG images); this Python has Tk %s. "
            "Use a Python built against Tcl/Tk 9." % version)


def _is_surface(widget):
    """Cards and notebook pages put their children on the card color."""
    if widget.winfo_class() in SURFACE_CLASSES:
        return True
    try:
        return str(widget.cget("style")).split(".")[-1] in SURFACE_CLASSES
    except tk.TclError:
        return False


def _image_name(element_name, index):
    return "winui_%s_%d" % (element_name.replace(".", "_"), index)


def _first(available, candidates):
    for name in candidates:
        if name in available:
            return name
    return None


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _dark_title_bar(root, dark):
    """Windows 10 1809+/11: match the title bar to the theme. No-op elsewhere."""
    if os.name != "nt":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = int(root.wm_frame(), 16)
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE (and pre-20H1)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def enable_dpi_awareness():
    """Windows: call before creating ``tk.Tk()`` so Windows doesn't bitmap-stretch the app."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def detect_scale(root):
    """Device pixels per WinUI effective pixel for this screen.

    ``WINUI_TTK_SCALE`` overrides it. Windows: the monitor's DPI / 96.
    macOS: 1 (Tk handles Retina). X11: GDK_SCALE, Xft.dpi, QT_SCALE_FACTOR,
    then the X server's DPI.
    """
    for var in ("WINUI_TTK_SCALE",):
        value = _env_float(var)
        if value:
            return value
    system = root.tk.call("tk", "windowingsystem")
    if system == "aqua":
        return 1.0
    if system == "win32":
        return max(1.0, round(root.winfo_fpixels("1i") / 96, 2))
    value = _env_float("GDK_SCALE")
    if value:
        return value
    try:
        out = subprocess.run(["xrdb", "-query"], capture_output=True, text=True, timeout=1).stdout
        m = re.search(r"^Xft\.dpi:\s*([\d.]+)", out, re.M)
        if m:
            return float(m.group(1)) / 96
    except (OSError, subprocess.SubprocessError):
        pass
    value = _env_float("QT_SCALE_FACTOR")
    if value:
        return value
    return max(1.0, round(root.winfo_fpixels("1i") / 96, 2))


def _env_float(name):
    try:
        value = float(os.environ[name])
    except (KeyError, ValueError):
        return None
    return value if value > 0 else None


def create_root(title="", mode="light", accent=None, scale=None):
    """A DPI-aware Tk root with the theme applied. Returns (root, theme)."""
    enable_dpi_awareness()
    root = tk.Tk()
    root.title(title)
    theme = Theme(root, mode=mode, accent=accent, scale=scale)
    return root, theme
