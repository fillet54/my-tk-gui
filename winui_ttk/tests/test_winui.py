import time
import tkinter as tk
import unittest
from tkinter import ttk

from winui_ttk import Theme, tokens
from winui_ttk.svg import Svg, rrect

try:
    _r = tk.Tk()
    HAVE_TK9 = bool(_r.tk.call("package", "vsatisfies", _r.tk.call("info", "patchlevel"), "9-"))
    _r.destroy()
except tk.TclError:
    HAVE_TK9 = False


class TestSvg(unittest.TestCase):
    def test_rrect_path_and_opacity(self):
        img = Svg(10, 8, (1, 1, 1, 1))
        img.draw(rrect(0, 0, 10, 8, 2), (1, 0, 0, 0.5))
        data = img.data()
        self.assertIn('<rect width="10" height="8" fill="#ffffff"/>', data)
        self.assertIn('fill="#ff0000" fill-opacity="0.5"', data)
        self.assertIn("A2 2 0 0 1", data)

    def test_degenerate_shapes_are_empty(self):
        self.assertEqual(rrect(5, 0, 5, 4, 1)((0, 0, 0, 1)), "")


class TestTokens(unittest.TestCase):
    def test_registry_palette_matches_default(self):
        data = bytes.fromhex("99ebff00 4cc2ff00 0091f800 0078d400 0067c000 003e9200 001a6800 f7630c00".replace(" ", ""))
        self.assertEqual(tokens.palette_from_registry(data), tokens.accent_palette("#0078D4"))

    def test_derived_palette_is_ordered(self):
        lum = lambda h: sum(int(h[i:i + 2], 16) for i in (1, 3, 5))
        p = tokens.accent_palette("#E3008C")
        order = [p[k] for k in ("Light3", "Light2", "Light1", "Accent", "Dark1", "Dark2", "Dark3")]
        self.assertEqual(order, sorted(order, key=lum, reverse=True))

    def test_accent_fill_per_mode(self):
        p = tokens.accent_palette("#0078D4")
        self.assertEqual(tokens.accent_tokens(p, dark=False)["AccentFillColorDefault"], "#FF0067C0")
        self.assertEqual(tokens.accent_tokens(p, dark=True)["AccentFillColorDefault"], "#FF4CC2FF")

    def test_normalize(self):
        self.assertEqual(tokens.normalize_hex("e3008c"), "#E3008C")
        self.assertEqual(tokens.normalize_hex("#abc"), "#AABBCC")
        with self.assertRaises(ValueError):
            tokens.normalize_hex("blue")


@unittest.skipUnless(HAVE_TK9, "needs a display and Tk 9")
class TestTheme(unittest.TestCase):
    def make(self, scale, **kw):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        return root, Theme(root, scale=scale, accent="#0078D4", **kw)

    def test_builds_at_common_windows_scales(self):
        for scale in (1.0, 1.25, 1.5, 1.75, 2.0):
            with self.subTest(scale=scale):
                root, theme = self.make(scale)
                self.assertEqual(root.tk.call("ttk::style", "theme", "use"), theme.name)
                box = root.tk.call("image", "width", "winui_Checkbutton_indicator_0")
                self.assertEqual(int(box), round(28 * scale))     # 20px box + 8px gap

    def test_control_heights_match_winui(self):
        # WinUI: Button, TextBox and ComboBox are 32epx tall. Allow 1px for the
        # fallback font's line height (Segoe UI is 19px at 14px, others vary).
        for scale in (1.0, 1.5, 2.0):
            root, theme = self.make(scale)
            frame = ttk.Frame(root)
            widgets = [ttk.Button(frame, text="Hi"), ttk.Entry(frame),
                       ttk.Combobox(frame, state="readonly"), ttk.Checkbutton(frame, text="x")]
            for w in widgets:
                w.pack()
            root.update_idletasks()
            for w in widgets:
                with self.subTest(scale=scale, widget=w.winfo_class()):
                    self.assertAlmostEqual(w.winfo_reqheight(), 32 * scale, delta=1.5 * scale)

    def test_accent_and_mode_repaint_in_place(self):
        root, theme = self.make(1.0)
        before = root.tk.call("winui_AccentButton_border_6", "data", "-format", "png")
        theme.set_accent("#E3008C")
        after = root.tk.call("winui_AccentButton_border_6", "data", "-format", "png")
        self.assertNotEqual(before, after)
        self.assertEqual(theme.accent, "#E3008C")

        theme.set_mode("dark")
        self.assertEqual(root.cget("background"), "#202020")
        self.assertEqual(ttk.Style(root).lookup("TLabel", "foreground"), "#ffffff")

    def test_widgets_in_cards_move_to_surface(self):
        root, theme = self.make(1.0)
        card = ttk.Frame(root, class_="Card")
        check = ttk.Checkbutton(card, style="Switch.TCheckbutton")
        outside = ttk.Button(root)

        class Event:
            pass

        for w in (check, outside):
            e = Event()
            e.widget = w
            theme._on_map(e)
        self.assertEqual(check.cget("style"), "Surface.Switch.TCheckbutton")
        self.assertEqual(str(outside.cget("style")), "")
        style = ttk.Style(root)
        self.assertEqual(style.lookup("Surface.Switch.TCheckbutton", "background"), theme.color(
            "CardBackgroundFillColorDefault"))

    def test_render_is_fast_enough(self):
        root, theme = self.make(2.0)
        self.assertLess(theme.last_render_ms, 1000)

    def test_every_image_is_opaque(self):
        # A partially transparent photo makes Tk read the window back from the
        # X server for every tile it draws: large widgets then take seconds.
        root, theme = self.make(1.5)
        for name, photo in theme.images.items():
            w, h = photo.width(), photo.height()
            for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (0, h // 2)):
                alpha = int(root.tk.call(photo, "get", x, y, "-withalpha")[3])
                self.assertEqual(alpha, 255, "%s pixel %d,%d" % (name, x, y))

    def test_large_window_draws_quickly(self):
        root, theme = self.make(2.0)
        root.deiconify()
        root.geometry("1600x1100")
        tabs = ttk.Notebook(root)
        tabs.pack(fill="both", expand=True)
        page = ttk.Frame(tabs)
        tabs.add(page, text="Page")
        for i in range(4):
            card = ttk.Frame(page, class_="Card")
            card.pack(fill="both", expand=True, padx=8, pady=8)
            ttk.Button(card, text="Button %d" % i).pack(fill="x")
            ttk.Entry(card).pack(fill="x")
        root.update()
        start = time.perf_counter()
        for _ in range(3):
            tabs.event_generate("<Expose>")
            root.update()
        self.assertLess(time.perf_counter() - start, 1.0)

    def test_card_padding_and_surface_layouts(self):
        root, theme = self.make(1.0)
        root.deiconify()
        card = ttk.Frame(root, class_="Card")
        card.pack(padx=20, pady=20)
        button = ttk.Button(card, text="Hi", style="Accent.TButton")
        button.pack()
        root.update()
        self.assertEqual((button.winfo_x(), button.winfo_y()), (16, 16))
        self.assertEqual(button.cget("style"), "Surface.Accent.TButton")
        layout = ttk.Style(root).layout("Surface.Accent.TButton")
        self.assertEqual(layout[0][0], "Surface.AccentButton.border")


if __name__ == "__main__":
    unittest.main()
