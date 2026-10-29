"""Drawing for every ttk element the theme replaces.

Each element is an ``Element``: its nine-slice geometry (which depends only
on the scale) and an ordered list of (ttk state spec, paint function). A
paint function takes the resolved ``Colors`` and returns an ``Svg``, so
switching light/dark or the accent repaints the same images in place.

Every image is opaque: it is painted over ``c.under``, the color it will
sit on. The theme builds each element twice, once on the window background
and once on the card surface (``Surface.<element>``), and widgets inside
cards switch to the second set. Elements drawn on top of other elements
(slider thumb, chevrons, scrollbar thumb, tree chevrons) bake in what is
beneath them.

Stretchable images have a wide middle (``TILE``) because ttk fills a
stretched element by tiling the middle slice; a 1px middle on a large panel
means hundreds of thousands of draw calls. ``size`` then sets the element's
requested size back to just its borders.

All coordinates are WinUI effective pixels times ``s``. Strokes that are
1epx in WinUI are rounded to whole device pixels (WinUI's layout rounding
does the same) so edges stay crisp at 125%/150%.
"""

import copy
import math

from .svg import Svg, circle, polygon, polyline, rrect
from .tokens import METRICS, over, parse

TILE = 64   # device pixels of stretchable middle in every nine-slice image


class Element:
    def __init__(self, name, states, border=0, sticky="nsew", padding=0, size=(-1, -1)):
        self.name = name
        self.states = states          # [(statespec tuple, paint fn)], "" = default
        self.border = border
        self.sticky = sticky
        self.padding = padding
        self.size = size              # requested (w, h); -1 = the image's own size


class Colors:
    """Token lookup for one mode + accent, composited to opaque colors.

    ``under`` is the color the element being painted sits on: the window
    background, or the card surface for the ``Surface.`` variants.
    """

    def __init__(self, tokens):
        self.tokens = tokens
        self.base = parse(tokens["SolidBackgroundFillColorBase"])
        self.surface = over(parse(tokens["CardBackgroundFillColorDefault"]), self.base)
        self.under = self.base

    def on_surface(self):
        other = copy.copy(self)
        other.under = self.surface
        return other

    def raw(self, name):
        return parse(self.tokens[name])

    def on(self, name, under=None):
        """Token ``name`` composited over ``under`` (default: what the element sits on)."""
        return over(parse(self.tokens[name]), under or self.under)


def stroke(s):
    return max(1, round(s))


def build(s):
    """Every element at scale ``s``."""
    st = stroke(s)
    focus_w = max(2, round(2 * s))
    return (
        _buttons(s, st, focus_w)
        + _entry(s, st)
        + _check_radio_switch(s, st)
        + _combobox(s, st)
        + _spinbox(s, st)
        + _menubutton(s, st)
        + _slider(s, st)
        + _progress(s, st)
        + _scrollbars(s, st)
        + _separators(s, st)
        + _list(s, st)
        + _tabs_and_cards(s, st)
    )


# --------------------------------------------------------------------------
# Shared drawing
# --------------------------------------------------------------------------

def _bordered(c, W, H, R, st, fill, top, bottom, bottom_width=None):
    """Rounded box whose border is ``top`` except a ``bottom`` edge (WinUI's
    elevation gradient). Border colors are composited over the fill, as WinUI
    draws backgrounds under borders (BackgroundSizing=OuterBorderEdge)."""
    bw = bottom_width or st
    img = Svg(W, H, c.under)
    img.draw(rrect(0, 0, W, H, R), bottom)
    img.draw(rrect(0, 0, W, H - bw, R), top)
    img.draw(rrect(st, st, W - st, H - bw, max(R - st, 0)), fill)
    return img


def _focused(c, W, H, R, st, ring, fill):
    img = Svg(W, H, c.under)
    img.draw(rrect(0, 0, W, H, R), c.on("FocusStrokeColorOuter"))
    img.draw(rrect(ring, ring, W - ring, H - ring, max(R - ring, 0)), c.on("FocusStrokeColorInner", fill))
    img.draw(rrect(ring + st, ring + st, W - ring - st, H - ring - st, max(R - ring - st, 0)), fill)
    return img


