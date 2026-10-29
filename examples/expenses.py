"""View model for the expense tracker demo.

No Tk here. Every number, message and enabled/disabled state the window
shows is a plain attribute you can read and test (see tests/test_expenses.py).
Nothing below says *when* anything updates -- dependencies are discovered
automatically.
"""

from mytkgui import ObservableList, command, computed, observable

CATEGORIES = ["Food", "Travel", "Housing", "Fun", "Other"]


class Expense:
    description = observable("")
    category = observable("Other")
    amount = observable(0.0)

    def __init__(self, description, category, amount):
        self.description = description
        self.category = category
        self.amount = amount

    def __repr__(self):
        return "Expense(%r, %r, %r)" % (self.description, self.category, self.amount)


class NewExpenseForm:
    description = observable("")
    category = observable("Food")
    amount_text = observable("")

    @computed
    def amount(self):
        try:
            return float(self.amount_text.replace("$", "").replace(",", ""))
        except ValueError:
            return None

    @computed
    def error(self):
        """Message under the form; empty until the user has typed something."""
        if not (self.description or self.amount_text):
            return ""
        if not self.description.strip():
            return "Describe the expense."
        if not self.amount_text.strip():
            return "Enter an amount."
        if self.amount is None:
            return "“%s” isn't a number." % self.amount_text
        if self.amount <= 0:
            return "Amount must be more than zero."
        return ""

    @computed
    def is_valid(self):
        return bool(self.description.strip()) and self.amount is not None and self.amount > 0

    def reset(self):
        self.description = ""
        self.amount_text = ""


class ExpensesViewModel:
    expenses = observable(factory=ObservableList)
    budget = observable(1500.0)
    search = observable("")
    category_filter = observable("All")
    selected = observable(None)
    dark_mode = observable(False)

    categories = CATEGORIES
    filter_options = ["All"] + CATEGORIES
    can_change_theme = False        # set by the app when its theme has light/dark modes

    def __init__(self, expenses=()):
        self.form = NewExpenseForm()
        self.expenses.extend(expenses)

    # -- what the list shows ----------------------------------------------------

    @computed
    def visible(self):
        text = self.search.strip().lower()
        return [e for e in self.expenses
                if (self.category_filter == "All" or e.category == self.category_filter)
                and text in e.description.lower()]

    @computed
    def summary(self):
        shown, total = len(self.visible), len(self.expenses)
        if shown == total:
            return "%d expenses" % total
        return "Showing %d of %d expenses" % (shown, total)

    @computed
    def visible_total(self):
        return sum(e.amount for e in self.visible)

    # -- budget -------------------------------------------------------------------

    @computed
    def total(self):
        return sum(e.amount for e in self.expenses)

    @computed
    def remaining(self):
        return self.budget - self.total

    @computed
    def budget_used(self):
        """Percent of budget used, capped at 100 for the progress bar."""
        if not self.budget:
            return 100.0
        return min(100.0, 100.0 * self.total / self.budget)

    @computed
    def budget_status(self):
        if self.remaining < 0:
            return "Over budget by ${:,.2f}".format(-self.remaining)
        return "${:,.2f} left of ${:,.2f}".format(self.remaining, self.budget)

    @computed
    def theme(self):
        return "dark" if self.dark_mode else "light"

    # -- commands -------------------------------------------------------------------

    @command(can_execute=lambda self: self.form.is_valid)
    def add(self):
        f = self.form
        expense = Expense(f.description.strip(), f.category, f.amount)
        self.expenses.append(expense)
        f.reset()
        self.selected = expense

    @command(can_execute=lambda self: self.selected is not None)
    def remove(self):
        self.expenses.remove(self.selected)
        self.selected = None

    @command(can_execute=lambda self: bool(self.search) or self.category_filter != "All")
    def clear_filters(self):
        self.search = ""
        self.category_filter = "All"


def sample():
    return ExpensesViewModel([
        Expense("Groceries", "Food", 182.40),
        Expense("Rent", "Housing", 950.00),
        Expense("Train to Portland", "Travel", 64.50),
        Expense("Concert tickets", "Fun", 120.00),
        Expense("Coffee beans", "Food", 18.75),
        Expense("Internet", "Housing", 70.00),
    ])
