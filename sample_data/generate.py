"""生成示例评测数据：4 个 Query × 好/部分/差三档，共 12 张图 + samples.csv。"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

W, H = 900, 600
ROOT = Path(__file__).parent
IMAGES = ROOT / "images"
IMAGES.mkdir(exist_ok=True)
random.seed(42)


def gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (W, y)], fill=color)
    return img


def overlay(base: Image.Image, draw_fn) -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer))
    return Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")


def degrade(img: Image.Image, blur: float = 3.0, noise: float = 0.18, darkness: float = 0.8) -> Image.Image:
    img = img.filter(ImageFilter.GaussianBlur(blur))
    grain = Image.effect_noise((W, H), 60).convert("RGB")
    img = Image.blend(img, grain, noise)
    return ImageEnhance.Brightness(img).enhance(darkness)


def cat_scene(color=(205, 45, 45), sun=True, broken=False) -> Image.Image:
    img = gradient((255, 214, 170), (110, 85, 135))
    if sun:
        img = overlay(
            img,
            lambda d: (
                d.ellipse((40, 30, 220, 210), fill=(255, 236, 180, 90)),
                d.ellipse((75, 65, 185, 175), fill=(255, 248, 215, 255)),
            ),
        )
    img = overlay(
        img,
        lambda d: (
            d.rectangle((0, 420, 900, 600), fill=(96, 64, 48, 255)),
            d.rectangle((0, 420, 900, 440), fill=(142, 100, 74, 255)),
            d.line((0, 382, 900, 382), fill=(70, 45, 35, 255), width=10),
            d.line((118, 0, 118, 420), fill=(70, 45, 35, 255), width=8),
            d.line((782, 0, 782, 420), fill=(70, 45, 35, 255), width=8),
        ),
    )

    body = (360, 340, 500, 470) if broken else (380, 300, 560, 470)
    head = (520, 200, 620, 300) if broken else (400, 250, 520, 360)
    img = overlay(
        img,
        lambda d: (
            d.ellipse(body, fill=color + (255,)),
            d.ellipse(head, fill=color + (255,)),
            d.polygon([(head[0] + 10, head[1] + 20), (head[0] + 25, head[1] - 45), (head[0] + 55, head[1] + 15)], fill=color + (255,)),
            d.polygon([(head[0] + 65, head[1] + 15), (head[0] + 95, head[1] - 45), (head[0] + 110, head[1] + 25)], fill=color + (255,)),
            d.line((body[2] - 15, body[1] + 100, body[2] + 80, body[1] + 30), fill=color + (255,), width=16),
            d.arc((body[2] + 50, body[1] + 0, body[2] + 130, body[1] + 80), 300, 90, fill=color + (255,), width=14),
            d.ellipse((head[0] + 25, head[1] + 45, head[0] + 45, head[1] + 65), fill=(20, 20, 20, 255)),
            d.ellipse((head[0] + 75, head[1] + 45, head[0] + 95, head[1] + 65), fill=(20, 20, 20, 255)),
            d.polygon([(head[0] + 50, head[1] + 75), (head[0] + 62, head[1] + 75), (head[0] + 56, head[1] + 86)], fill=(250, 190, 190, 255)),
        ),
    )
    if not broken:
        img = overlay(
            img,
            lambda d: (
                d.ellipse((360, 470, 590, 510), fill=(40, 30, 30, 80)),
                d.line((456, 336, 456, 362), fill=(60, 20, 20, 255), width=3),
                d.line((400, 330, 340, 320), fill=(60, 20, 20, 180), width=2),
                d.line((400, 340, 340, 350), fill=(60, 20, 20, 180), width=2),
                d.line((520, 330, 580, 320), fill=(60, 20, 20, 180), width=2),
                d.line((520, 340, 580, 350), fill=(60, 20, 20, 180), width=2),
            ),
        )
    return img


def birds_scene(count: int = 2, color=(50, 90, 220), broken=False) -> Image.Image:
    img = gradient((190, 220, 245), (245, 248, 252))
    img = overlay(
        img,
        lambda d: (
            d.polygon([(0, 420), (250, 160), (520, 420)], fill=(205, 215, 228, 255)),
            d.polygon([(300, 430), (600, 120), (900, 430)], fill=(225, 233, 242, 255)),
            d.polygon([(250, 420), (600, 120), (660, 240), (420, 300)], fill=(245, 250, 255, 255)),
            d.line((0, 470, 900, 430), fill=(96, 64, 40, 255), width=16),
        ),
    )
    xs = [280, 540, 720][:count]
    for i, x in enumerate(xs):
        y = 350 - (i % 2) * 28
        img = overlay(
            img,
            lambda d, x=x, y=y: (
                d.ellipse((x, y, x + 110, y + 70), fill=color + (255,)),
                d.ellipse((x + 70, y - 15, x + 120, y + 25), fill=color + (255,)),
                d.polygon([(x + 20, y + 10), (x - 30, y - 30), (x + 40, y + 30)], fill=color + (255,)),
                d.polygon([(x + 115, y + 8), (x + 150, y + 2), (x + 118, y + 18)], fill=(240, 170, 40, 255)),
                d.ellipse((x + 88, y - 6, x + 96, y + 2), fill=(20, 20, 20, 255)),
            ),
        )
    if broken:
        img = overlay(img, lambda d: d.line((200, 100, 700, 200), fill=(90, 60, 40, 255), width=22))
    return img


def child_scene(coat=(240, 200, 40), umbrella=True, broken=False) -> Image.Image:
    img = gradient((120, 140, 160), (60, 70, 85))
    img = overlay(
        img,
        lambda d: [d.line((x, 0, x - 60, 600), fill=(200, 215, 235, 120), width=2) for x in range(0, 1000, 40)],
    )
    img = overlay(
        img,
        lambda d: (
            d.rectangle((0, 500, 900, 600), fill=(52, 58, 66, 255)),
            d.ellipse((250, 520, 450, 560), fill=(120, 140, 160, 120)),
            d.ellipse((520, 530, 700, 565), fill=(120, 140, 160, 100)),
        ),
    )
    cx = 520 if broken else 470
    img = overlay(
        img,
        lambda d: (
            d.ellipse((cx - 30, 280, cx + 30, 340), fill=(245, 205, 170, 255)),
            d.polygon([(cx - 45, 340), (cx + 45, 340), (cx + 65, 500), (cx - 65, 500)], fill=coat + (255,)),
            d.line((cx - 20, 500, cx - 25, 560), fill=(40, 40, 50, 255), width=12),
            d.line((cx + 20, 500, cx + 25, 560), fill=(40, 40, 50, 255), width=12),
            d.arc((cx - 22, 300, cx + 22, 340), 200, 340, fill=(60, 40, 30, 255), width=4),
        ),
    )
    if umbrella:
        img = overlay(
            img,
            lambda d: (
                d.pieslice((cx - 170, 80, cx + 170, 380), 180, 360, fill=(220, 40, 55, 255)),
                d.line((cx, 225, cx, 430), fill=(90, 60, 40, 255), width=6),
                d.arc((cx - 70, 400, cx, 455), 0, 180, fill=(90, 60, 40, 255), width=6),
            ),
        )
    return img


def city_scene(neon=True, rain=True, broken=False) -> Image.Image:
    img = gradient((10, 8, 30), (48, 12, 64))
    rng = random.Random(7)
    shapes = []
    x = 0
    while x < W:
        bw = rng.randint(70, 150)
        bh = rng.randint(180, 420)
        shapes.append((x, H - bh, x + bw, H))
        x += bw + rng.randint(10, 30)
    img = overlay(img, lambda d: [d.rectangle(s, fill=(22, 20, 44, 255)) for s in shapes])

    if neon:
        colors = [(255, 60, 180), (50, 240, 230), (255, 210, 60), (120, 120, 255)]
        for i, s in enumerate(shapes[:7]):
            c = colors[i % len(colors)]
            x0 = s[0] + 15
            img = overlay(
                img,
                lambda d, x0=x0, s=s, c=c: (
                    d.rectangle((x0 - 6, s[1] + 24, x0 + 24, s[1] + 156), fill=c + (50,)),
                    d.rectangle((x0, s[1] + 30, x0 + 18, s[1] + 150), fill=c + (220,)),
                    d.line((s[0] + 8, s[1] + 190, s[2] - 8, s[1] + 190), fill=c + (200,), width=4),
                    d.rectangle((s[0] + 10, s[1] + 210, s[2] - 10, s[1] + 240), fill=c + (70,)),
                ),
            )

    if rain:
        img = overlay(
            img,
            lambda d: [d.line((x, 0, x - 80, 600), fill=(150, 180, 255, 90), width=1) for x in range(0, 1100, 24)],
        )
    img = overlay(img, lambda d: d.rectangle((0, 520, 900, 600), fill=(30, 20, 60, 120)))
    if broken:
        img = overlay(
            img,
            lambda d: (
                d.rectangle((250, 120, 650, 300), fill=(255, 255, 255, 40)),
                d.ellipse((300, 160, 600, 460), fill=(255, 0, 0, 60)),
            ),
        )
    return img


SAMPLES = [
    ("cat-good", "一只红色的猫坐在窗台上，阳光从左侧照进来", cat_scene(), "good"),
    ("cat-partial", "一只红色的猫坐在窗台上，阳光从左侧照进来", cat_scene(color=(160, 90, 50), sun=False), "partial"),
    ("cat-bad", "一只红色的猫坐在窗台上，阳光从左侧照进来", degrade(cat_scene(broken=True)), "bad"),
    ("birds-good", "两只蓝色的鸟停在树枝上，背景是雪山", birds_scene(count=2), "good"),
    ("birds-partial", "两只蓝色的鸟停在树枝上，背景是雪山", birds_scene(count=1), "partial"),
    ("birds-bad", "两只蓝色的鸟停在树枝上，背景是雪山", degrade(birds_scene(count=3, color=(40, 180, 90), broken=True)), "bad"),
    ("child-good", "一个穿黄色雨衣的小孩在雨中撑红伞", child_scene(), "good"),
    ("child-partial", "一个穿黄色雨衣的小孩在雨中撑红伞", child_scene(coat=(50, 90, 220)), "partial"),
    ("child-bad", "一个穿黄色雨衣的小孩在雨中撑红伞", degrade(child_scene(umbrella=False, broken=True)), "bad"),
    ("city-good", "赛博朋克风格的城市夜景，霓虹灯，下雨", city_scene(), "good"),
    ("city-partial", "赛博朋克风格的城市夜景，霓虹灯，下雨", city_scene(rain=False), "partial"),
    ("city-bad", "赛博朋克风格的城市夜景，霓虹灯，下雨", degrade(city_scene(broken=True), blur=4.0, darkness=0.6), "bad"),
]

rows = []
for sample_id, query, image, variant in SAMPLES:
    path = IMAGES / f"{sample_id}.jpg"
    image.save(path, format="JPEG", quality=88, optimize=True)
    rows.append(
        {
            "external_id": sample_id,
            "query": query,
            "image": path.name,
            "model_name": "demo-v1",
            "tags": f"demo;{variant}",
            "metadata": json.dumps({"variant": variant}, ensure_ascii=False),
        }
    )

csv_path = ROOT / "samples.csv"
with csv_path.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=["external_id", "query", "image", "model_name", "tags", "metadata"])
    writer.writeheader()
    writer.writerows(rows)

print(f"wrote {len(rows)} images to {IMAGES}")
print(f"wrote {csv_path}")
