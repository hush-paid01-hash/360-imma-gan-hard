"""Generates the Hush Emulator icon: python make_icon.py (needs Pillow)."""
from PIL import Image, ImageDraw, ImageFilter, ImageChops

S = 2048  # supersampled canvas, downscaled to 1024
LIME = (182, 255, 60)


def vgradient(top, bottom):
    img = Image.new("RGB", (S, S))
    d = ImageDraw.Draw(img)
    for y in range(S):
        t = y / (S - 1)
        d.line([(0, y), (S, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img


def build():
    base = vgradient((30, 36, 46), (7, 8, 11))

    # soft lime glow rising from the bottom
    glow = Image.new("L", (S, S), 0)
    ImageDraw.Draw(glow).ellipse([S * 0.1, S * 0.62, S * 0.9, S * 1.25], fill=45)
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.08))
    base.paste(Image.new("RGB", (S, S), LIME), mask=glow)

    # "H" mark: two stems + a crossbar that is a play-triangle notch
    mark = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(mark)
    stem_w, top, bot = S * 0.15, S * 0.24, S * 0.76
    lx, rx = S * 0.27, S * 0.58
    d.rounded_rectangle([lx, top, lx + stem_w, bot], radius=stem_w * 0.35, fill=255)
    d.rounded_rectangle([rx, top, rx + stem_w, bot], radius=stem_w * 0.35, fill=255)
    cy, bar_h = S * 0.5, S * 0.2
    d.rectangle([lx + stem_w * 0.5, cy - bar_h / 2, rx + stem_w * 0.5, cy + bar_h / 2], fill=255)
    # play triangle cut out of the crossbar
    tri = [(S * 0.455, cy - S * 0.065), (S * 0.455, cy + S * 0.065), (S * 0.552, cy)]
    d.polygon(tri, fill=0)

    # glow behind mark
    halo = mark.filter(ImageFilter.GaussianBlur(S * 0.03))
    base.paste(Image.new("RGB", (S, S), LIME), mask=halo.point(lambda v: int(v * 0.55)))

    # mark body with a vertical lime gradient
    grad = vgradient((226, 255, 150), (150, 235, 40))
    base.paste(grad, mask=mark)

    # soft top highlight on the mark
    sheen = Image.linear_gradient("L").rotate(180).resize((S, S))
    sheen = sheen.point(lambda v: int(v * 0.35))
    base.paste(Image.new("RGB", (S, S), (255, 255, 255)), mask=ImageChops.multiply(mark, sheen))

    return base.resize((1024, 1024), Image.LANCZOS)


if __name__ == "__main__":
    icon = build()
    icon.save("hush-icon-1024.png")
    icon.resize((180, 180), Image.LANCZOS).save("icon@2x.png")
    print("ok")
