"""Draw original resource-browser icons with project-local Pillow."""

import math
from pathlib import Path

from PIL import Image, ImageDraw


ASSETS = Path(__file__).resolve().parents[1] / "assets"
ASSETS.mkdir(exist_ok=True)
SIZE = 64
INK = (212, 216, 220, 255)


def icon(name, draw):
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw(ImageDraw.Draw(image))
    image.save(ASSETS / (name + ".png"), optimize=True)


def search(d):
    d.ellipse((10, 9, 43, 42), outline=INK, width=5)
    d.line((40, 39, 54, 53), fill=INK, width=5)


def confirm(d):
    d.line((11, 32, 25, 45, 53, 17), fill=INK, width=6, joint="curve")


def sidebar_left(d):
    d.rounded_rectangle((8, 9, 56, 55), radius=5, outline=INK, width=4)
    d.rectangle((11, 12, 22, 52), fill=INK)
    d.line((25, 11, 25, 53), fill=INK, width=3)


def sidebar_right(d):
    d.rounded_rectangle((8, 9, 56, 55), radius=5, outline=INK, width=4)
    d.rectangle((42, 12, 53, 52), fill=INK)
    d.line((39, 11, 39, 53), fill=INK, width=3)


def import_file(d):
    d.rounded_rectangle((10, 8, 54, 56), radius=4, outline=INK, width=4)
    d.line((20, 43, 44, 43), fill=INK, width=4)
    d.line((32, 15, 32, 36), fill=INK, width=5)
    d.line((23, 28, 32, 37, 41, 28), fill=INK, width=5, joint="curve")


def folder_add(d):
    d.line((8, 23, 8, 50, 56, 50, 56, 22, 31, 22, 27, 15, 8, 15, 8, 23),
           fill=INK, width=4, joint="curve")
    d.line((38, 29, 38, 43), fill=INK, width=4)
    d.line((31, 36, 45, 36), fill=INK, width=4)


def favorite_add(d):
    points = []
    for i in range(10):
        angle = math.radians(-90 + i*36)
        radius = 22 if i % 2 == 0 else 10
        points.append((27 + radius*math.cos(angle), 32 + radius*math.sin(angle)))
    d.line(points + [points[0]], fill=INK, width=4, joint="curve")
    d.line((51, 37, 51, 54), fill=INK, width=4)
    d.line((43, 45, 59, 45), fill=INK, width=4)


def more(d):
    for x in (16, 32, 48):
        d.ellipse((x-4, 28, x+4, 36), fill=INK)


def benzene(d, space_fill):
    cx, cy = 64, 64
    carbon = []
    hydrogen = []
    for i in range(6):
        angle = math.radians(30 + 60*i)
        carbon.append((cx + 34*math.cos(angle), cy + 34*math.sin(angle)))
        hydrogen.append((cx + 53*math.cos(angle), cy + 53*math.sin(angle)))
    if not space_fill:
        for i in range(6):
            p, q = carbon[i], carbon[(i+1)%6]
            d.line((p, q), fill=(125, 136, 146, 255), width=10)
            d.line((p, hydrogen[i]), fill=(165, 174, 184, 255), width=7)
        for x, y in carbon:
            d.ellipse((x-10, y-10, x+10, y+10), fill=(90, 100, 112, 255),
                      outline=(46, 56, 65, 255), width=2)
        for x, y in hydrogen:
            d.ellipse((x-6, y-6, x+6, y+6), fill=(247, 249, 251, 255),
                      outline=(160, 169, 178, 255), width=2)
    else:
        for x, y in carbon:
            d.ellipse((x-21, y-21, x+21, y+21), fill=(105, 115, 127, 255),
                      outline=(55, 65, 75, 255), width=2)
        for x, y in hydrogen:
            d.ellipse((x-10, y-10, x+10, y+10), fill=(247, 249, 251, 255),
                      outline=(163, 173, 183, 255), width=2)


def main():
    for name, draw in (("search", search), ("confirm", confirm),
                       ("sidebar_left", sidebar_left), ("sidebar_right", sidebar_right),
                       ("import", import_file), ("folder_add", folder_add),
                       ("favorite_add", favorite_add), ("more", more)):
        icon(name, draw)
    for name, space_fill in (("benzene_ball_stick", False),
                             ("benzene_space_fill", True)):
        image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        benzene(ImageDraw.Draw(image), space_fill)
        image.save(ASSETS / (name + ".png"), optimize=True)


if __name__ == "__main__":
    main()
