import tkinter as tk
from xml.etree.ElementTree import XML

PACK_OPTIONS = ['side', 'padx', 'pady', 'expand']
BINDING_OPTIONS = ['id', 'type']

def on_command_delegate(id, bindings):
    def inner():
        cb = bindings.get(id, lambda : None)
        cb()
    return inner

def bind(element, elem_options, bind_options, bindings):
    if 'id' in bind_options:
        id = bind_options['id']
        if element.tag in ['entry']:
            bindings[id] = tk.StringVar()
            elem_options['textvariable'] = bindings[id]
        elif element.tag in ['checkbutton']:
            bindings[id] = tk.IntVar()
            elem_options['variable'] = bindings[id]
        elif element.tag in ['button']: 
            command = on_command_delegate('on_%s_click' % id, bindings)
            elem_options['command'] = command
    elif len(bind_options) > 0:
        print("WARNING: ID required for binding")
    
    
def realize(master, element, bindings=None):
    is_root = bindings is None
    if bindings is None:
        bindings = dict()

    elem_options = {k:v 
                    for k,v in element.attrib.items() 
                      if k not in PACK_OPTIONS 
                      and k not in BINDING_OPTIONS}
    pack_options = {k:v 
                    for k,v in element.attrib.items() 
                       if k in PACK_OPTIONS} 
    bind_options = {k:v 
                    for k,v in element.attrib.items() 
                       if k in BINDING_OPTIONS} 
    
    if element.tag in ["form", 'group']:
        widget = tk.Frame(master, **elem_options)
        for subelement in element:
            sub_widget, sub_options = realize(widget, subelement, bindings)
            sub_widget.pack(**sub_options)
    else:
        if element:
            for subelement in element:
                elem_options[subelement.tag] = subelement.text
        bind(element, elem_options, bind_options, bindings)
        widget_factory = getattr(tk, element.tag.capitalize())
        widget = widget_factory(master, **elem_options)


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


