"""Declarative Tk views bound to reactive view models.

A view is XML. Attribute values in braces bind to the view model (see
``bindings`` for the expression syntax)::

    <entry text="{form.description}" />            two-way
    <label text="Total: {total|money}" />          one-way template
    <button text="Add" command="{add}" />          runs a command, enables itself

Containers
    group, form, row      children stack vertically / horizontally (``spacing``)
    fields                two-column grid; each child's ``label`` becomes a caption
    grid                  ``columns="auto,*,2*,120"`` ``rows="auto,*"``; children
                          take ``row``, ``column``, ``rowspan``, ``columnspan``, ``sticky``
    scroll                a scrolling group (``horizontal="true"`` adds a
                          horizontal bar)
    split                 resizable panes (``orient``); children take ``weight``
    tabs                  ``<tab text="...">`` children, or ``items="{pages}"`` with a
                          ``<template header="{title}">``; ``selected`` is two-way
    items                 one view per item of ``items="{list}"`` from its
                          ``<template>``, or from the item's type (``template``);
                          ``orientation``, ``spacing``, ``columns``
    content               the view registered for the view model in ``content``
                          (WPF's ContentControl); ``cache="true"`` keeps recent views

Widgets
    label, entry, button, spinbox, combobox, checkbutton, radiobutton, scale,
    progressbar (``active="{busy}"`` animates it), separator, treeview,
    textarea (multi-line), menubutton, any
    other ttk widget name, and ``register()``ed components (switch, accentbutton)

Non-visual elements
    shortcut              ``key="Ctrl+S" command="{save}"`` (active while shown)
    menubar               the window's menu: ``<menu label>``, ``<item label command
                          shortcut>``, ``<check checked>``, ``<radio value selected>``,
                          ``<separator>``; labels and states may be bound
    contextmenu           the same children, shown on right-click of its parent
    style                 ``name="Danger.TButton" foreground=... map_foreground=
                          "disabled:#999"`` configures a ttk style
    resource              ``name="gap" value="12"``, used as ``{@gap}`` below it

Special attributes
    id                    keep the widget in ``View.ids``
    context               data context for this element and its children (paths
                          become relative; ``{$root.x}`` still reaches the top
                          view model). Disabled while the context is None.
    enabled, visible      bool bindings; both cascade to children
    command_parameter     passed to this element's command(s) and ``can_execute``
    on_return, on_escape, on_delete, on_double_click, on_<Event>
                          run a command on that event
    default, cancel       a button that Return / Escape press in its window
    focus                 "true" for initial focus, or a binding that focuses
                          the widget when it becomes true
    tab_index             keyboard (Tab) order across the view
    theme                 "light"/"dark" (bound) for a theme with modes
    side, fill, expand, anchor, padx, pady, ipadx, ipady
                          pack options, applied by the parent

Sizes
    Pixel sizes in a view (padding, padx/pady, spacing, length, wraplength,
    column widths, grid sizes) are written at 1x and multiplied by the screen
    scale. Fonts are in points and scale through ``tk scaling``.
"""

import re
from typing import Any, Callable
import sys
import tkinter as tk
from collections import ChainMap, OrderedDict
from string import Template
from tkinter import ttk
from xml.etree.ElementTree import Element
from xml.parsers import expat

from .bindings import (BindingError, TemplateBinding, _converters, _materialize, _resolve,
                       _text, _tk_value, is_binding, parse)
from .reactive import untracked, watch

__all__ = ["register", "template", "template_for", "realize", "realize_for", "View", "ViewError"]

PACK_OPTIONS = {"side", "fill", "expand", "anchor", "padx", "pady", "ipadx", "ipady"}
GRID_OPTIONS = {"row", "column", "rowspan", "columnspan", "sticky"}
META_OPTIONS = {"id", "context", "enabled", "visible", "theme", "label", "command_parameter",
                "focus", "tab_index", "default", "cancel", "weight", "__line__"}
STACKS = {"group", "row", "form"}
CONTAINERS = STACKS | {"fields", "grid", "scroll", "split", "tabs", "tab"}
NON_VISUAL = {"shortcut", "menubar", "contextmenu", "style", "resource"}
# Attributes in pixels, written at 1x and scaled for the screen.
SCALED_OPTIONS = {"padding", "padx", "pady", "ipadx", "ipady", "spacing", "length", "wraplength"}

EVENTS = {
    "return": "<Return>",
    "escape": "<Escape>",
    "delete": "<Delete>",
    "double_click": "<Double-1>",
}


class ViewError(ValueError):
    """A mistake in a view's XML, with the element and line."""


# --------------------------------------------------------------------------
# XML with line numbers (so errors can say where)
# --------------------------------------------------------------------------

def parse_xml(text: str) -> Element:
    """Parse a view; each element keeps its line in a ``__line__`` attribute."""
    stack, roots = [], []
    parser = expat.ParserCreate()

    def start(tag, attrs):
        attrs = dict(attrs)
        attrs["__line__"] = str(parser.CurrentLineNumber)
        element = Element(tag, attrs)
        (stack[-1].append(element) if stack else roots.append(element))
        stack.append(element)

    parser.StartElementHandler = start
    parser.EndElementHandler = lambda tag: stack.pop()
    try:
        parser.Parse(text, True)
    except expat.ExpatError as e:
        raise ViewError("bad view XML: %s" % e) from None
    return roots[0]


def _where(element):
    line = element.attrib.get("__line__")
    attrs = " ".join('%s="%s"' % (k, v) for k, v in element.attrib.items() if k != "__line__")
    shown = "<%s%s>" % (element.tag, (" " + attrs) if attrs else "")
    if len(shown) > 70:
        shown = shown[:67] + "...>"
    return "%s, view line %s" % (shown, line) if line else shown


# --------------------------------------------------------------------------
# Custom components
# --------------------------------------------------------------------------

_components = {}