def _chevron(W, H, cx, cy, direction, s, half=4, width=1.0):
    """A chevron glyph painter: ``paint(c, under, color_name)``."""
    h, d = half * s, half / 2 * s
    pts = {
        "down": [(cx - h, cy - d), (cx, cy + d), (cx + h, cy - d)],
        "up": [(cx - h, cy + d), (cx, cy - d), (cx + h, cy + d)],
        "right": [(cx - d, cy - h), (cx + d, cy), (cx - d, cy + h)],
    }[direction]

    def paint(c, under, color_name):
        img = Svg(W, H, under)
        return img.draw(polyline(pts, width * s), c.on(color_name, under))
    return paint


# Fill token for each button state, shared by elements drawn on a button.
_BUTTON_FILLS = [
    (("disabled",), "ControlFillColorDisabled"),
    (("pressed",), "ControlFillColorTertiary"),
    (("active",), "ControlFillColorSecondary"),
    ("", "ControlFillColorDefault"),
]


# --------------------------------------------------------------------------
# Buttons: elevation border (darker bottom edge), state fills, focus ring
# --------------------------------------------------------------------------

def _buttons(s, st, ring):
    R = METRICS["ControlCornerRadius"] * s
    B = math.ceil(R) + ring + st
    W = H = 2 * B + TILE

    def standard(fill_name, flat=False, focus=False):
        def paint(c):
            fill = c.on(fill_name)
            if focus:
                return _focused(c, W, H, R, st, ring, fill)
            top = c.on("ControlStrokeColorDefault", fill)
            bottom = top if flat else c.on("ControlStrokeColorSecondary", fill)
            return _bordered(c, W, H, R, st, fill, top, bottom)
        return paint

    def accent(fill_name, border=True, focus=False):
        def paint(c):
            fill = c.on(fill_name)
            if focus:
                return _focused(c, W, H, R, st, ring, fill)
            if not border:
                return _bordered(c, W, H, R, st, fill, fill, fill)
            return _bordered(c, W, H, R, st, fill,
                             c.on("ControlStrokeColorOnAccentDefault", fill),
                             c.on("ControlStrokeColorOnAccentSecondary", fill))
        return paint

    def subtle(fill_name, focus=False):
        def paint(c):
            fill = c.on(fill_name) if fill_name else c.under
            if focus:
                return _focused(c, W, H, R, st, ring, fill)
            return Svg(W, H, c.under).draw(rrect(0, 0, W, H, R), fill)
        return paint

    standard_states = [
        (("disabled",), standard("ControlFillColorDisabled", flat=True)),
        (("focus", "pressed"), standard("ControlFillColorTertiary", focus=True)),
        (("focus", "active"), standard("ControlFillColorSecondary", focus=True)),
        (("focus",), standard("ControlFillColorDefault", focus=True)),
        (("pressed",), standard("ControlFillColorTertiary", flat=True)),
        (("active",), standard("ControlFillColorSecondary")),
        ("", standard("ControlFillColorDefault")),
    ]
    accent_states = [
        (("disabled",), accent("AccentFillColorDisabled", border=False)),
        (("focus", "pressed"), accent("AccentFillColorTertiary", focus=True)),
        (("focus", "active"), accent("AccentFillColorSecondary", focus=True)),
        (("focus",), accent("AccentFillColorDefault", focus=True)),
        (("pressed",), accent("AccentFillColorTertiary", border=False)),
        (("active",), accent("AccentFillColorSecondary")),
        ("", accent("AccentFillColorDefault")),
    ]

    def selected(states):
        """``states`` with "selected" added to each spec (the default becomes ("selected",))."""
        return [((spec if spec else ()) + ("selected",), paint) for spec, paint in states]

    size = (2 * B, 2 * B)
    return [
        Element("Button.border", standard_states, border=B, size=size),
        Element("AccentButton.border", accent_states, border=B, size=size),
        # ToggleButton: a standard button that turns accent when checked.
        Element("ToggleButton.border", selected(accent_states) + standard_states, border=B, size=size),
        # Toolbar / subtle button: no fill until hovered; accent when checked.
        Element("Toolbutton.border", selected(accent_states) + [
            (("disabled",), subtle(None)),
            (("pressed",), subtle("SubtleFillColorTertiary")),
            (("focus", "active"), subtle("SubtleFillColorSecondary", focus=True)),
            (("focus",), subtle(None, focus=True)),
            (("active",), subtle("SubtleFillColorSecondary")),
            ("", subtle(None)),
        ], border=B, size=size),
    ]


