"""Drive the real demo window the way a user would. Skipped without a display."""

import tkinter as tk
import unittest

import demo
import gui
from expenses import sample
from reactive import command, computed, observable

try:
    _root = tk.Tk()
    _root.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False


def find(widget, cls):
    found = []
    for child in widget.winfo_children():
        if child.winfo_class() == cls:
            found.append(child)
        found += find(child, cls)
    return found


def type_into(entry, text):
    entry.delete(0, "end")
    entry.insert(0, text)


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class GuiTestCase(unittest.TestCase):
    def setUp(self):
        self.root = gui.create_root("test")
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def build(self, xml, vm):
        view = gui.realize(self.root, xml, vm)
        view.widget.pack()
        self.root.update()
        return view


class TestDemo(GuiTestCase):
    def setUp(self):
        super().setUp()
        self.vm = sample()
        self.view = self.build(demo.VIEW, self.vm)
        self.tree = find(self.root, "Treeview")[0]
        entries = find(self.root, "TEntry")
        # In the order they appear in demo.VIEW (sidebar comes first).
        self.new_desc, self.new_amount, self.sel_desc, self.search = entries
        self.add_button = [b for b in find(self.root, "TButton") if b.cget("text") == "Add expense"][0]

    def labels(self):
        return [l.cget("text") for l in find(self.root, "TLabel")]

    def test_initial_render(self):
        self.assertEqual(len(self.tree.get_children()), 6)
        self.assertIn("6 expenses", self.labels())
        self.assertIn("$94.35 left of $1,500.00", self.labels())
        self.assertTrue(self.add_button.instate(["disabled"]))
        self.assertTrue(self.sel_desc.instate(["disabled"]))   # nothing selected

    def test_typing_validates_and_enables_add(self):
        type_into(self.new_desc, "Lunch")
        self.assertIn("Enter an amount.", self.labels())
        type_into(self.new_amount, "12.5")
        self.assertTrue(self.add_button.instate(["!disabled"]))
        self.add_button.invoke()
        self.root.update()
        self.assertEqual(len(self.tree.get_children()), 7)
        self.assertEqual(self.new_desc.get(), "")
        self.assertEqual(self.sel_desc.get(), "Lunch")          # new row selected

    def test_select_and_edit_updates_row_and_totals(self):
        first = self.tree.get_children()[0]
        self.tree.selection_set(first)
        self.root.update()
        self.assertIs(self.vm.selected, self.vm.expenses[0])
        self.assertTrue(self.sel_desc.instate(["!disabled"]))

        type_into(self.sel_desc, "Big shop")
        self.assertEqual(self.tree.item(first, "values")[0], "Big shop")

        self.vm.selected.amount = 282.40
        self.root.update()
        self.assertEqual(self.tree.item(first, "values")[2], "$282.40")
        self.assertIn("Over budget by $5.65", self.labels())

    def test_search_filters_tree(self):
        type_into(self.search, "co")
        self.assertEqual(len(self.tree.get_children()), 2)
        self.assertIn("Showing 2 of 6 expenses", self.labels())

    def test_theme_binding_is_a_no_op_on_the_platform_theme(self):
        self.vm.dark_mode = True        # nothing to switch; must not fail
        self.assertIsNone(self.root.ui_theme)

    def test_theme_binding_drives_a_theme_with_modes(self):
        modes = []

        class FakeTheme:
            def __init__(self, root, scale):
                pass

            def set_mode(self, mode):
                modes.append(mode)
        root = gui.create_root("t", theme=FakeTheme)
        root.withdraw()
        self.addCleanup(root.destroy)
        vm = sample()
        gui.realize(root, demo.VIEW, vm)
        vm.dark_mode = True
        self.assertEqual(modes, ["light", "dark"])


class Counter:
    count = observable(0)
    text = observable("")

    @computed
    def can_inc(self):
        return self.count < 2

    @command(can_execute=can_inc)
    def inc(self):
        self.count += 1