def register(name: str, template: str, **defaults: str) -> None:
    """Register ``<name ...>`` as an XML template.

    ``$attr`` in the template is replaced by the attribute given on the use
    site (or ``defaults``). Attributes the template doesn't mention are
    passed through to its root element, so bindings and layout just work::

        register("accentbutton", '<button style="Accent.TButton" />')
        <accentbutton text="Save" command="{save}" side="right" />
    """
    tree = parse_xml(template)

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
            attrs = {k: Template(v).safe_substitute(mapping) for k, v in node.attrib.items()
                     if k != "__line__"}
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
# View templates: which view shows a view model (WPF's DataTemplate)
# --------------------------------------------------------------------------

_templates = {}


def template(view_model_type: type, xml: "str | Callable[[Any], str]") -> None:
    """Show ``xml`` for view models of ``view_model_type`` (or a subclass)
    wherever a ``<content>``, ``<items>`` or dialog displays one::

        gui.template(SettingsViewModel, SETTINGS_VIEW)
        <content content="{nav.current}" />

    ``xml`` may also be a function of the view model returning the XML.
    """
    _templates[view_model_type] = xml


def template_for(view_model: Any) -> "str | None":
    for cls in type(view_model).__mro__:
        if cls in _templates:
            xml = _templates[cls]
            return xml(view_model) if callable(xml) else xml
    return None


# --------------------------------------------------------------------------
# Building views
# --------------------------------------------------------------------------

class View:
    def __init__(self, widget, ids):
        self.widget = widget
        self.ids = ids

    def destroy(self):
        self.widget.destroy()   # reactions are disposed via <Destroy>


def realize(master: tk.Misc, xml: "str | Element", view_model: Any, scheduler: "Callable | None" = None,
            scale: "float | None" = None) -> View:
    """Build ``xml`` under ``master``, bound to ``view_model``.

    ``scale`` defaults to the one ``create_root`` detected for the window.
    """
    if scale is None:
        scale = getattr(master._root(), "ui_scale", 1.0)
    root = lambda: view_model
    builder = _Builder(root, scheduler, scale)
    element = parse_xml(xml) if isinstance(xml, str) else xml
    widget = builder.build(master, element, root, None)
    if widget is None:
        raise ViewError("a view's top element must be a widget or container: %s" % _where(element))
    builder.finish()
    return View(widget, builder.ids)


def realize_for(master: tk.Misc, view_model: Any, scheduler: "Callable | None" = None,
                scale: "float | None" = None) -> View:
    """The view registered (``template``) for ``view_model``'s type."""
    xml = template_for(view_model)
    if xml is None:
        label = ttk.Label(master, text="No view registered for %s (use gui.template)"
                          % type(view_model).__name__)
        return View(label, {})
    return realize(master, xml, view_model, scheduler=scheduler, scale=scale)