# --------------------------------------------------------------------------
# TextBox: strong bottom stroke at rest, 2px accent underline when focused
# --------------------------------------------------------------------------

def _textbox_paint(W, H, R, st, underline, fill_name, bottom_name, thick=False, flat=False):
    def paint(c):
        fill = c.on(fill_name)
        top = c.on("ControlStrokeColorDefault", fill)
        bottom = top if flat else c.on(bottom_name, fill)
        return _bordered(c, W, H, R, st, fill, top, bottom, underline if thick else st)
    return paint


# (state spec, fill token, bottom stroke token, thick underline, flat) per TextBox state
TEXTBOX_STATES = [
    (("disabled",), "ControlFillColorDisabled", "ControlStrokeColorDefault", False, True),
    (("invalid", "focus"), "ControlFillColorInputActive", "SystemFillColorCritical", True, False),
    (("invalid",), "ControlFillColorDefault", "SystemFillColorCritical", True, False),
    (("focus",), "ControlFillColorInputActive", "AccentFillColorDefault", True, False),
    (("hover",), "ControlFillColorSecondary", "ControlStrongStrokeColorDefault", False, False),
    ("", "ControlFillColorDefault", "ControlStrongStrokeColorDefault", False, False),
]


def _textbox_geometry(s):
    R = METRICS["ControlCornerRadius"] * s
    underline = max(2, round(2 * s))
    B = math.ceil(R) + underline
    return R, underline, B, 2 * B + TILE


def _entry(s, st):
    R, underline, B, W = _textbox_geometry(s)
    return [Element("Entry.field", [
        (spec, _textbox_paint(W, W, R, st, underline, fill, bottom, thick=thick, flat=flat))
        for spec, fill, bottom, thick, flat in TEXTBOX_STATES
    ], border=B, size=(2 * B, 2 * B))]


# --------------------------------------------------------------------------
# CheckBox, RadioButton, ToggleSwitch
# --------------------------------------------------------------------------

