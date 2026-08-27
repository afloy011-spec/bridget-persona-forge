#!/usr/bin/env python3
"""Собрать графический ассет тату: PNG с альфой из флэш-эскиза.

  py -3 make_tattoo_asset.py [--out assets/<имя>.png] [--seed N]
                             [--from <файл эскиза>]

ПОЧЕМУ АССЕТ, А НЕ ПРОМПТ. Мелкая графика на запястье выходит у модели разной
кашей в каждом кадре, а в критериях оценки ТЗ тату стоит отдельной строкой
(«Attention to detail (tattoo, styling, mood)»). Значит рисуется один раз и
вклеивается композитом — тогда во всех кадрах она идентична по определению.

ЧТО РИСУЕМ. Тату у неё — Manolo Blahnik, и это датирующая деталь: ей было
около тридцати в нулевые. Поэтому не обобщённая шпилька, а узнаваемая
Hangisi — острый мыс, изогнутый каблук, квадратная пряжка-брошь на подъёме.

КАК ДЕЛАЕТСЯ АЛЬФА. Эскиз генерируется чёрным по белому, потом яркость
инвертируется в альфу, а цвет заливается ровным выцветшим сине-серым. Так
получается именно ЧЕРНИЛО, а не картинка тату: композит потом умножает её в
тени кожи, и белый фон эскиза не всплывает по краям.

Выцветание в синь обязательно: свежая чёрная линия на 51-летнем запястье
выглядит фальшиво — пятнадцатилетняя татуировка уходит в мягкий сине-серый.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import setup_console, work_dir, ROOT, cli_opt
import comfy_client as cc

FLASH_PROMPT = (
    "a minimal single-needle tattoo flash drawing of one elegant stiletto "
    "high-heeled pump in profile, pointed toe, slender curved heel, a small "
    "square jewelled buckle on the vamp, fine continuous black ink line work, "
    "no shading, no fill, no text, no lettering, centred on plain white paper, "
    "clean high contrast line art"
)

INK_RGB = (74, 88, 110)      # выцветший сине-серый — см. докстринг


def render_flash(seed=4242, size=1024):
    """Сгенерировать эскиз на сервере (эфемерно, как и всё остальное)."""
    from generate import build_graph
    if not cc.preflight():
        raise SystemExit("воркер не отвечает — эскиз не сгенерирован")
    out = work_dir("bridget", "tattoo")
    graph = build_graph(FLASH_PROMPT, seed, (size, size),
                        "persona-forge/tattoo_flash", "day")
    files = cc.run_graph(graph, out)
    if not files:
        raise RuntimeError("сервер не вернул эскиз")
    return files[0]


def to_ink(src, out, ink=INK_RGB, threshold=0.55, feather=0.6):
    """Эскиз чёрным по белому → RGBA-чернило с мягкими краями."""
    import numpy as np
    from PIL import Image, ImageFilter

    im = Image.open(src).convert("L")
    a = np.asarray(im).astype(np.float32) / 255.0

    # Нормировка по фактическому диапазону: у эскиза «белый» редко ровно 255,
    # и без неё порог срезает половину тонкой линии.
    lo, hi = float(a.min()), float(a.max())
    a = (a - lo) / max(hi - lo, 1e-6)

    alpha = np.clip((threshold - a) / max(threshold, 1e-6), 0.0, 1.0)
    # Гамма меньше единицы поднимает полутона линии: single-needle работа
    # состоит в основном из них, и без этого остаётся только жирный контур.
    alpha = alpha ** 0.75

    rgba = np.zeros(a.shape + (4,), dtype=np.uint8)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = ink
    rgba[..., 3] = (alpha * 255).astype(np.uint8)
    img = Image.fromarray(rgba, "RGBA")
    if feather:
        img = img.filter(ImageFilter.GaussianBlur(feather))

    # Обрезка по фактическим чернилам с полем: композит масштабирует ассет по
    # ширине запястья, и лишние поля вокруг рисунка ломают этот расчёт.
    bbox = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if bbox:
        pad = int(0.04 * max(bbox[2] - bbox[0], bbox[3] - bbox[1]))
        img = img.crop((max(bbox[0] - pad, 0), max(bbox[1] - pad, 0),
                        min(bbox[2] + pad, img.width),
                        min(bbox[3] + pad, img.height)))

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    img.save(out)
    print(f"ассет: {out}  {img.width}x{img.height}  "
          f"непрозрачных пикселей {int((np.asarray(img)[..., 3] > 8).sum())}")
    return out


def main():
    setup_console()
    args = sys.argv[1:]

    def opt(k, d=None):
        return cli_opt(args, k, d)

    src = opt("--from") or render_flash(int(opt("--seed", 4242)))
    print("эскиз:", src)
    to_ink(src, opt("--out", os.path.join(ROOT, "assets", "tattoo_flash.png")))


if __name__ == "__main__":
    main()