class _Builder:
    def __init__(self, root, scheduler, scale=1.0):
        self.root = root
        self.scheduler = scheduler
        self.scale = scale
        self.ids = {}
        self.resources = {}
        self.tab_order = []         # [(index, widget)]
        self.initial_focus = None

    def finish(self):
        if self.tab_order:
            _chain_tab_order([w for _, w in sorted(self.tab_order, key=lambda p: p[0])])
        if self.initial_focus is not None:
            widget = self.initial_focus
            widget.after_idle(lambda: widget.winfo_exists() and widget.focus_set())

    # -- reactions are owned by widgets and die with them ------------------

    def watch(self, widget, getter, callback):
        reaction = watch(getter, callback, scheduler=self.scheduler)
        _own(widget, reaction.dispose)
        return reaction

    def once(self, getter, callback):
        with untracked():
            callback(getter())

    # -- elements -----------------------------------------------------------

    def build(self, master, element, context, parent_enabled, parent_visible=None):
        """Build one element; returns its widget, or None for non-visual ones."""
        while element.tag in _components:
            line = element.attrib.get("__line__")
            element = _components[element.tag](element)
            if line:
                element.set("__line__", line)
        where = _where(element)

        if element.tag == "resource":
            self.resources[element.get("name")] = element.get("value", "")
            return None
        if element.tag == "style":
            self._style(master, element)
            return None

        attrs = dict(element.attrib)
        attrs.pop("__line__", None)
        if "context" in attrs:
            binding = self._parse(attrs.pop("context"), context, where)
            context = binding.value if is_binding(binding) else (lambda b=binding: b)
            # Nothing to show -> nothing to edit: disable the whole scope.
            has_context = lambda c=context: c() is not None
            parent_enabled = (has_context if parent_enabled is None else
                              lambda p=parent_enabled: p() and has_context())

        if element.tag in NON_VISUAL:
            return self._non_visual(master, element, attrs, context, where)

        # Parse after context is set, so this element's bindings see it.
        attrs = {k: self._parse(v, context, where) for k, v in attrs.items()}
        for k in SCALED_OPTIONS & attrs.keys():
            if isinstance(attrs[k], str):
                attrs[k] = _px(attrs[k], self.scale)
        meta = {k: attrs.pop(k) for k in list(attrs) if k in META_OPTIONS}
        events = {k: attrs.pop(k) for k in list(attrs) if k.startswith("on_")}
        for k in PACK_OPTIONS | GRID_OPTIONS:
            attrs.pop(k, None)

        parameter = meta.get("command_parameter")
        parameter = (parameter.value if is_binding(parameter) else (lambda p=parameter: p))
        enabled = self._enabled_getter(meta.get("enabled"), attrs.get("command"), parameter, parent_enabled)

        tag = element.tag
        try:
            if tag in CONTAINERS:
                widget = self._container(master, element, attrs, meta, context, enabled)
            elif tag == "content":
                widget = self._content(master, attrs)
            elif tag == "items":
                widget = self._items(master, element, attrs, context, enabled)
            elif tag == "textarea":
                widget = self._textarea(master, attrs)
            else:
                widget = self._widget(master, element, attrs, context, parameter)
        except (tk.TclError, TypeError) as e:
            raise ViewError("%s: %s" % (where, e)) from None

        if "id" in meta:
            self.ids[meta["id"]] = widget
        if "theme" in meta:
            self._bind_theme(widget, meta["theme"])
        for name, binding in events.items():
            self._bind_event(widget, name[3:], binding, parameter)
        if enabled is not None and tag not in CONTAINERS and tag not in ("content", "items"):
            self.watch(widget, enabled, lambda on: _set_enabled(widget, on))
        if "visible" in meta:
            widget._mytk_visible = _flag_getter(meta["visible"])
        self._focus_options(widget, meta)
        self._button_roles(widget, meta, tag)

        for child in element:
            if child.tag == "contextmenu":
                self._context_menu(widget, child, context, enabled)
        return widget

    def _parse(self, value, context, where):
        return parse(value, context, self.root, where, self.resources)

    def _enabled_getter(self, own, command, parameter, parent):
        getters = [g for g in (parent,) if g]
        if own is not None:
            getters.append(_flag_getter(own))
        if is_binding(command) and not isinstance(command, TemplateBinding):
            getters.append(lambda: _can_execute(command.value(), parameter()))
        if not getters:
            return None
        if len(getters) == 1:
            return lambda: bool(getters[0]())
        return lambda: all(g() for g in getters)

    # -- containers ----------------------------------------------------------

    def _container(self, master, element, attrs, meta, context, enabled):
        tag = element.tag
        spacing = attrs.pop("spacing", None)
        if spacing is None:
            spacing = _px("4", self.scale)
        if tag == "scroll":
            return self._scroll(master, element, attrs, context, enabled, spacing)
        if tag == "split":
            return self._split(master, element, attrs, context, enabled)
        if tag == "tabs":
            return self._tabs(master, element, attrs, context, enabled)

        for layout_only in ("columns", "rows", "text", "value"):
            attrs.pop(layout_only, None)        # read by the grid / tabs from the element
        label = meta.get("label")
        if label is not None:
            widget = ttk.LabelFrame(master, **_literals(attrs))
            if is_binding(label):
                self._bind_option(widget, "text", label)
            else:
                widget.configure(text=label)
        else:
            widget = ttk.Frame(master, **_literals(attrs))
        self._bind_options(widget, attrs)

        if tag == "fields":
            self._layout_fields(widget, element, context, enabled, spacing)
        elif tag == "grid":
            self._layout_grid(widget, element, attrs, context, enabled, spacing)
        else:
            self._layout_stack(widget, element, context, enabled, spacing, horizontal=(tag == "row"))
        return widget

    def _children(self, element):
        return [c for c in element if c.tag not in ("contextmenu", "template")]

    def _layout_stack(self, frame, element, context, enabled, spacing, horizontal=False):
        for child in self._children(element):
            widget = self.build(frame, child, context, enabled)
            if widget is None:
                continue
            defaults = ({"side": "left", "padx": (0, spacing)} if horizontal
                        else {"side": "top", "fill": "x", "pady": (0, spacing)})
            self._place(widget, "pack", _pack_options(child, defaults, self.scale))

    def _layout_fields(self, frame, element, context, enabled, spacing):
        frame.columnconfigure(1, weight=1)
        row = 0
        for child in self._children(element):
            caption = child.attrib.get("label")
            label = None
            if caption is not None and child.tag not in CONTAINERS:
                child = _without(child, "label")
                label = ttk.Label(frame, text=caption)
                if enabled is not None:
                    self.watch(label, enabled, lambda on, l=label: _set_enabled(l, on))
                column, span = 1, 1
            else:
                column, span = 0, 2
            widget = self.build(frame, child, context, enabled)
            if widget is None:
                if label is not None:
                    label.destroy()
                continue
            if label is not None:
                self._place(label, "grid", dict(row=row, column=0, sticky="w",
                                                padx=(0, spacing * 2), pady=(0, spacing)))
                widget._mytk_companions = [label]
            self._place(widget, "grid", dict(row=row, column=column, columnspan=span, sticky="ew",
                                             pady=(0, spacing)))
            row += 1

    def _layout_grid(self, frame, element, attrs, context, enabled, spacing):
        for axis, spec in (("column", element.get("columns", "")), ("row", element.get("rows", ""))):
            configure = frame.columnconfigure if axis == "column" else frame.rowconfigure
            for index, size in enumerate(s.strip() for s in spec.split(",") if s.strip()):
                configure(index, **_grid_size(size, self.scale))
        for child in self._children(element):
            widget = self.build(frame, child, context, enabled)
            if widget is None:
                continue
            options = dict(row=int(child.get("row", 0)), column=int(child.get("column", 0)),
                           rowspan=int(child.get("rowspan", 1)), columnspan=int(child.get("columnspan", 1)),
                           sticky=child.get("sticky", "nsew"))
            pad = {k: _px(child.get(k), self.scale) for k in ("padx", "pady", "ipadx", "ipady") if child.get(k)}
            options.setdefault("padx", (0, spacing))
            options.setdefault("pady", (0, spacing))
            options.update(pad)
            self._place(widget, "grid", options)

    def _scroll(self, master, element, attrs, context, enabled, spacing):
        horizontal = str(attrs.pop("horizontal", "false")).lower() in ("1", "true", "yes")
        outer = ttk.Frame(master, **_literals(attrs))
        canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        inner = ttk.Frame(canvas)
        window = canvas.create_window(0, 0, window=inner, anchor="nw")
        vbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        if horizontal:
            hbar = ttk.Scrollbar(outer, orient="horizontal", command=canvas.xview)
            canvas.configure(xscrollcommand=hbar.set)
            hbar.pack(side="bottom", fill="x")
        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        def resize(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            if not horizontal:
                canvas.itemconfigure(window, width=canvas.winfo_width())

        inner.bind("<Configure>", resize, add="+")
        canvas.bind("<Configure>", resize, add="+")

        def background(*_):
            style = str(inner.cget("style")) or "TFrame"
            color = ttk.Style(canvas).lookup(style, "background") or ttk.Style(canvas).lookup(".", "background")
            if color:
                canvas.configure(background=color)

        inner.bind("<Map>", lambda e: inner.after_idle(background), add="+")
        canvas.bind("<<ThemeChanged>>", background, add="+")
        theme = getattr(master._root(), "ui_theme", None)
        if hasattr(theme, "on_change"):
            listener = theme.on_change(lambda t: background())
            if hasattr(theme, "remove_listener"):
                _own(outer, lambda: theme.remove_listener(listener))

        def wheel(event):
            if event.num == 4 or getattr(event, "delta", 0) > 0:
                step = -1
            else:
                step = 1
            canvas.yview_scroll(step * (1 if getattr(event, "delta", 0) in (0, 120, -120) else 1), "units")
            return "break"

        def enter(_):
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.bind_all(sequence, wheel)

        def leave(_):
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.unbind_all(sequence)

        outer.bind("<Enter>", enter, add="+")
        outer.bind("<Leave>", leave, add="+")
        self._layout_stack(inner, element, context, enabled, spacing)
        outer.content = inner
        return outer

    def _split(self, master, element, attrs, context, enabled):
        orient = attrs.pop("orient", "horizontal")
        paned = ttk.Panedwindow(master, orient=orient, **_literals(attrs))
        for child in self._children(element):
            widget = self.build(paned, child, context, enabled)
            if widget is not None:
                paned.add(widget, weight=int(child.get("weight", 1)))
        return paned

    def _tabs(self, master, element, attrs, context, enabled):
        items = attrs.pop("items", None)
        selected = attrs.pop("selected", None)
        notebook = ttk.Notebook(master, **_literals(attrs))
        values = []                           # tab index -> value (static) / item (dynamic)

        def select(value):
            for index, candidate in enumerate(values):
                if candidate is value or candidate == value:
                    if notebook.index("current") != index:
                        notebook.select(index)
                    return

        if items is None:
            for index, child in enumerate(c for c in element if c.tag == "tab"):
                frame = self.build(notebook, child, context, enabled)
                value = child.get("value", str(index))
                title = child.get("text", value)
                notebook.add(frame, text="")
                binding = self._parse(title, context, _where(child))
                if is_binding(binding):
                    self.watch(frame, binding.value, lambda t, f=frame: notebook.tab(f, text=_text(t)))
                else:
                    notebook.tab(frame, text=binding)
                values.append(value)
                if getattr(frame, "_mytk_visible", None):
                    self.watch(frame, frame._mytk_visible,
                               lambda on, f=frame: notebook.tab(f, state="normal" if on else "hidden"))
        else:
            template = next((c for c in element if c.tag == "template"), None)
            pages = OrderedDict()                     # id(item) -> (item, frame)

            def render(current):
                current = list(current)
                keep = {id(i) for i in current}
                for key in [k for k in pages if k not in keep]:
                    pages.pop(key)[1].destroy()
                for index, item in enumerate(current):
                    entry = pages.get(id(item))
                    if entry is None:
                        frame = self._item_view(notebook, template, item, enabled)
                        pages[id(item)] = (item, frame)
                        notebook.add(frame, text="")
                        header = template.get("header") if template is not None else None
                        if header:
                            binding = self._parse(header, lambda i=item: i, _where(template))
                            if is_binding(binding):
                                self.watch(frame, binding.value,
                                           lambda t, f=frame: notebook.tab(f, text=_text(t)))
                            else:
                                notebook.tab(frame, text=binding)
                        else:
                            notebook.tab(frame, text=_text(getattr(item, "title", item)))
                    notebook.insert(index, pages[id(item)][1])
                values[:] = current
                if selected is not None:
                    with untracked():
                        select(selected.model())

            self.watch(notebook, lambda: _materialize(items.value() or ()), render)

        if selected is not None:
            self.watch(notebook, selected.model, select)

            def changed(event):
                if event.widget is not notebook or not notebook.tabs():
                    return
                index = notebook.index("current")
                if index < len(values) and selected.two_way:
                    value = values[index]
                    with untracked():
                        if selected.model() is not value:
                            selected.assign(value)

            notebook.bind("<<NotebookTabChanged>>", changed, add="+")
        return notebook

    def _item_view(self, master, template, item, enabled):
        """One item's view: from ``<template>``, or from the item's type."""
        if template is None:
            return realize_for(master, item, scheduler=self.scheduler, scale=self.scale).widget
        children = [c for c in template if c.tag != "contextmenu"]
        if len(children) == 1:
            widget = self.build(master, children[0], lambda i=item: i, enabled)
        else:
            body = Element("group", {k: v for k, v in template.attrib.items() if k != "header"})
            body.extend(children)
            widget = self.build(master, body, lambda i=item: i, enabled)
        return widget

    def _place(self, widget, manager, options):
        """Lay out ``widget``; if it has a visible binding, show/hide it in place."""
        widget._mytk_layout = (manager, options)
        master = widget.master
        order = getattr(master, "_mytk_order", None)
        if order is None:
            order = master._mytk_order = []
        order.append(widget)
        visible = getattr(widget, "_mytk_visible", None)
        if visible is None:
            _show(widget)
        else:
            self.watch(widget, visible, lambda on: _show(widget) if on else _hide(widget))

    # -- items control --------------------------------------------------------

    def _items(self, master, element, attrs, context, enabled):
        items = attrs.pop("items", None)
        horizontal = str(attrs.pop("orientation", "vertical")).startswith("h")
        columns = int(attrs.pop("columns", 0) or 0)
        spacing = attrs.pop("spacing", None)
        spacing = _px("4", self.scale) if spacing is None else spacing
        frame = ttk.Frame(master, **_literals(attrs))
        self._bind_options(frame, attrs)
        template = next((c for c in element if c.tag == "template"), None)
        views = OrderedDict()            # id(item) -> (item, widget)
        for c in range(columns):
            frame.columnconfigure(c, weight=1, uniform="items")

        def render(current):
            keep = {id(i) for i in current}
            for key in [k for k in views if k not in keep]:
                views.pop(key)[1].destroy()
            for index, item in enumerate(current):
                if id(item) not in views:
                    views[id(item)] = (item, self._item_view(frame, template, item, enabled))
            # Lay out in list order (cheap: geometry only).
            for index, item in enumerate(current):
                widget = views[id(item)][1]
                if columns:
                    widget.grid(row=index // columns, column=index % columns, sticky="nsew",
                                padx=(0, spacing), pady=(0, spacing))
                else:
                    widget.pack_forget()
            if not columns:
                for item in current:
                    widget = views[id(item)][1]
                    if horizontal:
                        widget.pack(side="left", fill="y", padx=(0, spacing))
                    else:
                        widget.pack(side="top", fill="x", pady=(0, spacing))

        if items is not None:
            self.watch(frame, lambda: list(_materialize(items.value() or ())), render)
        return frame

    # -- content host (views swapped by binding) ------------------------------

    def _content(self, master, attrs):
        binding = attrs.pop("content", None)
        limit = _cache_limit(attrs.pop("cache", "false"))
        frame = ttk.Frame(master, **_literals(attrs))
        self._bind_options(frame, attrs)
        shown = {"vm": None, "view": None}
        cached = OrderedDict()      # id(view model) -> (view model, View), oldest first

        def show(vm):
            if vm is shown["vm"] and shown["view"] is not None:
                return
            old = shown["view"]
            if old is not None:
                if limit:
                    old.widget.pack_forget()
                else:
                    old.destroy()
            shown["vm"], shown["view"] = vm, None
            if vm is None:
                return
            entry = cached.pop(id(vm), None)
            view = entry[1] if entry and entry[0] is vm else None
            if view is None:
                view = realize_for(frame, vm, scheduler=self.scheduler, scale=self.scale)
            if limit:
                cached[id(vm)] = (vm, view)
                while len(cached) > limit:
                    _, (_, oldest) = cached.popitem(last=False)
                    oldest.destroy()
            view.widget.pack(fill="both", expand=True)
            shown["view"] = view

        if is_binding(binding):
            self.watch(frame, binding.value, show)
        elif binding is not None:
            raise ViewError("<content> needs a binding: content=\"{...}\"")
        return frame

    # -- widgets -----------------------------------------------------------------

    def _widget(self, master, element, attrs, context, parameter=lambda: None):
        cls = _WIDGETS.get(element.tag) or getattr(ttk, element.tag.capitalize(), None)
        if cls is None:
            raise ViewError("unknown element %s" % _where(element))

        if cls is ttk.Treeview:
            return self._treeview(master, element, attrs)

        widget = cls(master, **_literals(attrs))
        kind = cls.__name__.lower()
        for name, binding in attrs.items():
            if not is_binding(binding):
                continue
            handler = _SPECIAL.get((kind, name)) or _SPECIAL.get(("*", name))
            if name == "command":
                self._bind_command(widget, binding, parameter)
            elif handler:
                handler(self, widget, binding)
            else:
                self._bind_option(widget, name, binding)
        return widget

    def _textarea(self, master, attrs):
        binding = attrs.pop("text", None)
        options = {"height": 4, "wrap": "word", "undo": True}
        options.update(_literals(attrs))
        widget = tk.Text(master, **options)
        self._bind_options(widget, attrs)
        if binding is None:
            return widget
        if not is_binding(binding):
            widget.insert("1.0", binding)
            return widget
        pushing = [False]

        def push(value):
            text = _text(binding.to_view(value))
            if widget.get("1.0", "end-1c") == text:
                return
            pushing[0] = True
            try:
                widget.delete("1.0", "end")
                widget.insert("1.0", text)
                widget.edit_modified(False)
            finally:
                pushing[0] = False

        def pull(*_):
            if pushing[0] or not widget.edit_modified():
                return
            widget.edit_modified(False)
            binding.assign(widget.get("1.0", "end-1c"))
            _touch(binding)

        if binding.one_time:
            self.once(binding.model, push)
        else:
            self.watch(widget, binding.model, push)
        if binding.two_way:
            if binding.trigger == "focus":
                widget.bind("<FocusOut>", pull, add="+")
            else:
                widget.bind("<<Modified>>", self._debounced(widget, pull, binding.delay), add="+")
        return widget

    # -- property bindings ----------------------------------------------------

    def _bind_options(self, widget, attrs):
        for name, binding in attrs.items():
            if is_binding(binding):
                self._bind_option(widget, name, binding)

    def _bind_option(self, widget, name, binding):
        option = _option_name(name)
        apply = lambda value: widget.configure(**{option: _tk_value(value)})
        getter = lambda: _materialize(binding.value())
        if getattr(binding, "one_time", False):
            self.once(getter, apply)
        else:
            self.watch(widget, getter, apply)

    def _bind_variable(self, widget, binding, var, option, to_var=_text):
        """Sync between a Tk variable and a binding (two-way unless the binding says not)."""
        widget.configure(**{option: var})
        pushing = [False]
        invalid = widget._mytk_invalid = {"convert": False, "rule": False}

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
            invalid["convert"] = False
            _show_invalid(widget)

        def pull(*_):
            if pushing[0]:
                return
            try:
                value = binding.to_model(var.get())
            except (ValueError, TypeError, tk.TclError):
                invalid["convert"] = True
                _show_invalid(widget)
                return
            invalid["convert"] = False
            _show_invalid(widget)
            binding.assign(value)
            _touch(binding)

        if binding.one_time:
            self.once(binding.model, push)
        else:
            self.watch(widget, binding.model, push)
        if binding.two_way:
            if binding.trigger == "focus":
                widget.bind("<FocusOut>", pull, add="+")
                widget.bind("<Return>", pull, add="+")
            else:
                _trace(widget, var, self._debounced(widget, pull, binding.delay))

            # Validation: the field's rule error (Validatable.error_for).
            def rule_error():
                target, name = binding.target()
                check = getattr(target, "error_for", None)
                return bool(check(name)) if check is not None else False

            def show_rule(bad):
                invalid["rule"] = bad
                _show_invalid(widget)

            self.watch(widget, rule_error, show_rule)
        widget._var = var   # keep it alive

    def _debounced(self, widget, fn, delay):
        if not delay:
            return fn
        pending = [None]

        def later(*args):
            if pending[0] is not None:
                widget.after_cancel(pending[0])
            pending[0] = widget.after(delay, lambda: (pending.__setitem__(0, None), fn()))
        return later

    def _bind_text(self, widget, binding):
        self._bind_variable(widget, binding, tk.StringVar(widget), "textvariable")

    def _bind_checked(self, widget, binding):
        self._bind_variable(widget, binding, tk.BooleanVar(widget), "variable", to_var=bool)

    def _bind_radio(self, widget, binding):
        self._bind_variable(widget, binding, tk.StringVar(widget), "variable")

    def _bind_scale(self, widget, binding):
        self._bind_variable(widget, binding, tk.DoubleVar(widget), "variable",
                            to_var=lambda v: float(v or 0))

    def _bind_active(self, widget, binding):
        """``active`` on a progressbar: animate (indeterminate mode) while true."""
        self.watch(widget, lambda: bool(binding.value()),
                   lambda on: widget.start(15) if on else widget.stop())

    def _bind_command(self, widget, binding, parameter=lambda: None):
        def run():
            with untracked():
                fn, arg = binding.value(), parameter()
            if _can_execute(fn, arg):
                _execute(fn, arg)
        widget.configure(command=run)

    def _bind_event(self, widget, name, binding, parameter=lambda: None):
        sequence = EVENTS.get(name, "<%s>" % name)

        def run(event):
            with untracked():
                fn = binding.value() if is_binding(binding) else None
                arg = parameter()
            if _can_execute(fn, arg):
                _execute(fn, arg)
                return "break"

        widget.bind(sequence, run, add="+")

    def _bind_theme(self, widget, binding):
        # Only a theme object passed to create_root() has light/dark modes;
        # the platform's own ttk theme follows the OS, so this does nothing.
        theme = getattr(widget._root(), "ui_theme", None)
        if not hasattr(theme, "set_mode"):
            return
        apply = lambda name: theme.set_mode(name or "light")
        if is_binding(binding):
            self.watch(widget, binding.value, apply)
        else:
            apply(binding)

    # -- focus, tab order, default/cancel buttons -----------------------------

    def _focus_options(self, widget, meta):
        focus = meta.get("focus")
        if is_binding(focus):
            self.watch(widget, lambda: bool(focus.value()),
                       lambda on: on and widget.after_idle(lambda: widget.winfo_exists() and widget.focus_set()))
        elif focus is not None and _truthy(focus) and self.initial_focus is None:
            self.initial_focus = widget
        if "tab_index" in meta:
            self.tab_order.append((float(meta["tab_index"]), widget))

    def _button_roles(self, widget, meta, tag):
        for role, key in (("default", "Return"), ("cancel", "Escape")):
            if role in meta and _truthy(meta[role]):
                if role == "default":
                    try:
                        widget.configure(default="active")
                    except tk.TclError:
                        pass
                _window_keys(widget).add("<%s>" % key, widget, lambda w=widget: _invoke(w),
                                         skip_in_text=(key == "Return"))

    # -- non-visual elements ----------------------------------------------------

    def _non_visual(self, master, element, attrs, context, where):
        tag = element.tag
        if tag == "shortcut":
            attrs = {k: self._parse(v, context, where) for k, v in attrs.items()}
            key = attrs.get("key")
            if not key:
                raise ViewError("<shortcut> needs key=\"Ctrl+S\" (%s)" % where)
            parameter = attrs.get("command_parameter")
            parameter = parameter.value if is_binding(parameter) else (lambda p=parameter: p)
            command = attrs.get("command")
            self._add_shortcut(master, key, command, parameter)
        elif tag == "menubar":
            window = master.winfo_toplevel()
            menu = tk.Menu(window, tearoff=0)
            self._fill_menu(menu, element, context, None, master)
            window.configure(menu=menu)
            _own(master, lambda: window.winfo_exists() and window.configure(menu=""))
        elif tag == "contextmenu":
            self._context_menu(master, element, context, None)
        return None

    def _add_shortcut(self, owner, key, command, parameter):
        def run():
            with untracked():
                fn = command.value() if is_binding(command) else None
                arg = parameter()
            if _can_execute(fn, arg):
                _execute(fn, arg)
                return True
            return False
        _window_keys(owner).add(key_sequence(key), owner, run)

    def _fill_menu(self, menu, element, context, enabled, owner):
        for child in element:
            where = _where(child)
            attrs = {k: self._parse(v, context, where) for k, v in child.attrib.items() if k != "__line__"}
            index = None
            if child.tag == "separator":
                menu.add_separator()
                continue
            label = attrs.get("label", "")
            if child.tag == "menu":
                sub = tk.Menu(menu, tearoff=0)
                self._fill_menu(sub, child, context, enabled, owner)
                menu.add_cascade(label="", menu=sub)
            elif child.tag == "item":
                command = attrs.get("command")
                parameter = attrs.get("command_parameter")
                parameter = parameter.value if is_binding(parameter) else (lambda p=parameter: p)

                def run(command=command, parameter=parameter):
                    with untracked():
                        fn = command.value() if is_binding(command) else None
                        arg = parameter()
                    if _can_execute(fn, arg):
                        _execute(fn, arg)
                menu.add_command(label="", command=run)
                shortcut = attrs.get("shortcut")
                if shortcut:
                    menu.entryconfigure(menu.index("end"), accelerator=accelerator_text(shortcut))
                    self._add_shortcut(owner, shortcut, command, parameter)
                own_enabled = self._enabled_getter(attrs.get("enabled"), command, parameter, enabled)
                if own_enabled is not None:
                    i = menu.index("end")
                    self.watch(menu, own_enabled,
                               lambda on, i=i: menu.entryconfigure(i, state="normal" if on else "disabled"))
            elif child.tag in ("check", "radio"):
                var = tk.BooleanVar(menu) if child.tag == "check" else tk.StringVar(menu)
                binding = attrs.get("checked" if child.tag == "check" else "selected")
                if child.tag == "check":
                    menu.add_checkbutton(label="", variable=var)
                else:
                    menu.add_radiobutton(label="", variable=var, value=attrs.get("value", label))
                if is_binding(binding):
                    _sync_var(self, menu, var, binding)
                menu._vars = getattr(menu, "_vars", []) + [var]
            else:
                raise ViewError("unknown menu element %s" % where)
            index = menu.index("end")
            if is_binding(label):
                self.watch(menu, label.value, lambda t, i=index: menu.entryconfigure(i, label=_text(t)))
            else:
                menu.entryconfigure(index, label=label)

    def _context_menu(self, widget, element, context, enabled):
        menu = tk.Menu(widget, tearoff=0)
        self._fill_menu(menu, element, context, enabled, widget)

        def popup(event):
            menu.tk_popup(event.x_root, event.y_root)
            return "break"

        def attach(w):
            for sequence in ("<Button-3>",) + (("<Button-2>",) if w.tk.call("tk", "windowingsystem") == "aqua" else ()):
                w.bind(sequence, popup, add="+")
        attach(widget)
        # Children built so far (a container's content) get it too.
        widget.after_idle(lambda: widget.winfo_exists() and [attach(w) for w in _descendants(widget)])

    def _style(self, master, element):
        attrs = {k: v for k, v in element.attrib.items() if k != "__line__"}
        name = attrs.pop("name", None)
        if not name:
            raise ViewError("<style> needs a name (%s)" % _where(element))
        style = ttk.Style(master)
        options, maps = {}, {}
        for key, value in attrs.items():
            value = self._parse(value, lambda: None, _where(element))
            if key.startswith("map_"):
                maps[key[4:]] = [tuple(part.strip().split(":", 1)[0].split()) + (part.strip().split(":", 1)[1],)
                                 for part in str(value).split(",") if ":" in part]
            else:
                options[key] = _px(value, self.scale) if key in SCALED_OPTIONS else value
        if options:
            style.configure(name, **options)
        if maps:
            style.map(name, **maps)

    # -- treeview -------------------------------------------------------------

    def _treeview(self, master, element, attrs):
        columns = []
        for col in element.findall("column"):
            key = col.get("key")
            conv = col.get("format")
            columns.append((key, tuple(key.split(".")), _converters[conv] if conv else None))

        items, selection = attrs.pop("items", None), attrs.pop("selection", None)
        sort = attrs.pop("sort", None)
        tree = ttk.Treeview(master, columns=[c[0] for c in columns], show="headings",
                            **_literals(attrs))
        self._bind_options(tree, attrs)
        headings = {}
        for col, (key, _, _) in zip(element.findall("column"), columns):
            heading = col.get("heading", key)
            headings[key] = (heading, col.get("sort", key))
            tree.heading(key, text=heading, anchor=col.get("anchor", "w"))
            tree.column(key, anchor=col.get("anchor", "w"),
                        width=_px(col.get("width", "120"), self.scale), stretch=col.get("stretch", "1") == "1")

        if sort is not None:
            # A CollectionView: clicking a heading sorts by that column.
            def sort_by(key):
                view = sort.value()
                if view is not None:
                    _execute(view.sort_by, key)
            for key, (_, sort_key) in headings.items():
                tree.heading(key, command=lambda k=sort_key: sort_by(k))

            def arrows():
                view = sort.value()
                return (getattr(view, "sort_key", None), getattr(view, "descending", False)) if view else (None, False)

            def show_arrows(state):
                current, descending = state
                for key, (heading, sort_key) in headings.items():
                    mark = (" ▼" if descending else " ▲") if sort_key == current else ""
                    tree.heading(key, text=heading + mark)
            self.watch(tree, arrows, show_arrows)

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
    "separator": ttk.Separator, "treeview": ttk.Treeview, "menubutton": ttk.Menubutton,
}