def _check_radio_switch(s, st):
    box = METRICS["CheckBoxSize"] * s
    gap = METRICS["CheckBoxGap"] * s
    H = round(box)
    W = round(box + gap)
    R = METRICS["ControlCornerRadius"] * s
    cy = H / 2

    # Unchecked look shared by all three: strong stroke around a subtle fill.
    UNCHECKED = {
        "rest": ("ControlAltFillColorSecondary", "ControlStrongStrokeColorDefault"),
        "hover": ("ControlAltFillColorTertiary", "ControlStrongStrokeColorDefault"),
        "pressed": ("ControlAltFillColorQuarternary", "ControlStrongStrokeColorDefault"),
        "disabled": ("ControlAltFillColorDisabled", "ControlStrongStrokeColorDisabled"),
    }
    ACCENT = {
        "rest": "AccentFillColorDefault", "hover": "AccentFillColorSecondary",
        "pressed": "AccentFillColorTertiary", "disabled": "AccentFillColorDisabled",
    }
    GLYPH = {
        "rest": "TextOnAccentFillColorPrimary", "hover": "TextOnAccentFillColorPrimary",
        "pressed": "TextOnAccentFillColorSecondary", "disabled": "TextOnAccentFillColorDisabled",
    }

    def outlined(img, c, shape_outer, shape_inner, state):
        fill_name, stroke_name = UNCHECKED[state]
        fill = c.on(fill_name)
        img.draw(shape_outer, c.on(stroke_name, fill))
        img.draw(shape_inner, fill)

    # -- CheckBox --
    def check(kind, state):
        def paint(c):
            img = Svg(W, H, c.under)
            outer = rrect(0, 0, box, box, R)
            if kind == "off":
                outlined(img, c, outer, rrect(st, st, box - st, box - st, max(R - st, 0)), state)
                return img
            fill = c.on(ACCENT[state])
            img.draw(outer, fill)
            glyph = c.on(GLYPH[state], fill)
            k = box / 20
            if kind == "on":
                pts = [(5.25 * k, 10.5 * k), (8.5 * k, 13.75 * k), (14.75 * k, 7.0 * k)]
            else:
                pts = [(6.0 * k, 10 * k), (14.0 * k, 10 * k)]
            img.draw(polyline(pts, 1.3 * s), glyph)
            return img
        return paint

    def states(paint, kinds):
        out = []
        for flag, kind in kinds:
            pre = (flag,) if flag else ()
            out += [
                (("disabled",) + pre, paint(kind, "disabled")),
                (("pressed",) + pre, paint(kind, "pressed")),
                (("active",) + pre, paint(kind, "hover")),
                (pre or "", paint(kind, "rest")),
            ]
        return out

    check_el = Element("Checkbutton.indicator",
                       states(check, [("alternate", "mixed"), ("selected", "on"), (None, "off")]),
                       sticky="")

    # -- RadioButton --
    r_out = box / 2
    DOT = {"rest": 6, "hover": 7, "pressed": 5, "disabled": 6}

    def radio(kind, state):
        def paint(c):
            img = Svg(W, H, c.under)
            if kind == "off":
                outlined(img, c, circle(r_out, cy, r_out), circle(r_out, cy, r_out - st), state)
                return img
            fill = c.on(ACCENT[state])
            img.draw(circle(r_out, cy, r_out), fill)
            img.draw(circle(r_out, cy, DOT[state] * s), c.on(GLYPH[state], fill))
            return img
        return paint

    radio_el = Element("Radiobutton.indicator",
                       states(radio, [("selected", "on"), (None, "off")]), sticky="")

    # -- ToggleSwitch --
    tw, th = (v * s for v in METRICS["ToggleSwitchTrack"])
    SW = round(tw + METRICS["ToggleSwitchGap"] * s)
    SH = round(th)
    tcy = SH / 2
    KNOB_TEXT = {
        "rest": "TextFillColorSecondary", "hover": "TextFillColorSecondary",
        "pressed": "TextFillColorSecondary", "disabled": "TextFillColorDisabled",
    }

    def switch(kind, state):
        def paint(c):
            img = Svg(SW, SH, c.under)
            track = rrect(0, 0, tw, th, th / 2)
            if kind == "off":
                outlined(img, c, track, rrect(st, st, tw - st, th - st, th / 2 - st), state)
                knob_color = c.on(KNOB_TEXT[state], c.on(UNCHECKED[state][0]))
                cx = 10 * s
            else:
                fill = c.on(ACCENT[state])
                img.draw(track, fill)
                knob_color = c.on("TextOnAccentFillColorDisabled" if state == "disabled"
                                  else "TextOnAccentFillColorPrimary", fill)
                cx = tw - 10 * s
            if state == "pressed":
                kw, kh = 17 * s, 14 * s
                x0 = cx - 7 * s if kind == "off" else cx + 7 * s - kw
                img.draw(rrect(x0, tcy - kh / 2, x0 + kw, tcy + kh / 2, kh / 2), knob_color)
            else:
                img.draw(circle(cx, tcy, (7 if state == "hover" else 6) * s), knob_color)
            return img
        return paint

    switch_el = Element("Switch.indicator",
                        states(switch, [("selected", "on"), (None, "off")]), sticky="")
    return [check_el, radio_el, switch_el]


# --------------------------------------------------------------------------
# ComboBox: button look when read-only, TextBox look when editable
# --------------------------------------------------------------------------

