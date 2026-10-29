"""WinUI 3 design tokens: colors, accent palette, sizes and type ramp.

Names and values follow WinUI's theme resources (Common_themeresources_any.xaml)
so they can be checked against the source. Colors are "#AARRGGBB" like XAML.
"""

import colorsys
import os

# --------------------------------------------------------------------------
# Theme colors (accent-independent)
# --------------------------------------------------------------------------

LIGHT = {
    "TextFillColorPrimary": "#E4000000",
    "TextFillColorSecondary": "#9E000000",
    "TextFillColorTertiary": "#72000000",
    "TextFillColorDisabled": "#5C000000",
    "TextOnAccentFillColorPrimary": "#FFFFFFFF",
    "TextOnAccentFillColorSecondary": "#B3FFFFFF",
    "TextOnAccentFillColorDisabled": "#FFFFFFFF",

    "ControlFillColorDefault": "#B3FFFFFF",
    "ControlFillColorSecondary": "#80F9F9F9",
    "ControlFillColorTertiary": "#4DF9F9F9",
    "ControlFillColorDisabled": "#4DF9F9F9",
    "ControlFillColorInputActive": "#FFFFFFFF",
    "ControlStrongFillColorDefault": "#72000000",
    "ControlStrongFillColorDisabled": "#51000000",
    "ControlSolidFillColorDefault": "#FFFFFFFF",
    "SubtleFillColorSecondary": "#09000000",
    "SubtleFillColorTertiary": "#06000000",
    "ControlAltFillColorSecondary": "#06000000",
    "ControlAltFillColorTertiary": "#0F000000",
    "ControlAltFillColorQuarternary": "#18000000",
    "ControlAltFillColorDisabled": "#00FFFFFF",

    "ControlStrokeColorDefault": "#0F000000",
    "ControlStrokeColorSecondary": "#29000000",
    "ControlStrokeColorOnAccentDefault": "#14FFFFFF",
    "ControlStrokeColorOnAccentSecondary": "#66000000",
    "ControlStrongStrokeColorDefault": "#72000000",
    "ControlStrongStrokeColorDisabled": "#37000000",
    "CardStrokeColorDefault": "#0F000000",
    "DividerStrokeColorDefault": "#0F000000",
    "FocusStrokeColorOuter": "#E4000000",
    "FocusStrokeColorInner": "#B3FFFFFF",

    "SolidBackgroundFillColorBase": "#FFF3F3F3",
    "CardBackgroundFillColorDefault": "#B3FFFFFF",
    "AcrylicBackgroundFillColorDefault": "#FFFCFCFC",
    "AccentFillColorDisabled": "#37000000",
    "SystemFillColorCritical": "#FFC42B1C",
}

DARK = {
    "TextFillColorPrimary": "#FFFFFFFF",
    "TextFillColorSecondary": "#C5FFFFFF",
    "TextFillColorTertiary": "#87FFFFFF",
    "TextFillColorDisabled": "#5DFFFFFF",
    "TextOnAccentFillColorPrimary": "#FF000000",
    "TextOnAccentFillColorSecondary": "#80000000",
    "TextOnAccentFillColorDisabled": "#87FFFFFF",

    "ControlFillColorDefault": "#0FFFFFFF",
    "ControlFillColorSecondary": "#15FFFFFF",
    "ControlFillColorTertiary": "#08FFFFFF",
    "ControlFillColorDisabled": "#0BFFFFFF",
    "ControlFillColorInputActive": "#B31E1E1E",
    "ControlStrongFillColorDefault": "#8BFFFFFF",
    "ControlStrongFillColorDisabled": "#3FFFFFFF",
    "ControlSolidFillColorDefault": "#FF454545",
    "SubtleFillColorSecondary": "#0FFFFFFF",
    "SubtleFillColorTertiary": "#0AFFFFFF",
    "ControlAltFillColorSecondary": "#19000000",
    "ControlAltFillColorTertiary": "#0BFFFFFF",
    "ControlAltFillColorQuarternary": "#12FFFFFF",
    "ControlAltFillColorDisabled": "#00FFFFFF",

    "ControlStrokeColorDefault": "#12FFFFFF",
    "ControlStrokeColorSecondary": "#18FFFFFF",
    "ControlStrokeColorOnAccentDefault": "#14FFFFFF",
    "ControlStrokeColorOnAccentSecondary": "#23000000",
    "ControlStrongStrokeColorDefault": "#8BFFFFFF",
    "ControlStrongStrokeColorDisabled": "#28FFFFFF",
    "CardStrokeColorDefault": "#19000000",
    "DividerStrokeColorDefault": "#15FFFFFF",
    "FocusStrokeColorOuter": "#FFFFFFFF",
    "FocusStrokeColorInner": "#B3000000",

    "SolidBackgroundFillColorBase": "#FF202020",
    "CardBackgroundFillColorDefault": "#0DFFFFFF",
    "AcrylicBackgroundFillColorDefault": "#FF2C2C2C",
    "AccentFillColorDisabled": "#28FFFFFF",
    "SystemFillColorCritical": "#FFFF99A4",
}

# --------------------------------------------------------------------------
# Accent palette
# --------------------------------------------------------------------------

DEFAULT_ACCENT = "#0078D4"

# Windows' own palette for its default blue (the AccentPalette registry value).
_DEFAULT_PALETTE = {
    "Light3": "#99EBFF", "Light2": "#4CC2FF", "Light1": "#0091F8",
    "Accent": "#0078D4",
    "Dark1": "#0067C0", "Dark2": "#003E92", "Dark3": "#001A68",
}

