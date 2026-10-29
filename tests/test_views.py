"""The view elements and attributes added for real apps. Skipped without a display."""

import tkinter as tk
import unittest
from tkinter import ttk

from mytkgui import (CollectionView, ObservableList, Validatable, command, computed, gui, observable,
                     validator)
from mytkgui.bindings import BindingError, strict_bindings

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


def shown(widget):
    top = widget.winfo_toplevel()
    while widget is not top:
        if not widget.winfo_manager():
            return False
        widget = widget.master
    return True


def texts(root, cls="TLabel"):
    """Text of the shown widgets, top to bottom then left to right."""
    widgets = [w for w in find(root, cls) if shown(w)]
    widgets.sort(key=lambda w: (w.winfo_rooty(), w.winfo_rootx()))
    return [str(w.cget("text")) for w in widgets]


class Thing:
    name = observable("")
    flag = observable(True)

    def __init__(self, name=""):
        self.name = name


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class ViewTest(unittest.TestCase):
    def setUp(self):
        self.root = gui.create_root("test", scale=1.0)
        self.root.withdraw()
        strict_bindings(True)

    def tearDown(self):
        strict_bindings(False)
        self.root.destroy()

    def build(self, xml, vm):
        view = gui.realize(self.root, xml, vm)
        view.widget.pack(fill="both", expand=True)
        self.root.update()
        return view


class TestVisible(ViewTest):
    def test_hide_and_show_in_place(self):
        vm = Thing()
        self.build("""<group>
            <label text="one" />
            <label text="two" visible="{flag}" />
            <label text="three" />
        </group>""", vm)
        self.assertEqual(texts(self.root), ["one", "two", "three"])
        vm.flag = False
        self.root.update()
        self.assertEqual(texts(self.root), ["one", "three"])
        vm.flag = True
        self.root.update()
        labels = [w for w in find(self.root, "TLabel") if shown(w)]
        ys = [w.winfo_y() for w in labels]
        self.assertEqual([str(w.cget("text")) for w in labels], ["one", "two", "three"])
        self.assertEqual(ys, sorted(ys))            # back in its original place

    def test_fields_hide_their_caption(self):
        vm = Thing()
        self.build('<fields><entry label="Name" text="{name}" visible="{flag}" /></fields>', vm)
        vm.flag = False
        self.root.update()
        self.assertEqual(texts(self.root), [])
        vm.flag = True
        self.root.update()
        self.assertEqual(texts(self.root), ["Name"])


class TestItems(ViewTest):
    def test_template_per_item_follows_the_list(self):
        class VM:
            things = observable(factory=ObservableList)
        vm = VM()
        a, b = Thing("a"), Thing("b")
        vm.things.extend([a, b])
        self.build("""<group><items items="{things}">
            <template><label text="item {name}" /></template>
        </items></group>""", vm)
        self.assertEqual(texts(self.root), ["item a", "item b"])
        first = find(self.root, "TLabel")[0]
        vm.things.insert(0, Thing("c"))
        vm.things.remove(b)
        a.name = "A"
        self.root.update()
        self.assertEqual(texts(self.root), ["item c", "item A"])
        self.assertTrue(first.winfo_exists())       # kept, not rebuilt

    def test_view_by_item_type_and_columns(self):
        gui.template(Thing, '<label text="typed {name}" />')

        class VM:
            things = observable(())
        vm = VM()
        vm.things = (Thing("x"), Thing("y"), Thing("z"))
        self.build('<group><items items="{things}" columns="2" /></group>', vm)
        labels = [w for w in find(self.root, "TLabel")]
        self.assertEqual(sorted(str(l.cget("text")) for l in labels), ["typed x", "typed y", "typed z"])
        self.assertEqual(labels[2].master.grid_info()["row"] if labels[2].master.winfo_manager() == "grid"
                         else labels[2].grid_info()["row"], 1)