def _combobox(s, st):
    R, underline, B, W = _textbox_geometry(s)
    H = W

    def button(fill_name, flat=False):
        def paint(c):
            fill = c.on(fill_name)
            top = c.on("ControlStrokeColorDefault", fill)
            bottom = top if flat else c.on("ControlStrokeColorSecondary", fill)
            return _bordered(c, W, H, R, st, fill, top, bottom)
        return paint

    # (state spec, field fill token, field paint)
    FIELD = [
        (("readonly", "disabled"), "ControlFillColorDisabled", button("ControlFillColorDisabled", flat=True)),
        (("readonly", "pressed"), "ControlFillColorTertiary", button("ControlFillColorTertiary", flat=True)),
        (("readonly", "hover"), "ControlFillColorSecondary", button("ControlFillColorSecondary")),
        (("readonly",), "ControlFillColorDefault", button("ControlFillColorDefault")),
    ] + [
        (spec, fill, _textbox_paint(W, H, R, st, underline, fill, bottom, thick=thick, flat=flat))
        for spec, fill, bottom, thick, flat in TEXTBOX_STATES if "invalid" not in spec
    ]
    # The field reserves its right stroke so the opaque chevron column never covers it.
    field = Element("Combobox.field", [(spec, paint) for spec, _, paint in FIELD],
                    border=B, padding=(0, 0, st, 0), size=(2 * B, 2 * B))

    AW = round(METRICS["ComboBoxGlyphColumn"] * s) - st
    AH = round(12 * s)
    glyph = _chevron(AW, AH, AW - 20 * s + st, AH / 2, "down", s)

    # The chevron sits on the field, so each state is painted on that state's fill.
    arrow = Element("Combobox.downarrow", [
        (spec, lambda c, fill=fill, spec=spec: glyph(
            c, c.on(fill), "TextFillColorDisabled" if "disabled" in spec else "TextFillColorSecondary"))
        for spec, fill, _ in FIELD
    ], sticky="")
    return [field, arrow]


# --------------------------------------------------------------------------
# NumberBox (Spinbox): a TextBox with inline up/down buttons
# --------------------------------------------------------------------------

def _spinbox(s, st):
    R, underline, B, W = _textbox_geometry(s)
    field = Element("Spinbox.field", [
        (spec, _textbox_paint(W, W, R, st, underline, fill, bottom, thick=thick, flat=flat))
        for spec, fill, bottom, thick, flat in TEXTBOX_STATES
    ], border=B, padding=(0, 0, st, 0), size=(2 * B, 2 * B))

    AW = round(METRICS["NumberBoxSpinButton"] * s)
    AH = round(20 * s)
    out = [field]
    for name, direction in (("uparrow", "up"), ("downarrow", "down")):
        glyph = _chevron(AW, AH, AW / 2, AH / 2, direction, s)
        out.append(Element("Spinbox.%s" % name, [
            (spec, lambda c, fill=fill, spec=spec, glyph=glyph: glyph(
                c, c.on(fill), "TextFillColorDisabled" if "disabled" in spec else "TextFillColorSecondary"))
            for spec, fill, _, _, _ in TEXTBOX_STATES
        ], sticky=""))
    return out


# --------------------------------------------------------------------------
# DropDownButton (Menubutton): a button with a chevron after the label
# --------------------------------------------------------------------------

def _menubutton(s, st):
    gap, glyph_w = METRICS["DropDownGap"] * s, 12 * s
    W, H = round(gap + glyph_w), round(12 * s)
    glyph = _chevron(W, H, W - glyph_w / 2, H / 2, "down", s)
    return [Element("Menubutton.indicator", [
        (spec, lambda c, fill=fill, spec=spec: glyph(
            c, c.on(fill), "TextFillColorDisabled" if "disabled" in spec else "TextFillColorSecondary"))
        for spec, fill in _BUTTON_FILLS
    ], sticky="")]


# --------------------------------------------------------------------------
# Slider
# --------------------------------------------------------------------------