class TestBindings(GuiTestCase):
    def test_number_field_does_not_fight_typing(self):
        class VM:
            amount = observable(1.0)
        vm = VM()
        self.build('<group><entry text="{amount|number}" /></group>', vm)
        entry = find(self.root, "TEntry")[0]
        type_into(entry, "12.")             # mid-typing; means 12.0
        self.assertEqual(vm.amount, 12.0)
        self.assertEqual(entry.get(), "12.")
        type_into(entry, "abc")
        self.assertTrue(entry.instate(["invalid"]))
        self.assertEqual(vm.amount, 12.0)
        vm.amount = 3
        self.assertEqual(entry.get(), "3")
        self.assertFalse(entry.instate(["invalid"]))

    def test_command_enables_itself(self):
        vm = Counter()
        self.build('<group><button text="{count}" command="{inc}" /></group>', vm)
        button = find(self.root, "TButton")[0]
        button.invoke(); button.invoke(); button.invoke()
        self.assertEqual(vm.count, 2)
        self.assertEqual(str(button.cget("text")), "2")
        self.assertTrue(button.instate(["disabled"]))

    def test_radio_group(self):
        class VM:
            size = observable("M")
        vm = VM()
        self.build("""<row>
            <radiobutton text="S" value="S" selected="{size}" />
            <radiobutton text="M" value="M" selected="{size}" />
        </row>""", vm)
        small, medium = find(self.root, "TRadiobutton")
        self.assertTrue(medium.instate(["selected"]))
        small.invoke()
        self.assertEqual(vm.size, "S")
        self.assertTrue(medium.instate(["!selected"]))

    def test_component_passthrough(self):
        gui.register("bigbutton", '<button text="$caption!" width="$w" />', w="20")
        vm = Counter()
        self.build('<group><bigbutton caption="Go" command="{inc}" /></group>', vm)
        button = find(self.root, "TButton")[0]
        self.assertEqual(button.cget("text"), "Go!")
        button.invoke()
        self.assertEqual(vm.count, 1)

    def test_reactions_disposed_with_widget(self):
        vm = Counter()
        view = self.build('<group><label text="{count}" /></group>', vm)
        label = find(self.root, "TLabel")[0]
        reactions = list(label._reactions)
        view.destroy()
        self.assertTrue(all(r.disposed for r in reactions))
        vm.count = 5   # must not touch the dead widget


class Page:
    def __init__(self, name):
        self.name = name


class OtherPage:
    pass


class Host:
    current = observable(None)


class TestContentAndParameters(GuiTestCase):
    def setUp(self):
        super().setUp()
        gui.template(Page, '<group><label text="Page {name}" /></group>')

    def labels(self):
        """Text of the labels that are laid out (the window itself is withdrawn)."""
        def shown(w):
            while w is not self.root:
                if not w.winfo_manager():
                    return False
                w = w.master
            return True
        return [str(l.cget("text")) for l in find(self.root, "TLabel") if shown(l)]

    def test_command_parameter_drives_can_execute_and_execute(self):
        class VM:
            item = observable(None)
            opened = observable(None)

            @command(can_execute=lambda self, item: item is not None)
            def open(self, item):
                self.opened = item
        vm = VM()
        self.build('<group><button text="Open" command="{open}" command_parameter="{item}" /></group>', vm)
        button = find(self.root, "TButton")[0]
        self.assertTrue(button.instate(["disabled"]))
        vm.item = "a"
        self.root.update()
        self.assertTrue(button.instate(["!disabled"]))
        button.invoke()
        self.assertEqual(vm.opened, "a")

    def test_literal_parameter_and_plain_callable(self):
        got = []

        class VM:
            pass
        vm = VM()
        vm.pick = got.append
        self.build('<group><button text="x" command="{pick}" command_parameter="settings" /></group>', vm)
        find(self.root, "TButton")[0].invoke()
        self.assertEqual(got, ["settings"])

    def test_content_swaps_views_by_type(self):
        host = Host()
        self.build('<group><content content="{current}" /></group>', host)
        self.assertEqual(self.labels(), [])
        host.current = Page("one")
        self.root.update()
        self.assertEqual(self.labels(), ["Page one"])
        host.current = Page("two")
        self.root.update()
        self.assertEqual(self.labels(), ["Page two"])
        self.assertEqual(len(find(self.root, "TLabel")), 1)   # old view destroyed
        host.current = OtherPage()
        self.root.update()
        self.assertIn("No view registered for OtherPage", self.labels()[0])

    def test_content_cache_keeps_recent_views(self):
        host = Host()
        self.build('<group><content content="{current}" cache="2" /></group>', host)
        a, b, c = Page("a"), Page("b"), Page("c")
        for page in (a, b, a):
            host.current = page
            self.root.update()
        self.assertEqual(len(find(self.root, "TLabel")), 2)   # a and b kept
        self.assertEqual(self.labels(), ["Page a"])
        host.current = c
        self.root.update()
        self.assertEqual(len(find(self.root, "TLabel")), 2)   # b evicted (oldest)