_SPECIAL = {
    ("entry", "text"): _Builder._bind_text,
    ("spinbox", "text"): _Builder._bind_text,
    ("combobox", "text"): _Builder._bind_text,
    ("checkbutton", "checked"): _Builder._bind_checked,
    ("radiobutton", "selected"): _Builder._bind_radio,
    ("scale", "value"): _Builder._bind_scale,
    ("progressbar", "active"): _Builder._bind_active,
}

# Attributes that are bindings-only (no Tk option of that name).
_BINDING_ONLY = {"checked", "selected", "active"}


# --------------------------------------------------------------------------
# Keyboard: shortcuts and default/cancel buttons, per window
# --------------------------------------------------------------------------

class _WindowKeys:
    """Key handlers for one toplevel. The most recently added handler whose
    owner is on screen and that can run wins."""

    def __init__(self, window):
        self.window = window
        self.handlers = {}          # sequence -> [(owner, run, skip_in_text)]

    def add(self, sequence, owner, run, skip_in_text=False):
        if sequence not in self.handlers:
            self.handlers[sequence] = []
            self.window.bind(sequence, lambda e, s=sequence: self._fire(s, e), add="+")
        entry = (owner, run, skip_in_text)
        self.handlers[sequence].append(entry)
        _own(owner, lambda: entry in self.handlers[sequence] and self.handlers[sequence].remove(entry))

    def _fire(self, sequence, event):
        focus = event.widget
        for owner, run, skip_in_text in reversed(self.handlers.get(sequence, ())):
            if skip_in_text and isinstance(focus, tk.Widget) and focus.winfo_class() == "Text":
                continue
            if not _on_screen(owner):
                continue
            if run() is not False:
                return "break"


