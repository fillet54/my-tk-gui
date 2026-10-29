"""Automatic dependency tracking for view models (in the style of Assisticant).

Nothing here knows about Tk. There are three kinds of node:

* ``Observable`` -- a value you set. Reading it inside a computation
  records a dependency.
* ``Computed`` -- a value derived from a function. Its dependencies are
  discovered by running it, and rediscovered on every run, so branches
  (``a if flag else b``) only depend on what they actually read. It is
  lazy: a change marks it stale, and it recalculates on the next read.
* ``Reaction`` -- a side effect (e.g. pushing a value into a widget) that
  reruns when anything it read changes. The scheduler decides *when*;
  the Tk layer will pass ``root.after_idle``.

Changes flow in two phases: a ``set`` pushes "stale" marks through the
graph, then pending reactions run. Nothing recalculates during the push,
so a reaction never sees a half-updated graph.

Memory: a node subscribes to its sources only while it is up to date.
When it goes stale it unsubscribes, so a discarded view model is released
after the next change to anything it depended on (or at once by calling
``dispose()`` on reactions).

Class-level sugar::

    class Person:
        first = observable("")
        last = observable("")

        @computed
        def full(self):
            return f"{self.first} {self.last}".strip()
"""

import functools
import inspect
import threading
from collections.abc import MutableSequence
from contextlib import contextmanager

__all__ = [
    "Observable", "Computed", "Reaction", "ObservableList",
    "observable", "computed", "command", "Command", "RelayCommand", "BoundCommand", "autorun", "watch",
    "batch", "untracked", "CycleError",
]


class CycleError(RuntimeError):
    """A computed value depends on itself, or reactions keep retriggering."""


# Runaway guard: a reaction that writes to its own input reschedules forever.
MAX_REACTION_RUNS = 10_000


class _State(threading.local):
    def __init__(self):
        self.frames = []      # stack of sets: sources read by running computations
        self.batch_depth = 0
        self.pending = []     # reactions waiting to be scheduled
        self.flushing = False


_state = _State()


def _record(source):
    if _state.frames:
        frame = _state.frames[-1]
        if frame is not None:   # None means untracked()
            frame.add(source)


@contextmanager
def _tracking(frame):
    _state.frames.append(frame)
    try:
        yield
    finally:
        _state.frames.pop()


@contextmanager
def untracked():
    """Read values without recording dependencies."""
    with _tracking(None):
        yield


@contextmanager
def batch():
    """Group several writes so reactions run once, after the last one."""
    _state.batch_depth += 1
    try:
        yield
    finally:
        _state.batch_depth -= 1
        if _state.batch_depth == 0:
            _flush()


def _flush():
    if _state.flushing:
        return
    _state.flushing = True
    first_error = None
    runs = 0
    try:
        while _state.pending:
            reaction = _state.pending.pop(0)
            runs += 1
            if runs > MAX_REACTION_RUNS:
                _state.pending.clear()
                raise CycleError(
                    "reactions retriggered %d times; does a reaction write "
                    "a value it reads?" % MAX_REACTION_RUNS)
            try:
                reaction._schedule()
            except Exception as e:
                # Keep the other reactions running; report the first error.
                if first_error is None:
                    first_error = e
    finally:
        _state.flushing = False
    if first_error is not None:
        raise first_error


class _Source:
    """Something that can be depended on."""

    __slots__ = ("_dependents", "__weakref__")

    def __init__(self):
        self._dependents = set()

    def _depend(self):
        _record(self)

    def _changed(self):
        if not self._dependents:
            return
        with batch():
            dependents, self._dependents = self._dependents, set()
            for d in dependents:
                d._invalidate()


class _Dependent:
    """Something that tracks sources while it runs."""

    __slots__ = ()

    def _run_tracked(self, fn):
        frame = set()
        try:
            with _tracking(frame):
                return fn()
        finally:
            # Subscribe even if fn raised: fixing an input should retry it.
            self._sources = frame
            for s in frame:
                s._dependents.add(self)

    def _unsubscribe(self):
        for s in self._sources:
            s._dependents.discard(self)
        self._sources = set()


