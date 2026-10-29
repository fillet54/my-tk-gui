"""A tiny SVG builder for element images, rendered by Tk 9's built-in SVG
support (``image create photo -format svg``).

Coordinates are device pixels. ``Svg(w, h, under)`` starts with an opaque
rectangle in ``under`` (the color the image will sit on), so every pixel is
fully opaque. That matters for speed: Tk draws a photo that has partially
transparent pixels by reading the window back from the X server for every
tile it draws, which stalls a large stretched element for seconds. Opaque
photos are a plain pixmap copy.
"""


def _n(v):
    return ("%.3f" % v).rstrip("0").rstrip(".") or "0"


def _paint(color, attr="fill"):
    r, g, b, a = color
    out = '%s="#%02x%02x%02x"' % (attr, round(r * 255), round(g * 255), round(b * 255))
    if a < 1:
        out += ' %s-opacity="%s"' % (attr, _n(a))
    return out


class Svg:
    def __init__(self, width, height, under=None):
        self.width, self.height = width, height
        self.parts = []
        if under is not None:
            self.parts.append('<rect width="%d" height="%d" %s/>' % (width, height, _paint(under)))

    def draw(self, shape, color):
        self.parts.append(shape(color))
        return self

    def data(self):
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">%s</svg>'
                % (self.width, self.height, self.width, self.height, "".join(self.parts)))


# -- shapes: each returns a function color -> SVG element ------------------------

def rrect(x0, y0, x1, y1, r=0, radii=None):
    """Rounded rectangle; ``radii`` = (top-left, top-right, bottom-right, bottom-left)."""
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return lambda color: ""
    limit = min(w, h) / 2
    tl, tr, br, bl = (min(max(v, 0), limit) for v in (radii or (r, r, r, r)))
    if not any((tl, tr, br, bl)):
        return lambda color: '<rect x="%s" y="%s" width="%s" height="%s" %s/>' % (
            _n(x0), _n(y0), _n(w), _n(h), _paint(color))

    def arc(rad, x, y):
        return "A%s %s 0 0 1 %s %s" % (_n(rad), _n(rad), _n(x), _n(y)) if rad else "L%s %s" % (_n(x), _n(y))

    d = ("M%s %s H%s %s V%s %s H%s %s V%s %s Z" % (
        _n(x0 + tl), _n(y0), _n(x1 - tr), arc(tr, x1, y0 + tr), _n(y1 - br), arc(br, x1 - br, y1),
        _n(x0 + bl), arc(bl, x0, y1 - bl), _n(y0 + tl), arc(tl, x0 + tl, y0)))
    return lambda color: '<path d="%s" %s/>' % (d, _paint(color))


def circle(cx, cy, r):
    return lambda color: '<circle cx="%s" cy="%s" r="%s" %s/>' % (_n(cx), _n(cy), _n(r), _paint(color))


def polyline(points, width):
    pts = " ".join("%s,%s" % (_n(x), _n(y)) for x, y in points)
    return lambda color: ('<polyline points="%s" fill="none" stroke-width="%s" stroke-linecap="round" '
                          'stroke-linejoin="round" %s/>' % (pts, _n(width), _paint(color, "stroke")))


def polygon(points):
    pts = " ".join("%s,%s" % (_n(x), _n(y)) for x, y in points)
    return lambda color: '<polygon points="%s" %s/>' % (pts, _paint(color))