class TestLayout(ViewTest):
    def test_grid(self):
        vm = Thing()
        view = self.build("""<grid columns="auto,*,2*,120" rows="auto,*">
            <label text="a" row="0" column="0" />
            <entry row="0" column="1" columnspan="2" id="e" />
            <label text="b" row="1" column="3" sticky="e" />
        </grid>""", vm)
        grid = view.widget
        self.assertEqual(int(grid.columnconfigure(2)["weight"]), 2)
        self.assertEqual(int(grid.columnconfigure(3)["minsize"]), 120)
        info = view.ids["e"].grid_info()
        self.assertEqual((int(info["column"]), int(info["columnspan"])), (1, 2))

    def test_scroll_split_tabs(self):
        class VM:
            tab = observable("b")
        vm = VM()
        view = self.build("""<split orient="horizontal">
            <scroll weight="1" id="s">
              <label text="in scroll" />
            </scroll>
            <tabs weight="2" selected="{tab}" id="t">
              <tab text="A" value="a"><label text="tab a" /></tab>
              <tab text="B" value="b"><label text="tab b" /></tab>
            </tabs>
        </split>""", vm)
        self.assertEqual(len(view.widget.panes()), 2)
        self.assertIn("in scroll", [str(w.cget("text")) for w in find(view.ids["s"], "TLabel")])
        notebook = view.ids["t"]
        self.assertEqual(notebook.index("current"), 1)
        notebook.select(0)
        self.root.update()
        self.assertEqual(vm.tab, "a")
        vm.tab = "b"
        self.root.update()
        self.assertEqual(notebook.index("current"), 1)

    def test_tabs_from_items(self):
        class VM:
            pages = observable(())
            current = observable(None)
        vm = VM()
        one, two = Thing("One"), Thing("Two")
        vm.pages, vm.current = (one, two), two
        view = self.build("""<tabs items="{pages}" selected="{current}">
            <template header="{name}"><label text="page {name}" /></template>
        </tabs>""", vm)
        notebook = view.widget
        self.assertEqual([notebook.tab(t, "text") for t in notebook.tabs()], ["One", "Two"])
        self.assertEqual(notebook.index("current"), 1)
        one.name = "Uno"
        self.root.update()
        self.assertEqual(notebook.tab(notebook.tabs()[0], "text"), "Uno")


class TestInput(ViewTest):
    def test_textarea_two_way(self):
        class VM:
            notes = observable("hello")
        vm = VM()
        self.build('<group><textarea text="{notes}" /></group>', vm)
        text = find(self.root, "Text")[0]
        self.assertEqual(text.get("1.0", "end-1c"), "hello")
        text.insert("end", " world")
        self.root.update()
        self.assertEqual(vm.notes, "hello world")
        vm.notes = "new"
        self.root.update()
        self.assertEqual(text.get("1.0", "end-1c"), "new")

    def test_trigger_focus_and_onetime(self):
        class VM:
            search = observable("")
            title = observable("first")
        vm = VM()
        self.build("""<group>
            <entry text="{search; trigger=focus}" />
            <label text="{title; mode=onetime}" />
        </group>""", vm)
        entry = find(self.root, "TEntry")[0]
        entry.insert(0, "abc")
        self.root.update()
        self.assertEqual(vm.search, "")
        entry.event_generate("<FocusOut>")
        self.assertEqual(vm.search, "abc")
        vm.title = "second"
        self.root.update()
        self.assertEqual(texts(self.root), ["first"])

    def test_validation_marks_field(self):
        class Form(Validatable):
            name = observable("x")

            @validator("name")
            def _name(self, value):
                return "" if value else "Required."
        form = Form()
        self.build('<group><entry text="{name}" /><label text="{errors.name}" /></group>', form)
        entry = find(self.root, "TEntry")[0]
        self.assertFalse(entry.instate(["invalid"]))
        entry.delete(0, "end")                      # user edit: touched, now invalid
        self.root.update()
        self.assertTrue(entry.instate(["invalid"]))
        self.assertEqual(texts(self.root), ["Required."])

    def test_binding_error_names_the_line(self):
        with self.assertRaises(BindingError) as cm:
            gui.realize(self.root, '<group>\n  <label text="{nmae}" />\n</group>', Thing())
        self.assertIn("view line 2", str(cm.exception))
        self.assertIn("nmae", str(cm.exception))


class Editor:
    saved = observable(0)
    dark = observable(False)
    can = observable(True)

    @command(can_execute=lambda self: self.can)
    def save(self):
        self.saved += 1


