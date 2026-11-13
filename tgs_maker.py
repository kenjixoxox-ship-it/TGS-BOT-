"""Logo (SVG / PNG / JPG) -> animated Telegram sticker / custom emoji (.tgs).

A .tgs is a gzipped Lottie JSON. Telegram's rules: 512x512, max 3 s, <= 64 KB,
vector shapes only. So raster logos are vectorised first (vtracer), then
wrapped in a Lottie animation with a transform preset (pulse, spin, ...).
"""
import gzip
import json
import os
import tempfile

from PIL import Image
from lottie import NVector, objects
from lottie.exporters.tgs import export_tgs
from lottie.importers.svg import import_svg
from lottie.objects import easing

SIZE = 512
FPS = 60
FRAMES = 120          # 2 seconds at 60 fps (Telegram max is 3 s)
FILL = 0.80           # logo fills 80% of canvas -> clean margins
MAX_BYTES = 64 * 1024
C = SIZE / 2

# (filter_speckle, color_precision, layer_difference) - coarser each step
VECTOR_LEVELS = [(4, 6, 16), (8, 5, 24), (14, 4, 32), (24, 3, 48), (40, 2, 64)]

EASE = easing.Sigmoid()


# ---------------------------------------------------------------- keyframes
def _kf(prop, frames):
    for f, v in frames:
        prop.add_keyframe(f, v, EASE)


def _s(x, y=None):
    return NVector(x, x if y is None else y)


def _p(y, x=C):
    return NVector(x, y)


def pulse(n):
    _kf(n.transform.scale, [(0, _s(100)), (60, _s(112)), (120, _s(100))])


def heartbeat(n):
    _kf(n.transform.scale, [(0, _s(100)), (14, _s(120)), (28, _s(100)),
                            (42, _s(120)), (60, _s(100)), (120, _s(100))])


def spin(n):
    _kf(n.transform.rotation, [(0, 0), (80, 360), (120, 360)])


def flip(n):
    _kf(n.transform.scale, [(0, _s(100)), (40, _s(-100, 100)),
                            (80, _s(100)), (120, _s(100))])


def bounce(n):
    _kf(n.transform.position, [(0, _p(C)), (30, _p(C - 66)), (60, _p(C)),
                               (75, _p(C - 16)), (90, _p(C)), (120, _p(C))])
    _kf(n.transform.scale, [(0, _s(100)), (30, _s(96, 106)), (58, _s(100)),
                            (62, _s(114, 88)), (70, _s(100)), (120, _s(100))])


def shake(n):
    _kf(n.transform.rotation, [(0, 0), (10, -9), (25, 9), (40, -6),
                               (55, 6), (70, 0), (120, 0)])


def float_(n):
    _kf(n.transform.position, [(0, _p(C)), (60, _p(C - 16)), (120, _p(C))])
    _kf(n.transform.rotation, [(0, -3), (60, 3), (120, -3)])


def pop(n):
    _kf(n.transform.scale, [(0, _s(0)), (25, _s(118)), (40, _s(100)),
                            (100, _s(100)), (120, _s(0))])


def swing(n):
    _kf(n.transform.rotation, [(0, -12), (60, 12), (120, -12)])


ANIMATIONS = {
    "pulse": ("💗 Pulse", pulse),
    "heartbeat": ("❤️ Heartbeat", heartbeat),
    "spin": ("🌀 Spin", spin),
    "flip": ("🪙 Coin flip", flip),
    "bounce": ("⚽ Bounce", bounce),
    "shake": ("📳 Shake", shake),
    "float": ("🎈 Float", float_),
    "pop": ("✨ Pop in/out", pop),
    "swing": ("🔔 Swing", swing),
}


# ------------------------------------------------------------ vectorising
def raster_to_svg(src, dst, level):
    import vtracer

    speckle, precision, layer_diff = VECTOR_LEVELS[level]
    img = Image.open(src).convert("RGBA")
    img.thumbnail((SIZE, SIZE))
    w, h = img.size

    # JPG / flat PNG with a white background -> make the white transparent
    if img.getchannel("A").getextrema()[0] == 255:
        px = img.load()
        corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
        if all(min(c[:3]) > 235 for c in corners):
            img.putdata([(r, g, b, 0) if min(r, g, b) > 235 else (r, g, b, a)
                         for r, g, b, a in img.getdata()])

    tmp_png = dst + ".png"
    img.save(tmp_png)
    vtracer.convert_image_to_svg_py(
        tmp_png, dst,
        colormode="color", hierarchical="stacked", mode="spline",
        filter_speckle=speckle, color_precision=precision,
        layer_difference=layer_diff, corner_threshold=60,
        length_threshold=4.0, splice_threshold=45, path_precision=2,
    )
    os.remove(tmp_png)


# -------------------------------------------------------------- lottie
def build_animation(svg_path, anim_key):
    svg = import_svg(svg_path)
    w, h = svg.width, svg.height
    scale = SIZE * FILL / max(w, h) * 100

    an = objects.Animation(FRAMES)
    an.width = an.height = SIZE
    an.frame_rate = FPS
    an.in_point, an.out_point = 0, FRAMES

    null = objects.NullLayer()
    null.in_point, null.out_point = 0, FRAMES
    null.transform.anchor_point.value = NVector(C, C)
    null.transform.position.value = NVector(C, C)
    an.add_layer(null)
    ANIMATIONS[anim_key][1](null)

    # imported SVG layers: centred + fitted, parented to the animated null
    for layer in list(svg.layers):
        layer.in_point, layer.out_point = 0, FRAMES
        layer.transform.anchor_point.value = NVector(w / 2, h / 2)
        layer.transform.position.value = NVector(C, C)
        layer.transform.scale.value = NVector(scale, scale)
        layer.parent = null
        an.add_layer(layer)
    return an


def _write_tgs(an, out_path):
    try:
        with open(out_path, "wb") as f:
            export_tgs(an, f)
    except TypeError:  # API difference between lottie versions
        data = json.dumps(an.to_dict(), separators=(",", ":")).encode()
        with gzip.open(out_path, "wb", 9) as f:
            f.write(data)


def make_tgs(src_path, anim_key, out_path):
    """Returns out_path. Raises ValueError if it can't fit in 64 KB."""
    is_svg = src_path.lower().endswith(".svg")
    work = tempfile.mkdtemp(prefix="tgs_")

    levels = [None] if is_svg else range(len(VECTOR_LEVELS))
    for lvl in levels:
        if is_svg:
            svg_path = src_path
        else:
            svg_path = os.path.join(work, "trace.svg")
            raster_to_svg(src_path, svg_path, lvl)
        _write_tgs(build_animation(svg_path, anim_key), out_path)
        if os.path.getsize(out_path) <= MAX_BYTES:
            return out_path

    raise ValueError(
        "Logo is too detailed to fit Telegram's 64 KB limit. "
        "Send a simpler / flatter version (ideally an SVG)."
    )
