#!/usr/bin/env python3
"""Картинки для документации собираются ЭТИМ скриптом, а не руками.

  py -3 doc_figures.py <project_dir> [hero|range|tattoo|all]

ЗАЧЕМ ОТДЕЛЬНЫЙ СКРИПТ. Четыре иллюстрации README и docs/ собирались
одноразовыми файлами во временной папке: они не под гитом, их нет у того, кто
получит репозиторий, и пересобрать картинку после пересъёмки кадра было нечем.
Это тот же класс расхождения, что числа в прозе рядом с кодом, который их
меняет — только вместо числа картинка. Одна замена кадра в сдаче уже привела к
тому, что docs/range.jpg показывала кадр, которого в папке больше нет.

ВХОД — ТОЛЬКО ТО, ЧТО ЛЕЖИТ В РЕПОЗИТОРИИ: deliverables/<id>/ для полос со
сдачей и references/ для полосы про тату. GPU не нужен, воркер не нужен;
скрипт работает у любого, кто склонировал репозиторий.

ГЛАВНАЯ ГРАБЛЯ ЗДЕСЬ — РАСТЯЖЕНИЕ. Первая редакция геро-полосы масштабировала
кадр по высоте и, если он выходил у́же ячейки, растягивала его до неё по
ширине. Кадры «в рост» 704x1856 у́же ячейки на 63% — и четыре из восьми поехали
вширь, лица стали шире, чем они есть; заметила это заказчица, а не тест.
Правило теперь одно и без ветвлений: масштаб по БОЛЬШЕМУ из двух отношений,
лишнее обрезается, изображение не искажается никогда. Функция `fill` — то
единственное место, где это правило живёт.

ВТОРАЯ ГРАБЛЯ — НОРМАЛИЗАЦИЯ МАСШТАБА ЛИЦА. Сетка «разброс» когда-то приводила
все лица к одной доле ячейки, чтобы не резать головы. Побочно это стирало
единственную ось, по которой набор реально разный: лицо занимает от 23% до 45%
ширины кадра, почти вдвое. Поэтому `range` масштабирует по ШИРИНЕ (доля лица
сохраняется как снято), а по высоте режет вокруг найденного лица.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from _util import ROOT, cli_opt, project_name, setup_console

BG = (247, 246, 244)
INK = (28, 32, 36)
MUTED = (120, 126, 132)

# ВЫБОР КАДРОВ ЗАКРЕПЛЁН ЗДЕСЬ, А НЕ В ГОЛОВЕ. Полосы — это витрина, и кадры в
# них выбраны глазами; но раз выбраны — записаны, иначе следующая пересборка
# даст другую витрину и сравнить две редакции README будет нечем.
HERO = [("trends", n) for n in (
    "01_lift_mirror_flash_selfie", "04_station_platform_first_light",
    "08_taxi_green_sign", "10_saturday_market_exchange",
    "12_golden_hour_sand_wind", "14_blue_hour_shopfront",
    "16_salon_mirror_station", "20_bar_porch_flash")]

# Порядок чередует сторону поворота головы, чтобы взгляды не сбивались в ряд.
# Первые четыре — отбор заказчицы, он и есть лучшее.
RANGE = [
    ("part2_story", "01_silk_robe_bedroom"),
    ("trends", "13_launderette_late_flash"),
    ("part2_story", "03_bedside_close"),
    ("trends", "20_bar_porch_flash"),
    ("part1_profile", "02_street_full_length"),
    ("trends", "14_blue_hour_shopfront"),
    ("part2_story", "04_bath_filling_over_shoulder"),
    ("trends", "08_taxi_green_sign"),
    ("trends", "07_arms_length_train_selfie"),
    ("trends", "10_saturday_market_exchange"),
    ("part1_profile", "01_hero_portrait"),
    ("part1_profile", "03_paddle_court"),
]

# Окно прохода на носителе тату: те же числа, что у detail_tattoo по умолчанию.
TATTOO_AT = (0.47, 0.47)
TATTOO_PAD = 0.42


def font(size, bold=False):
    for name in (("segoeuib.ttf" if bold else "segoeui.ttf"), "arial.ttf"):
        p = os.path.join(r"C:\Windows\Fonts", name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def fill(im, cw, ch, top_bias=0.14):
    """Кадр в ячейку БЕЗ искажения: масштаб по большему отношению, лишнее режем.

    Ветвления здесь нет намеренно — см. шапку модуля. Любое «а если кадр у́же»
    заканчивается растянутым лицом.
    """
    s = max(cw / im.width, ch / im.height)
    im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))),
                   Image.LANCZOS)
    left = (im.width - cw) // 2
    top = max(0, min(int((im.height - ch) * top_bias), im.height - ch))
    out = im.crop((left, top, left + cw, top + ch))
    assert out.size == (cw, ch), out.size
    return out


def frame_path(pid, part, name):
    p = os.path.join(ROOT, "deliverables", pid, part, name + ".jpg")
    if not os.path.exists(p):
        raise SystemExit("нет кадра сдачи: %s\n  Полоса собирается ИЗ СДАЧИ; "
                         "если кадр пересняли под другим именем, поправь "
                         "таблицу в этом файле, а не имя файла на диске." % p)
    return p


def build_hero(pid, out):
    h, gap = 520, 6
    cw = int(h * 0.62)
    tiles = [fill(Image.open(frame_path(pid, a, b)).convert("RGB"), cw, h)
             for a, b in HERO]
    band = Image.new("RGB", (len(tiles) * cw + gap * (len(tiles) - 1), h),
                     (14, 22, 26))
    for i, t in enumerate(tiles):
        band.paste(t, (i * (cw + gap), 0))
    band.save(out, "JPEG", quality=88, optimize=True, progressive=True)
    return band.size, len(tiles)


def build_range(pid, out):
    cols, cw, ch, gap, margin = 4, 520, 650, 18, 26
    try:
        from metrics import faces
    except Exception:
        faces = None
    rows = (len(RANGE) + cols - 1) // cols
    sheet = Image.new("RGB",
                      (margin * 2 + cols * cw + (cols - 1) * gap,
                       margin * 2 + rows * ch + (rows - 1) * gap), BG)
    for i, (part, name) in enumerate(RANGE):
        p = frame_path(pid, part, name)
        im = Image.open(p).convert("RGB")
        # ПО ШИРИНЕ, а не по большему отношению: так доля, которую занимает
        # лицо, остаётся такой, какой снята. См. вторую грабли в шапке.
        s = cw / im.width
        im = im.resize((cw, max(1, round(im.height * s))), Image.LANCZOS)
        if im.height <= ch:
            im = im.resize((cw, ch), Image.LANCZOS)
        else:
            cy = im.height * 0.30
            if faces is not None:
                r = faces.detect(p)
                if r.get("state") == "PASS" and r.get("bbox"):
                    _x0, y0, _x1, y1 = r["bbox"]
                    cy = (y0 + (y1 - y0) * 0.42) * s
            top = max(0, min(int(cy - ch * 0.38), im.height - ch))
            im = im.crop((0, top, cw, top + ch))
        sheet.paste(im, (margin + (i % cols) * (cw + gap),
                         margin + (i // cols) * (ch + gap)))
    sheet.save(out, "JPEG", quality=90, optimize=True, progressive=True)
    return sheet.size, len(RANGE)


def _ink_box(im, pad=0.10):
    """Рамка вокруг чернила на холсте прохода.

    Чернило — пиксели заметно темнее ЛОКАЛЬНОЙ кожи, а не темнее какого-то
    порога: у кадра при свече и у кадра у окна яркость кожи разная, и
    абсолютный порог мерил бы освещение (та же грабля, что в metrics/tattoo).
    """
    import numpy as np
    g = np.asarray(im.convert("L"), dtype=np.float32)
    k = max(3, (min(im.size) // 24) | 1)
    bg = np.asarray(Image.fromarray(g.astype("uint8")).filter(
        ImageFilter.MedianFilter(size=min(k, 21))), dtype=np.float32)
    ink = (bg - g) > 12
    ys, xs = np.nonzero(ink)
    if len(xs) < 50:                       # чернила не нашлось — отдаём всё
        return (0, 0, im.width, im.height)
    px, py = int(im.width * pad), int(im.height * pad)
    return (max(0, int(xs.min()) - px), max(0, int(ys.min()) - py),
            min(im.width, int(xs.max()) + px),
            min(im.height, int(ys.max()) + py))


def build_tattoo(out):
    """Полоса про тату: кадр целиком с рамкой окна и тот же участок крупно.

    Правая половина берётся из ХОЛСТА прохода, а не из уменьшенного кадра. Это
    и есть смысл полосы: чернило нарисовано в 1024, а в кадре занимает 400 px,
    и всё, ради чего проход делался — разнотолщинный штрих, поры и веснушки
    вокруг, — видно только в родном разрешении.
    """
    host = os.path.join(ROOT, "references", "tattoo_host_wrist_inked.png")
    canvas = os.path.join(ROOT, "references", "tattoo_canvas_1024.png")
    for p in (host, canvas):
        if not os.path.exists(p):
            raise SystemExit("нет исходника полосы: " + p)
    height, pad, gap = 620, 34, 22
    full = Image.open(host).convert("RGB")
    full = full.resize((round(full.width * height / full.height), height),
                       Image.LANCZOS)
    d = ImageDraw.Draw(full)
    half = int(min(full.size) * TATTOO_PAD / 2)
    cx, cy = int(TATTOO_AT[0] * full.width), int(TATTOO_AT[1] * full.height)
    d.rectangle([cx - half, cy - half, cx + half, cy + half],
                outline=(214, 168, 46), width=3)

    hi = Image.open(canvas).convert("RGB")
    # КРОП ИЩЕТ САМУ НАДПИСЬ, А НЕ БЕРЁТ ЗАШИТУЮ ПОЛОСУ. Здесь стояли доли
    # 0.20-0.66 по высоте, снятые с одного конкретного сида. Сид сменился — и
    # полоса разрезала слово пополам: строка у каждого прогона идёт под своим
    # углом и на своей высоте. Границы берутся по маске чернила (пиксели темнее
    # локальной кожи), с запасом вокруг.
    hi = hi.crop(_ink_box(hi))
    hi = hi.resize((round(hi.width * height / hi.height), height),
                   Image.LANCZOS)

    top = 74
    sheet = Image.new("RGB",
                      (pad * 2 + full.width + gap + hi.width,
                       top + height + pad + 30), BG)
    dr = ImageDraw.Draw(sheet)
    dr.text((pad, 24), "Тату нарисована диффузией в окне 1024",
            fill=INK, font=font(30, True))
    sheet.paste(full, (pad, top))
    sheet.paste(hi, (pad + full.width + gap, top))
    dr.text((pad, top + height + 10), "кадр целиком, рамкой — окно прохода",
            fill=MUTED, font=font(19))
    dr.text((pad + full.width + gap, top + height + 10),
            "тот же участок в разрешении, в каком он нарисован",
            fill=MUTED, font=font(19))
    sheet.save(out, "JPEG", quality=92, optimize=True, progressive=True)
    return sheet.size, 2


def build_details(out):
    """Полоса «как деталь появляется»: окно → до → после.

    Панелей ТРИ, а не четыре. Четвёртой стояла вклейка графики «для
    сравнения», и полоса пережила смену вывода: с тех пор как чернило рисует
    диффузия, вклейка — запасной путь, а не равный вариант, и держать её в
    витрине значит показывать читателю выбор, которого проект уже не делает.
    Прежняя полоса вдобавок собиралась на МЯГКОМ носителе — том самом, про
    который detail_tattoo предупреждает отдельной проверкой резкости.
    """
    clean = os.path.join(ROOT, "references", "tattoo_host_wrist.png")
    inked = os.path.join(ROOT, "references", "tattoo_host_wrist_inked.png")
    for p in (clean, inked):
        if not os.path.exists(p):
            raise SystemExit("нет исходника полосы: " + p)
    ch, gap, top = 470, 6, 26
    src = Image.open(clean).convert("RGB")
    ink = Image.open(inked).convert("RGB")
    half = int(min(src.size) * TATTOO_PAD / 2)
    cx, cy = int(TATTOO_AT[0] * src.width), int(TATTOO_AT[1] * src.height)
    win = (cx - half, cy - half, cx + half, cy + half)

    # ПЕРВАЯ ПАНЕЛЬ ШИРЕ ОСТАЛЬНЫХ НАМЕРЕННО: она отвечает на вопрос «где на
    # руке окно», и ответ виден только вместе с рукой. Вторая и третья — РОВНО
    # окно, кадр в кадр, чтобы «до» и «после» сравнивались без сдвига.
    wide = (max(0, cx - half * 2), max(0, cy - int(half * 1.3)),
            min(src.width, cx + half * 2),
            min(src.height, cy + int(half * 1.3)))
    marked = src.crop(wide)
    dx, dy = cx - wide[0], cy - wide[1]
    ImageDraw.Draw(marked).rectangle(
        [dx - half, dy - half, dx + half, dy + half],
        outline=(214, 168, 46), width=5)
    panels = [("где окно на руке", marked),
              ("окно: до", src.crop(win)),
              ("окно: после, диффузия 0.42", ink.crop(win))]
    widths = [round(im.width * ch / im.height) for _, im in panels]
    sheet = Image.new("RGB", (sum(widths) + gap * (len(panels) - 1),
                              top + ch), (18, 18, 18))
    dr = ImageDraw.Draw(sheet)
    x = 0
    for (label, im), w in zip(panels, widths):
        sheet.paste(im.resize((w, ch), Image.LANCZOS), (x, top))
        dr.text((x + 8, 4), label, fill=(225, 225, 225), font=font(18))
        x += w + gap
    sheet.save(out, "JPEG", quality=91, optimize=True, progressive=True)
    return sheet.size, len(panels)


def main():
    setup_console()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    pid = project_name(args[0])
    which = (args[1] if len(args) > 1 else "all").lower()
    docs = cli_opt(sys.argv[1:], "--docs", os.path.join(ROOT, "docs"))
    jobs = {"hero": lambda: build_hero(pid, os.path.join(docs, "hero.jpg")),
            "range": lambda: build_range(pid, os.path.join(docs, "range.jpg")),
            "tattoo": lambda: build_tattoo(os.path.join(docs, "tattoo.jpg")),
            "details": lambda: build_details(os.path.join(docs,
                                                          "details.jpg"))}
    if which not in jobs and which != "all":
        raise SystemExit("не знаю полосы «%s»; есть: %s, all"
                         % (which, ", ".join(jobs)))
    for name in (jobs if which == "all" else [which]):
        size, n = jobs[name]()
        p = os.path.join(docs, name + ".jpg")
        print("%-8s %dx%d, панелей %d, %.2f МБ"
              % (name, size[0], size[1], n, os.path.getsize(p) / 1e6))


if __name__ == "__main__":
    main()
