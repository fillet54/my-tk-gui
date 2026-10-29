"""Declarative Tk views bound to reactive view models.

A view is XML. Attribute values in braces bind to the view model::

    <entry text="{form.description}" />            two-way
    <label text="Total: {total|money}" />          one-way template
    <button text="Add" command="{add}" />          runs a command, enables itself
    <group context="{selected}" enabled="{selected|exists}"> ... </group>

The view model is plain Python built from ``reactive`` (observable,
computed, command). Dependencies are tracked automatically, so the view
never needs to be told what changed.

Elements
    group, row, form      frames; children stack vertically / horizontally
    fields                two-column grid; each child's ``label`` becomes a caption
    any ttk widget name   label, entry, button, spinbox, combobox, treeview, ...
    register()ed names    custom components (switch and accentbutton are built in)

Special attributes
    id                    keep the widget in ``View.ids``
    context               data context for this element and its children (paths
                          become relative; ``{$root.x}`` still reaches the top
                          view model). Disabled while the context is None.
    enabled               bool binding; disabled cascades to children
    theme                 "light" or "dark" (usually bound)
    on_return, on_escape, on_delete, on_double_click, on_<Event>
                          run a command on that event
    side, fill, expand, anchor, padx, pady, ipadx, ipady
                          pack options, applied by the parent

Sizes
    Pixel sizes in a view (padding, padx/pady, spacing, length, wraplength,
    column widths) are written at 1x and multiplied by the screen scale.
    Fonts are in points and scale through ``tk scaling``. Character-based
    sizes (an entry's width, a treeview's height in rows) don't need to.
"""

import os
import re
import subprocess
import tkinter as tk
import tkinter.font as tkfont
from collections import ChainMap
from string import Template
from tkinter import ttk
from xml.etree.ElementTree import XML, Element

from reactive import BoundCommand, ObservableList, untracked, watch

HERE = os.path.dirname(os.path.abspath(__file__))

PACK_OPTIONS = {"side", "fill", "expand", "anchor", "padx", "pady", "ipadx", "ipady"}
META_OPTIONS = {"id", "context", "enabled", "theme", "label"}
CONTAINERS = {"group", "row", "form", "fields"}
# Attributes in pixels, written at 1x and scaled for the screen.
SCALED_OPTIONS = {"padding", "padx", "pady", "ipadx", "ipady", "spacing", "length", "wraplength"}

EVENTS = {
    "return": "<Return>",
    "escape": "<Escape>",
    "delete": "<Delete>",
    "double_click": "<Double-1>",
}


# --------------------------------------------------------------------------
# Converters: {path|name}
# --------------------------------------------------------------------------

class Converter:
    def __init__(self, to_view, to_model=None):
        self.to_view = to_view
        self.to_model = to_model     # None means one-way only


_converters = {}


def converter(name, to_view, to_model=None):
    """Register a converter usable as ``{path|name}`` in views."""
    _converters[name] = Converter(to_view, to_model)


def _parse_number(text):
    text = str(text).strip().replace(",", "").lstrip("$")
    if not text:
        raise ValueError("empty")
    return float(text)


converter("number", lambda v: "" if v is None else "%g" % v, _parse_number)
converter("int", lambda v: "" if v is None else str(int(v)), lambda s: int(_parse_number(s)))
converter("money", lambda v: "" if v is None else "${:,.2f}".format(v), _parse_number)
converter("percent", lambda v: "" if v is None else "{:.0%}".format(v))
converter("not", lambda v: not v, lambda v: not v)
converter("exists", lambda v: v is not None)
converter("upper", lambda v: "" if v is None else str(v).upper())


# --------------------------------------------------------------------------
# Binding expressions
# --------------------------------------------------------------------------

_TOKEN = re.compile(r"\{\{|\}\}|\{([^{}]*)\}")