class TestKeyboardAndMenus(ViewTest):
    def build(self, xml, vm):
        # Tk only delivers (synthetic) key events to a shown, focused window.
        self.root.deiconify()
        view = super().build(xml, vm)
        self.root.focus_force()
        self.root.update()
        return view

    def test_shortcut(self):
        vm = Editor()
        self.build('<group><shortcut key="Ctrl+S" command="{save}" /><label text="x" /></group>', vm)
        self.root.event_generate("<Control-s>")
        self.assertEqual(vm.saved, 1)
        vm.can = False
        self.root.event_generate("<Control-s>")
        self.assertEqual(vm.saved, 1)

    def test_key_sequences(self):
        self.assertEqual(gui.key_sequence("Ctrl+S"), "<Control-s>")
        self.assertEqual(gui.key_sequence("Ctrl+Shift+S"), "<Control-S>")
        self.assertEqual(gui.key_sequence("F5"), "<F5>")
        self.assertEqual(gui.key_sequence("Alt+Delete"), "<Alt-Delete>")

    def test_menubar(self):
        vm = Editor()
        self.build("""<group>
            <menubar>
              <menu label="File">
                <item label="Save" command="{save}" shortcut="Ctrl+S" />
                <separator />
                <check label="Dark" checked="{dark}" />
              </menu>
            </menubar>
            <label text="x" />
        </group>""", vm)
        bar = self.root.nametowidget(self.root.cget("menu"))
        file_menu = self.root.nametowidget(bar.entrycget(0, "menu"))
        self.assertEqual(file_menu.entrycget(0, "label"), "Save")
        self.assertEqual(file_menu.entrycget(0, "accelerator"), "Ctrl+S")
        file_menu.invoke(0)
        self.assertEqual(vm.saved, 1)
        vm.can = False
        self.root.update()
        self.assertEqual(str(file_menu.entrycget(0, "state")), "disabled")
        file_menu.invoke(2)
        self.assertTrue(vm.dark)

    def test_default_and_cancel_buttons(self):
        class VM:
            log = observable(())

            @command
            def ok(self):
                self.log += ("ok",)

            @command
            def cancel(self):
                self.log += ("cancel",)
        vm = VM()
        self.build("""<row>
            <button text="OK" command="{ok}" default="true" />
            <button text="Cancel" command="{cancel}" cancel="true" />
        </row>""", vm)
        self.root.event_generate("<Return>")
        self.root.event_generate("<Escape>")
        self.assertEqual(vm.log, ("ok", "cancel"))

    def test_focus_and_tab_order(self):
        self.root.deiconify()
        view = self.build("""<group>
            <entry id="a" tab_index="2" />
            <entry id="b" tab_index="3" />
            <entry id="c" tab_index="1" focus="true" />
        </group>""", Thing())
        a, b, c = (view.ids[k] for k in "abc")
        self.root.update()
        c.focus_force()
        self.root.update()
        c.event_generate("<Tab>")
        self.root.update()
        self.assertIs(self.root.focus_lastfor(), a)
        a.event_generate("<Tab>")
        self.root.update()
        self.assertIs(self.root.focus_lastfor(), b)
        b.event_generate("<Tab>")
        self.root.update()
        self.assertIs(self.root.focus_lastfor(), c)

    def test_context_menu(self):
        vm = Editor()
        view = self.build("""<group id="g">
            <contextmenu><item label="Save" command="{save}" /></contextmenu>
            <label text="x" />
        </group>""", vm)
        self.root.update()
        label = find(self.root, "TLabel")[0]
        self.assertTrue(label.bind("<Button-3>"))
        self.assertTrue(view.ids["g"].bind("<Button-3>"))


class TestStylesAndResources(ViewTest):
    def test_style_and_resource(self):
        gui.resource("brand", "#123456")
        self.build("""<group>
            <style name="Brand.TLabel" foreground="{@brand}" padding="4" />
            <resource name="hello" value="Hi" />
            <label text="{@hello}" style="Brand.TLabel" />
        </group>""", Thing())
        style = ttk.Style(self.root)
        self.assertEqual(str(style.lookup("Brand.TLabel", "foreground")), "#123456")
        self.assertEqual(texts(self.root), ["Hi"])


class TestSortableTree(ViewTest):
    def test_heading_sorts_collection_view(self):
        class Row:
            def __init__(self, name, amount):
                self.name, self.amount = name, amount

        class VM:
            def __init__(self):
                self.rows = ObservableList([Row("b", 2), Row("a", 1), Row("c", 3)])
                self.view = CollectionView(self.rows)
        vm = VM()
        self.build("""<treeview items="{view}" sort="{view}">
            <column key="name" heading="Name" />
            <column key="amount" heading="Amount" />
        </treeview>""", vm)
        tree = find(self.root, "Treeview")[0]
        names = lambda: [tree.item(i, "values")[0] for i in tree.get_children()]
        self.assertEqual(names(), ["b", "a", "c"])
        tree.tk.call(tree.heading("amount", "command"))
        self.root.update()
        self.assertEqual(names(), ["a", "b", "c"])
        self.assertIn("▲", tree.heading("amount", "text"))
        tree.tk.call(tree.heading("amount", "command"))
        self.root.update()
        self.assertEqual(names(), ["c", "b", "a"])


if __name__ == "__main__":
    unittest.main()


class TestTkDialog(ViewTest):
    def test_modal_custom_dialog(self):
        from mytkgui import DialogViewModel, TkDialogs

        class Rename(DialogViewModel):
            title = "Rename"
            name = observable("old")

            def make_result(self):
                return self.name

        gui.template(Rename, """<group padding="12">
            <entry text="{name}" />
            <row><button text="OK" command="{accept}" default="true" />
                 <button text="Cancel" command="{cancel}" /></row>
        </group>""")
        self.root.deiconify()
        vm = Rename()

        def answer():
            vm.name = "new"
            vm.accept()
        self.root.after(300, answer)
        self.assertEqual(TkDialogs(self.root).show(vm), "new")