def _slider(s, st):
    T = METRICS["SliderThumb"] * s
    H = round(T)
    c0 = H / 2
    track = METRICS["SliderTrack"] * s
    bx = math.ceil(track / 2) + 1
    L = 2 * bx + TILE
    rest, hover, pressed = METRICS["SliderInnerThumb"]
    out = []

    for orient in ("Horizontal", "Vertical"):
        vertical = orient == "Vertical"

        def band(img, l0, l1, color, vertical=vertical):
            """The track from l0 to l1 along the slider, centered across it."""
            a0, a1 = c0 - track / 2, c0 + track / 2
            box = (a0, l0, a1, l1) if vertical else (l0, a0, l1, a1)
            return img.draw(rrect(*box, track / 2), color)

        def trough(color_name, band=band, vertical=vertical):
            def paint(c):
                img = Svg(*((H, L) if vertical else (L, H)), c.under)
                return band(img, 0, L, c.on(color_name))
            return paint

        out.append(Element("%s.Scale.trough" % orient, [
            (("disabled",), trough("ControlStrongFillColorDisabled")),
            ("", trough("ControlStrongFillColorDefault")),
        ], border=(0, bx, 0, bx) if vertical else (bx, 0, bx, 0), sticky="ns" if vertical else "ew",
            size=(-1, 2 * bx) if vertical else (2 * bx, -1)))

        # The thumb always sits on the track, so the track runs through its image.
        def thumb(inner, inner_color, track_color, band=band):
            def paint(c):
                img = band(Svg(H, H, c.under), -track, H + track, c.on(track_color))
                solid = c.on("ControlSolidFillColorDefault")
                img.draw(circle(c0, c0, T / 2), c.on("ControlStrokeColorSecondary", solid))
                img.draw(circle(c0, c0 - st / 2, T / 2 - st / 2), c.on("ControlStrokeColorDefault", solid))
                img.draw(circle(c0, c0, T / 2 - st), solid)
                img.draw(circle(c0, c0, inner * s / 2), c.on(inner_color, solid))
                return img
            return paint

        out.append(Element("%s.Scale.slider" % orient, [
            (("disabled",), thumb(rest, "AccentFillColorDisabled", "ControlStrongFillColorDisabled")),
            (("pressed",), thumb(pressed, "AccentFillColorTertiary", "ControlStrongFillColorDefault")),
            (("hover",), thumb(hover, "AccentFillColorSecondary", "ControlStrongFillColorDefault")),
            ("", thumb(rest, "AccentFillColorDefault", "ControlStrongFillColorDefault")),
        ], sticky=""))
    return out


# --------------------------------------------------------------------------
# ProgressBar: 1px track, 3px rounded accent indicator
# --------------------------------------------------------------------------

def _progress(s, st):
    H = max(3, round(METRICS["ProgressBarIndicator"] * s))
    c0 = H / 2
    b = math.ceil(H / 2)
    PW = 2 * b + TILE
    moving = round(METRICS["ProgressBarIndeterminate"] * s)
    out = []

    for orient in ("Horizontal", "Vertical"):
        vertical = orient == "Vertical"

        def size(length, vertical=vertical):
            return (H, length) if vertical else (length, H)

        def track(c, length, vertical=vertical, size=size):
            box = (c0 - st / 2, 0, c0 + st / 2, length) if vertical else (0, c0 - st / 2, length, c0 + st / 2)
            return Svg(*size(length), c.under).draw(rrect(*box, 0), c.on("ControlStrongStrokeColorDefault"))

        # The bar sits on the track line, so it is painted over it.
        def bar(color_name, track=track, size=size):
            def paint(c):
                return track(c, PW).draw(rrect(0, 0, *size(PW), H / 2), c.on(color_name))
            return paint

        out += [
            Element("%s.Progressbar.trough" % orient, [("", lambda c, track=track: track(c, 2 + TILE))],
                    border=(0, 1, 0, 1) if vertical else (1, 0, 1, 0), sticky="ns" if vertical else "ew",
                    size=(-1, 2) if vertical else (2, -1)),
            # ttk sizes the moving bar of an indeterminate progressbar from this length.
            Element("%s.Progressbar.pbar" % orient, [
                (("disabled",), bar("AccentFillColorDisabled")),
                ("", bar("AccentFillColorDefault")),
            ], border=(0, b, 0, b) if vertical else (b, 0, b, 0), sticky="nsew",
                size=(-1, moving) if vertical else (moving, -1)),
        ]
    return out


