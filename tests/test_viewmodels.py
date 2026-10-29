"""Tasks, validation, dialogs, navigation lifecycle and collection views. No Tk."""

import threading
import time
import unittest

from mytkgui import (Cancelled, CollectionView, DialogService, DialogViewModel, Dispatcher, FakeDialogs,
                     Navigator, ObservableList, Validatable, async_command, autorun, background,
                     command, computed, dialogs, observable, sleep, validator)
from mytkgui.bindings import Binding, BindingError, parse, resource, strict_bindings


def wait(task):
    return Dispatcher.current.wait(task)


class Loader:
    rows = observable(())
    log = observable(())

    @async_command
    async def load(self):
        self.log = self.log + (("start", threading.get_ident()),)
        rows = await background(lambda: [1, 2, 3])
        self.log = self.log + (("resumed", threading.get_ident()),)
        self.rows = tuple(rows)
        return len(rows)

    @async_command
    async def slow(self):
        await sleep(5)
        self.rows = ("never",)

    @async_command
    async def broken(self):
        await background(lambda: 1 / 0)

    @async_command(can_execute=lambda self, n: n > 0)
    async def count(self, n):
        total = 0
        for _ in range(n):
            total += await background(lambda: 1)
        return total


class TestAsyncCommands(unittest.TestCase):
    def test_runs_worker_and_resumes_on_ui_thread(self):
        vm = Loader()
        task = vm.load.execute()
        self.assertTrue(vm.load.is_running)
        self.assertFalse(vm.load.can_execute())          # no double runs
        wait(task)
        self.assertEqual(task.status, "done")
        self.assertEqual(task.result, 3)
        self.assertEqual(vm.rows, (1, 2, 3))
        ui = threading.get_ident()
        self.assertEqual([t for _, t in vm.log], [ui, ui])
        self.assertFalse(vm.load.is_running)

    def test_is_running_is_observable(self):
        vm = Loader()
        seen = []
        autorun(lambda: seen.append(vm.load.is_running))
        wait(vm.load.execute())
        self.assertEqual(seen, [False, True, False])

    def test_cancel(self):
        vm = Loader()
        task = vm.slow.execute()
        self.assertTrue(vm.slow.cancel.can_execute())
        vm.slow.cancel()
        wait(task)
        self.assertEqual(task.status, "cancelled")
        self.assertEqual(vm.rows, ())

    def test_failure_is_captured(self):
        import io
        import contextlib
        vm = Loader()
        with contextlib.redirect_stderr(io.StringIO()):
            task = wait(vm.broken.execute())
        self.assertEqual(task.status, "failed")
        self.assertIsInstance(vm.broken.error, ZeroDivisionError)

    def test_parameter(self):
        vm = Loader()
        self.assertFalse(vm.count.can_execute(0))
        self.assertEqual(wait(vm.count.execute(3)).result, 3)


class Form(Validatable):
    name = observable("")
    low = observable(0)
    high = observable(10)

    @validator("name")
    def _name(self, value):
        if not value.strip():
            return "Required."

    @validator("high", "low")
    def _range(self):
        if self.low > self.high:
            return "Low must not exceed high."


class TestValidation(unittest.TestCase):
    def test_errors_appear_once_touched(self):
        f = Form()
        self.assertFalse(f.is_valid)
        self.assertEqual(f.errors.name, "")             # not touched yet
        self.assertEqual(f.all_errors.name, "Required.")
        f.touch("name")
        self.assertEqual(f.errors.name, "Required.")
        self.assertEqual(f.error_for("name"), "Required.")
        f.name = "x"
        self.assertEqual(f.errors.name, "")
        self.assertTrue(f.is_valid)

    def test_validate_shows_everything(self):
        f = Form()
        f.name, f.low = "x", 20
        self.assertFalse(f.validate())
        self.assertEqual(f.errors.high, "Low must not exceed high.")
        self.assertEqual(f.errors.low, "Low must not exceed high.")
        f.reset_validation()
        self.assertFalse(f.errors)

    def test_errors_are_reactive(self):
        f = Form()
        f.touch("name")
        seen = []
        autorun(lambda: seen.append(f.errors.name))
        f.name = "ok"
        self.assertEqual(seen, ["Required.", ""])


