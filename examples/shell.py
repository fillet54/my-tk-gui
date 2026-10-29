"""A shell app that uses every part of mytkgui.

    python3 -m examples.shell            # the platform's own look
    python3 -m examples.shell --winui    # the optional WinUI theme (needs Tk 9)

* Navigation pane, Back (Alt+Left), pages swapped by binding (Navigator, <content>)
* Menu bar with shortcuts: Ctrl+N new expense, Ctrl+E export, F5 refresh
* Home: summary cards from a list (<items>, <grid>), an async refresh with a
  progress bar that is only visible while it runs
* Expenses: search as you type (delay), click a heading to sort
  (CollectionView), right-click menu, delete with confirmation (dialogs)
* Expense page: an edit form with validation, Save as the default button,
  and a guard when leaving with unsaved changes
* New expense: a custom modal dialog (DialogViewModel) that can't be
  accepted until valid
* Settings: tabs, a scrolling page, a multi-line note, dark mode through the
  Messenger
"""

import csv

from mytkgui import (CollectionView, DialogViewModel, Messenger, Navigator, Validatable, async_command,
                     background, command, computed, dialogs, gui, observable, sleep, validator, watch)

from .demo import theme_option
from .expenses import CATEGORIES, Expense, sample


class DarkModeChanged:
    def __init__(self, dark):
        self.dark = dark


# --------------------------------------------------------------------------
# A validated expense form, shared by the edit page and the new-expense dialog
# --------------------------------------------------------------------------

class ExpenseForm(Validatable):
    description = observable("")
    category = observable("Food")
    amount = observable("")
    categories = CATEGORIES

    @validator("description")
    def _description(self, value):
        if not value.strip():
            return "Describe the expense."

    @validator("amount")
    def _amount(self, value):
        try:
            amount = float(str(value).replace("$", "").replace(",", ""))
        except ValueError:
            return "Enter an amount, like 12.50."
        if amount <= 0:
            return "The amount must be more than zero."

    def load(self, expense):
        self.description, self.category, self.amount = expense.description, expense.category, "%g" % expense.amount

    def save_to(self, expense):
        expense.description = self.description.strip()
        expense.category = self.category
        expense.amount = float(str(self.amount).replace("$", "").replace(",", ""))


FORM_FIELDS = """
<fields>
  <entry label="Description" text="{description}" focus="true" tab_index="1" />
  <label text="{errors.description}" style="Error.TLabel" visible="{errors.description|any}" />
  <combobox label="Category" text="{category}" values="{categories}" state="readonly" tab_index="2" />
  <entry label="Amount" text="{amount}" tab_index="3" />
  <label text="{errors.amount}" style="Error.TLabel" visible="{errors.amount|any}" />
</fields>
"""


class NewExpenseDialog(DialogViewModel, ExpenseForm):
    title = "New expense"

    @computed
    def can_accept(self):
        return self.is_valid

    def make_result(self):
        expense = Expense("", "Other", 0.0)
        self.save_to(expense)
        return expense


# --------------------------------------------------------------------------
# Pages (no Tk)
# --------------------------------------------------------------------------

class HomePage:
    title = "Home"
    refreshed = observable("never")

    def __init__(self, data, nav):
        self.data, self.nav = data, nav

    @computed
    def greeting(self):
        return "You have %d expenses this month." % len(self.data.expenses)

    @computed
    def cards(self):
        """One summary card per category that has spending."""
        totals = {}
        for e in self.data.expenses:
            totals[e.category] = totals.get(e.category, 0.0) + e.amount
        return [Card(name, total, sum(1 for e in self.data.expenses if e.category == name))
                for name, total in sorted(totals.items(), key=lambda kv: -kv[1])]

    @async_command
    async def refresh(self):
        """Pretend to sync with a server (runs off the UI thread)."""
        stamp = await background(_slow_sync)
        await sleep(0.3)
        self.refreshed = stamp

    @command
    def show_expenses(self):
        self.nav.go("expenses")


def _slow_sync():
    import time
    time.sleep(1.2)
    return time.strftime("%H:%M:%S")


class Card:
    def __init__(self, name, total, count):
        self.name, self.total, self.count = name, total, count
        self.count_text = "1 expense" if count == 1 else "%d expenses" % count


class ExpensesPage:
    title = "Expenses"
    search = observable("")

    def __init__(self, data, nav):
        self.data, self.nav = data, nav
        self.view = CollectionView(lambda: self.data.expenses,
                                   filter=lambda e: self.search.lower() in e.description.lower(),
                                   sort_key="amount", descending=True)

    @computed
    def summary(self):
        return "%d of %d expenses · %s" % (len(self.view), len(self.data.expenses),
                                          "${:,.2f}".format(sum(e.amount for e in self.view)))

    @command(can_execute=lambda self, expense: expense is not None)
    def open(self, expense):
        self.nav.go("expense", expense)

    @command(can_execute=lambda self, expense: expense is not None)
    def delete(self, expense):
        if dialogs.ask_yes_no("Delete “%s”?" % expense.description, title="Delete expense"):
            self.data.expenses.remove(expense)
            self.data.selected = None


