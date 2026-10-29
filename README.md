# MyTkGui

Reactive MVVM for tkinter. You write a **view model** in plain Python and a
**view** in XML. Neither one says *when* anything updates. Dependencies are
discovered automatically (in the style of [Assisticant](https://github.com/michaellperry/Assisticant)),
so every label, list and enabled state follows the data on its own.

```
python3 demo.py                          # expense tracker
python3 shell.py                         # shell app: nav pane, pages, back button
python3-tk9 shell.py --winui             # the same with the WinUI theme (Tk 9)
python3 -m unittest discover -s tests    # 60 tests, most need no window
```

The library is small enough to read and change (`reactive.py`, `gui.py`,
`mvvm.py`).
Fork it and grow the abstractions your own app needs.

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

**Here** (from [`expenses.py`](expenses.py) and [`demo.py`](demo.py)):

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

## Reactive core (`reactive.py`)

| | |
|---|---|
| `observable(default, factory=)` | a settable attribute; reads are tracked |
| `@computed` | a cached derived value; lazy, recalculated when an input changes |
| `@command(can_execute=)` | an action (optionally taking a parameter); bound buttons enable/disable themselves |
| `RelayCommand(execute, can_execute)` | the same from plain functions, built at runtime |
| `ObservableList` | a list whose reads are tracked and whose changes notify |
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

    def __init__(self):
        self.refresh = RelayCommand(self._reload, lambda: not self.loading)
```

```xml
<button text="Open" command="{open}" command_parameter="{data.selected}" />
<button text="Settings" command="{nav.navigate}" command_parameter="settings" />
```

Unlike MVVM Light, you rarely call `raise_can_execute_changed()`:
`can_execute` reads observables, so it updates on its own. Call it only
when `can_execute` depends on something that isn't observable.

## Shell apps (`mvvm.py`, `<content>`)

A shell swaps pages by changing a view model; the view follows.

* **`<content content="{nav.current}" />`** shows a view for whatever view
  model the binding holds, chosen by its type, and swaps views when it
  changes (WPF's `ContentControl` + `DataTemplate`). Register views with
  `gui.template(PageViewModel, xml)`. `cache="true"` keeps the 10 most
  recent views alive (`cache="N"` for N), so a page keeps its scroll
  position and selection when you come back.
* **`Navigator(routes)`** holds `current`, `current_route` and a back
  stack. `go(route, parameter)`, the bindable `navigate` command, and
  `go_back` (disabled when there's nothing to go back to).
* **`Messenger`** sends messages between view models that don't know each
  other, by message type, with optional tokens as channels. Recipients are
  held weakly. `Messenger.default` is a shared instance.

`shell.py` puts these together: a navigation pane bound to the navigator,
a back button, list and detail pages (the detail page is opened with a
command parameter), and a Settings page that turns on dark mode by sending
a message the shell listens for.

## Views (`gui.py`)

```xml
<form padding="16" theme="{theme}">
  <row>                                  <!-- children left to right -->
    <entry text="{search}" on_escape="{clear_filters}" />
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

* **Bindings:** `{path}`, `{path|converter}`, or text mixed with bindings:
  `"Total: {total|money}"`. A path walks attributes (`form.amount_text`).
  `{.}` is the context itself, and `{$root.x}` is the top view model.
* **Two-way:** `text` on entry, spinbox and combobox; `checked` on
  checkbutton and switch; `selected` on radiobutton; `value` on scale;
  `selection` on treeview. Text that doesn't convert (e.g. "abc" in a
  `number` field) puts the widget in the theme's *invalid* state instead of
  writing to the model. A field that already means the model's value isn't
  rewritten, so typing `12.` in a number field doesn't lose the dot.
* **Any other option** can be bound one-way: `foreground="{status_color}"`.
* **Converters:** `number`, `int`, `money`, `percent`, `not`, `exists`,
  `upper`. Add your own with `gui.converter(name, to_view, to_model=None)`.
* **Commands:** `command="{save}"`, `on_return="{add}"`, `on_delete=...`,
  with an optional `command_parameter="{...}"`. A bound command disables its
  widget when `can_execute` is false.
* **Components:** `gui.register("switch", '<checkbutton style="Switch.TCheckbutton" />')`.
  `$attr` is substituted from the use site. Attributes the template doesn't
  use (bindings, layout) pass through to its root element.
* **Lifetime:** a widget's bindings are disposed when the widget is destroyed.

## Themes

Widgets use the platform's own ttk theme: Windows' native look on
Windows, Aqua on macOS, and `clam` on Linux, which has no native one.
`gui.py` depends on no theme.

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

* Item templates (rendering arbitrary widgets per list item). Treeview is
  the only list widget so far.
* Per-item list change events. Treeview diffs rows itself, which is fine
  for hundreds of rows but not for many thousands.
* Background threads. Tk isn't thread-safe; marshal changes onto the UI
  thread (e.g. `root.after`) before writing to the view model.