def _window_keys(widget):
    window = widget.winfo_toplevel()
    keys = getattr(window, "_mytk_keys", None)
    if keys is None:
        keys = window._mytk_keys = _WindowKeys(window)
    return keys


_MODIFIERS = {"ctrl": "Control", "control": "Control", "alt": "Alt", "shift": "Shift",
              "cmd": "Command", "command": "Command", "meta": "Meta"}
_KEY_NAMES = {"del": "Delete", "delete": "Delete", "esc": "Escape", "escape": "Escape",
              "enter": "Return", "return": "Return", "space": "space", "tab": "Tab",
              "plus": "plus", "minus": "minus", "up": "Up", "down": "Down", "left": "Left",
              "right": "Right", "home": "Home", "end": "End", "pageup": "Prior", "pagedown": "Next",
              "backspace": "BackSpace", "insert": "Insert"}


def key_sequence(spec: str) -> str:
    """"Ctrl+S" -> "<Control-s>", "Ctrl+Shift+S" -> "<Control-S>", "F5" -> "<F5>".
    Tk event sequences ("<Control-s>") pass through. On macOS, Ctrl means Command."""
    if spec.startswith("<"):
        return spec
    parts = [p.strip() for p in spec.replace("-", "+").split("+") if p.strip()]
    *mods, key = parts
    names = []
    shift = False
    for mod in mods:
        name = _MODIFIERS.get(mod.lower(), mod)
        if name == "Control" and sys.platform == "darwin":
            name = "Command"
        if name == "Shift":
            shift = True
            continue
        names.append(name)
    if len(key) == 1:
        key = key.upper() if shift else key.lower()
    else:
        key = _KEY_NAMES.get(key.lower(), key)
        if shift:
            names.append("Shift")
    return "<%s>" % "-".join(names + [key])


