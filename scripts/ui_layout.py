#!/usr/bin/env python3
"""Правила раскладки холста ComfyUI. Одно место на все сборщики воркфлоу.

ЗАЧЕМ ОТДЕЛЬНЫМ МОДУЛЕМ. Правила жили константами внутри build_ui.py, и
второй сборщик получил свою копию — с тем же значением, но уже не связанную.
Первая правка развела бы их молча.

ГЛАВНОЕ ПРАВИЛО: НОДА ЦЕЛИКОМ ВНУТРИ СВОЕЙ РАМКИ И НИЧЕГО НЕ ПЕРЕСЕКАЕТ.
Просвет — это чистое расстояние до рамки, а не координатная разница.

Из этого следует то, что легко упустить: **заголовок группы рисуется ПОЛОСОЙ
ВНУТРИ рамки**, а не над ней. Нода, поставленная на просвет ниже верхней
кромки, въезжает в эту полосу — рамка визуально «прошита» нодой. Поэтому
верхний отступ считается как высота полосы плюс TOP.

Высота полосы берётся из `font_size` группы, а не константой: у групп разного
кегля она разная, и зашитое число разъедется на первом же изменении шрифта.
"""

# Три числа, а не одно, и это не небрежность: у каждой стороны своя задача.
# Сверху поле отделяет ноду от ПОЛОСЫ ЗАГОЛОВКА, который рисуется внутри
# рамки, — там нужен воздух. С боков и снизу оно ничего не отделяет и просто
# делает рамку шире и выше содержимого.
TOP = 60            # от низа полосы заголовка до первой ноды
SIDE = 30           # по бокам
BOTTOM = 30         # под последней нодой
GROUP_GAP = 60      # между коробками групп, одинаково по X и по Y
GAP = 80            # между нодами внутри колонки
FONT = 24           # кегль заголовка группы


def header(font_size=FONT):
    """Высота полосы заголовка внутри рамки.

    Множитель 1.4 — то, что litegraph отводит под строку заголовка группы;
    округление вверх, чтобы просвет никогда не оказался меньше заявленного.
    """
    return int(font_size * 1.4 + 0.999)


def group_box(nodes, font_size=FONT):
    """Габариты группы: (ширина, высота) с просветом CLEAR со всех сторон."""
    w = max(n["size"][0] for n in nodes) + SIDE * 2
    h = (sum(n["size"][1] for n in nodes) + GAP * (len(nodes) - 1)
         + header(font_size) + TOP + BOTTOM)
    return w, h