class Binding:
    """One ``{path|conv|conv}`` expression, evaluated against a data context.

    ``context`` is a function returning the current context object. Reads
    go through observables, so calling ``value()`` inside a reaction tracks
    every step of the path.
    """

    def __init__(self, context, expression, root=None):
        path, *names = [part.strip() for part in expression.split("|")]
        self.expression = expression
        self.path = () if path in ("", ".") else tuple(path.split("."))
        if self.path[:1] == ("$root",):
            context, self.path = root, self.path[1:]
        self.context = context
        try:
            self.converters = [_converters[n] for n in names]
        except KeyError as e:
            raise ValueError("unknown converter %s in {%s}" % (e, expression)) from None

    @property
    def two_way(self):
        return bool(self.path) and all(c.to_model for c in self.converters)

    def model(self):
        return _resolve(self.context(), self.path)

    def to_view(self, value):
        for c in self.converters:
            value = c.to_view(value)
        return value

    def to_model(self, value):
        for c in reversed(self.converters):
            value = c.to_model(value)
        return value

    def value(self):
        return self.to_view(self.model())

    def assign(self, model_value):
        target = _resolve(self.context(), self.path[:-1])
        if target is not None:
            setattr(target, self.path[-1], model_value)


class TemplateBinding:
    """Literal text mixed with bindings: ``"Total: {total|money}"``. One-way."""

    two_way = False

    def __init__(self, parts):
        self.parts = parts

    def value(self):
        return "".join(p if isinstance(p, str) else _text(p.value()) for p in self.parts)

    model = value


def parse(value, context, root=None):
    """Return a Binding/TemplateBinding, or the literal string (braces unescaped)."""
    parts, pos = [], 0
    for m in _TOKEN.finditer(value):
        parts.append(value[pos:m.start()])
        token = m.group(0)
        parts.append(token[0] if token in ("{{", "}}") else Binding(context, m.group(1), root))
        pos = m.end()
    parts.append(value[pos:])
    parts = [p for p in parts if p != ""]
    bindings = [p for p in parts if not isinstance(p, str)]
    if not bindings:
        return "".join(parts)
    if len(parts) == 1:
        return parts[0]
    return TemplateBinding(parts)


def is_binding(value):
    return isinstance(value, (Binding, TemplateBinding))


def _resolve(obj, path):
    for name in path:
        if obj is None:
            return None
        obj = getattr(obj, name)
    return obj


def _text(value):
    return "" if value is None else str(value)


def _tk_value(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple, ObservableList)):
        return tuple(value)
    return value


def _materialize(value):
    # Read list contents inside the tracked getter, not in the callback.
    if isinstance(value, ObservableList):
        return tuple(value)
    return value


# --------------------------------------------------------------------------
# Custom components
# --------------------------------------------------------------------------

_components = {}


def register(name, template, **defaults):
    """Register ``<name ...>`` as an XML template.

    ``$attr`` in the template is replaced by the attribute given on the use
    site (or ``defaults``). Attributes the template doesn't mention are
    passed through to its root element, so bindings and layout just work::

        register("accentbutton", '<button style="Accent.TButton" />')
        <accentbutton text="Save" command="{save}" side="right" />
    """
    tree = XML(template)

    def expand(use):
        values = ChainMap(dict(use.attrib), defaults)
        used = set()

        class Recorder(dict):
            def __missing__(self, key):
                raise KeyError(key)

            def __getitem__(self, key):
                used.add(key)
                return values[key]

        mapping = Recorder()

        def copy(node):
            attrs = {k: Template(v).safe_substitute(mapping) for k, v in node.attrib.items()}
            out = Element(node.tag, attrs)
            out.extend(copy(child) for child in node)
            return out

        root = copy(tree)
        for k, v in use.attrib.items():
            if k not in used and k not in root.attrib:
                root.set(k, v)
        root.extend(use)
        return root

    _components[name] = expand


register("switch", '<checkbutton style="Switch.TCheckbutton" />')
register("accentbutton", '<button style="Accent.TButton" />')


# --------------------------------------------------------------------------
# Building views
# --------------------------------------------------------------------------

class View:
    def __init__(self, widget, ids):
        self.widget = widget
        self.ids = ids

    def destroy(self):
        self.widget.destroy()   # reactions are disposed via <Destroy>