class ExpensePage:
    def __init__(self, expense, data, nav):
        self.expense, self.data, self.nav = expense, data, nav
        self.form = ExpenseForm()
        self.form.load(expense)

    @computed
    def title(self):
        return self.expense.description or "Expense"

    @computed
    def dirty(self):
        f, e = self.form, self.expense
        return (f.description, f.category, f.amount) != (e.description, e.category, "%g" % e.amount)

    @command(can_execute=lambda self: self.dirty and self.form.is_valid)
    def save(self):
        self.form.save_to(self.expense)

    @command
    def close(self):
        self.nav.go_back()

    def on_navigating_from(self, args):
        """Unsaved changes: ask before leaving."""
        if self.dirty:
            return dialogs.ask_yes_no("Discard your changes?", title="Unsaved changes")
        return True


class SettingsPage:
    title = "Settings"
    dark_mode = observable(False)
    notes = observable("Budget review on the 1st.\nKeep receipts for travel.")

    def __init__(self, data, can_change_theme=False):
        self.data = data
        self.can_change_theme = can_change_theme
        self._announce = watch(lambda: self.dark_mode,
                               lambda dark: Messenger.default.send(DarkModeChanged(dark)),
                               fire_immediately=False)


# --------------------------------------------------------------------------
# The shell
# --------------------------------------------------------------------------

SECTIONS = ("home", "expenses", "settings")
PARENT = {"expense": "expenses"}


class Shell:
    dark = observable(False)

    def __init__(self, data, can_change_theme=False):
        self.data = data
        self.can_change_theme = can_change_theme
        home, expenses = HomePage(data, None), ExpensesPage(data, None)
        settings = SettingsPage(data, can_change_theme)
        self.nav = Navigator({
            "home": lambda _: home,
            "expenses": lambda _: expenses,
            "settings": lambda _: settings,
            "expense": lambda expense: ExpensePage(expense, data, self.nav),
        })
        self.home = home
        home.nav = expenses.nav = self.nav
        Messenger.default.register(self, DarkModeChanged, self.on_dark_mode)
        self.nav.go("home")

    def on_dark_mode(self, message):
        self.dark = message.dark

    @computed
    def theme(self):
        return "dark" if self.dark else "light"

    @computed
    def title(self):
        page = self.nav.current
        return getattr(page, "title", "") if page is not None else ""

    @property
    def section(self):
        route = self.nav.current_route
        return PARENT.get(route, route)

    @section.setter
    def section(self, value):
        if value in SECTIONS and value != self.section:
            self.nav.go(value)

    @command
    def new_expense(self):
        expense = dialogs.show(NewExpenseDialog())
        if expense is not None:
            self.data.expenses.append(expense)
            self.data.selected = expense

    @async_command
    async def export(self):
        path = dialogs.save_file("Export expenses", filetypes=(("CSV", "*.csv"),), default_extension=".csv")
        if not path:
            return
        rows = [(e.description, e.category, e.amount) for e in self.data.expenses]
        await background(_write_csv, path, rows)
        dialogs.info("Saved %d expenses to %s" % (len(rows), path), title="Export")

    @command
    def about(self):
        dialogs.info("A demo of mytkgui: reactive MVVM for tkinter.", title="About")

    @command
    def quit(self):
        raise SystemExit


def _write_csv(path, rows):
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows([("Description", "Category", "Amount")] + rows)


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------

gui.resource("danger", "#c42b1c")