def place(nodes, x, y, box_w, font_size=FONT):
    """Разложить ноды внутри рамки с левым верхним углом (x, y).

    Центрируются по ШИРИНЕ РАМКИ, а не по своей самой широкой ноде: колонка
    может быть шире группы, и центрирование «по себе» прижимает содержимое
    влево, оставляя справа пустую полосу.
    """
    cy = y + header(font_size) + TOP
    for n in nodes:
        n["pos"] = [x + (box_w - n["size"][0]) // 2, cy]
        cy += n["size"][1] + GAP
    return nodes


def columns(spec, origin=(40, 40), font_size=FONT):
    """Разложить колонки групп с постоянным зазором. Возвращает рамки."""
    out = []
    x = origin[0]
    for col in spec:
        boxes = [group_box(nodes, font_size) for _t, nodes, _c in col]
        col_w = max(w for w, _h in boxes)
        y = origin[1]
        for (title, nodes, color), (_w, h) in zip(col, boxes):
            place(nodes, x, y, col_w, font_size)
            out.append({"id": 0, "title": title,
                        "bounding": [x, y, col_w, h],
                        "color": color, "font_size": font_size, "flags": {}})
            y += h + GROUP_GAP
        x += col_w + GROUP_GAP
    return out


def check(wf, font_size=FONT):
    """Проверить холст на налипания. Возвращает список претензий.

    Проверяется ровно то, что просил заказчик, и ничего сверх: ноды внутри
    своих рамок с просветом, ноды не пересекают чужие рамки, ноды не налезают
    друг на друга, рамки не налезают друг на друга.
    """
    bad = []
    groups = wf.get("groups") or []
    nodes = wf.get("nodes") or []

    def box(n):
        return (n["pos"][0], n["pos"][1],
                n["pos"][0] + n["size"][0], n["pos"][1] + n["size"][1])

    def overlap(a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    owner = {}
    for g in groups:
        gx, gy, gw, gh = g["bounding"]
        gb = (gx, gy, gx + gw, gy + gh)
        for n in nodes:
            nb = box(n)
            if overlap(nb, gb):
                owner.setdefault(id(n), []).append(g)
                # внутри целиком?
                if not (nb[0] >= gx and nb[2] <= gx + gw
                        and nb[1] >= gy and nb[3] <= gy + gh):
                    bad.append("нода «%s» вылезает за рамку «%s»"
                               % (n.get("title", n["type"]), g["title"]))
                    continue
                top_free = nb[1] - (gy + header(font_size))
                if top_free < TOP:
                    bad.append("нода «%s» подходит к заголовку «%s» на %d px "
                               "при просвете %d"
                               % (n.get("title", n["type"]), g["title"],
                                  top_free, TOP))
                for name, free, need in (("слева", nb[0] - gx, SIDE),
                                         ("справа", gx + gw - nb[2], SIDE),
                                         ("снизу", gy + gh - nb[3], BOTTOM)):
                    if free < need:
                        bad.append("нода «%s» %s от рамки «%s» на %d px "
                                   "при просвете %d"
                                   % (n.get("title", n["type"]), name,
                                      g["title"], free, need))

    for n in nodes:
        if len(owner.get(id(n), [])) > 1:
            bad.append("нода «%s» попала сразу в %d рамки"
                       % (n.get("title", n["type"]), len(owner[id(n)])))

    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            if overlap(box(a), box(b)):
                bad.append("ноды «%s» и «%s» налезают друг на друга"
                           % (a.get("title", a["type"]), b.get("title", b["type"])))

    for i, g1 in enumerate(groups):
        x1, y1, w1, h1 = g1["bounding"]
        for g2 in groups[i + 1:]:
            x2, y2, w2, h2 = g2["bounding"]
            if overlap((x1, y1, x1 + w1, y1 + h1), (x2, y2, x2 + w2, y2 + h2)):
                bad.append("рамки «%s» и «%s» пересекаются"
                           % (g1["title"], g2["title"]))
    return bad

# ---------------------------------------------------------------- размеры нод

TITLE_H = 30        # шапка ноды
SLOT_H = 20         # строка порта
WIDGET_H = 26       # строка обычного виджета
FOOT = 12           # подвал ноды
LINK_TYPES = {"MODEL", "CLIP", "VAE", "IMAGE", "LATENT", "CONDITIONING",
              "MASK", "UPSCALE_MODEL", "CONTROL_NET", "STYLE_MODEL"}


def node_height(spec, widgets, multiline=0):
    """Высота ноды по ЕЁ ОБЪЯВЛЕНИЮ НА СЕРВЕРЕ, а не по нашему графу.

    ЗАЧЕМ ИМЕННО ТАК, И ЭТО ИСПРАВЛЕНИЕ ПО СКРИНШОТУ. Высоты стояли таблицей,
    набитой на глаз, и `Krea2EditModelPatch` вылезал из своей рамки. Причина:
    ComfyUI рисует ВСЕ объявленные входы, включая необязательные, а мы
    подключаем не все. У патча их восемь (source_latent_b, ref_boost_mask,
    vae, source_image, source_image_b сверх обязательных), в графе разведено
    пять — и нода оказалась на сотню пикселей выше расчёта.

    Поэтому порты считаются по /object_info: сколько сервер объявил, столько
    он и нарисует, независимо от того, что мы подключили.

    `multiline` — число текстовых полей: они занимают не строку, а блок.
    """
    ins = 0
    for sec in ("required", "optional"):
        for _k, v in (spec.get(sec) or {}).items():
            t = v[0] if isinstance(v, list) and v else None
            if isinstance(t, str) and t in LINK_TYPES:
                ins += 1
    outs = spec.get("_outputs", 1)
    plain = max(0, widgets - multiline)
    return (TITLE_H + max(ins, outs) * SLOT_H + plain * WIDGET_H
            + multiline * 170 + FOOT)