def accelerator_text(spec: str) -> str:
    """What a menu shows for a shortcut ("Ctrl+S")."""
    if spec.startswith("<"):
        return spec.strip("<>").replace("Control", "Ctrl").replace("-", "+")
    if sys.platform == "darwin":
        return spec.replace("Ctrl+", "Cmd+")
    return spec


def _invoke(widget):
    if not widget.winfo_exists():
        return False
    try:
        if widget.instate(["disabled"]):
            return False
    except (AttributeError, tk.TclError):
        pass
    widget.invoke()
    return True


def _on_screen(widget):
    try:
        return bool(widget.winfo_exists()) and _laid_out(widget)
    except tk.TclError:
        return False


def _laid_out(widget):
    """Shown, ignoring whether the window itself is mapped (tests withdraw it)."""
    top = widget.winfo_toplevel()
    while widget is not top:
        if not widget.winfo_manager():
            return False
        widget = widget.master
    return True


def _chain_tab_order(widgets):
    def move(index, step):
        def go(event):
            for offset in range(1, len(widgets) + 1):
                target = widgets[(index + step * offset) % len(widgets)]
                if _on_screen(target) and str(target.cget("takefocus") if "takefocus" in target.keys() else "1") != "0":
                    try:
                        if target.instate(["disabled"]):
                            continue
                    except (AttributeError, tk.TclError):
                        pass
                    target.focus_set()
                    return "break"
            return "break"
        return go

    for index, widget in enumerate(widgets):
        widget.bind("<Tab>", move(index, 1), add="+")
        for sequence in ("<Shift-Tab>", "<ISO_Left_Tab>"):
            try:
                widget.bind(sequence, move(index, -1), add="+")
            except tk.TclError:
                pass


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _own(widget, dispose):
    """Run ``dispose`` when ``widget`` is destroyed."""
    owned = getattr(widget, "_reactions", None)
    if owned is None:
        owned = widget._reactions = []

        def on_destroy(event, widget=widget):
            if event.widget is widget:
                for fn in widget._reactions:
                    fn()
                widget._reactions.clear()

        widget.bind("<Destroy>", on_destroy, add="+")
    owned.append(dispose)