def realize(master, xml, view_model, scheduler=None, scale=None):
    """Build ``xml`` under ``master``, bound to ``view_model``.

    ``scale`` defaults to the one ``create_root`` detected for the window.
    """
    if scale is None:
        scale = getattr(master._root(), "ui_scale", 1.0)
    root = lambda: view_model
    builder = _Builder(root, scheduler, scale)
    element = XML(xml) if isinstance(xml, str) else xml
    widget = builder.build(master, element, root, None)
    return View(widget, builder.ids)


class _Builder:
    def __init__(self, root, scheduler, scale=1.0):
        self.root = root
        self.scheduler = scheduler
        self.scale = scale
        self.ids = {}

    # -- reactions are owned by widgets and die with them ------------------

    def watch(self, widget, getter, callback):
        reaction = watch(getter, callback, scheduler=self.scheduler)
        owned = getattr(widget, "_reactions", None)
        if owned is None:
            owned = widget._reactions = []

            def on_destroy(event, widget=widget):
                if event.widget is widget:
                    for r in widget._reactions:
                        r.dispose()
                    widget._reactions.clear()

            widget.bind("<Destroy>", on_destroy, add="+")
        owned.append(reaction)
        return reaction

    # -- elements -----------------------------------------------------------

    def build(self, master, element, context, parent_enabled):
        while element.tag in _components:
            element = _components[element.tag](element)

        attrs = dict(element.attrib)
        if "context" in attrs:
            binding = parse(attrs.pop("context"), context, self.root)
            context = binding.value if is_binding(binding) else (lambda b=binding: b)
            # Nothing to show -> nothing to edit: disable the whole scope.
            has_context = lambda c=context: c() is not None
            parent_enabled = (has_context if parent_enabled is None else
                              lambda p=parent_enabled: p() and has_context())

        # Parse after context is set, so this element's bindings see it.
        attrs = {k: parse(v, context, self.root) for k, v in attrs.items()}
        for k in SCALED_OPTIONS & attrs.keys():
            if isinstance(attrs[k], str):
                attrs[k] = _px(attrs[k], self.scale)
        meta = {k: attrs.pop(k) for k in list(attrs) if k in META_OPTIONS}
        events = {k: attrs.pop(k) for k in list(attrs) if k.startswith("on_")}
        for k in PACK_OPTIONS:
            attrs.pop(k, None)

        enabled = self._enabled_getter(meta.get("enabled"), attrs.get("command"), parent_enabled)

        if element.tag in CONTAINERS:
            widget = self._container(master, element, attrs, meta, context, enabled)
        else:
            widget = self._widget(master, element, attrs, context)

        if "id" in meta:
            self.ids[meta["id"]] = widget
        if "theme" in meta:
            self._bind_theme(widget, meta["theme"])
        for name, binding in events.items():
            self._bind_event(widget, name[3:], binding)
        if enabled is not None and element.tag not in CONTAINERS:
            self.watch(widget, enabled, lambda on: widget.state(["!disabled" if on else "disabled"]))
        return widget

    def _enabled_getter(self, own, command, parent):
        getters = [g for g in (parent,) if g]
        if own is not None:
            getters.append(own.value if is_binding(own) else (lambda v=own: v not in ("0", "false", "")))
        if isinstance(command, Binding):
            getters.append(lambda: _can_execute(command.value()))
        if not getters:
            return None
        if len(getters) == 1:
            return lambda: bool(getters[0]())
        return lambda: all(g() for g in getters)

    def _container(self, master, element, attrs, meta, context, enabled):
        label = meta.get("label")
        spacing = attrs.pop("spacing", None)
        if spacing is None:
            spacing = _px("4", self.scale)
        if label is not None:
            widget = ttk.LabelFrame(master, **_literals(attrs))
            if is_binding(label):
                self._bind_option(widget, "text", label)
            else:
                widget.configure(text=label)
        else:
            widget = ttk.Frame(master, **_literals(attrs))
        self._bind_options(widget, attrs)

        if element.tag == "fields":
            self._layout_fields(widget, element, context, enabled, spacing)
            return widget

        horizontal = element.tag == "row"
        for child in element:
            child_widget = self.build(widget, child, context, enabled)
            defaults = ({"side": "left", "padx": (0, spacing)} if horizontal
                        else {"side": "top", "fill": "x", "pady": (0, spacing)})
            child_widget.pack(**_pack_options(child, defaults, self.scale))
        return widget

    def _layout_fields(self, frame, element, context, enabled, spacing):
        frame.columnconfigure(1, weight=1)
        for row, child in enumerate(element):
            caption = child.attrib.get("label")
            if caption is not None and child.tag not in CONTAINERS:
                child = _without(child, "label")
                label = ttk.Label(frame, text=caption)
                label.grid(row=row, column=0, sticky="w", padx=(0, spacing * 2), pady=(0, spacing))
                if enabled is not None:
                    self.watch(label, enabled, lambda on, l=label: l.state(["!disabled" if on else "disabled"]))
                column, span = 1, 1
            else:
                column, span = 0, 2
            widget = self.build(frame, child, context, enabled)
            widget.grid(row=row, column=column, columnspan=span, sticky="ew", pady=(0, spacing))

    def _widget(self, master, element, attrs, context):
        cls = _WIDGETS.get(element.tag) or getattr(ttk, element.tag.capitalize(), None)
        if cls is None:
            raise ValueError("unknown element <%s>" % element.tag)

        if cls is ttk.Treeview:
            return self._treeview(master, element, attrs)

        widget = cls(master, **_literals(attrs))
        kind = cls.__name__.lower()
        for name, binding in attrs.items():
            if not is_binding(binding):
                continue
            handler = _SPECIAL.get((kind, name)) or _SPECIAL.get(("*", name))
            if handler:
                handler(self, widget, binding)
            else:
                self._bind_option(widget, name, binding)
        return widget

    # -- property bindings ----------------------------------------------------

    def _bind_options(self, widget, attrs):
        for name, binding in attrs.items():
            if is_binding(binding):
                self._bind_option(widget, name, binding)

    def _bind_option(self, widget, name, binding):
        option = _option_name(name)
        self.watch(widget, lambda: _materialize(binding.value()),
                   lambda v: widget.configure(**{option: _tk_value(v)}))

    def _bind_variable(self, widget, binding, var, option, to_var=_text):
        """Two-way sync between a Tk variable and a binding."""
        widget.configure(**{option: var})
        pushing = [False]

        def push(model):
            if binding.two_way:
                # Don't rewrite text the user is typing if it already means
                # this value ("12." vs 12.0) -- it would move the cursor.
                try:
                    if binding.to_model(var.get()) == model:
                        return
                except (ValueError, TypeError, tk.TclError):
                    pass
            pushing[0] = True
            try:
                var.set(to_var(binding.to_view(model)))
            finally:
                pushing[0] = False
            _set_invalid(widget, False)

        def pull(*_):
            if pushing[0]:
                return
            try:
                value = binding.to_model(var.get())
            except (ValueError, TypeError, tk.TclError):
                _set_invalid(widget, True)
                return
            _set_invalid(widget, False)
            binding.assign(value)

        self.watch(widget, binding.model, push)
        if binding.two_way:
            var.trace_add("write", pull)
        widget._var = var   # keep it alive

    def _bind_text(self, widget, binding):
        self._bind_variable(widget, binding, tk.StringVar(widget), "textvariable")

    def _bind_checked(self, widget, binding):
        self._bind_variable(widget, binding, tk.BooleanVar(widget), "variable", to_var=bool)

    def _bind_radio(self, widget, binding):
        self._bind_variable(widget, binding, tk.StringVar(widget), "variable")

    def _bind_scale(self, widget, binding):
        self._bind_variable(widget, binding, tk.DoubleVar(widget), "variable",
                            to_var=lambda v: float(v or 0))

    def _bind_command(self, widget, binding):
        def run():
            with untracked():
                fn = binding.value()
            if _can_execute(fn):
                fn()
        widget.configure(command=run)

    def _bind_event(self, widget, name, binding):
        sequence = EVENTS.get(name, "<%s>" % name)

        def run(event):
            with untracked():
                fn = binding.value() if is_binding(binding) else None
            if _can_execute(fn):
                fn()
                return "break"

        widget.bind(sequence, run, add="+")

    def _bind_theme(self, widget, binding):
        apply = lambda name: widget.tk.call("set_theme", name or "light")
        if is_binding(binding):
            self.watch(widget, binding.value, apply)
        else:
            apply(binding)

    # -- treeview -------------------------------------------------------------

    def _treeview(self, master, element, attrs):
        columns = []
        for col in element.findall("column"):
            key = col.get("key")
            conv = col.get("format")
            columns.append((key, tuple(key.split(".")), _converters[conv] if conv else None))

        items, selection = attrs.pop("items", None), attrs.pop("selection", None)
        tree = ttk.Treeview(master, columns=[c[0] for c in columns], show="headings",
                            **_literals(attrs))
        self._bind_options(tree, attrs)
        for col, (key, _, _) in zip(element.findall("column"), columns):
            tree.heading(key, text=col.get("heading", key), anchor=col.get("anchor", "w"))
            tree.column(key, anchor=col.get("anchor", "w"),
                        width=_px(col.get("width", "120"), self.scale), stretch=col.get("stretch", "1") == "1")

        by_iid, iid_of = {}, {}

        def rows():
            # Tracked: the list, and every displayed field of every row.
            result = []
            for item in (items.value() or ()):
                values = []
                for _, path, conv in columns:
                    v = _resolve(item, path)
                    values.append(_text(conv.to_view(v) if conv else v))
                result.append((item, tuple(values)))
            return result

        def render(rows):
            keep = set()
            for index, (item, values) in enumerate(rows):
                iid = iid_of.get(id(item))
                if iid is None:
                    iid = tree.insert("", "end", values=values)
                    by_iid[iid], iid_of[id(item)] = item, iid
                else:
                    tree.item(iid, values=values)
                tree.move(iid, "", index)
                keep.add(iid)
            for iid in tree.get_children(""):
                if iid not in keep:
                    tree.delete(iid)
                    iid_of.pop(id(by_iid.pop(iid)), None)
            if selection is not None:
                with untracked():
                    select(selection.model())

        def select(item):
            iid = iid_of.get(id(item)) if item is not None else None
            current = tree.selection()
            if iid is None:
                if current:
                    tree.selection_set(())
            elif current != (iid,):
                tree.selection_set(iid)
                tree.see(iid)

        def on_select(event):
            chosen = tree.selection()
            selection.assign(by_iid.get(chosen[0]) if chosen else None)

        if items is not None:
            self.watch(tree, rows, render)
        if selection is not None:
            self.watch(tree, selection.model, select)
            tree.bind("<<TreeviewSelect>>", on_select, add="+")
        return tree


