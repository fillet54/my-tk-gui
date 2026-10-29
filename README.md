# MyTkGui

Reactive MVVM for tkinter. You write a **view model** in plain Python and a
**view** in XML. Neither one says *when* anything updates. Dependencies are
discovered automatically (in the style of [Assisticant](https://github.com/michaellperry/Assisticant)),
so every label, list and enabled state follows the data on its own.

```
pip install -e .                                 # or just run from the repo
python3 -m examples.demo                         # expense tracker
python3 -m examples.shell                        # shell app using every feature
python3-tk9 -m examples.shell --winui            # the same with the WinUI theme (Tk 9)
python3 -m unittest discover -s tests -t .       # 102 tests, many need no window
```

No dependencies beyond the standard library (Python 3.10+, Tk 8.6 or 9).

## The idea

```python
class Person:
    first = observable("")
    last = observable("")

    @computed
    def full(self):
        return f"{self.first} {self.last}".strip()

    @command(can_execute=lambda self: bool(self.full))
    def greet(self):
        print("Hello,", self.full)
```

```xml
<group>
  <entry text="{first}" />
  <entry text="{last}" />
  <label text="Hello, {full}" />
  <button text="Greet" command="{greet}" />
</group>
```

There's no `INotifyPropertyChanged`, no `trace_add`, no list of properties
to re-announce. `full` records what it read while it ran. Change `first` and
`full` is marked stale, the label re-renders, and the button re-checks
`can_execute` and enables itself.

## Why not plain tkinter?

Take one feature of the demo: a form for adding an expense. The Add button
is enabled only when the input is valid, there's an inline error message,
and the list, filtered count, totals and budget bar all have to stay right.

**Raw tkinter.** Each handler has to know about everything that might be
affected:

```python
desc_var, amount_var = tk.StringVar(), tk.StringVar()

def validate(*_):
    desc, text = desc_var.get(), amount_var.get()
    try:
        amount = float(text)
    except ValueError:
        amount = None
    if not (desc or text):           msg = ""
    elif not desc.strip():           msg = "Describe the expense."
    elif amount is None:             msg = f"“{text}” isn't a number."
    elif amount <= 0:                msg = "Amount must be more than zero."
    else:                            msg = ""
    error_label.configure(text=msg)
    add_button.state(["!disabled"] if desc.strip() and amount and amount > 0 else ["disabled"])

desc_var.trace_add("write", validate)
amount_var.trace_add("write", validate)

def add():
    expenses.append(Expense(desc_var.get(), category_var.get(), float(amount_var.get())))
    refresh_tree()          # ...which has to re-apply the search and category filter
    refresh_summary()       # "Showing 3 of 7"
    refresh_totals()        # filtered total, overall total
    refresh_budget()        # progress bar, "left of" text
    desc_var.set(""); amount_var.set("")
    select_row(expenses[-1])  # ...and populate the editor, and enable Delete
    validate()
```

Every new feature adds another `refresh_*`, and it has to be called from the
add handler, the delete handler, the edit handlers, the budget spinbox, and
the filter callbacks. Miss one and the window shows stale data.

**Here** (from [`examples/expenses.py`](examples/expenses.py) and [`examples/demo.py`](examples/demo.py)):

```python
@computed
def error(self): ...              # same rules, written once, no widgets

@computed
def is_valid(self): ...

@command(can_execute=lambda self: self.form.is_valid)
def add(self):
    expense = Expense(f.description.strip(), f.category, f.amount)
    self.expenses.append(expense)
    f.reset()
    self.selected = expense
```

```xml
<label text="{form.error}" foreground="#d83b01" />
<accentbutton text="Add expense" command="{add}" />
```

`add` only changes the data. The tree, count, totals, budget bar, selection
editor and Delete button are all `computed` values or bindings, so they
update themselves, including in situations nobody wrote a handler for.
Two examples: editing a row's category while a category filter is active
makes it drop out of the list, and changing the budget updates the bar and
the "left of" text.

And the logic is testable without a window. [`tests/test_expenses.py`](tests/test_expenses.py)
exercises the whole demo by setting attributes and reading results.

## Package layout

| Module | What's in it | Tk? |
|---|---|---|
| `mytkgui.reactive` | observables, computed values, reactions, commands, `ObservableList` | no |
| `mytkgui.validation` | `Validatable`, `@validator` | no |
| `mytkgui.tasks` | `@async_command`, `background()`, `sleep()`, the UI-thread `Dispatcher` | no |
| `mytkgui.mvvm` | `Navigator`, `Messenger`, `CollectionView` | no |
| `mytkgui.dialogs` | `dialogs` (an IDialogService), `DialogViewModel`, `FakeDialogs` for tests | only `TkDialogs` |
| `mytkgui.gui` | views: `run`, `create_root`, `realize`, `template`, `register`, `converter`, `resource` | yes |
| `winui_ttk` | an optional WinUI 3 theme (Tk 9); `mytkgui` never imports it | yes |

View models import from `mytkgui` and never touch Tk, so they're tested
without a window. `from mytkgui import gui` is everything for views.

## Reactive core

| | |
|---|---|
| `observable(default, factory=)` | a settable attribute; reads are tracked |
| `@computed` | a cached derived value; lazy, recalculated when an input changes |
| `@command(can_execute=)` | an action (optionally taking a parameter); bound buttons enable/disable themselves |
| `RelayCommand(execute, can_execute)` | the same from plain functions, built at runtime |
| `@async_command` | an `async def` action with `is_running`, `error` and `cancel` |
| `ObservableList` | a list whose reads are tracked; `subscribe()` reports each insert/remove |
| `watch(getter, callback)`, `autorun(fn)` | side effects that rerun on change |
| `batch()` | group writes so reactions run once |
| `untracked()` | read without creating a dependency |

Dependencies are rediscovered on every run, so `a if flag else b` depends
only on the branch it took. A change first marks everything downstream
stale, then reactions run, so a reaction never sees half-updated values.
A node holds subscriptions only while it is up to date, which means a
discarded view model is freed after the next change to its inputs.

## Commands

Commands follow MVVM Light's `ICommand`: `execute(parameter)`,
`can_execute(parameter)` and `raise_can_execute_changed()`. Calling a
command is `execute`. A command only runs when `can_execute` allows it,
and it runs inside `batch()`.

```python
class ExpensesPage:
    @command(can_execute=lambda self, expense: expense is not None)
    def open(self, expense):
        self.nav.go("expense", expense)
```

```xml
<button text="Open" command="{open}" command_parameter="{data.selected}" />
<button text="Settings" command="{nav.navigate}" command_parameter="settings" />
```

You rarely call `raise_can_execute_changed()`: `can_execute` reads
observables, so it updates on its own.

## Background work

Write the command as `async def`. It runs on the UI thread, so it can read
and write the view model; `await background(fn)` runs slow work on a
worker thread and resumes on the UI thread with the result (like `await`
in a WPF app):

```python
@async_command
async def refresh(self):
    self.rows = await background(fetch_rows)      # fetch_rows runs on a worker
```

```xml
<button text="Refresh" command="{refresh}" />     <!-- disabled while running -->
<progressbar mode="indeterminate" active="{refresh.is_running}" visible="{refresh.is_running}" />
<button text="Stop" command="{refresh.cancel}" />
```

`refresh.error` holds the exception if the last run failed. Worker code
must not touch observables or Tk; return a value instead. In tests,
`Dispatcher.current.wait(task)` runs a command to completion without Tk.

## Validation

```python
class ExpenseForm(Validatable):
    amount = observable("")

    @validator("amount")
    def _amount(self, value):
        if not value.replace(".", "", 1).isdigit():
            return "Enter an amount, like 12.50."
```

`form.is_valid`, `form.errors.amount` (shown once the field is edited, or
after `form.validate()`), `form.all_errors`. A field bound to `{amount}`
goes into the theme's *invalid* state while it has an error; show the
message with `<label text="{errors.amount}" visible="{errors.amount|any}" />`.

## Dialogs

```python
from mytkgui import dialogs

@command
def delete(self, expense):
    if dialogs.ask_yes_no("Delete it?", title="Delete"):
        ...
```

`info`, `warning`, `error`, `ask_yes_no`, `ask_ok_cancel`,
`ask_yes_no_cancel`, `open_file(s)`, `save_file`, `choose_directory`, and
`show(view_model)` for custom modal dialogs: subclass `DialogViewModel`,
register a view with `gui.template`, bind buttons to `{accept}` and
`{cancel}`, and `show` returns the result. In tests, set
`DialogService.current = FakeDialogs(ask_yes_no=False, ...)`.

## Shell apps

* **`<content content="{nav.current}" />`** shows the view registered with
  `gui.template(PageViewModel, xml)` for the bound view model's type
  (WPF's ContentControl + DataTemplate). `cache="true"` keeps the 10 most
  recent views alive so pages keep their state.
* **`Navigator(routes)`**: `current`, `current_route`, a back stack,
  `go(route, parameter)`, bindable `navigate` and `go_back`. Pages may
  define `on_navigated_to(args)` (can be `async def`, to load data),
  `on_navigated_from(args)`, and `on_navigating_from(args)`, which returns
  False to stay, e.g. after asking about unsaved changes.
* **`Messenger`** sends messages between view models that don't know each
  other, by type, with tokens as channels. Recipients are held weakly.
* **`CollectionView(source, filter=, sort_key=, group_key=)`** filters,
  sorts and groups a list. `<treeview items="{view}" sort="{view}">` makes
  the headings sort it.

`examples/shell.py` uses all of these.

## Views

```xml
<form padding="16" theme="{theme}">
  <row>                                  <!-- children left to right -->
    <entry text="{search; delay=250}" on_escape="{clear_filters}" />
    <combobox text="{category_filter}" values="{filter_options}" state="readonly" />
  </row>
  <treeview items="{visible}" selection="{selected}" fill="both" expand="1">
    <column key="amount" heading="Amount" format="money" anchor="e" />
  </treeview>
  <group label="Selected" context="{selected}">   <!-- disabled while None -->
    <fields>                                       <!-- label / widget grid -->
      <entry label="Description" text="{description}" />
      <spinbox label="Amount" text="{amount|number}" from="0" to="1000" />
    </fields>
    <button text="Delete" command="{$root.remove}" />
  </group>
</form>
```

**Bindings.** `{path}`, `{path|converter}`, or text mixed with bindings
(`"Total: {total|money}"`). `{.}` is the context, `{$root.x}` the top view
model. Options after `;`:

| Option | |
|---|---|
| `mode=oneway` / `onetime` | don't write back / read once |
| `trigger=focus` | write typed text back on focus-out or Return, not every keystroke |
| `delay=250` | write back once typing pauses (search boxes) |
| `fallback=—` | shown when the path can't be resolved |
| `null=(none)` | shown when the value is None |

Two-way: `text` (entry, spinbox, combobox, textarea), `checked`,
`selected` (radiobutton, tabs), `value` (scale), `selection` (treeview).
Any other option can be bound one-way. Converters: `number`, `int`,
`money`, `percent`, `not`, `exists`, `upper`, `count`, `any`; add your own
with `gui.converter(name, to_view, to_model=None)`.

**Layout.**

| Element | |
|---|---|
| `group`, `form`, `row` | stack children vertically / horizontally (`spacing`) |
| `fields` | label/widget grid; each child's `label` becomes a caption |
| `grid` | `columns="auto,*,2*,120"` `rows="auto,*"`; children take `row`, `column`, `rowspan`, `columnspan`, `sticky` |
| `scroll` | a scrolling group (`horizontal="true"` for both directions) |
| `split` | resizable panes; children take `weight` |
| `tabs` | `<tab text="..." value="...">` children, or `items="{pages}"` with `<template header="{title}">`; `selected` is two-way |
| `items` | a view per item of `items="{list}"`, from its `<template>` or the item's type; `columns="3"` for a grid |
| `content` | the view for the bound view model |

**Attributes on any element.** `visible` and `enabled` (bindings; both
cascade), `context`, `id`, `command_parameter`, `on_return`/`on_escape`/
`on_delete`/`on_double_click`/`on_<Event>`, `focus` ("true" or a binding),
`tab_index`, `default`/`cancel` (buttons that Return/Escape press), and
pack options (`side`, `fill`, `expand`, `anchor`, `padx`, `pady`).

**Keyboard and menus.**

```xml
<shortcut key="Ctrl+S" command="{save}" />
<menubar>
  <menu label="File">
    <item label="Save" command="{save}" shortcut="Ctrl+S" />
    <separator />
    <check label="Dark mode" checked="{dark}" />
  </menu>
</menubar>
<treeview ...>
  <contextmenu><item label="Delete" command="{delete}" command_parameter="{selected}" /></contextmenu>
</treeview>
```

Shortcuts belong to the view they're in: a page's shortcuts only work
while that page is shown. On macOS, Ctrl means Command.

**Styles and resources.**

```xml
<style name="Danger.TButton" foreground="{@danger}" map_foreground="disabled:#999" />
<resource name="gap" value="12" />
<group spacing="{@gap}"> ... </group>
```

`gui.resource("danger", "#c42b1c")` registers app-wide resources.

**Components.** `gui.register("switch", '<checkbutton style="Switch.TCheckbutton" />')`.
`$attr` is substituted from the use site; other attributes pass through.

**Errors.** A binding that can't be evaluated is reported once with the
element and view line: `{nmae} on <label text="{nmae}">, view line 12:
Thing has no attribute 'nmae'`. Call `gui.strict_bindings()` in tests to
raise instead.

**Lifetime.** A widget's bindings, traces and shortcuts are removed when
the widget is destroyed, and a destroyed view frees its view model.

## Themes

Widgets use the platform's own ttk theme: Windows' native look on
Windows, Aqua on macOS, and `clam` on Linux, which has no native one.
`mytkgui` depends on no theme.

To use another theme, pass it to `create_root` or `run`:

```python
import winui_ttk
gui.run(VIEW, vm, title="App", theme=winui_ttk.Theme)    # needs Tk 9
```

`theme` is called as `theme(root, scale=scale)`. If the object it returns
has `set_mode("light" | "dark")`, a view's `theme="{...}"` binding switches
it; with the platform theme that binding does nothing. Views can ask for
styles a theme may not have (`Accent.TButton`, `Switch.TCheckbutton`,
`Toolbutton`): ttk falls back to the plain style, so the same view works
either way. Both demos take `--winui` (see `winui_ttk/README.md`).

## HiDPI

`gui.create_root()` detects the screen scale, so views are written in plain
1x pixels and look the same size on every screen.

* **Detection:** Windows asks the monitor. macOS is left to Tk, which handles
  Retina itself. On X11 it follows what GTK and Qt apps follow: `GDK_SCALE`,
  then `Xft.dpi`, then `QT_SCALE_FACTOR`, then the X server's DPI. Set
  `MYTKGUI_SCALE=1.5` (or pass `scale=`) to override.
* **Fonts** are in points and scale through `tk scaling`. Tk's default fonts
  are converted from pixels to points so they scale too.
* **Pixel attributes** in views are multiplied by the scale: `padding`,
  `padx`/`pady`, `ipadx`/`ipady`, `spacing`, `length`, `wraplength` and
  treeview column widths. Values in Tk units (`"5p"`) are left alone.
* **Platform theme:** Treeview row heights follow the font. On Linux,
  `clam`'s arrows and check marks are scaled too (Windows and macOS draw
  theirs at the system DPI).

## Not done yet

* **Not run on Windows or macOS yet.** Everything here was built and tested
  on Linux. The Windows-specific parts (DPI detection, native dialogs and
  menus) need a run there.
* **Lists re-diff on change.** `<items>` and `<treeview>` reconcile the
  whole list (by identity) on each change. That's fine for a few thousand
  items. `ObservableList.subscribe()` reports single inserts and removes
  for anything that needs to do better.
* **Async commands await `background()`, `sleep()` and other tasks**, not
  asyncio coroutines. Wrap asyncio code in `background(asyncio.run, coro())`.
* **No animations or transitions**; ttk can't do them well.
* **Accessibility** is whatever Tk provides, which is little.