class Observable(_Source):
    """A settable value that records reads and announces changes."""

    __slots__ = ("_value", "name")

    def __init__(self, value=None, name=None):
        super().__init__()
        self._value = value
        self.name = name

    def get(self):
        self._depend()
        return self._value

    def set(self, value):
        if _same(self._value, value):
            return
        self._value = value
        self._changed()

    value = property(get, set)

    def __repr__(self):
        return "Observable(%s%r)" % (self.name + "=" if self.name else "", self._value)


class Computed(_Source, _Dependent):
    """A cached value derived from other observables and computeds."""

    __slots__ = ("_fn", "_value", "_error", "_stale", "_computing", "_sources", "name")

    def __init__(self, fn, name=None):
        _Source.__init__(self)
        self._fn = fn
        self._value = None
        self._error = None
        self._stale = True
        self._computing = False
        self._sources = set()
        self.name = name or getattr(fn, "__qualname__", None)

    def get(self):
        if self._computing:
            raise CycleError("computed %r depends on itself" % self.name)
        self._depend()
        if self._stale:
            self._recompute()
        if self._error is not None:
            raise self._error
        return self._value

    value = property(get)

    def _recompute(self):
        self._computing = True
        try:
            self._value = self._run_tracked(self._fn)
            self._error = None
        except CycleError:
            self._unsubscribe()   # stay stale so the next read retries
            raise
        except Exception as e:
            # Cache the error like a value; it is re-raised on every read
            # until an input changes.
            self._value, self._error = None, e
        finally:
            self._computing = False
        self._stale = False

    def _invalidate(self):
        if self._stale:
            return
        self._stale = True
        self._unsubscribe()
        self._changed()

    def __repr__(self):
        state = "stale" if self._stale else repr(self._value)
        return "Computed(%s: %s)" % (self.name, state)


def _run_now(fn):
    fn()


class Reaction(_Dependent):
    """Runs ``fn`` now, and again (via ``scheduler``) whenever its inputs change.

    ``scheduler`` is called with a zero-argument function and must run it
    eventually, e.g. ``root.after_idle``. Several changes before it runs
    coalesce into a single rerun.
    """

    __slots__ = ("_fn", "_scheduler", "_sources", "_scheduled", "_disposed", "__weakref__")

    def __init__(self, fn, scheduler=None):
        self._fn = fn
        self._scheduler = scheduler or _run_now
        self._sources = set()
        self._scheduled = False
        self._disposed = False
        self._run()

    def _invalidate(self):
        if self._scheduled or self._disposed:
            return
        self._scheduled = True
        self._unsubscribe()
        _state.pending.append(self)

    def _schedule(self):
        self._scheduler(self._run)

    def _run(self):
        self._scheduled = False
        if self._disposed:
            return
        self._run_tracked(self._fn)

    def dispose(self):
        self._disposed = True
        self._unsubscribe()

    @property
    def disposed(self):
        return self._disposed


def autorun(fn, scheduler=None):
    """Run ``fn`` now and whenever anything it reads changes."""
    return Reaction(fn, scheduler)


_MISSING = object()


def watch(getter, callback, scheduler=None, fire_immediately=True):
    """Call ``callback(value)`` whenever ``getter()`` produces a new value.

    Only ``getter`` is tracked; ``callback`` runs untracked, so writing to
    a widget inside it doesn't create dependencies. This is the shape a
    one-way binding takes.
    """
    last = [_MISSING]

    def run():
        value = getter()
        previous, last[0] = last[0], value
        if previous is _MISSING:
            if not fire_immediately:
                return
        elif _same(previous, value):
            return
        with untracked():
            callback(value)

    return Reaction(run, scheduler)


def _same(a, b):
    if a is b:
        return True
    try:
        return bool(a == b)
    except Exception:
        # e.g. numpy arrays, where == is elementwise
        return False


# --------------------------------------------------------------------------
# Class-level descriptors
# --------------------------------------------------------------------------

