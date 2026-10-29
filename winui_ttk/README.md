# winui_ttk

A WinUI 3 (Fluent) theme for ttk. Every element image is drawn at startup
from WinUI's design tokens, at the exact screen scale (including 125%, 150%
and 175%), and repainted in place when you change light/dark mode or the
accent color. The images are SVG, rendered by Tk itself, so there are no
dependencies beyond the standard library.

**Needs Tk 9**, for its built-in SVG images. Check with
`python3 -c "import tkinter; print(tkinter.TkVersion)"`.

```
python3-tk9 -m winui_ttk.demo                     # controls gallery
python3-tk9 -m unittest discover -s winui_ttk/tests -t .
WINUI_TTK_SCALE=1.25 python3-tk9 -m winui_ttk.demo   # try another scale
```

## Getting a Python with Tk 9

- **Linux:** distros still package Tk 8.6, and the prebuilt Pythons from
  mise/uv (python-build-standalone) have Tk 9 but no Xft, so every font is
  the X11 bitmap font. `./build-python-tk9.sh` builds Tcl/Tk 9.0.4 with Xft
  and Python 3.14 against it under `~/.local/opt`, and links
  `~/.local/bin/python3-tk9`. It takes a few minutes.
- **Windows / macOS:** check `tkinter.TkVersion` on the python.org build you
  use; if it's 8.6, build or install one with Tk 9.

```python
import winui_ttk
from tkinter import ttk

root, theme = winui_ttk.create_root("App", mode="dark", accent="#E3008C")
card = ttk.Frame(root, class_="Card")    # rounded card, 16px padding (style="Card" works too)
ttk.Button(card, text="Save", style="Accent.TButton").pack()
ttk.Checkbutton(card, text="Wi-Fi", style="Switch.TCheckbutton").pack()
theme.set_mode("light")
theme.set_accent("#00B294")
```

This package doesn't depend on the rest of this repo. To split it out,
move the folder.

## Controls

| WinUI control | ttk widget / style | States drawn |
|---|---|---|
| Button | `TButton` | rest, hover, pressed, disabled, keyboard focus |
| Accent button | `Accent.TButton` | same |
| TextBox | `TEntry` | rest, hover, focus (accent underline), disabled, `invalid` |
| ComboBox | `TCombobox` | read-only looks like a button; editable looks like a TextBox |
| CheckBox | `TCheckbutton` | unchecked, checked, indeterminate × rest/hover/pressed/disabled |
| RadioButton | `TRadiobutton` | unselected, selected × 4 |
| ToggleSwitch | `Switch.TCheckbutton` | off, on × 4, with the knob growing on hover and stretching on press |
| Slider | `Horizontal.TScale` | thumb grows on hover, shrinks on press |
| ProgressBar | `Horizontal.TProgressbar` | 1px track, 3px rounded accent bar, indeterminate |
| ListView + ScrollBar | `Treeview`, `TScrollbar` | 40px rows, rounded selection with the accent pill; the scrollbar is a 2px line that expands to a thumb and arrows on hover |
| TabView | `TNotebook` | selected tab joins the content panel; hover |
| Card / typography | `Frame(class_="Card")`, `Caption/Body/BodyStrong/Subtitle/Title/TitleLarge/Display.TLabel`, `Secondary.TLabel`, `Accent.TLabel` | |

Widgets inside a `Card` or `Notebook` move to the card surface color
automatically (they get a `Surface.<style>` style when first shown). You
never need to name those styles.

## How it works

- `tokens.py` holds WinUI's color brushes for light and dark mode, the
  accent palette, sizes and the type ramp, under WinUI's resource names.
- `elements.py` draws each element and state as SVG (`svg.py`) in
  effective pixels × scale, as nine-slice images so they stretch to any size.
- **Every image is opaque.** Tk draws a photo with any partly transparent
  pixel by reading the window back from the X server for each tile, and ttk
  stretches an element by tiling its middle. On a large panel that is
  hundreds of thousands of round trips, and the window never finishes
  painting. So each image is painted over the color it will sit on, in two
  sets: on the window background, and on the card surface
  (`Surface.<element>`). Widgets inside a card or notebook switch to the
  second set when first shown. Elements drawn over other elements (slider
  thumb, combobox chevron, scrollbar thumb) include what is under them.
- Stretchable images have a 64px middle, so a large panel is a few hundred
  cheap pixmap copies.
- `theme.py` creates the ttk theme, layouts, styles and fonts (sized in
  pixels, so they don't depend on Tk's DPI guess).
- The accent shades are Windows' own palette for the default blue (read
  from the registry on Windows), and derived the same way for other colors.

Startup draws 198 images in about 50ms at 200%. Mode and accent changes
take the same time.

Because images are opaque, a widget placed on a background the theme
doesn't know (a frame you colored yourself) shows the window color around
its rounded corners.

## How faithful it is

The values come from WinUI 3's theme resources as I know them (colors,
corner radii, padding, control sizes). I haven't been able to compare it
side by side with a real WinUI app; it was built and checked on Linux, so
please check it against WinUI 3 Gallery on Windows. On Windows it uses
Segoe UI Variable. On Linux it falls back to Noto Sans, and semibold
becomes bold.

Known gaps, which are ttk limits rather than missing work:

- **No animations.** WinUI fades between states; ttk switches instantly.
- **Slider:** ttk can't fill the track up to the thumb in accent color.
- **ComboBox dropdown:** it's a plain Tk listbox, so the colors match but
  it has no rounded corners, shadow or 40px items.
- **ListView:** ttk (Tk 9 included) has no per-row hover.
- **Focus rings:** buttons only. On check, radio and switch controls a ring
  would push the control off WinUI's left edge.
- **Text rendering:** Tk uses GDI rather than DirectWrite on Windows, so
  text looks a little different. There's no Mica/Acrylic backdrop.
- **Window chrome:** only the dark title bar (Windows 10 1809+). The
  Windows-specific code (registry accent, DPI awareness, title bar) is
  untested.
- **Per-monitor DPI:** the scale is fixed at startup. Moving to a monitor
  with a different scale needs a new `Theme(scale=...)`.
