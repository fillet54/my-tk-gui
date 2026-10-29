"""App-level MVVM pieces: messenger, navigator, collection views. No Tk here.

``Messenger`` lets view models talk without references to each other
(MVVM Light's Messenger). ``Navigator`` holds the current page of a shell
and its back stack; a view shows it with ``<content content="{nav.current}" />``.
``CollectionView`` filters, sorts and groups a list for display.
"""

import inspect
from typing import Any, Callable
import weakref
from itertools import groupby

from .reactive import ObservableList, batch, command, computed, observable, untracked

__all__ = ["Messenger", "Navigator", "NavigationArgs", "CollectionView"]


# --------------------------------------------------------------------------
# Messenger
# --------------------------------------------------------------------------

class _Subscription:
    def __init__(self, recipient, message_type, handler, token):
        self.recipient = weakref.ref(recipient)
        self.message_type = message_type
        self.token = token
        # A bound method of the recipient must not keep it alive.
        if getattr(handler, "__self__", None) is recipient:
            self.handler = weakref.WeakMethod(handler)
        else:
            self.handler = lambda h=handler: h

    def alive(self):
        return self.recipient() is not None and self.handler() is not None


class Messenger:
    """Publish/subscribe between view models, by message type::

        class DarkModeChanged:
            def __init__(self, dark): self.dark = dark

        Messenger.default.register(self, DarkModeChanged, self.on_dark_mode)
        Messenger.default.send(DarkModeChanged(True))

    Recipients are held weakly: a view model that goes away stops getting
    messages without unregistering. ``token`` narrows a message to the
    subscribers that registered with the same token (a "channel").
    """

    default = None      # set below

    def __init__(self):
        self._subscriptions = []

    def register(self, recipient: Any, message_type: type, handler: Callable[[Any], Any],
                 token: Any = None) -> None:
        self._subscriptions.append(_Subscription(recipient, message_type, handler, token))

    def unregister(self, recipient, message_type=None, token=None):
        self._subscriptions = [
            s for s in self._subscriptions
            if not (s.recipient() is recipient
                    and (message_type is None or s.message_type is message_type)
                    and (token is None or s.token == token))]

    def send(self, message: Any, token: Any = None) -> None:
        """Deliver ``message`` to every live subscriber for its type (or a base type)."""
        self._subscriptions = [s for s in self._subscriptions if s.alive()]
        targets = [s.handler() for s in self._subscriptions
                   if isinstance(message, s.message_type) and s.token == token]
        with batch():
            for handler in targets:
                if handler is not None:
                    handler(message)


Messenger.default = Messenger()


# --------------------------------------------------------------------------
# Navigator
# --------------------------------------------------------------------------

class NavigationArgs:
    """What a page's lifecycle hooks receive."""

    def __init__(self, parameter, mode, route):
        self.parameter = parameter
        self.mode = mode            # "new" or "back"
        self.route = route

    def __repr__(self):
        return "NavigationArgs(%r, %r, %r)" % (self.parameter, self.mode, self.route)


