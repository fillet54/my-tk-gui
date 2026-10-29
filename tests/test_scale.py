"""Size and lifetime: large lists, many computeds, views freeing their view models."""

import gc
import time
import tkinter as tk
import unittest
import weakref

from mytkgui import ObservableList, autorun, computed, gui, observable

try:
    _root = tk.Tk()
    _root.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False


class Row:
    name = observable("")
    amount = observable(0.0)

    def __init__(self, i):
        self.name, self.amount = "row %d" % i, float(i)


class Many:
    def __init__(self, n):
        self.rows = ObservableList(Row(i) for i in range(n))

    @computed
    def total(self):
        return sum(r.amount for r in self.rows)


class TestReactiveScale(unittest.TestCase):
    def test_wide_graph_updates_quickly(self):
        sources = [observable_cell(i) for i in range(2000)]
        sums = [computed_cell(lambda s=s: s.get() * 2) for s in sources]
        total = computed_cell(lambda: sum(c.get() for c in sums))
        seen = []
        autorun(lambda: seen.append(total.get()))
        start = time.perf_counter()
        for s in sources[:200]:
            s.set(s.get() + 1)
        elapsed = time.perf_counter() - start
        self.assertEqual(seen[-1], 2 * (sum(range(2000)) + 200))
        self.assertLess(elapsed, 2.0)


def observable_cell(v):
    from mytkgui import Observable
    return Observable(v)


def computed_cell(fn):
    from mytkgui import Computed
    return Computed(fn)


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class TestViewScale(unittest.TestCase):
    def setUp(self):
        self.root = gui.create_root("t", scale=1.0)
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_large_treeview_edits(self):
        vm = Many(3000)
        start = time.perf_counter()
        gui.realize(self.root, """<group><treeview items="{rows}">
            <column key="name" /><column key="amount" />
        </treeview><label text="{total}" /></group>""", vm).widget.pack()
        self.root.update()
        build = time.perf_counter() - start
        start = time.perf_counter()
        vm.rows[10].amount = 99.0
        vm.rows.append(Row(5000))
        self.root.update()
        edit = time.perf_counter() - start
        self.assertLess(build, 5.0)
        self.assertLess(edit, 2.0)

    def test_destroyed_view_frees_view_model(self):
        class VM:
            text = observable("x")
        vm = VM()
        view = gui.realize(self.root, '<group><entry text="{text}" /><label text="{text}" /></group>', vm)
        view.widget.pack()
        self.root.update()
        ref = weakref.ref(vm)
        view.destroy()
        self.root.update()
        del vm, view
        gc.collect()
        self.assertIsNone(ref())


if __name__ == "__main__":
    unittest.main()
