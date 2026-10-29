"""Background work without freezing the window: a UI-thread dispatcher and
async commands. No Tk here (``app.create_root`` connects the dispatcher to Tk).

Write a command as ``async def``. It runs on the UI thread, so it may read
and write the view model freely; ``await background(fn, ...)`` runs slow
work on a worker thread and comes back to the UI thread with the result::

    class Page:
        rows = observable(())

        @async_command
        async def load(self):
            self.rows = await background(fetch_rows)     # fetch_rows runs on a worker

    page.load.is_running     # True while it runs (bind a spinner to it)
    page.load.error          # the exception, if the last run failed
    page.load.cancel()       # raises Cancelled at the next await

Worker code must not touch observables or Tk; return a value instead.
"""

import functools
from typing import Any, Callable
import queue
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

from .reactive import Command, Observable, RelayCommand, _call, _takes_parameter, batch, untracked

__all__ = ["Dispatcher", "Task", "Cancelled", "background", "sleep", "async_command",
           "AsyncRelayCommand"]


# --------------------------------------------------------------------------
# Dispatcher
# --------------------------------------------------------------------------

class Dispatcher:
    """Runs callbacks on the UI thread, in the order they were posted.

    ``Dispatcher.current`` is the app's dispatcher. With Tk, ``create_root``
    drains it from the event loop; without Tk (tests), call ``run_pending()``
    or ``wait(task)``.
    """

    current = None

    def __init__(self):
        self._queue = queue.SimpleQueue()
        self.ui_thread = threading.get_ident()

    def post(self, fn, *args):
        """Run ``fn(*args)`` on the UI thread soon. Safe from any thread."""
        self._queue.put((fn, args))

    def invoke(self, fn, *args):
        """Run now if on the UI thread, else post."""
        if threading.get_ident() == self.ui_thread:
            return fn(*args)
        self.post(fn, *args)

    def run_pending(self):
        """Run everything posted so far (call on the UI thread)."""
        ran = 0
        while True:
            try:
                fn, args = self._queue.get_nowait()
            except queue.Empty:
                return ran
            ran += 1
            try:
                fn(*args)
            except Exception:
                traceback.print_exc()

    def wait(self, task, timeout=5.0):
        """Pump posted callbacks until ``task`` finishes (tests, scripts)."""
        import time
        end = time.monotonic() + timeout
        while task.is_running:
            if time.monotonic() > end:
                raise TimeoutError("task still running after %.1fs" % timeout)
            if not self.run_pending():
                time.sleep(0.002)
        self.run_pending()
        return task


Dispatcher.current = Dispatcher()

_workers = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mytkgui")


# --------------------------------------------------------------------------
# Awaitables
# --------------------------------------------------------------------------

class Cancelled(Exception):
    """Raised inside an async command at its next ``await`` after ``cancel()``."""


class _Waitable:
    """Something a task can await: resumes the task on the UI thread."""

    def __init__(self):
        self._done, self._result, self._error, self._callbacks = False, None, None, []

    def _finish(self, result=None, error=None):
        # Called on any thread; delivery happens on the UI thread.
        def deliver():
            if self._done:
                return
            self._done, self._result, self._error = True, result, error
            for callback in self._callbacks:
                callback(self)
        Dispatcher.current.post(deliver)

    def _on_done(self, callback):
        if self._done:
            callback(self)
        else:
            self._callbacks.append(callback)

    def __await__(self):
        yield self
        if self._error is not None:
            raise self._error
        return self._result


