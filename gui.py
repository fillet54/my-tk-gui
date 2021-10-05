import tkinter as tk
from collections import ChainMap
from string import Formatter
from xml.etree.ElementTree import XML

def select_keys(m, keys):
    return {k:m[k] for k in keys if k in m}

def disassoc(m, keys):
    return {k:m[k] for k in m.keys() if k not in keys}

PACK_OPTIONS = ['side', 'padx', 'pady', 'expand']
BIND_OPTIONS = ['id']

def create_change_listener(var):
    change_listeners = []
    def add_change_listener(listener):
        change_listeners.append(listener)
    def on_change_action(var):
        for listener in change_listeners:
            try:
                listener(var)
            except:
                pass
    var.trace('w', lambda nm, idx, mode, var=var: on_change_action(var))
    return add_change_listener

def on_command_delegate(id, bindings):
    def inner():
        cb = bindings.get(id, lambda bindings: None)
        try:
            cb(bindings)
        except:
            # Don't force bindings to be taken
            cb()
    return inner

def bind(element, widget, bindings):
    if 'id' in element.attrib and len(element.attrib['id']):
        id = element.attrib['id']

        # Not sure how to properly handle custom components
        # and binding for now if something is already bound then return
        if id in bindings:
            return 

        if element.tag in ['entry']:
            bindings[id] = tk.StringVar()
            widget.configure(textvariable=bindings[id])
        elif element.tag in ['checkbutton']:
            bindings[id] = tk.IntVar()
            widget.configure(variable=bindings[id])
        elif element.tag in ['button']: 
            command = on_command_delegate('on_%s_click' % id, bindings)
            widget.configure(command=command)

        if element.tag in ['entry', 'checkbutton']:
            bindings['on_%s_change' % id] = create_change_listener(bindings[id])

        # common bindings
        bindings['%s_widget' % id] = widget

__custom_elements = {}
def register(name, xml, defaults):
    names = [fn for _, fn, _, _ in Formatter().parse(xml) if fn is not None]
    assert all(name in defaults for name in names), "Must provide default for each key"

    def widget_factory(master, element, bindings):
        options = ChainMap(element.attrib, defaults)
        widget, pack_options = realize(master, XML(xml.format(**options)), bindings=bindings)
        pack_options = ChainMap(select_keys(options, PACK_OPTIONS), pack_options)
        return widget, pack_options
    __custom_elements[name] = widget_factory

    
def realize(master, element, bindings=None):
    is_root = bindings is None
    if bindings is None:
        bindings = dict()

    elem_options = disassoc(element.attrib, PACK_OPTIONS + BIND_OPTIONS)
    pack_options = select_keys(element.attrib, PACK_OPTIONS)
    bind_options = select_keys(element.attrib, BIND_OPTIONS)
    
    if element.tag in ["form", 'group']:
        widget = tk.Frame(master, **elem_options)
        for subelement in element:
            sub_widget, sub_options = realize(widget, subelement, bindings)
            sub_widget.pack(**sub_options)
    else:
        if element:
            for subelement in element:
                elem_options[subelement.tag] = subelement.text

        if element.tag in __custom_elements:
            widget, pack_options = __custom_elements[element.tag](master, element, bindings)
        else:
            widget_factory = getattr(tk, element.tag.capitalize())
            widget = widget_factory(master, **elem_options)
        
        bind(element, widget, bindings)

    if is_root:
        return widget, bindings
    else:
        return widget, pack_options

def realize_root(model):
    root = tk.Tk()
    root.title("ElementTk")

    frame, bindings = realize(root, XML(model))
    frame.pack()

    return root, bindings