def _show(widget):
    manager, options = getattr(widget, "_mytk_layout", (None, None))
    companions = getattr(widget, "_mytk_companions", ())
    if manager == "grid":
        for w in companions:
            w.grid()
            if not w.winfo_manager():
                w.grid(**w._mytk_layout[1])
        widget.grid(**options)
    elif manager == "pack":
        if widget.winfo_manager() == "pack":
            return
        # Keep document order: pack before the next sibling that is shown.
        order = getattr(widget.master, "_mytk_order", [])
        after = order[order.index(widget) + 1:] if widget in order else []
        before = next((w for w in after if w.winfo_exists() and w.winfo_manager() == "pack"), None)
        widget.pack(**dict(options, **({"before": before} if before is not None else {})))


def _hide(widget):
    manager = getattr(widget, "_mytk_layout", (None, None))[0]
    for w in getattr(widget, "_mytk_companions", ()):
        w.grid_remove()
    if manager == "grid":
        widget.grid_remove()
    elif manager == "pack":
        widget.pack_forget()


def _sync_var(builder, owner, var, binding):
    pushing = [False]

    def push(value):
        pushing[0] = True
        try:
            var.set(_text(binding.to_view(value)) if isinstance(var, tk.StringVar) else bool(binding.to_view(value)))
        finally:
            pushing[0] = False

    def pull(*_):
        if not pushing[0] and binding.two_way:
            binding.assign(binding.to_model(var.get()))
    builder.watch(owner, binding.model, push)
    _trace(owner, var, pull)


