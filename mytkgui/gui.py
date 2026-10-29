"""Everything for building windows from views, in one namespace::

    from mytkgui import gui
    gui.template(PageViewModel, PAGE_VIEW)
    gui.run(SHELL_VIEW, shell, title="App")

See ``views`` for the XML elements and attributes, ``bindings`` for the
binding syntax and ``app`` for windows, scaling and themes.
"""

from .app import create_root, detect_scale, run, system_prefers_dark
from .bindings import (BindingError, Binding, TemplateBinding, converter, is_binding, parse, resource,
                       strict_bindings)
from .views import (View, ViewError, accelerator_text, key_sequence, parse_xml, realize, realize_for,
                    register, template, template_for)

__all__ = ["create_root", "detect_scale", "run", "system_prefers_dark",
           "BindingError", "Binding", "TemplateBinding", "converter", "is_binding", "parse", "resource",
           "strict_bindings", "View", "ViewError", "accelerator_text", "key_sequence", "parse_xml",
           "realize", "realize_for", "register", "template", "template_for"]