SHELL = """
<row fill="both" expand="1" theme="{theme}">
  <style name="Error.TLabel" foreground="{@danger}" />
  <style name="Title.TLabel" font="-size 20 -weight bold" />
  <style name="Big.TLabel" font="-size 16 -weight bold" />

  <menubar>
    <menu label="File">
      <item label="New expense…" command="{new_expense}" shortcut="Ctrl+N" />
      <item label="Export…" command="{export}" shortcut="Ctrl+E" />
      <separator />
      <item label="Quit" command="{quit}" shortcut="Ctrl+Q" />
    </menu>
    <menu label="View">
      <radio label="Home" value="home" selected="{section}" />
      <radio label="Expenses" value="expenses" selected="{section}" />
      <radio label="Settings" value="settings" selected="{section}" />
      <separator />
      <item label="Back" command="{nav.go_back}" shortcut="Alt+Left" />
      <item label="Refresh" command="{home.refresh}" shortcut="F5" />
    </menu>
    <menu label="Help">
      <item label="About" command="{about}" />
    </menu>
  </menubar>

  <group side="left" fill="y" padding="8 12" spacing="2">
    <button text="← Back" command="{nav.go_back}" style="Toolbutton" pady="0 12" />
    <radiobutton text="Home" selected="{section}" value="home" style="Toolbutton" />
    <radiobutton text="Expenses" selected="{section}" value="expenses" style="Toolbutton" />
    <radiobutton text="Settings" selected="{section}" value="settings" style="Toolbutton" side="bottom" />
  </group>
  <separator orient="vertical" side="left" fill="y" padx="0" />
  <grid side="left" fill="both" expand="1" padding="24 16" columns="*,auto" rows="auto,*">
    <label text="{title}" style="Title.TLabel" row="0" column="0" sticky="w" />
    <accentbutton text="New expense" command="{new_expense}" row="0" column="1" sticky="e" />
    <content content="{nav.current}" cache="true" row="1" column="0" columnspan="2" pady="12 0" />
  </grid>
</row>
"""

gui.template(HomePage, """
<group spacing="12">
  <label text="{greeting}" />
  <label text="{data.budget_status}" />
  <progressbar value="{data.budget_used}" maximum="100" length="320" fill="none" anchor="w" />
  <items items="{cards}" columns="3" spacing="8">
    <template>
      <group label="{name}" padding="12">
        <label text="{total|money}" style="Big.TLabel" />
        <label text="{count_text}" />
      </group>
    </template>
  </items>
  <row>
    <button text="Refresh (F5)" command="{refresh}" />
    <progressbar mode="indeterminate" length="160" visible="{refresh.is_running}"
                 active="{refresh.is_running}" />
    <label text="Last refreshed: {refreshed}" visible="{refresh.is_running|not}" />
  </row>
  <accentbutton text="See expenses" command="{show_expenses}" fill="none" anchor="w" />
</group>
""")

gui.template(ExpensesPage, """
<group spacing="8">
  <shortcut key="Ctrl+O" command="{open}" command_parameter="{data.selected}" />
  <row fill="x">
    <label text="Search" />
    <entry text="{search; delay=250}" width="28" />
    <button text="Delete" command="{delete}" command_parameter="{data.selected}" side="right" padx="0" />
    <button text="Open" command="{open}" command_parameter="{data.selected}" side="right" />
  </row>
  <treeview items="{view}" sort="{view}" selection="{data.selected}" height="12" fill="both" expand="1"
            on_double_click="{open}" on_return="{open}" on_delete="{delete}"
            command_parameter="{data.selected}">
    <column key="description" heading="Description" width="240" />
    <column key="category" heading="Category" width="110" />
    <column key="amount" heading="Amount" format="money" width="110" anchor="e" />
    <contextmenu>
      <item label="Open" command="{open}" command_parameter="{data.selected}" />
      <item label="Delete…" command="{delete}" command_parameter="{data.selected}" />
    </contextmenu>
  </treeview>
  <label text="{summary}  ·  click a heading to sort, right-click a row" />
</group>
""")

gui.template(ExpensePage, """
<group spacing="12">
  <group context="{form}">""" + FORM_FIELDS + """</group>
  <row>
    <accentbutton text="Save" command="{save}" default="true" />
    <button text="Close" command="{close}" cancel="true" />
    <label text="Unsaved changes" visible="{dirty}" />
  </row>
</group>
""")

gui.template(NewExpenseDialog, """
<group padding="20" spacing="12">
  <label text="New expense" style="Big.TLabel" />""" + FORM_FIELDS + """
  <row>
    <accentbutton text="Add" command="{accept}" default="true" />
    <button text="Cancel" command="{cancel}" cancel="true" />
  </row>
</group>
""")

gui.template(SettingsPage, """
<tabs fill="both" expand="1">
  <tab text="General">
    <scroll fill="both" expand="1" padding="12" spacing="12">
      <switch text="Dark mode" checked="{dark_mode}" enabled="{can_change_theme}" />
      <label text="Dark mode needs a theme with light/dark modes: run with --winui."
             visible="{can_change_theme|not}" />
      <fields>
        <spinbox label="Monthly budget" text="{data.budget|number}" from="0" to="100000" increment="100" />
      </fields>
      <label text="Notes" />
      <textarea text="{notes}" height="6" />
    </scroll>
  </tab>
  <tab text="About">
    <group padding="12">
      <label text="Settings sends a DarkModeChanged message; the shell listens for it." />
    </group>
  </tab>
</tabs>
""")


if __name__ == "__main__":
    theme = theme_option()
    gui.run(SHELL, Shell(sample(), can_change_theme=theme is not None),
            title="Shell", minsize=(900, 600), theme=theme)