class TestShellDemo(GuiTestCase):
    def test_navigation(self):
        import shell
        vm = shell.Shell(sample())
        self.build(shell.SHELL, vm)
        nav_items = find(self.root, "TRadiobutton")
        nav_items[1].invoke()                                  # Expenses
        self.root.update()
        self.assertIsInstance(vm.nav.current, shell.ExpensesPage)
        vm.data.selected = vm.data.expenses[0]
        self.root.update()
        open_button = [b for b in find(self.root, "TButton") if str(b.cget("text")) == "Open"][0]
        open_button.invoke()
        self.root.update()
        self.assertIsInstance(vm.nav.current, shell.ExpensePage)
        self.assertEqual(vm.title, "Groceries")
        self.assertEqual(vm.section, "expenses")
        vm.nav.go_back()
        nav_items[2].invoke()                                  # Settings
        vm.nav.current.dark_mode = True                        # sent via the Messenger
        self.assertEqual(vm.theme, "dark")


class TestPx(unittest.TestCase):
    def test_px(self):
        self.assertEqual(gui._px("16", 2), 32)
        self.assertEqual(gui._px("12 0", 2), (24, 0))
        self.assertEqual(gui._px("3", 1.25), 4)
        self.assertEqual(gui._px("5p", 2), "5p")       # Tk units scale themselves

    def test_override(self):
        import os
        os.environ["MYTKGUI_SCALE"] = "1.5"
        try:
            self.assertEqual(gui.detect_scale(None), 1.5)
        finally:
            del os.environ["MYTKGUI_SCALE"]


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class TestScaling(unittest.TestCase):
    XML = """<group padding="10">
        <label text="a" padx="3 5" />
        <treeview><column key="x" width="100" /></treeview>
    </group>"""

    def build(self, scale):
        root = gui.create_root("t", scale=scale)
        root.withdraw()
        self.addCleanup(root.destroy)
        view = gui.realize(root, self.XML, object())
        frame = view.widget
        label = find(root, "TLabel")[0]
        tree = find(root, "Treeview")[0]
        return {
            "padding": [int(str(p)) for p in frame.cget("padding")],
            "padx": label.pack_info()["padx"],
            "column": tree.column("x", "width"),
            "tk scaling": round(float(root.tk.call("tk", "scaling")), 2),
        }

    def test_1x(self):
        self.assertEqual(self.build(1.0), {
            "padding": [10], "padx": (3, 5), "column": 100, "tk scaling": 1.33})

    def test_2x(self):
        self.assertEqual(self.build(2.0), {
            "padding": [20], "padx": (6, 10), "column": 200, "tk scaling": 2.67})


if __name__ == "__main__":
    unittest.main()
