"""Shell-level MVVM pieces: a messenger and a navigator. No Tk here.

``Messenger`` lets view models talk without references to each other
(MVVM Light's Messenger). ``Navigator`` holds the current page of a shell
and its back stack; a view shows it with ``<content content="{nav.current}" />``.
"""

import weakref

from reactive import ObservableList, batch, command, computed, observable, untracked

__all__ = ["Messenger", "Navigator"]


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

    def register(self, recipient, message_type, handler, token=None):
        self._subscriptions.append(_Subscription(recipient, message_type, handler, token))

    def unregister(self, recipient, message_type=None, token=None):
        self._subscriptions = [
            s for s in self._subscriptions
            if not (s.recipient() is recipient
                    and (message_type is None or s.message_type is message_type)
                    and (token is None or s.token == token))]

    def send(self, message, token=None):
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

class Navigator:
    """The current page of a shell, with a back stack.

    Routes map a name to a factory taking the navigation parameter::

        nav = Navigator({
            "home": lambda _: HomeViewModel(),
            "expense": lambda expense: ExpenseViewModel(expense),
        })
        nav.go("home")
        nav.navigate.execute("home")          # the same, as a bindable command
        nav.go("expense", selected_expense)

    A factory may return the same view model every time (a page that keeps
    its state), or a new one. ``navigate`` also accepts a view model.
    """

    current = observable(None)
    current_route = observable(None)

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.back_stack = ObservableList()      # [(route, view model)]

    def go(self, route, parameter=None, remember=True):
        """Show ``route`` (a name, or a view model itself)."""
        with untracked():
            if isinstance(route, str):
                if route not in self.routes:
                    raise KeyError("no route %r" % route)
                name, view_model = route, self.routes[route](parameter)
            else:
                name, view_model = None, route
            if view_model is self.current:
                return
            with batch():
                if remember and self.current is not None:
                    self.back_stack.append((self.current_route, self.current))
                self.current_route, self.current = name, view_model

    @command
    def navigate(self, route):
        """Bindable: ``command="{nav.navigate}" command_parameter="settings"``."""
        self.go(route)

    @computed
    def can_go_back(self):
        return len(self.back_stack) > 0

    @command(can_execute=can_go_back)
    def go_back(self):
        self.current_route, self.current = self.back_stack.pop()
