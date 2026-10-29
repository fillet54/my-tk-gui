"""Binding expressions, converters, resources and binding errors. No widgets here.

An attribute value in a view is a literal, a binding, or text mixed with
bindings::

    text="{form.amount|number}"                    path, then converters
    text="Total: {total|money}"                    template (one-way)
    text="{search; trigger=focus}"                 options after ';'
    text="{selected.name; fallback=—; null=(none)}"
    foreground="{@danger}"                         named resource (static)
    text="{{literal braces}}"

Options:
    mode=twoway|oneway|onetime   default: two-way where the widget can edit
    trigger=change|focus         when edited text is written back (default
                                 every change; focus = on focus-out / Return)
    delay=300                    write back after typing pauses (ms)
    fallback=TEXT                shown when the path can't be resolved
    null=TEXT                    shown when the value is None
"""

import re
from typing import Any, Callable
import sys
import traceback

from .reactive import ObservableList

__all__ = ["converter", "resource", "Binding", "TemplateBinding", "BindingError", "parse",
           "is_binding", "strict_bindings"]


# --------------------------------------------------------------------------
# Converters: {path|name}
# --------------------------------------------------------------------------

class Converter:
    def __init__(self, to_view, to_model=None):
        self.to_view = to_view
        self.to_model = to_model     # None means one-way only


_converters = {}


def converter(name: str, to_view: Callable[[Any], Any], to_model: "Callable[[Any], Any] | None" = None) -> None:
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
converter("count", lambda v: 0 if v is None else len(v))
converter("any", lambda v: bool(v))


# --------------------------------------------------------------------------
# Resources: {@name}
# --------------------------------------------------------------------------

_resources = {}


def resource(name: str, value: Any) -> None:
    """Register a named value usable as ``{@name}`` in any view (colors, fonts, sizes)."""
    _resources[name] = value


def resource_value(name, local=None):
    if local and name in local:
        return local[name]
    if name in _resources:
        return _resources[name]
    raise KeyError(name)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

class BindingError(Exception):
    """A binding that can't be evaluated, with where it is in the view."""


_strict = [False]
_reported = set()


def strict_bindings(on: bool = True) -> None:
    """Raise binding errors instead of logging them (use in tests)."""
    _strict[0] = on


def report(error, key):
    """Raise in strict mode, else print once per binding."""
    if _strict[0]:
        raise error
    if key in _reported:
        return
    _reported.add(key)
    cause = error.__cause__
    detail = "".join(traceback.format_exception_only(type(cause), cause)).strip() if cause else ""
    print("mytkgui binding error: %s%s" % (error, ("\n    " + detail) if detail else ""), file=sys.stderr)


# --------------------------------------------------------------------------
# Binding expressions
# --------------------------------------------------------------------------

_TOKEN = re.compile(r"\{\{|\}\}|\{([^{}]*)\}")
_MISSING = object()
_MODES = ("twoway", "oneway", "onetime")
_TRIGGERS = ("change", "focus")


class Binding:
    """One ``{path|conv; options}`` expression, evaluated against a data context.

    ``context`` is a function returning the current context object. Reads
    go through observables, so calling ``value()`` inside a reaction tracks
    every step of the path.
    """

    def __init__(self, context, expression, root=None, where=""):
        self.expression = expression
        self.where = where
        body, _, options = expression.partition(";")
        path, *names = [part.strip() for part in body.split("|")]
        self.path = () if path in ("", ".") else tuple(path.split("."))
        if self.path[:1] == ("$root",):
            context, self.path = root, self.path[1:]
        self.context = context
        try:
            self.converters = [_converters[n] for n in names]
        except KeyError as e:
            raise BindingError("unknown converter %s in {%s}%s" % (e, expression, _at(where))) from None

        self.mode, self.trigger, self.delay = None, "change", 0
        self.fallback, self.null = _MISSING, _MISSING
        for option in filter(None, (o.strip() for o in options.split(";"))):
            key, _, value = option.partition("=")
            key, value = key.strip(), value.strip()
            if key == "mode" and value in _MODES:
                self.mode = value
            elif key == "trigger" and value in _TRIGGERS:
                self.trigger = value
            elif key == "delay" and value.isdigit():
                self.delay = int(value)
            elif key == "fallback":
                self.fallback = value
            elif key == "null":
                self.null = value
            else:
                raise BindingError("bad binding option %r in {%s}%s" % (option, expression, _at(where)))

    @property
    def two_way(self):
        if self.mode in ("oneway", "onetime"):
            return False
        return bool(self.path) and all(c.to_model for c in self.converters)

    @property
    def one_time(self):
        return self.mode == "onetime"

    def _error(self, exc):
        error = BindingError("{%s} on %s: %s" % (self.expression, self.where or "a view",
                                                  _describe(exc)))
        error.__cause__ = exc
        report(error, (self.where, self.expression))

    def model(self):
        try:
            return _resolve(self.context(), self.path)
        except Exception as exc:          # a typo in the path, or the view model raised
            if self.fallback is not _MISSING:
                return _MISSING
            self._error(exc)
            return None

    def to_view(self, value):
        if value is _MISSING:
            return self.fallback
        if value is None and self.null is not _MISSING:
            return self.null
        try:
            for c in self.converters:
                value = c.to_view(value)
        except Exception as exc:
            if self.fallback is not _MISSING:
                return self.fallback
            self._error(exc)
            return None
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

    def target(self):
        """(object, attribute name) this binding writes to, or (None, None)."""
        if not self.path:
            return None, None
        try:
            return _resolve(self.context(), self.path[:-1]), self.path[-1]
        except Exception:
            return None, None


class TemplateBinding:
    """Literal text mixed with bindings: ``"Total: {total|money}"``. One-way."""

    two_way = False
    one_time = False
    trigger = "change"
    delay = 0

    def __init__(self, parts):
        self.parts = parts

    def value(self):
        return "".join(p if isinstance(p, str) else _text(p.value()) for p in self.parts)

    model = value

    def to_view(self, value):
        return value

    def target(self):
        return None, None


def parse(value, context, root=None, where="", resources=None):
    """Return a Binding/TemplateBinding, or the literal (braces unescaped,
    ``{@name}`` resources substituted)."""
    parts, pos = [], 0
    for m in _TOKEN.finditer(value):
        parts.append(value[pos:m.start()])
        token = m.group(0)
        if token in ("{{", "}}"):
            parts.append(token[0])
        elif m.group(1).strip().startswith("@"):
            name = m.group(1).strip()[1:]
            try:
                parts.append(resource_value(name, resources))
            except KeyError:
                raise BindingError("unknown resource @%s%s" % (name, _at(where))) from None
        else:
            parts.append(Binding(context, m.group(1), root, where))
        pos = m.end()
    parts.append(value[pos:])
    parts = [p for p in parts if p != ""]
    bindings = [p for p in parts if is_binding(p)]
    if not bindings:
        if len(parts) == 1:
            return parts[0]            # keeps a resource's own type
        return "".join(str(p) for p in parts)
    if len(parts) == 1:
        return parts[0]
    return TemplateBinding([p if is_binding(p) else str(p) for p in parts])


def is_binding(value):
    return isinstance(value, (Binding, TemplateBinding))


def _at(where):
    return " (%s)" % where if where else ""


def _describe(exc):
    if isinstance(exc, AttributeError) and getattr(exc, "name", None):
        return "%s has no attribute %r" % (type(exc.obj).__name__ if getattr(exc, "obj", None) is not None
                                           else "object", exc.name)
    return "%s: %s" % (type(exc).__name__, exc)


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