_WIDGETS = {
    "label": ttk.Label, "button": ttk.Button, "entry": ttk.Entry,
    "spinbox": ttk.Spinbox, "combobox": ttk.Combobox,
    "checkbutton": ttk.Checkbutton, "radiobutton": ttk.Radiobutton,
    "scale": ttk.Scale, "progressbar": ttk.Progressbar,
    "separator": ttk.Separator, "treeview": ttk.Treeview,
}

_SPECIAL = {
    ("entry", "text"): _Builder._bind_text,
    ("spinbox", "text"): _Builder._bind_text,
    ("combobox", "text"): _Builder._bind_text,
    ("checkbutton", "checked"): _Builder._bind_checked,
    ("radiobutton", "selected"): _Builder._bind_radio,
    ("scale", "value"): _Builder._bind_scale,
    ("*", "command"): _Builder._bind_command,
}

# Attributes that are bindings-only (no Tk option of that name).
_BINDING_ONLY = {"checked", "selected"}


def _can_execute(fn):
    if fn is None:
        return False
    if isinstance(fn, BoundCommand):
        return fn.can_execute
    return True


def _set_invalid(widget, invalid):
    try:
        widget.state(["invalid" if invalid else "!invalid"])
    except (AttributeError, tk.TclError):
        pass


def _option_name(name):
    return name + "_" if name in ("from",) else name


