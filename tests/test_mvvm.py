"""Commands, Messenger and Navigator. No Tk."""

import gc
import unittest

from mvvm import Messenger, Navigator
from reactive import RelayCommand, autorun, command, computed, observable


class Editor:
    name = observable("")
    saved = observable(None)

    @computed
    def can_save(self):
        return bool(self.name)

    @command(can_execute=can_save)
    def save(self):
        self.saved = self.name

    @command(can_execute=lambda self, item: item is not None)
    def open(self, item):
        self.saved = item


class TestCommands(unittest.TestCase):
    def test_command_without_parameter(self):
        e = Editor()
        self.assertFalse(e.save.can_execute())
        e.save()                                  # refused: can't execute
        self.assertIsNone(e.saved)
        e.name = "x"
        self.assertTrue(e.save.can_execute())
        e.save.execute()
        self.assertEqual(e.saved, "x")

    def test_command_with_parameter(self):
        e = Editor()
        self.assertFalse(e.open.can_execute(None))
        self.assertTrue(e.open.can_execute("a"))
        e.open.execute("a")
        self.assertEqual(e.saved, "a")

    def test_can_execute_is_tracked(self):
        e = Editor()
        seen = []
        autorun(lambda: seen.append(e.save.can_execute()))
        e.name = "x"
        self.assertEqual(seen, [False, True])

    def test_relay_command(self):
        state = {"n": 0, "allowed": False}
        cmd = RelayCommand(lambda by: state.update(n=state["n"] + by), lambda by: state["allowed"])
        seen = []
        autorun(lambda: seen.append(cmd.can_execute(1)))
        cmd.execute(5)
        self.assertEqual(state["n"], 0)
        state["allowed"] = True                   # not observable...
        cmd.raise_can_execute_changed()           # ...so say so
        self.assertEqual(seen, [False, True])
        cmd(5)
        self.assertEqual(state["n"], 5)

    def test_relay_command_without_parameter(self):
        calls = []
        cmd = RelayCommand(lambda: calls.append(1))
        cmd.execute("ignored")
        self.assertEqual(calls, [1])

    def test_bound_command_raise_can_execute_changed(self):
        class VM:
            limit = 1

            @command(can_execute=lambda self: self.limit > 0)
            def go(self):
                pass
        vm = VM()
        seen = []
        autorun(lambda: seen.append(vm.go.can_execute()))
        vm.limit = 0
        vm.go.raise_can_execute_changed()
        self.assertEqual(seen, [True, False])


class Ping:
    pass


class Special(Ping):
    pass


class Listener:
    def __init__(self):
        self.got = []

    def on(self, message):
        self.got.append(message)


class TestMessenger(unittest.TestCase):
    def test_delivers_by_type_and_subtype(self):
        m, a = Messenger(), Listener()
        m.register(a, Ping, a.on)
        m.send(Ping())
        m.send(Special())
        m.send("other")
        self.assertEqual(len(a.got), 2)

    def test_tokens_are_channels(self):
        m, a, b = Messenger(), Listener(), Listener()
        m.register(a, Ping, a.on, token="left")
        m.register(b, Ping, b.on)
        m.send(Ping(), token="left")
        self.assertEqual((len(a.got), len(b.got)), (1, 0))

    def test_recipients_are_weak(self):
        m, a = Messenger(), Listener()
        m.register(a, Ping, a.on)
        del a
        gc.collect()
        m.send(Ping())                            # no error, nobody left
        self.assertEqual(m._subscriptions, [])

    def test_unregister(self):
        m, a = Messenger(), Listener()
        m.register(a, Ping, a.on)
        m.unregister(a)
        m.send(Ping())
        self.assertEqual(a.got, [])


class TestNavigator(unittest.TestCase):
    def setUp(self):
        self.home = object()
        self.nav = Navigator({"home": lambda _: self.home, "item": lambda p: ("item", p)})

    def test_go_and_back(self):
        nav = self.nav
        self.assertFalse(nav.go_back.can_execute())
        nav.navigate.execute("home")
        nav.go("item", 7)
        self.assertEqual(nav.current, ("item", 7))
        self.assertEqual(nav.current_route, "item")
        self.assertTrue(nav.can_go_back)
        nav.go_back()
        self.assertIs(nav.current, self.home)
        self.assertEqual(nav.current_route, "home")
        self.assertFalse(nav.go_back.can_execute())

    def test_same_page_is_not_pushed_twice(self):
        self.nav.go("home")
        self.nav.go("home")
        self.assertEqual(len(self.nav.back_stack), 0)

    def test_view_model_target_and_unknown_route(self):
        page = object()
        self.nav.go(page)
        self.assertIs(self.nav.current, page)
        self.assertIsNone(self.nav.current_route)
        with self.assertRaises(KeyError):
            self.nav.go("missing")


if __name__ == "__main__":
    unittest.main()