class observable:
    """Declares an observable attribute on a class.

    Use ``factory`` for mutable defaults: ``items = observable(factory=ObservableList)``.
    """

    def __init__(self, default=None, *, factory=None):
        self._default = default
        self._factory = factory
        self._name = None

    def __set_name__(self, owner, name):
        self._name = name

    def cell(self, instance):
        """The underlying ``Observable`` for this attribute on ``instance``."""
        cells = instance.__dict__.setdefault("__reactive_cells__", {})
        cell = cells.get(self._name)
        if cell is None:
            value = self._factory() if self._factory else self._default
            cell = cells[self._name] = Observable(value, name=self._name)
        return cell

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return self.cell(instance).get()

    def __set__(self, instance, value):
        self.cell(instance).set(value)


class computed:
    """Declares a computed attribute on a class (used like ``@property``)."""

    def __init__(self, fn):
        self._fn = fn
        self._name = fn.__name__
        self.__doc__ = fn.__doc__

    def __set_name__(self, owner, name):
        self._name = name

    def cell(self, instance):
        """The underlying ``Computed`` for this attribute on ``instance``."""
        cells = instance.__dict__.setdefault("__reactive_cells__", {})
        cell = cells.get(self._name)
        if cell is None:
            fn = self._fn
            cell = cells[self._name] = Computed(
                lambda: fn(instance),
                name="%s.%s" % (type(instance).__name__, self._name))
        return cell

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return self.cell(instance).get()

    def __set__(self, instance, value):
        raise AttributeError("computed attribute %r is read-only" % self._name)


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def _takes_parameter(fn, bound=0):
    """True if ``fn`` accepts a positional argument after ``bound`` others."""
    try:
        return _takes_parameter_cached(fn, bound)
    except TypeError:          # unhashable callable
        return _signature_takes_parameter(fn, bound)


@functools.lru_cache(maxsize=1024)
def _takes_parameter_cached(fn, bound):
    return _signature_takes_parameter(fn, bound)


def _signature_takes_parameter(fn, bound):
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return True
    if any(p.kind is p.VAR_POSITIONAL for p in params):
        return True
    positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    return len(positional) > bound


class Command:
    """What a view binds ``command="{...}"`` to (MVVM Light's ICommand).

    ``execute(parameter)`` runs the action, inside ``batch()``, if
    ``can_execute(parameter)`` allows it. ``can_execute`` is read through
    observables, so a bound button enables and disables itself; call
    ``raise_can_execute_changed()`` only when it depends on something that
    isn't observable. Calling the command is the same as ``execute``.
    """

    def execute(self, parameter=None):
        raise NotImplementedError

    def can_execute(self, parameter=None):
        return True

    def raise_can_execute_changed(self):
        pass

    def __call__(self, parameter=None):
        return self.execute(parameter)


class RelayCommand(Command):
    """A command from plain functions, like MVVM Light's RelayCommand::

        self.save = RelayCommand(self._save, lambda: bool(self.name))
        self.open = RelayCommand(lambda item: ..., lambda item: item is not None)

    Either function may take the command parameter or not.
    """

    def __init__(self, execute, can_execute=None, name=None):
        self._execute = execute
        self._check = can_execute
        self._version = Observable(0)
        self.name = name or getattr(execute, "__name__", "command")

    def can_execute(self, parameter=None):
        self._version.get()
        if self._check is None:
            return True
        return bool(_call(self._check, (), parameter))

    def execute(self, parameter=None):
        with batch():
            if self.can_execute(parameter):
                return _call(self._execute, (), parameter)

    def raise_can_execute_changed(self):
        with untracked():
            self._version.set(self._version.get() + 1)

    def __repr__(self):
        return "<RelayCommand %s>" % self.name


def _call(fn, bound, parameter):
    """Call ``fn(*bound)``, adding ``parameter`` if ``fn`` takes one more argument."""
    if _takes_parameter(fn, len(bound)):
        return fn(*bound, parameter)
    return fn(*bound)


class BoundCommand(Command):
    """A ``@command`` method on one view model instance."""

    __slots__ = ("_instance", "_command")

    def __init__(self, instance, command):
        self._instance = instance
        self._command = command

    def execute(self, parameter=None):
        with batch():
            if self.can_execute(parameter):
                return _call(self._command._fn, (self._instance,), parameter)

    def can_execute(self, parameter=None):
        return self._command._can_execute(self._instance, parameter)

    def raise_can_execute_changed(self):
        version = self._command._version(self._instance)
        with untracked():
            version.set(version.get() + 1)

    @property
    def name(self):
        return self._command._name

    def __repr__(self):
        return "<command %s>" % self._command._name