def _literals(attrs):
    """Options passed to the widget constructor (bound ones are wired later)."""
    return {_option_name(k): v for k, v in attrs.items()
            if not is_binding(v) and k not in _BINDING_ONLY}


def _pack_options(element, defaults, scale=1.0):
    options = dict(defaults)
    for k in PACK_OPTIONS:
        if k in element.attrib:
            value = element.attrib[k]
            options[k] = _px(value, scale) if k in SCALED_OPTIONS else value
    return options


_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def _px(value, scale):
    """Scale a 1x pixel size: "16" -> 32, "12 0" -> (24, 0) at 2x.

    Values with Tk units ("5p", "1c") are left alone; Tk already scales those.
    """
    parts = str(value).split()
    out = tuple(int(round(float(p) * scale)) if _NUMBER.match(p) else p for p in parts)
    return out[0] if len(out) == 1 else out


def _without(element, attr):
    copy = Element(element.tag, {k: v for k, v in element.attrib.items() if k != attr})
    copy.extend(element)
    return copy


# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------

def system_prefers_dark():
    """Best-effort OS dark mode check (Windows registry, GNOME/portal setting)."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except ImportError:
        pass
    except OSError:
        return False
    try:
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                             capture_output=True, text=True, timeout=1).stdout
        return "dark" in out
    except (OSError, subprocess.SubprocessError):
        return False


def detect_scale(root):
    """How many physical pixels one 1x pixel should take on this screen.

    ``MYTKGUI_SCALE`` overrides it. Otherwise: Windows asks the monitor;
    macOS is 1 (Tk handles Retina itself); X11 follows the same settings as
    GTK and Qt apps (GDK_SCALE, then Xft.dpi, then QT_SCALE_FACTOR, then the
    X server's DPI).
    """
    override = os.environ.get("MYTKGUI_SCALE")
    if override:
        return float(override)

    system = root.tk.call("tk", "windowingsystem")
    if system == "aqua":
        return 1.0
    if system == "win32":
        from hidpi import Get_HWND_DPI
        return Get_HWND_DPI(root.winfo_id())[2]

    gdk = _env_number("GDK_SCALE")
    if gdk:
        return gdk
    dpi = _xft_dpi()
    if dpi:
        return dpi / 96
    qt = _env_number("QT_SCALE_FACTOR")
    if qt:
        return qt
    return max(1.0, round(root.winfo_fpixels("1i") / 96, 2))


def _env_number(name):
    try:
        value = float(os.environ[name])
    except (KeyError, ValueError):
        return None
    return value if value > 0 else None


def _xft_dpi():
    try:
        out = subprocess.run(["xrdb", "-query"], capture_output=True, text=True, timeout=1).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"^Xft\.dpi:\s*([\d.]+)", out, re.M)
    return float(m.group(1)) if m else None


def _fonts_to_points(root):
    # Tk's default fonts on X11 are sized in pixels (negative sizes), which
    # ignore ``tk scaling``. Convert them to the same size in points.
    for name in tkfont.names(root):
        font = tkfont.nametofont(name, root=root)
        size = int(font.cget("size"))
        if size < 0:
            font.configure(size=max(1, round(-size * 72 / 96)))


def create_root(title="", scale=None):
    """A themed Tk root window, scaled for the screen it's on."""
    if os.name == "nt":
        try:   # must happen before Tk creates its first window
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    root.title(title)

    root.ui_scale = scale = scale or detect_scale(root)
    if root.tk.call("tk", "windowingsystem") != "aqua":
        root.tk.call("tk", "scaling", scale * 96 / 72)   # points -> pixels
        _fonts_to_points(root)

    # The theme ships 1x and 2x images; it scales its own borders to match.
    root.tk.eval("namespace eval ::sv {variable scale %d}" % (2 if scale >= 1.5 else 1))
    root.tk.call("source", os.path.join(HERE, "theme", "sun-valley.tcl"))
    root.tk.call("set_theme", "light")
    return root


def run(xml, view_model, title="", minsize=None):
    """Create a window, bind ``xml`` to ``view_model`` and run the event loop."""
    root = create_root(title)
    view = realize(root, xml, view_model)
    view.widget.pack(fill="both", expand=True)
    if minsize:
        root.minsize(*(round(v * root.ui_scale) for v in minsize))
    root.mainloop()