# --------------------------------------------------------------------------
# ScrollBar: a 2px indicator that expands to a 6px thumb and arrows on hover
# --------------------------------------------------------------------------

def _scrollbars(s, st):
    out = []
    S = round(METRICS["ScrollBarSize"] * s)
    B = math.ceil(6 * s) + 1
    L = 2 * B + TILE

    for orient in ("Vertical", "Horizontal"):
        vertical = orient == "Vertical"

        def box(across, along, vertical=vertical):
            """(x0, y0, x1, y1) from across/along coords for this orientation."""
            (a0, a1), (l0, l1) = across, along
            return (a0, l0, a1, l1) if vertical else (l0, a0, l1, a1)

        size = (S, L) if vertical else (L, S)
        mid = S / 2

        def panel(c):
            return c.on("AcrylicBackgroundFillColorDefault")

        def trough_paint(hovered, size=size, box=box):
            def paint(c):
                img = Svg(*size, c.under)
                if hovered:
                    img.draw(rrect(*box((0, S), (0, L)), S / 2), panel(c))
                return img
            return paint

        # On hover the thumb sits on the expanded panel, otherwise on the background.
        def thumb_paint(width, color_name, hovered, size=size, box=box, mid=mid):
            def paint(c):
                under = panel(c) if hovered else c.under
                img = Svg(*size, under)
                w = width * s
                img.draw(rrect(*box((mid - w / 2, mid + w / 2), (st, L - st)), w / 2), c.on(color_name, under))
                return img
            return paint

        across_border = (S - 1) // 2
        border = ((across_border, B, S - 1 - across_border, B) if vertical
                  else (B, across_border, B, S - 1 - across_border))
        min_size = (-1, 2 * B) if vertical else (2 * B, -1)

        out.append(Element("%s.Scrollbar.trough" % orient, [
            (("hover",), trough_paint(True)), ("", trough_paint(False)),
        ], border=border, sticky="nsew", size=min_size))
        out.append(Element("%s.Scrollbar.thumb" % orient, [
            (("pressed",), thumb_paint(6, "TextFillColorTertiary", True)),
            (("hover",), thumb_paint(6, "ControlStrongFillColorDefault", True)),
            ("", thumb_paint(2, "ControlStrongFillColorDefault", False)),
        ], border=border, sticky="nsew", size=min_size))

        for name, direction in ((("uparrow", -1), ("downarrow", 1)) if vertical
                                else (("leftarrow", -1), ("rightarrow", 1))):
            # Arrows sit at the ends of the panel, so on hover they include its rounded cap.
            def arrow(shown, direction=direction, vertical=vertical, box=box):
                def paint(c):
                    img = Svg(S, S, c.under)
                    if shown:
                        along = (0, 2 * S) if direction < 0 else (-S, S)
                        img.draw(rrect(*box((0, S), along), S / 2), panel(c))
                        cx = cy = S / 2
                        h, w = 2 * s * direction, 3 * s
                        pts = ([(cx - w, cy - h), (cx + w, cy - h), (cx, cy + h)] if vertical
                               else [(cx - h, cy - w), (cx - h, cy + w), (cx + h, cy)])
                        img.draw(polygon(pts), c.on("ControlStrongFillColorDefault", panel(c)))
                    return img
                return paint
            out.append(Element("%s.Scrollbar.%s" % (orient, name), [
                (("hover",), arrow(True)), ("", arrow(False)),
            ], sticky=""))
    return out


# --------------------------------------------------------------------------
# Separator: a 1px divider line
# --------------------------------------------------------------------------

def _separators(s, st):
    L = 2 + TILE

    def line(vertical):
        def paint(c):
            img = Svg(*((st, L) if vertical else (L, st)), c.under)
            return img.draw(rrect(0, 0, *((st, L) if vertical else (L, st)), 0), c.on("DividerStrokeColorDefault"))
        return paint

    return [
        Element("Horizontal.Separator.separator", [("", line(False))], border=(1, 0, 1, 0),
                sticky="ew", size=(2, -1)),
        Element("Vertical.Separator.separator", [("", line(True))], border=(0, 1, 0, 1),
                sticky="ns", size=(-1, 2)),
    ]