class Navigator:
    """The current page of a shell, with a back stack.

    Routes map a name to a factory taking the navigation parameter::

        nav = Navigator({
            "home": lambda _: home_page,                       # same page each time
            "expense": lambda expense: ExpensePage(expense),   # a new page per visit
        })
        nav.go("home")
        nav.navigate.execute("home")          # the same, as a bindable command
        nav.go("expense", selected_expense)

    Pages may define any of these hooks (WinUI's Page lifecycle):

    ``on_navigating_from(args)``  return False to stay (e.g. unsaved changes)
    ``on_navigated_from(args)``   the page is being left
    ``on_navigated_to(args)``     the page is shown; may be ``async def`` to load data

    ``args`` is a NavigationArgs: ``parameter``, ``mode`` ("new"/"back"), ``route``.
    """

    current = observable(None)
    current_route = observable(None)

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.back_stack = ObservableList()      # [(route, view model)]

    def go(self, route: Any, parameter: Any = None, remember: bool = True) -> bool:
        """Show ``route`` (a name, or a view model itself). Returns False if
        the current page refused to be left."""
        with untracked():
            if isinstance(route, str):
                if route not in self.routes:
                    raise KeyError("no route %r" % route)
                name = route
                view_model = self.routes[route](parameter)
            else:
                name, view_model = None, route
            if view_model is self.current:
                return True
            args = NavigationArgs(parameter, "new", name)
            if not self._leave(args):
                return False
            with batch():
                if remember and self.current is not None:
                    self.back_stack.append((self.current_route, self.current))
                self.current_route, self.current = name, view_model
            _hook(view_model, "on_navigated_to", args)
            return True

    @command
    def navigate(self, route):
        """Bindable: ``command="{nav.navigate}" command_parameter="settings"``."""
        self.go(route)

    @computed
    def can_go_back(self):
        return len(self.back_stack) > 0

    @command(can_execute=can_go_back)
    def go_back(self):
        with untracked():
            route, page = self.back_stack[-1]
            args = NavigationArgs(None, "back", route)
            if not self._leave(args):
                return
            with batch():
                self.back_stack.pop()
                self.current_route, self.current = route, page
            _hook(page, "on_navigated_to", args)

    def _leave(self, args):
        page = self.current
        if page is None:
            return True
        guard = getattr(page, "on_navigating_from", None)
        if guard is not None and guard(args) is False:
            return False
        _hook(page, "on_navigated_from", args)
        return True


def _hook(page, name, args):
    fn = getattr(page, name, None)
    if fn is None:
        return
    result = fn(args)
    if inspect.iscoroutine(result):
        from .tasks import Task, _report
        Task(result, on_finish=_report)


# --------------------------------------------------------------------------
# CollectionView
# --------------------------------------------------------------------------

class CollectionView:
    """A filtered, sorted and grouped view of a list (WPF's CollectionView).

        self.view = CollectionView(lambda: self.expenses,
                                   filter=lambda e: self.search.lower() in e.description.lower(),
                                   sort_key="amount", descending=True)

    ``items`` (also iteration and ``len``) is the result; ``groups`` is
    ``[(key, [items])]`` when ``group_key`` is set. ``sort_key`` and
    ``group_key`` are attribute names or functions. Filters that read
    observables update the view on their own. ``sort_by`` is a command:
    the same key again flips the direction; treeview headings call it.
    """

    filter = observable(None)
    sort_key = observable(None)
    descending = observable(False)
    group_key = observable(None)

    def __init__(self, source, filter=None, sort_key=None, descending=False, group_key=None):
        self._source = source if callable(source) else (lambda: source)
        self.filter, self.sort_key, self.descending, self.group_key = filter, sort_key, descending, group_key

    @computed
    def items(self):
        items = list(self._source() or ())
        if self.filter is not None:
            items = [item for item in items if self.filter(item)]
        if self.sort_key is not None:
            key = _key(self.sort_key)
            present = [i for i in items if key(i) is not None]
            missing = [i for i in items if key(i) is None]          # None sorts last
            items = sorted(present, key=key, reverse=self.descending) + missing
        return items

    @computed
    def groups(self):
        if self.group_key is None:
            return [(None, list(self.items))]
        key = _key(self.group_key)
        ordered = sorted(self.items, key=lambda i: _sortable(key(i)))
        return [(k, list(g)) for k, g in groupby(ordered, key=key)]

    @command
    def sort_by(self, key):
        with batch():
            if self.sort_key == key:
                self.descending = not self.descending
            else:
                self.sort_key, self.descending = key, False

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)


def _key(key):
    if callable(key):
        return key
    path = key.split(".")

    def get(item):
        for name in path:
            if item is None:
                return None
            item = getattr(item, name)
        return item
    return get


def _sortable(value):
    return (value is None, "" if value is None else value)