class _CommandDescriptor:
    def __init__(self, fn, can_execute):
        self._fn = fn
        self._name = fn.__name__
        self._check = can_execute
        self.__doc__ = fn.__doc__

    def __set_name__(self, owner, name):
        self._name = name

    def _cells(self, instance):
        return instance.__dict__.setdefault("__reactive_cells__", {})

    def _version(self, instance):
        cells = self._cells(instance)
        key = self._name + ".version"
        if key not in cells:
            cells[key] = Observable(0, name="%s.%s" % (type(instance).__name__, key))
        return cells[key]

    def _can_execute(self, instance, parameter):
        version = self._version(instance)
        check = self._check
        if check is None:
            version.get()
            return True
        if hasattr(check, "__get__") and not callable(check):      # a @computed
            version.get()
            return bool(check.__get__(instance))
        if not _takes_parameter(check, 1):
            # No parameter: cache it like a computed property. The version is
            # read inside, so raise_can_execute_changed() recomputes it.
            cells = self._cells(instance)
            key = self._name + ".can_execute"
            if key not in cells:
                cells[key] = Computed(lambda: version.get() is not None and bool(check(instance)),
                                      name="%s.%s" % (type(instance).__name__, key))
            return cells[key].get()
        version.get()
        return bool(check(instance, parameter))

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return BoundCommand(instance, self)


def command(fn=None, *, can_execute=None):
    """Declares a view model action (a ``Command``).

    The method may take a parameter (``command_parameter`` in a view, or
    ``vm.open.execute(item)``). ``can_execute`` is a function of ``self``,
    of ``self`` and the parameter, or a ``@computed`` declared above it::

        @computed
        def can_save(self):
            return bool(self.name)

        @command(can_execute=can_save)
        def save(self): ...

        @command(can_execute=lambda self, item: item is not None)
        def open(self, item): ...
    """
    if fn is None:
        return lambda f: _CommandDescriptor(f, can_execute)
    return _CommandDescriptor(fn, can_execute)


# --------------------------------------------------------------------------
# Collections
# --------------------------------------------------------------------------

class ObservableList(MutableSequence):
    """A list whose reads are tracked and whose mutations notify.

    Any read depends on the whole list, and any mutation invalidates every
    reader. Per-item change events (for efficient Treeview updates) can be
    added on top later without changing this contract.
    """

    def __init__(self, iterable=()):
        self._items = list(iterable)
        self._source = _Source()

    # reads
    def __len__(self):
        self._source._depend()
        return len(self._items)

    def __getitem__(self, index):
        self._source._depend()
        return self._items[index]

    def __iter__(self):
        self._source._depend()
        return iter(list(self._items))

    def __contains__(self, value):
        self._source._depend()
        return value in self._items

    def __eq__(self, other):
        self._source._depend()
        if isinstance(other, ObservableList):
            other = other._items
        return self._items == other

    __hash__ = None

    def __repr__(self):
        return "ObservableList(%r)" % (self._items,)

    # writes
    def __setitem__(self, index, value):
        self._items[index] = value
        self._source._changed()

    def __delitem__(self, index):
        del self._items[index]
        self._source._changed()

    def insert(self, index, value):
        self._items.insert(index, value)
        self._source._changed()

    def append(self, value):
        self._items.append(value)
        self._source._changed()

    def extend(self, values):
        values = list(values)
        if values:
            self._items.extend(values)
            self._source._changed()

    def clear(self):
        if self._items:
            self._items.clear()
            self._source._changed()

    def sort(self, *, key=None, reverse=False):
        self._items.sort(key=key, reverse=reverse)
        self._source._changed()

    def reverse(self):
        self._items.reverse()
        self._source._changed()

    def replace(self, iterable):
        """Swap in new contents with a single notification."""
        self._items[:] = list(iterable)
        self._source._changed()
