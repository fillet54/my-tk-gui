"""A shell app: navigation pane, back button and pages swapped by binding.

    python3 shell.py            # the platform's own look
    python3 shell.py --winui    # the optional WinUI theme (needs Tk 9)

Every page is a view model with a view registered by type (``gui.template``).
The shell shows whichever page ``nav.current`` holds; clicking a nav item,
opening an expense or pressing Back only changes view models. The Settings
page tells the shell about dark mode through the Messenger, without either
holding a reference to the other.
"""

import gui
from demo import theme_option
from expenses import CATEGORIES, sample
from mvvm import Messenger, Navigator
from reactive import command, computed, observable, watch


class DarkModeChanged:
    def __init__(self, dark):
        self.dark = dark


# --------------------------------------------------------------------------
# Pages (no Tk)
# --------------------------------------------------------------------------

class HomePage:
    title = "Home"

    def __init__(self, data, nav):
        self.data, self.nav = data, nav

    @computed
    def greeting(self):
        return "You have %d expenses this month." % len(self.data.expenses)

    @command
    def show_expenses(self):
        self.nav.go("expenses")


class ExpensesPage:
    title = "Expenses"

    def __init__(self, data, nav):
        self.data, self.nav = data, nav

    @command(can_execute=lambda self, expense: expense is not None)
    def open(self, expense):
        """Opens the detail page for the expense passed as the command parameter."""
        self.nav.go("expense", expense)


class ExpensePage:
    def __init__(self, expense, data, nav):
        self.expense, self.data, self.nav = expense, data, nav
        self.categories = CATEGORIES

    @computed
    def title(self):
        return self.expense.description or "Expense"

    @command
    def delete(self):
        self.data.expenses.remove(self.expense)
        self.data.selected = None
        self.nav.go_back()


class SettingsPage:
    title = "Settings"
    dark_mode = observable(False)

    def __init__(self, data, can_change_theme=False):
        self.data = data
        self.can_change_theme = can_change_theme
        # Tell whoever cares; the shell listens for DarkModeChanged.
        self._announce = watch(lambda: self.dark_mode,
                               lambda dark: Messenger.default.send(DarkModeChanged(dark)),
                               fire_immediately=False)


# --------------------------------------------------------------------------
# The shell
# --------------------------------------------------------------------------

SECTIONS = ("home", "expenses", "settings")
PARENT = {"expense": "expenses"}      # detail pages light up their section


class Shell:
    dark = observable(False)

    def __init__(self, data, can_change_theme=False):
        self.data = data
        home, expenses = HomePage(data, None), ExpensesPage(data, None)
        settings = SettingsPage(data, can_change_theme)
        self.nav = Navigator({
            "home": lambda _: home,
            "expenses": lambda _: expenses,
            "settings": lambda _: settings,
            "expense": lambda expense: ExpensePage(expense, data, self.nav),
        })
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

    # The nav pane's radio buttons bind to this; setting it navigates.
    @property
    def section(self):
        route = self.nav.current_route
        return PARENT.get(route, route)

    @section.setter
    def section(self, value):
        if value in SECTIONS and value != self.section:
            self.nav.go(value)


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------

SHELL = """
<row fill="both" expand="1" theme="{theme}">
  <group side="left" fill="y" padding="8 12" spacing="2">
    <button text="← Back" command="{nav.go_back}" style="Toolbutton" pady="0 12" />
    <radiobutton text="Home" selected="{section}" value="home" style="Toolbutton" />
    <radiobutton text="Expenses" selected="{section}" value="expenses" style="Toolbutton" />
    <radiobutton text="Settings" selected="{section}" value="settings" style="Toolbutton"
                 side="bottom" />
  </group>
  <separator orient="vertical" side="left" fill="y" padx="0" />
  <group side="left" fill="both" expand="1" padding="24 16" spacing="12">
    <label text="{title}" font="-size 20 -weight bold" />
    <content content="{nav.current}" cache="true" fill="both" expand="1" />
  </group>
</row>
"""

gui.template(HomePage, """
<group spacing="12">
  <label text="{greeting}" />
  <label text="{data.budget_status}" />
  <progressbar value="{data.budget_used}" maximum="100" length="320" fill="none" anchor="w" />
  <accentbutton text="See expenses" command="{show_expenses}" fill="none" anchor="w" />
</group>
""")

gui.template(ExpensesPage, """
<group spacing="8">
  <row fill="x">
    <entry text="{data.search}" width="24" on_escape="{data.clear_filters}" />
    <combobox text="{data.category_filter}" values="{data.filter_options}" state="readonly" width="10" />
    <button text="Open" command="{open}" command_parameter="{data.selected}" side="right" padx="0" />
  </row>
  <treeview items="{data.visible}" selection="{data.selected}" height="12" fill="both" expand="1"
            on_double_click="{open}" on_return="{open}" command_parameter="{data.selected}">
    <column key="description" heading="Description" width="240" />
    <column key="category" heading="Category" width="110" />
    <column key="amount" heading="Amount" format="money" width="110" anchor="e" />
  </treeview>
  <label text="{data.summary}  ·  double-click or Open to see an expense" />
</group>
""")

gui.template(ExpensePage, """
<group spacing="12">
  <fields context="{expense}">
    <entry label="Description" text="{description}" />
    <combobox label="Category" text="{category}" values="{$root.categories}" state="readonly" />
    <spinbox label="Amount" text="{amount|number}" from="0" to="100000" increment="5" />
  </fields>
  <button text="Delete expense" command="{delete}" fill="none" anchor="w" />
</group>
""")

gui.template(SettingsPage, """
<group spacing="12">
  <switch text="Dark mode" checked="{dark_mode}" enabled="{can_change_theme}" />
  <fields>
    <spinbox label="Monthly budget" text="{data.budget|number}" from="0" to="100000" increment="100" />
  </fields>
  <label text="The switch sends a DarkModeChanged message; the shell listens for it.&#10;(It needs a theme with light/dark modes: run with --winui.)" />
</group>
""")


if __name__ == "__main__":
    theme = theme_option()
    gui.run(SHELL, Shell(sample(), can_change_theme=theme is not None),
            title="Shell", minsize=(860, 540), theme=theme)
