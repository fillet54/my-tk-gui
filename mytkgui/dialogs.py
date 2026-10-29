"""Dialogs from view models, without Tk in the view model (an IDialogService).

    from mytkgui.dialogs import dialogs

    class Page:
        @command
        def delete(self):
            if dialogs.ask_yes_no("Delete this expense?", title="Delete"):
                ...

``dialogs`` forwards to ``DialogService.current``: ``TkDialogs`` once
``create_root`` has run, or a ``FakeDialogs`` you install in tests::

    fake = FakeDialogs(ask_yes_no=False)
    DialogService.current = fake
    page.delete()
    assert fake.calls[0][0] == "ask_yes_no"

Custom dialogs are view models shown modally with a view registered by
``gui.template`` (WinUI's ContentDialog). Subclass ``DialogViewModel``,
bind buttons to ``{accept}`` / ``{cancel}``, and ``dialogs.show(vm)``
returns ``vm.result`` (None when cancelled).
"""

from .reactive import command, computed, observable

__all__ = ["DialogService", "TkDialogs", "FakeDialogs", "DialogViewModel", "dialogs"]

ALL_FILES = (("All files", "*"),)


class DialogService:
    """What view models may ask for. ``current`` is the app's service."""

    current = None

    def info(self, message, title=""):
        raise NotImplementedError

    def warning(self, message, title=""):
        raise NotImplementedError

    def error(self, message, title=""):
        raise NotImplementedError

    def ask_yes_no(self, message, title=""):
        raise NotImplementedError

    def ask_ok_cancel(self, message, title=""):
        raise NotImplementedError

    def ask_yes_no_cancel(self, message, title=""):
        """True, False, or None for Cancel."""
        raise NotImplementedError

    def open_file(self, title="", filetypes=ALL_FILES, initial_dir=None):
        """A path, or None."""
        raise NotImplementedError

    def open_files(self, title="", filetypes=ALL_FILES, initial_dir=None):
        """A list of paths (empty when cancelled)."""
        raise NotImplementedError

    def save_file(self, title="", filetypes=ALL_FILES, default_extension="", initial_file=""):
        raise NotImplementedError

    def choose_directory(self, title="", initial_dir=None):
        raise NotImplementedError

    def show(self, view_model, title=""):
        """Show a custom dialog for ``view_model`` and return its result."""
        raise NotImplementedError


class _Current:
    def __getattr__(self, name):
        service = DialogService.current
        if service is None:
            raise RuntimeError("no DialogService: call gui.create_root() or set "
                               "DialogService.current (FakeDialogs in tests)")
        return getattr(service, name)


dialogs = _Current()


class DialogViewModel:
    """Base for custom dialogs. Override ``can_accept`` (a computed) and set
    ``result`` before accepting, or override ``make_result()``."""

    title = "Dialog"
    closed = observable(False)
    result = observable(None)

    @computed
    def can_accept(self):
        return True

    def make_result(self):
        return True

    # Looked up on the instance, so subclasses can override can_accept.
    @command(can_execute=lambda self: self.can_accept)
    def accept(self):
        if self.result is None:
            self.result = self.make_result()
        self.closed = True

    @command
    def cancel(self):
        self.result = None
        self.closed = True


