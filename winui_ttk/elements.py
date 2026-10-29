"""Drawing for every ttk element the theme replaces.

Each element is an ``Element``: its nine-slice geometry (which depends only
on the scale) and an ordered list of (ttk state spec, paint function). A
paint function takes the resolved ``Colors`` and returns an ``Svg``, so
switching light/dark or the accent repaints the same images in place.

Every image is opaque: it is painted over ``c.under``, the color it will
sit on. The theme builds each element twice, once on the window background
and once on the card surface (``Surface.<element>``), and widgets inside
cards switch to the second set. Elements drawn on top of other elements
(slider thumb, combobox chevron, scrollbar thumb) bake in what is beneath them.

Stretchable images have a wide middle (``TILE``) because ttk fills a
stretched element by tiling the middle slice; a 1px middle on a large panel
means hundreds of thousands of draw calls.

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
        self.size = size              # requested (w, h); -1 = the image's own size
        self.states = states          # [(statespec tuple, paint fn)], "" = default
        self.border = border
        self.sticky = sticky
        self.padding = padding


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
        + _slider(s, st)
        + _progress(s, st)
        + _scrollbars(s, st)
        + _list(s, st)
        + _tabs_and_cards(s, st)
    )


# --------------------------------------------------------------------------
# Buttons: elevation border (darker bottom edge), state fills, focus ring
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

    button = Element("Button.border", [
        (("disabled",), standard("ControlFillColorDisabled", flat=True)),
        (("focus", "pressed"), standard("ControlFillColorTertiary", focus=True)),
        (("focus", "active"), standard("ControlFillColorSecondary", focus=True)),
        (("focus",), standard("ControlFillColorDefault", focus=True)),
        (("pressed",), standard("ControlFillColorTertiary", flat=True)),
        (("active",), standard("ControlFillColorSecondary")),
        ("", standard("ControlFillColorDefault")),
    ], border=B, size=(2 * B, 2 * B))

    accent_button = Element("AccentButton.border", [
        (("disabled",), accent("AccentFillColorDisabled", border=False)),
        (("focus", "pressed"), accent("AccentFillColorTertiary", focus=True)),
        (("focus", "active"), accent("AccentFillColorSecondary", focus=True)),
        (("focus",), accent("AccentFillColorDefault", focus=True)),
        (("pressed",), accent("AccentFillColorTertiary", border=False)),
        (("active",), accent("AccentFillColorSecondary")),
        ("", accent("AccentFillColorDefault")),
    ], border=B, size=(2 * B, 2 * B))
    return [button, accent_button]


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
_TEXTBOX_STATES = [
    (("disabled",), "ControlFillColorDisabled", "ControlStrokeColorDefault", False, True),
    (("invalid", "focus"), "ControlFillColorInputActive", "SystemFillColorCritical", True, False),
    (("invalid",), "ControlFillColorDefault", "SystemFillColorCritical", True, False),
    (("focus",), "ControlFillColorInputActive", "AccentFillColorDefault", True, False),
    (("hover",), "ControlFillColorSecondary", "ControlStrongStrokeColorDefault", False, False),
    ("", "ControlFillColorDefault", "ControlStrongStrokeColorDefault", False, False),
]


def _entry(s, st):
    R = METRICS["ControlCornerRadius"] * s
    underline = max(2, round(2 * s))
    B = math.ceil(R) + underline
    W = H = 2 * B + TILE
    return [Element("Entry.field", [
        (spec, _textbox_paint(W, H, R, st, underline, fill, bottom, thick=thick, flat=flat))
        for spec, fill, bottom, thick, flat in _TEXTBOX_STATES
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
    R = METRICS["ControlCornerRadius"] * s
    underline = max(2, round(2 * s))
    B = math.ceil(R) + underline
    W = H = 2 * B + TILE

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
        for spec, fill, bottom, thick, flat in _TEXTBOX_STATES if "invalid" not in spec
    ]
    # The field reserves its right stroke so the opaque chevron column never covers it.
    field = Element("Combobox.field", [(spec, paint) for spec, _, paint in FIELD],
                    border=B, padding=(0, 0, st, 0), size=(2 * B, 2 * B))

    AW = round(METRICS["ComboBoxGlyphColumn"] * s) - st
    AH = round(12 * s)
    cx, cy = AW - 20 * s + st, AH / 2

    # The chevron sits on the field, so each state is painted on that state's fill.
    def chevron(fill_name, color_name):
        def paint(c):
            fill = c.on(fill_name)
            img = Svg(AW, AH, fill)
            pts = [(cx - 4 * s, cy - 2 * s), (cx, cy + 2 * s), (cx + 4 * s, cy - 2 * s)]
            img.draw(polyline(pts, 1.0 * s), c.on(color_name, fill))
            return img
        return paint

    arrow = Element("Combobox.downarrow", [
        (spec, chevron(fill, "TextFillColorDisabled" if "disabled" in spec else "TextFillColorSecondary"))
        for spec, fill, _ in FIELD
    ], sticky="")
    return [field, arrow]


# --------------------------------------------------------------------------
# Slider
# --------------------------------------------------------------------------

def _slider(s, st):
    T = METRICS["SliderThumb"] * s
    H = round(T)
    cy = H / 2
    track = METRICS["SliderTrack"] * s
    bx = math.ceil(track / 2) + 1
    W = 2 * bx + TILE

    def band(img, x0, x1, color):
        return img.draw(rrect(x0, cy - track / 2, x1, cy + track / 2, track / 2), color)

    def trough(color_name):
        def paint(c):
            return band(Svg(W, H, c.under), 0, W, c.on(color_name))
        return paint

    trough_el = Element("Horizontal.Scale.trough", [
        (("disabled",), trough("ControlStrongFillColorDisabled")),
        ("", trough("ControlStrongFillColorDefault")),
    ], border=(bx, 0, bx, 0), sticky="ew", size=(2 * bx, -1))

    rest, hover, pressed = METRICS["SliderInnerThumb"]

    # The thumb always sits on the track, so the track runs through its image.
    def thumb(inner, inner_color, track_color):
        def paint(c):
            img = band(Svg(H, H, c.under), -track, H + track, c.on(track_color))
            solid = c.on("ControlSolidFillColorDefault")
            img.draw(circle(cy, cy, T / 2), c.on("ControlStrokeColorSecondary", solid))
            img.draw(circle(cy, cy - st / 2, T / 2 - st / 2), c.on("ControlStrokeColorDefault", solid))
            img.draw(circle(cy, cy, T / 2 - st), solid)
            img.draw(circle(cy, cy, inner * s / 2), c.on(inner_color, solid))
            return img
        return paint

    slider_el = Element("Horizontal.Scale.slider", [
        (("disabled",), thumb(rest, "AccentFillColorDisabled", "ControlStrongFillColorDisabled")),
        (("pressed",), thumb(pressed, "AccentFillColorTertiary", "ControlStrongFillColorDefault")),
        (("hover",), thumb(hover, "AccentFillColorSecondary", "ControlStrongFillColorDefault")),
        ("", thumb(rest, "AccentFillColorDefault", "ControlStrongFillColorDefault")),
    ], sticky="")
    return [trough_el, slider_el]


# --------------------------------------------------------------------------
# ProgressBar: 1px track, 3px rounded accent indicator
# --------------------------------------------------------------------------

def _progress(s, st):
    H = max(3, round(METRICS["ProgressBarIndicator"] * s))
    cy = H / 2

    def track(c, w):
        img = Svg(w, H, c.under)
        return img.draw(rrect(0, cy - st / 2, w, cy + st / 2, 0), c.on("ControlStrongStrokeColorDefault"))

    b = math.ceil(H / 2)
    PW = 2 * b + TILE

    # The bar sits on the track line, so it is painted over it.
    def bar(color_name):
        def paint(c):
            return track(c, PW).draw(rrect(0, 0, PW, H, H / 2), c.on(color_name))
        return paint

    return [
        Element("Horizontal.Progressbar.trough", [("", lambda c: track(c, 2 + TILE))],
                border=(1, 0, 1, 0), sticky="ew", size=(2, -1)),
        Element("Horizontal.Progressbar.pbar", [
            (("disabled",), bar("AccentFillColorDisabled")),
            ("", bar("AccentFillColorDefault")),
        # ttk sizes the moving bar of an indeterminate progressbar from this width.
        ], border=(b, 0, b, 0), sticky="nsew", size=(round(METRICS["ProgressBarIndeterminate"] * s), -1)),
    ]


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
# ListView rows (Treeview) and headings
# --------------------------------------------------------------------------

def row_height(s):
    return round(METRICS["ListViewItemHeight"] * s)


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
        (("selected",), row("SubtleFillColorSecondary", True)),
        ("", row(None, False)),
    ], border=(BL, top, BR, H - 1 - top), sticky="nsew", size=(BL + BR, -1))

    HH = st + 2

    def heading(c):
        img = Svg(2 + TILE, HH, c.under)
        return img.draw(rrect(0, HH - st, 2 + TILE, HH, 0), c.on("DividerStrokeColorDefault"))

    heading_el = Element("Treeheading.cell", [("", heading)], border=(1, 1, 1, st), sticky="nsew",
                         size=(2, -1))
    return [row_el, heading_el]


# --------------------------------------------------------------------------
# TabView (Notebook) and Card
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

    # Padding keeps pages and card content (opaque, square) off the rounded border.
    client_el = Element("Notebook.client", [("", panel((0, R, R, R)))], border=B, sticky="nsew",
                        padding=B, size=(2 * B, 2 * B))
    card_el = Element("Card.border", [("", panel((R, R, R, R)))], border=B, sticky="nsew",
                      padding=round(METRICS["CardPadding"] * s), size=(2 * B, 2 * B))
    return [tab_el, client_el, card_el]
