"""The demo's behaviour, tested with no window at all."""

import unittest

from examples.expenses import Expense, ExpensesViewModel, sample


class TestNewExpenseForm(unittest.TestCase):
    def test_add_enabled_only_when_valid(self):
        vm = ExpensesViewModel()
        self.assertFalse(vm.add.can_execute())
        self.assertEqual(vm.form.error, "")          # quiet until typed into

        vm.form.description = "Lunch"
        self.assertEqual(vm.form.error, "Enter an amount.")
        vm.form.amount_text = "abc"
        self.assertEqual(vm.form.error, "“abc” isn't a number.")
        vm.form.amount_text = "-3"
        self.assertEqual(vm.form.error, "Amount must be more than zero.")
        vm.form.amount_text = "$12.50"
        self.assertEqual(vm.form.error, "")
        self.assertTrue(vm.add.can_execute())

    def test_add_appends_resets_and_selects(self):
        vm = ExpensesViewModel()
        vm.form.description, vm.form.amount_text = "Lunch", "12.5"
        vm.add()
        self.assertEqual(len(vm.expenses), 1)
        self.assertIs(vm.selected, vm.expenses[0])
        self.assertEqual(vm.selected.amount, 12.5)
        self.assertEqual((vm.form.description, vm.form.amount_text), ("", ""))
        self.assertFalse(vm.add.can_execute())


class TestFiltering(unittest.TestCase):
    def test_search_and_category(self):
        vm = sample()
        vm.search = "co"
        self.assertEqual([e.description for e in vm.visible], ["Concert tickets", "Coffee beans"])
        self.assertEqual(vm.summary, "Showing 2 of 6 expenses")
        vm.category_filter = "Food"
        self.assertEqual([e.description for e in vm.visible], ["Coffee beans"])
        self.assertAlmostEqual(vm.visible_total, 18.75)

    def test_clear_filters(self):
        vm = sample()
        self.assertFalse(vm.clear_filters.can_execute())
        vm.search = "x"
        self.assertTrue(vm.clear_filters.can_execute())
        vm.clear_filters()
        self.assertEqual((vm.search, vm.category_filter), ("", "All"))

    def test_editing_an_expense_refilters(self):
        vm = sample()
        vm.category_filter = "Fun"
        groceries = vm.expenses[0]
        groceries.category = "Fun"
        self.assertIn(groceries, vm.visible)


class TestBudget(unittest.TestCase):
    def test_totals_follow_edits(self):
        vm = ExpensesViewModel([Expense("A", "Food", 100.0)])
        vm.budget = 400
        self.assertEqual(vm.budget_used, 25.0)
        vm.expenses[0].amount = 500
        self.assertEqual(vm.budget_status, "Over budget by $100.00")
        self.assertEqual(vm.budget_used, 100.0)

    def test_remove(self):
        vm = sample()
        self.assertFalse(vm.remove.can_execute())
        vm.selected = vm.expenses[1]
        vm.remove()
        self.assertEqual(len(vm.expenses), 5)
        self.assertIsNone(vm.selected)


if __name__ == "__main__":
    unittest.main()