# How far each shade moves toward white (Light) or black (Dark), measured
# from Windows' default palette and applied to any accent.
_LIGHT_STEPS = {"Light1": 0.12, "Light2": 0.40, "Light3": 0.66}
_DARK_STEPS = {"Dark1": 0.10, "Dark2": 0.31, "Dark3": 0.51}

# The colors offered in Windows' Settings > Personalization > Colors.
WINDOWS_ACCENTS = [
    "#FFB900", "#FF8C00", "#F7630C", "#CA5010", "#DA3B01", "#EF6950",
    "#D13438", "#FF4343", "#E74856", "#E81123", "#EA005E", "#C30052",
    "#E3008C", "#BF0077", "#C239B3", "#9A0089", "#0078D4", "#0063B1",
    "#8E8CD8", "#6B69D6", "#8764B8", "#744DA9", "#B146C2", "#881798",
    "#0099BC", "#2D7D9A", "#00B7C3", "#038387", "#00B294", "#018574",
    "#00CC6A", "#10893E", "#7A7574", "#5D5A58", "#68768A", "#515C6B",
    "#567C73", "#486860", "#498205", "#107C10", "#767676", "#4C4A48",
    "#69797E", "#4A5459", "#647C64", "#525E54", "#847545", "#7E735F",
]


def accent_palette(accent):
    """Light1-3 / Dark1-3 shades for an accent color, like Windows derives them."""
    accent = normalize_hex(accent)
    if accent == DEFAULT_ACCENT:
        return dict(_DEFAULT_PALETTE)
    r, g, b = (int(accent[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    palette = {"Accent": accent}
    for name, step in _LIGHT_STEPS.items():
        palette[name] = _hls_hex(h, l + (1 - l) * step, s)
    for name, step in _DARK_STEPS.items():
        palette[name] = _hls_hex(h, l * (1 - step), s)
    return palette


def system_accent():
    """The Windows accent palette from the registry, or None elsewhere."""
    if os.name != "nt":
        return None
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent")
        data, _ = winreg.QueryValueEx(key, "AccentPalette")
    except OSError:
        return None
    return palette_from_registry(data)


def palette_from_registry(data):
    """Decode the 32-byte AccentPalette value (8 RGBA colors, light to dark)."""
    names = ["Light3", "Light2", "Light1", "Accent", "Dark1", "Dark2", "Dark3"]
    return {name: "#%02X%02X%02X" % tuple(data[i * 4:i * 4 + 3]) for i, name in enumerate(names)}


def accent_tokens(palette, dark):
    """The accent-derived WinUI brushes for one theme."""
    base = palette["Light2"] if dark else palette["Dark1"]
    return {
        "AccentFillColorDefault": "#FF" + base[1:],
        "AccentFillColorSecondary": "#E6" + base[1:],
        "AccentFillColorTertiary": "#CC" + base[1:],
        "AccentTextFillColorPrimary": "#FF" + (palette["Light3"] if dark else palette["Dark2"])[1:],
        "AccentFillColorSelectedTextBackground": "#FF" + palette["Accent"][1:],
    }


def normalize_hex(value):
    value = value.strip().upper()
    if not value.startswith("#"):
        value = "#" + value
    if len(value) == 4:
        value = "#" + "".join(c * 2 for c in value[1:])
    if len(value) != 7 or any(c not in "0123456789ABCDEF" for c in value[1:]):
        raise ValueError("not a #RRGGBB color: %r" % value)
    return value


def _hls_hex(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), s)
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


# --------------------------------------------------------------------------
# Color math
# --------------------------------------------------------------------------

def parse(color):
    """'#AARRGGBB' or '#RRGGBB' -> (r, g, b, a) floats."""
    c = color.lstrip("#")
    if len(c) == 6:
        c = "FF" + c
    a, r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4, 6))
    return (r, g, b, a)


def over(top, bottom):
    """Composite ``top`` over an opaque ``bottom``; returns an opaque color."""
    r, g, b, a = top
    br, bg, bb, _ = bottom
    return (r * a + br * (1 - a), g * a + bg * (1 - a), b * a + bb * (1 - a), 1.0)


def to_hex(color):
    r, g, b = color[:3]
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


# --------------------------------------------------------------------------
# Sizes (effective pixels) and type ramp
# --------------------------------------------------------------------------

METRICS = {
    "ControlCornerRadius": 4,
    "OverlayCornerRadius": 8,
    "ButtonPadding": (11, 5, 11, 6),
    "TextControlPadding": (10, 5, 6, 6),
    "ComboBoxPadding": (12, 5, 0, 7),
    "ComboBoxGlyphColumn": 38,
    "CheckBoxSize": 20,
    "CheckBoxGap": 8,
    "ToggleSwitchTrack": (40, 20),
    "ToggleSwitchGap": 12,
    "SliderThumb": 20,
    "SliderInnerThumb": (12, 14, 10),        # rest, hover, pressed
    "SliderTrack": 4,
    "ProgressBarTrack": 1,
    "ProgressBarIndicator": 3,
    "ProgressBarIndeterminate": 120,
    "ScrollBarSize": 12,
    "ListViewItemHeight": 40,
    "TabHeight": 32,
    "CardPadding": 16,
    "NumberBoxSpinButton": 30,
    "DropDownGap": 8,
    "TreeViewIndent": 24,
    "LabelFrameHeaderGap": 8,
}

# (size px, semibold)
TYPE_RAMP = {
    "Caption": (12, False),
    "Body": (14, False),
    "BodyStrong": (14, True),
    "BodyLarge": (18, False),
    "Subtitle": (20, True),
    "Title": (28, True),
    "TitleLarge": (40, True),
    "Display": (68, True),
}