class TestDialogs(unittest.TestCase):
    def setUp(self):
        self.previous = DialogService.current
        self.addCleanup(setattr, DialogService, "current", self.previous)

    def test_fake_answers_and_records(self):
        DialogService.current = fake = FakeDialogs(ask_yes_no=[False, True], open_file="/tmp/a.csv")
        self.assertFalse(dialogs.ask_yes_no("Delete?"))
        self.assertTrue(dialogs.ask_yes_no("Really?"))
        self.assertEqual(dialogs.open_file("Open"), "/tmp/a.csv")
        self.assertEqual([c[0] for c in fake.calls], ["ask_yes_no", "ask_yes_no", "open_file"])

    def test_custom_dialog_view_model(self):
        class Rename(DialogViewModel):
            name = observable("")

            @computed
            def can_accept(self):
                return bool(self.name)

            def make_result(self):
                return self.name

        def fill(vm):
            self.assertFalse(vm.accept.can_execute())
            vm.name = "new"
            vm.accept()
        DialogService.current = FakeDialogs(show=fill)
        self.assertEqual(dialogs.show(Rename()), "new")

    def test_no_service(self):
        DialogService.current = None
        with self.assertRaises(RuntimeError):
            dialogs.info("x")


class Page:
    def __init__(self, name, dirty=False):
        self.name, self.dirty, self.events = name, dirty, []

    def on_navigating_from(self, args):
        return not self.dirty

    def on_navigated_from(self, args):
        self.events.append(("from", args.mode))

    def on_navigated_to(self, args):
        self.events.append(("to", args.mode, args.parameter))


class AsyncPage:
    loaded = observable(False)

    async def on_navigated_to(self, args):
        self.loaded = await background(lambda: True)


class TestNavigationLifecycle(unittest.TestCase):
    def test_hooks_and_guard(self):
        a, b = Page("a"), Page("b")
        nav = Navigator({"a": lambda _: a, "b": lambda p: b})
        nav.go("a")
        nav.go("b", 7)
        self.assertEqual(a.events, [("to", "new", None), ("from", "new")])
        self.assertEqual(b.events, [("to", "new", 7)])
        b.dirty = True
        self.assertFalse(nav.go("a"))           # refused
        nav.go_back()                           # also refused
        self.assertIs(nav.current, b)
        b.dirty = False
        nav.go_back()
        self.assertIs(nav.current, a)
        self.assertEqual(a.events[-1], ("to", "back", None))

    def test_async_on_navigated_to(self):
        page = AsyncPage()
        Navigator({"p": lambda _: page}).go("p")
        deadline = time.monotonic() + 3
        while not page.loaded and time.monotonic() < deadline:
            Dispatcher.current.run_pending()
            time.sleep(0.005)
        self.assertTrue(page.loaded)


class Item:
    def __init__(self, name, amount, kind):
        self.name, self.amount, self.kind = name, amount, kind


class TestCollectionView(unittest.TestCase):
    def setUp(self):
        self.source = ObservableList([Item("a", 3, "x"), Item("b", 1, "y"), Item("c", None, "x")])

    def test_filter_sort_group(self):
        class VM:
            text = observable("")
        vm = VM()
        view = CollectionView(self.source, filter=lambda i: vm.text in i.name, sort_key="amount")
        self.assertEqual([i.name for i in view], ["b", "a", "c"])      # None last
        view.sort_by("amount")                                         # same key: flip
        self.assertEqual([i.name for i in view.items], ["a", "b", "c"])
        vm.text = "a"
        self.assertEqual([i.name for i in view], ["a"])
        vm.text = ""
        view.group_key = "kind"
        self.assertEqual([(k, len(g)) for k, g in view.groups], [("x", 2), ("y", 1)])

    def test_follows_source(self):
        view = CollectionView(self.source)
        seen = []
        autorun(lambda: seen.append(len(view)))
        self.source.append(Item("d", 0, "y"))
        self.assertEqual(seen, [3, 4])


class TestBindingOptions(unittest.TestCase):
    def tearDown(self):
        strict_bindings(False)

    def test_options(self):
        class VM:
            name = observable(None)
        vm = VM()
        b = Binding(lambda: vm, "name; null=(none); mode=oneway; trigger=focus; delay=200")
        self.assertEqual(b.value(), "(none)")
        self.assertFalse(b.two_way)
        self.assertEqual((b.trigger, b.delay), ("focus", 200))
        self.assertTrue(Binding(lambda: vm, "name; mode=onetime").one_time)

    def test_fallback_and_errors(self):
        class VM:
            pass
        vm = VM()
        self.assertEqual(Binding(lambda: vm, "missing; fallback=—").value(), "—")
        strict_bindings(True)
        with self.assertRaises(BindingError) as cm:
            Binding(lambda: vm, "missing", where='<label text="{missing}">, view line 3').value()
        self.assertIn("view line 3", str(cm.exception))
        self.assertIn("missing", str(cm.exception))
        with self.assertRaises(BindingError):
            Binding(lambda: vm, "x; colour=red")

    def test_resources(self):
        resource("danger", "#c42b1c")
        self.assertEqual(parse("{@danger}", lambda: None), "#c42b1c")
        self.assertEqual(parse("{@gap}", lambda: None, resources={"gap": "12"}), "12")
        with self.assertRaises(BindingError):
            parse("{@nope}", lambda: None)


if __name__ == "__main__":
    unittest.main()