def _trace(owner, var, callback):
    """A write trace removed with ``owner``. Tcl holds trace callbacks where
    Python's garbage collector can't see them, so a callback that refers to
    its variable would otherwise keep both (and the view model) alive."""
    trace = var.trace_add("write", callback)

    def remove():
        try:
            var.trace_remove("write", trace)
        except tk.TclError:
            pass
    _own(owner, remove)


def _touch(binding):
    target, name = binding.target()
    touch = getattr(target, "touch", None)
    if touch is not None:
        touch(name)


def _show_invalid(widget):
    flags = getattr(widget, "_mytk_invalid", {})
    try:
        widget.state(["invalid" if any(flags.values()) else "!invalid"])
    except (AttributeError, tk.TclError):
        pass


def _set_enabled(widget, on):
    try:
        widget.state(["!disabled" if on else "disabled"])
    except AttributeError:
        widget.configure(state="normal" if on else "disabled")


def _flag_getter(value):
    if is_binding(value):
        return lambda: bool(value.value())
    return lambda v=value: _truthy(v)


def _truthy(value):
    return str(value).strip().lower() not in ("0", "false", "no", "")


def _grid_size(size, scale):
    """Grid row/column sizes: "auto", "*", "2*", or pixels ("120")."""
    if size == "auto":
        return {"weight": 0}
    if size.endswith("*"):
        return {"weight": int(size[:-1] or 1)}
    return {"weight": 0, "minsize": _px(size, scale)}


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _cache_limit(value):
    """``cache`` on <content>: "true" keeps the 10 most recent views, a number that many."""
    value = str(value).strip().lower()
    if value in ("", "0", "false", "no"):
        return 0
    return 10 if value in ("1", "true", "yes") else int(value)


def _can_execute(fn, parameter=None):
    """Commands (``reactive.Command``) say; plain callables can always run."""
    if fn is None:
        return False
    check = getattr(fn, "can_execute", None)
    return bool(check(parameter)) if callable(check) else True


def _execute(fn, parameter=None):
    if hasattr(fn, "execute"):
        fn.execute(parameter)
    elif parameter is None:
        fn()
    else:
        fn(parameter)


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