class TkDialogs(DialogService):
    """Tk message boxes and file pickers, parented to ``root``."""

    def __init__(self, root):
        self.root = root

    def _box(self, name, message, title):
        from tkinter import messagebox
        return getattr(messagebox, name)(title or self.root.title(), message, parent=self._parent())

    def _parent(self):
        focus = self.root.focus_get()
        return focus.winfo_toplevel() if focus is not None else self.root

    def info(self, message, title=""):
        self._box("showinfo", message, title)

    def warning(self, message, title=""):
        self._box("showwarning", message, title)

    def error(self, message, title=""):
        self._box("showerror", message, title)

    def ask_yes_no(self, message, title=""):
        return bool(self._box("askyesno", message, title))

    def ask_ok_cancel(self, message, title=""):
        return bool(self._box("askokcancel", message, title))

    def ask_yes_no_cancel(self, message, title=""):
        return self._box("askyesnocancel", message, title)

    def open_file(self, title="", filetypes=ALL_FILES, initial_dir=None):
        from tkinter import filedialog
        return filedialog.askopenfilename(parent=self._parent(), title=title, filetypes=filetypes,
                                          initialdir=initial_dir) or None

    def open_files(self, title="", filetypes=ALL_FILES, initial_dir=None):
        from tkinter import filedialog
        return list(filedialog.askopenfilenames(parent=self._parent(), title=title,
                                                filetypes=filetypes, initialdir=initial_dir))

    def save_file(self, title="", filetypes=ALL_FILES, default_extension="", initial_file=""):
        from tkinter import filedialog
        return filedialog.asksaveasfilename(parent=self._parent(), title=title, filetypes=filetypes,
                                            defaultextension=default_extension,
                                            initialfile=initial_file) or None

    def choose_directory(self, title="", initial_dir=None):
        from tkinter import filedialog
        return filedialog.askdirectory(parent=self._parent(), title=title, initialdir=initial_dir) or None

    def show(self, view_model, title=""):
        import tkinter as tk
        from tkinter import ttk

        from .reactive import watch
        from .views import realize_for

        parent = self._parent()
        window = tk.Toplevel(parent)
        window.title(title or getattr(view_model, "title", ""))
        window.transient(parent)
        frame = ttk.Frame(window)
        frame.pack(fill="both", expand=True)
        view = realize_for(frame, view_model)
        view.widget.pack(fill="both", expand=True)
        window.protocol("WM_DELETE_WINDOW", view_model.cancel)
        window.bind("<Escape>", lambda e: view_model.cancel(), add="+")
        closer = watch(lambda: getattr(view_model, "closed", False),
                       lambda closed: closed and window.destroy())
        window.update_idletasks()
        # Centre over the parent.
        x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_reqheight()) // 3
        window.geometry("+%d+%d" % (max(0, x), max(0, y)))
        window.grab_set()
        window.wait_window()
        closer.dispose()
        return getattr(view_model, "result", None)


class FakeDialogs(DialogService):
    """Scripted answers for tests; ``calls`` records ``(method, args)``.

        FakeDialogs(ask_yes_no=False, open_file="/tmp/x.csv")
        FakeDialogs(show=lambda vm: vm.accept())   # drive custom dialogs
    """

    def __init__(self, **answers):
        self.answers = answers
        self.calls = []

    def _answer(self, name, default, *args):
        self.calls.append((name, args))
        answer = self.answers.get(name, default)
        if isinstance(answer, list):           # a queue of answers
            return answer.pop(0) if answer else default
        return answer

    def info(self, message, title=""):
        self._answer("info", None, message, title)

    def warning(self, message, title=""):
        self._answer("warning", None, message, title)

    def error(self, message, title=""):
        self._answer("error", None, message, title)

    def ask_yes_no(self, message, title=""):
        return self._answer("ask_yes_no", True, message, title)

    def ask_ok_cancel(self, message, title=""):
        return self._answer("ask_ok_cancel", True, message, title)

    def ask_yes_no_cancel(self, message, title=""):
        return self._answer("ask_yes_no_cancel", True, message, title)

    def open_file(self, title="", filetypes=ALL_FILES, initial_dir=None):
        return self._answer("open_file", None, title)

    def open_files(self, title="", filetypes=ALL_FILES, initial_dir=None):
        return self._answer("open_files", [], title)

    def save_file(self, title="", filetypes=ALL_FILES, default_extension="", initial_file=""):
        return self._answer("save_file", None, title)

    def choose_directory(self, title="", initial_dir=None):
        return self._answer("choose_directory", None, title)

    def show(self, view_model, title=""):
        self.calls.append(("show", (view_model,)))
        driver = self.answers.get("show")
        if callable(driver):
            driver(view_model)
        return getattr(view_model, "result", None)