def background(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> "_Waitable":
    """Run ``fn`` on a worker thread; awaiting it gives its result (or raises)."""
    waitable = _Waitable()

    def work():
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:
            waitable._finish(error=exc)
        else:
            waitable._finish(result)
    _workers.submit(work)
    return waitable


def sleep(seconds: float) -> "_Waitable":
    """Await a pause without blocking the window."""
    waitable = _Waitable()
    timer = threading.Timer(seconds, waitable._finish)
    timer.daemon = True
    timer.start()
    return waitable


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------

class Task:
    """One run of an async function, stepped on the UI thread."""

    def __init__(self, coroutine, on_finish=None):
        self._coroutine = coroutine
        self._on_finish = on_finish
        self._status = Observable("running")
        self.result = None
        self.error = None
        self._cancelled = False
        self._waiting = None
        self._step(None, None)

    @property
    def status(self):
        """"running", "done", "failed" or "cancelled" (observable)."""
        return self._status.get()

    @property
    def is_running(self):
        return self.status == "running"

    def cancel(self):
        if not self.is_running or self._cancelled:
            return
        self._cancelled = True
        if self._waiting is not None:          # don't wait for the worker to finish
            self._waiting = None
            Dispatcher.current.post(self._step, None, Cancelled())

    def _resume(self, waitable):
        if waitable is not self._waiting:      # cancelled meanwhile
            return
        self._waiting = None
        self._step(waitable, None)

    def _step(self, waitable, error):
        try:
            with batch():
                if error is not None:
                    yielded = self._coroutine.throw(error)
                elif waitable is None:
                    yielded = self._coroutine.send(None)
                else:
                    # Re-enter __await__ after its yield: it returns or raises.
                    yielded = self._coroutine.send(None)
        except StopIteration as stop:
            self._finish("done", result=stop.value)
            return
        except Cancelled:
            self._finish("cancelled")
            return
        except Exception as exc:
            self._finish("failed", error=exc)
            return
        if not isinstance(yielded, _Waitable):
            self._coroutine.close()
            self._finish("failed", error=TypeError(
                "async commands can await background(), sleep() and other tasks, not %r" % (yielded,)))
            return
        if self._cancelled:
            Dispatcher.current.post(self._step, None, Cancelled())
            return
        self._waiting = yielded
        yielded._on_done(self._resume)

    def _finish(self, status, result=None, error=None):
        self.result, self.error = result, error
        with untracked():
            self._status.set(status)
        if self._on_finish:
            self._on_finish(self)

    def __await__(self):
        # Awaiting a task from another task.
        waitable = _Waitable()
        if not self.is_running:
            waitable._done, waitable._result, waitable._error = True, self.result, self.error
        else:
            previous = self._on_finish

            def chain(task):
                if previous:
                    previous(task)
                waitable._finish(task.result, task.error)
            self._on_finish = chain
        return waitable.__await__()


def _report(task):
    if task.status == "failed":
        print("mytkgui: async command failed:", file=sys.stderr)
        traceback.print_exception(type(task.error), task.error, task.error.__traceback__)


# --------------------------------------------------------------------------
# Async commands
# --------------------------------------------------------------------------

class AsyncRelayCommand(Command):
    """A command whose action is ``async def``. It can't run again while
    running (unless ``concurrent=True``). ``is_running``, ``error`` and
    ``task`` are observable; ``cancel`` is a bindable command."""

    def __init__(self, execute, can_execute=None, concurrent=False, name=None):
        self._execute = execute
        self._check = can_execute
        self._concurrent = concurrent
        self._running = Observable(0)
        self._error = Observable(None)
        self._task = Observable(None)
        self._version = Observable(0)
        self.name = name or getattr(execute, "__name__", "command")
        self.cancel = RelayCommand(self._cancel, lambda: self.is_running, name="cancel")

    @property
    def is_running(self):
        return self._running.get() > 0

    @property
    def error(self):
        return self._error.get()

    @property
    def task(self):
        return self._task.get()

    def can_execute(self, parameter=None):
        self._version.get()
        if self.is_running and not self._concurrent:
            return False
        return self._check is None or bool(_call(self._check, (), parameter))

    def execute(self, parameter=None):
        with untracked():
            if not self.can_execute(parameter):
                return None
        coroutine = _call(self._execute, (), parameter)
        with untracked():
            self._error.set(None)
            self._running.set(self._running.get() + 1)
        task = Task(coroutine, on_finish=self._finished)
        if task.is_running:
            with untracked():
                self._task.set(task)
        return task

    def _finished(self, task):
        with untracked():
            self._running.set(max(0, self._running.get() - 1))
            if task.status == "failed":
                self._error.set(task.error)
        _report(task)

    def _cancel(self):
        task = self.task
        if task is not None:
            task.cancel()

    def raise_can_execute_changed(self):
        with untracked():
            self._version.set(self._version.get() + 1)

    def __repr__(self):
        return "<AsyncRelayCommand %s>" % self.name


class _AsyncCommandDescriptor:
    def __init__(self, fn, can_execute, concurrent):
        self._fn = fn
        self._check = can_execute
        self._concurrent = concurrent
        self._name = fn.__name__
        self.__doc__ = fn.__doc__

    def __set_name__(self, owner, name):
        self._name = name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        cells = instance.__dict__.setdefault("__reactive_cells__", {})
        key = self._name + ".async"
        command = cells.get(key)
        if command is None:
            check = self._check
            if check is not None and hasattr(check, "__get__") and not callable(check):
                bound_check = lambda check=check: check.__get__(instance)
            elif check is not None:
                bound_check = (functools.partial(check, instance) if not _takes_parameter(check, 1)
                               else (lambda parameter, check=check: check(instance, parameter)))
            else:
                bound_check = None
            fn = self._fn
            execute = (functools.partial(fn, instance) if not _takes_parameter(fn, 1)
                       else (lambda parameter, fn=fn: fn(instance, parameter)))
            command = cells[key] = AsyncRelayCommand(execute, bound_check, self._concurrent,
                                                     name=self._name)
        return command


def async_command(fn: "Callable | None" = None, *, can_execute: Any = None, concurrent: bool = False) -> Any:
    """Declares an ``async def`` view model action (see the module docs)."""
    if fn is None:
        return lambda f: _AsyncCommandDescriptor(f, can_execute, concurrent)
    return _AsyncCommandDescriptor(fn, can_execute, concurrent)
