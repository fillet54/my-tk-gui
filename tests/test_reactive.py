import gc
import unittest
import weakref

from reactive import (
    Computed, CycleError, Observable, ObservableList, autorun, batch,
    computed, observable, untracked, watch,
)


class Person:
    first = observable("")
    last = observable("")
    show_last = observable(True)

    def __init__(self, first="", last=""):
        self.first, self.last = first, last
        self.full_calls = 0

    @computed
    def full(self):
        self.full_calls += 1
        if self.show_last:
            return f"{self.first} {self.last}".strip()
        return self.first

    @computed
    def greeting(self):
        return "Hello, " + self.full


class TestObservable(unittest.TestCase):
    def test_get_set(self):
        o = Observable(1)
        o.set(2)
        self.assertEqual(o.get(), 2)
        o.value = 3
        self.assertEqual(o.value, 3)

    def test_equal_write_does_not_notify(self):
        o = Observable(1)
        runs = []
        autorun(lambda: runs.append(o.get()))
        o.set(1)
        self.assertEqual(runs, [1])


class TestComputed(unittest.TestCase):
    def test_lazy_and_cached(self):
        p = Person("Ada", "Lovelace")
        self.assertEqual(p.full_calls, 0)
        self.assertEqual(p.full, "Ada Lovelace")
        self.assertEqual(p.full, "Ada Lovelace")
        self.assertEqual(p.full_calls, 1)

    def test_recomputes_after_change(self):
        p = Person("Ada", "Lovelace")
        p.full
        p.last = "Byron"
        self.assertEqual(p.full_calls, 1)  # still lazy
        self.assertEqual(p.full, "Ada Byron")
        self.assertEqual(p.full_calls, 2)

    def test_chained(self):
        p = Person("Ada", "Lovelace")
        self.assertEqual(p.greeting, "Hello, Ada Lovelace")
        p.first = "Augusta"
        self.assertEqual(p.greeting, "Hello, Augusta Lovelace")

    def test_dynamic_dependencies(self):
        p = Person("Ada", "Lovelace")
        p.show_last = False
        self.assertEqual(p.full, "Ada")
        calls = p.full_calls
        p.last = "Byron"           # not read on this branch
        self.assertEqual(p.full, "Ada")
        self.assertEqual(p.full_calls, calls)

    def test_per_instance(self):
        a, b = Person("A"), Person("B")
        self.assertEqual((a.full, b.full), ("A", "B"))

    def test_read_only(self):
        with self.assertRaises(AttributeError):
            Person().full = "x"

    def test_error_cached_then_recovers(self):
        d = Observable(0)
        calls = []

        def inv():
            calls.append(1)
            return 1 / d.get()

        c = Computed(inv)
        for _ in range(2):
            with self.assertRaises(ZeroDivisionError):
                c.get()
        self.assertEqual(len(calls), 1)
        d.set(4)
        self.assertEqual(c.get(), 0.25)

    def test_cycle(self):
        holder = {}
        c = Computed(lambda: holder["c"].get() + 1, name="loop")
        holder["c"] = c
        with self.assertRaises(CycleError):
            c.get()


class TestReactions(unittest.TestCase):
    def test_autorun_reruns_on_change(self):
        p = Person("Ada", "Lovelace")
        seen = []
        r = autorun(lambda: seen.append(p.greeting))
        p.first = "Augusta"
        self.assertEqual(seen, ["Hello, Ada Lovelace", "Hello, Augusta Lovelace"])
        r.dispose()
        p.first = "X"
        self.assertEqual(len(seen), 2)

    def test_batch_coalesces(self):
        p = Person("Ada", "Lovelace")
        seen = []
        autorun(lambda: seen.append(p.full))
        with batch():
            p.first = "Charles"
            p.last = "Babbage"
        self.assertEqual(seen, ["Ada Lovelace", "Charles Babbage"])

    def test_diamond_runs_once_with_consistent_values(self):
        a = Observable(1)
        double = Computed(lambda: a.get() * 2)
        triple = Computed(lambda: a.get() * 3)
        seen = []
        autorun(lambda: seen.append((double.get(), triple.get())))
        a.set(2)
        self.assertEqual(seen, [(2, 3), (4, 6)])

    def test_deferred_scheduler(self):
        queue = []
        o = Observable(1)
        seen = []
        autorun(lambda: seen.append(o.get()), scheduler=queue.append)
        o.set(2)
        o.set(3)
        self.assertEqual(seen, [1])
        self.assertEqual(len(queue), 1)   # coalesced
        queue.pop()()
        self.assertEqual(seen, [1, 3])

    def test_watch_skips_unchanged_and_callback_untracked(self):
        p = Person("Ada", "Lovelace")
        other = Observable(0)
        seen = []

        def cb(v):
            other.get()  # must not become a dependency
            seen.append(v)

        watch(lambda: p.first.upper(), cb)
        p.first = "ADA"                    # same upper-case value
        other.set(1)
        p.first = "Bob"
        self.assertEqual(seen, ["ADA", "BOB"])

    def test_error_in_one_reaction_does_not_block_others(self):
        o = Observable(0)
        seen = []

        def bad():
            if o.get():
                raise ValueError("boom")

        autorun(bad)
        autorun(lambda: seen.append(o.get()))
        with self.assertRaises(ValueError):
            o.set(1)
        self.assertEqual(seen, [0, 1])

    def test_untracked(self):
        o = Observable(1)
        seen = []

        def run():
            with untracked():
                seen.append(o.get())

        autorun(run)
        o.set(2)
        self.assertEqual(seen, [1])


class TestObservableList(unittest.TestCase):
    def test_tracks_mutations(self):
        items = ObservableList([1, 2])
        total = Computed(lambda: sum(items))
        self.assertEqual(total.get(), 3)
        items.append(3)
        self.assertEqual(total.get(), 6)
        items[0] = 10
        self.assertEqual(total.get(), 15)
        del items[1]
        self.assertEqual(total.get(), 13)
        items.replace([5])
        self.assertEqual(total.get(), 5)

    def test_extend_notifies_once(self):
        items = ObservableList()
        seen = []
        autorun(lambda: seen.append(len(items)))
        items.extend([1, 2, 3])
        self.assertEqual(seen, [0, 3])

    def test_descriptor_factory(self):
        class Todo:
            items = observable(factory=ObservableList)

            @computed
            def count(self):
                return len(self.items)

        a, b = Todo(), Todo()
        a.items.append("x")
        self.assertEqual((a.count, b.count), (1, 0))


class TestMemory(unittest.TestCase):
    def test_stale_view_model_is_released(self):
        shared = Observable(1)

        class VM:
            @computed
            def doubled(self):
                return shared.get() * 2

        vm = VM()
        vm.doubled
        ref = weakref.ref(vm)
        del vm
        shared.set(2)   # invalidation unsubscribes the computed
        gc.collect()
        self.assertIsNone(ref())


if __name__ == "__main__":
    unittest.main()
