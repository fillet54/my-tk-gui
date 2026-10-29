"""WinUI 3 (Fluent) look for ttk, drawn at the exact screen scale.

    import tkinter as tk
    import winui_ttk

    root, theme = winui_ttk.create_root("App", mode="dark", accent="#E3008C")
    ...
    theme.set_mode("light")
    theme.set_accent("#00B294")

No dependencies beyond the standard library. Every element image is drawn
at startup from WinUI's design tokens (see tokens.py), so it is sharp at
any scale, including 125%, 150% and 175%.
"""

from .theme import Theme, create_root, detect_scale, enable_dpi_awareness
from .tokens import DEFAULT_ACCENT, WINDOWS_ACCENTS, accent_palette
from .widgets import TextBox, theme_of

__all__ = ["Theme", "create_root", "detect_scale", "enable_dpi_awareness",
           "DEFAULT_ACCENT", "WINDOWS_ACCENTS", "accent_palette", "TextBox", "theme_of"]
