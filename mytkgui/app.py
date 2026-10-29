"""The application window: screen scale, platform theme, dialogs and the
UI-thread dispatcher.

    gui.run(VIEW, view_model, title="App")                     # platform look
    gui.run(VIEW, view_model, title="App", theme=winui_ttk.Theme)
"""

import os
from typing import Any, Callable
import re
import subprocess
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from .dialogs import DialogService, TkDialogs
from .tasks import Dispatcher
from .views import realize

__all__ = ["create_root", "run", "detect_scale", "system_prefers_dark"]

def system_prefers_dark():
    """Best-effort OS dark mode check (Windows registry, GNOME/portal setting)."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except ImportError:
        pass
    except OSError:
        return False
    try:
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                             capture_output=True, text=True, timeout=1).stdout
        return "dark" in out
    except (OSError, subprocess.SubprocessError):
        return False


def detect_scale(root: "tk.Misc | None") -> float:
    """How many physical pixels one 1x pixel should take on this screen.

    ``MYTKGUI_SCALE`` overrides it. Otherwise: Windows asks the monitor;
    macOS is 1 (Tk handles Retina itself); X11 follows the same settings as
    GTK and Qt apps (GDK_SCALE, then Xft.dpi, then QT_SCALE_FACTOR, then the
    X server's DPI).
    """
    override = os.environ.get("MYTKGUI_SCALE")
    if override:
        return float(override)

    system = root.tk.call("tk", "windowingsystem")
    if system == "aqua":
        return 1.0
    if system == "win32":
        return _windows_scale(root)

    gdk = _env_number("GDK_SCALE")
    if gdk:
        return gdk
    dpi = _xft_dpi()
    if dpi:
        return dpi / 96
    qt = _env_number("QT_SCALE_FACTOR")
    if qt:
        return qt
    return max(1.0, round(root.winfo_fpixels("1i") / 96, 2))


def _windows_scale(root):
    """The effective DPI of the monitor the window is on, / 96."""
    try:
        from ctypes import byref, windll, wintypes
        monitor = windll.user32.MonitorFromWindow(wintypes.HWND(root.winfo_id()), 2)  # nearest
        x, y = wintypes.UINT(), wintypes.UINT()
        windll.shcore.GetDpiForMonitor(monitor, 0, byref(x), byref(y))       # effective DPI
        return (x.value + y.value) / (2 * 96)
    except (AttributeError, OSError):
        return 1.0


def _env_number(name):
    try:
        value = float(os.environ[name])
    except (KeyError, ValueError):
        return None
    return value if value > 0 else None


def _xft_dpi():
    try:
        out = subprocess.run(["xrdb", "-query"], capture_output=True, text=True, timeout=1).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"^Xft\.dpi:\s*([\d.]+)", out, re.M)
    return float(m.group(1)) if m else None


def _fonts_to_points(root):
    # Tk's default fonts on X11 are sized in pixels (negative sizes), which
    # ignore ``tk scaling``. Convert them to the same size in points.
    for name in tkfont.names(root):
        font = tkfont.nametofont(name, root=root)
        size = int(font.cget("size"))
        if size < 0:
            font.configure(size=max(1, round(-size * 72 / 96)))


def create_root(title: str = "", scale: "float | None" = None,
                theme: "Callable[..., Any] | None" = None) -> tk.Tk:
    """A Tk root window, scaled for the screen it's on.

    Widgets use the platform's own ttk theme (Windows' native look on
    Windows, Aqua on macOS, ``clam`` on Linux, which has no native one).
    ``theme`` is an optional theme to install instead, called as
    ``theme(root, scale=scale)``; for example ``winui_ttk.Theme``. If the
    object it returns has ``set_mode("light" | "dark")``, a view's
    ``theme="{...}"`` binding switches it.
    """
    if os.name == "nt":
        try:   # must happen before Tk creates its first window
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    root.title(title)

    root.ui_scale = scale = scale or detect_scale(root)
    if root.tk.call("tk", "windowingsystem") != "aqua":
        root.tk.call("tk", "scaling", scale * 96 / 72)   # points -> pixels
        _fonts_to_points(root)

    root.ui_theme = None
    if theme is not None:
        root.ui_theme = theme(root, scale=scale)
    else:
        style = ttk.Style(root)
        if root.tk.call("tk", "windowingsystem") == "x11":
            style.theme_use("clam")
            # clam draws arrows and check/radio marks at fixed pixel sizes
            # (Windows and macOS draw theirs at the system's DPI).
            arrow = round(14 * scale)
            for name in ("TCombobox", "TSpinbox", "TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):
                style.configure(name, arrowsize=arrow)
            for name in ("TCheckbutton", "TRadiobutton"):
                style.configure(name, indicatorsize=round(12 * scale), indicatormargin=round(4 * scale))
        # The platform themes give Treeview rows a fixed pixel height, which
        # clips text once fonts scale up; size rows from the font instead.
        line = tkfont.nametofont("TkDefaultFont", root=root).metrics("linespace")
        style.configure("Treeview", rowheight=line + round(6 * scale))
        # Show the "invalid" state (bad input, validation errors); the
        # platform themes draw nothing for it.
        for name in ("TEntry", "TCombobox", "TSpinbox"):
            style.map(name, fieldbackground=[("invalid", "#fde7e9")])

    # View models reach Tk through these: dialogs, and work posted from threads.
    DialogService.current = TkDialogs(root)
    dispatcher = Dispatcher.current
    dispatcher.ui_thread = threading.get_ident()

    def pump():
        if not root.winfo_exists():
            return
        dispatcher.run_pending()
        root.after(15, pump)
    root.after(15, pump)
    return root


def run(xml: str, view_model: Any, title: str = "", minsize: "tuple[int, int] | None" = None,
        theme: "Callable[..., Any] | None" = None) -> None:
    """Create a window, bind ``xml`` to ``view_model`` and run the event loop."""
    root = create_root(title, theme=theme)
    view = realize(root, xml, view_model)
    view.widget.pack(fill="both", expand=True)
    if minsize:
        root.minsize(*(round(v * root.ui_scale) for v in minsize))
    root.mainloop()
