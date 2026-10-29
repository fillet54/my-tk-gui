"""Reactive MVVM for tkinter.

View models (no Tk needed)::

    from mytkgui import observable, computed, command, async_command, Validatable, validator
    from mytkgui import Navigator, Messenger, CollectionView, dialogs

Views::

    from mytkgui import gui
    gui.run(VIEW, view_model, title="App")
"""

from .dialogs import DialogService, DialogViewModel, FakeDialogs, TkDialogs, dialogs
from .mvvm import CollectionView, Messenger, NavigationArgs, Navigator
from .reactive import (BoundCommand, Command, Computed, CycleError, ListChange, Observable, ObservableList,
                       Reaction, RelayCommand, autorun, batch, command, computed, observable, untracked,
                       watch)
from .tasks import AsyncRelayCommand, Cancelled, Dispatcher, Task, async_command, background, sleep
from .validation import ErrorMap, Validatable, validator

__version__ = "0.2.0"

__all__ = [
    "Observable", "Computed", "Reaction", "ObservableList", "ListChange", "observable", "computed",
    "autorun", "watch", "batch", "untracked", "CycleError",
    "Command", "RelayCommand", "BoundCommand", "command",
    "AsyncRelayCommand", "async_command", "Task", "Cancelled", "Dispatcher", "background", "sleep",
    "Validatable", "validator", "ErrorMap",
    "Navigator", "NavigationArgs", "Messenger", "CollectionView",
    "DialogService", "DialogViewModel", "TkDialogs", "FakeDialogs", "dialogs",
]