# --------------------------------------------------------------------------
# ListView / TreeView rows (Treeview), tree chevrons and headings
# --------------------------------------------------------------------------

def row_height(s):
    return round(METRICS["ListViewItemHeight"] * s)


def tree_indent(s):
    return round(METRICS["TreeViewIndent"] * s)


SELECTED_ROW = "SubtleFillColorSecondary"


def _list(s, st):
    H = row_height(s)
    R = METRICS["ControlCornerRadius"] * s
    BL = math.ceil(8 * s) + 1
    BR = math.ceil(8 * s) + 1
    W = BL + BR + TILE
    top = (H - 1) // 2

    def row(bg_name, pill):
        def paint(c):
            img = Svg(W, H, c.under)
            if bg_name:
                img.draw(rrect(4 * s, 2 * s, W - 4 * s, H - 2 * s, R), c.on(bg_name))
            if pill:
                ph = 16 * s
                img.draw(rrect(4 * s, H / 2 - ph / 2, 7 * s, H / 2 + ph / 2, 1.5 * s), c.on("AccentFillColorDefault"))
            return img
        return paint

    row_el = Element("Treeitem.row", [
        (("selected",), row(SELECTED_ROW, True)),
        ("", row(None, False)),
    ], border=(BL, top, BR, H - 1 - top), sticky="nsew", size=(BL + BR, -1))

    HH = st + 2
    HW = 2 + TILE

    def heading(fill_name):
        def paint(c):
            img = Svg(HW, HH, c.on(fill_name) if fill_name else c.under)
            return img.draw(rrect(0, HH - st, HW, HH, 0), c.on("DividerStrokeColorDefault"))
        return paint

    heading_el = Element("Treeheading.cell", [
        (("pressed",), heading("SubtleFillColorTertiary")),
        (("active",), heading("SubtleFillColorSecondary")),
        ("", heading(None)),
    ], border=(1, 1, 1, st), sticky="nsew", size=(2, -1))
    return [row_el, heading_el]


# --------------------------------------------------------------------------
# TabView (Notebook), Card and LabelFrame
# --------------------------------------------------------------------------

def _tabs_and_cards(s, st):
    R = METRICS["OverlayCornerRadius"] * s
    B = math.ceil(R) + st
    W = H = 2 * B + TILE

    def tab(kind):
        def paint(c):
            img = Svg(W, H, c.under)
            if kind == "selected":
                img.draw(rrect(0, 0, W, H, 0, (R, R, 0, 0)), c.on("CardStrokeColorDefault", c.surface))
                img.draw(rrect(st, st, W - st, H + R, 0, (R - st, R - st, 0, 0)), c.surface)
            elif kind == "hover":
                img.draw(rrect(0, 0, W, H, 0, (R, R, 0, 0)), c.on("SubtleFillColorSecondary"))
            return img
        return paint

    tab_el = Element("Notebook.tab", [
        (("selected",), tab("selected")),
        (("active",), tab("hover")),
        ("", tab("rest")),
    ], border=B, sticky="nsew", size=(2 * B, 2 * B))

    def panel(radii):
        def paint(c):
            img = Svg(W, H, c.under)
            img.draw(rrect(0, 0, W, H, 0, radii), c.on("CardStrokeColorDefault", c.surface))
            inner = tuple(max(r - st, 0) for r in radii)
            img.draw(rrect(st, st, W - st, H - st, 0, inner), c.surface)
            return img
        return paint

    # Padding keeps pages (opaque, square) off the rounded border. Cards and
    # LabelFrames get theirs from the widget's -padding (see Theme).
    card = [("", panel((R, R, R, R)))]
    return [
        tab_el,
        Element("Notebook.client", [("", panel((0, R, R, R)))], border=B, sticky="nsew",
                padding=B, size=(2 * B, 2 * B)),
        Element("Card.border", card, border=B, sticky="nsew", size=(2 * B, 2 * B)),
        Element("Labelframe.border", card, border=B, sticky="nsew", size=(2 * B, 2 * B)),
    ]
