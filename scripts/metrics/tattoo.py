#!/usr/bin/env python3
"""Тату на кадре: лежит ли чернило ТАМ, ГДЕ ЗАЯВЛЕНО, и той ли оно формы.

  py -3 scripts/metrics/tattoo.py [<кадр> …]   # самотест и перекалибровка

Без аргументов берёт сданные кадры Part 1 — они лежат в репозитории, и на них
воспроизводится вся таблица ниже.

ВОПРОС, НА КОТОРЫЙ ОТВЕЧАЮТ ЭТИ ВОРОТА, НЕ «ЕСТЬ ЛИ ТЁМНОЕ НА ЗАПЯСТЬЕ».
Тёмного на запястье полно: браслет, часы, тень от кисти, вена, край рукава.
Метрика меряет СОВПАДЕНИЕ С ФОРМОЙ — сколько чернила нашлось в тех пикселях,
где ассет держит штрих, минус сколько его нашлось там, где ассет держит кожу.
Отсюда же и ответ на вторую половину вопроса, «похожа ли тату на себя же на
других кадрах»: во всех кадрах вклеивается ОДИН И ТОТ ЖЕ файл (буква в букву —
см. character.json → tattoo._), поэтому сверка каждого кадра с эталоном и есть
попарная сверка кадров между собой, только считается за один проход, а не за
N². Отдельной попарной матрицы, как у «сета», здесь нет намеренно: сравнивать
надписи между кадрами напрямую значит сравнивать два разных ракурса одной руки,
и разъехавшийся ракурс читался бы как разъехавшаяся тату.

ГДЕ РАМКА. Ровно там, куда кладёт надпись сам конвейер: metrics/wrist.py
разбирает разметку поверхностей тела, находит тыльную сторону нужного
запястья, и отдаёт `at` (центр строки в долях кадра), `size` (длина в долях
ширины) и `rot`. Своей геометрии здесь НЕТ и быть не должно — вторая точка
правды рядом с вклейкой означала бы, что ворота меряют не то место, куда
попадает тату. Готовую запись разметки (`wrist.record`) можно передать
аргументом `place`, и тогда ворота не ходят на воркер вовсе.

ЗАМЕР. Через разметку прогнано 17 кадров: 5 сданных Part 1 и 12 сырых из ячеек
P3/P5. Площадку она приняла на 12, остальные отвергла сама и по своим причинам
(левой руки в кадре нет; ладонь к камере; надпись вышла бы мельче порога
читаемости; масштаб по лицу и по руке разошёлся вшестеро). Из этих 12 рамок
одиннадцать несут ГОЛОЕ запястье, и одна — 03_paddle_court.jpg — сдана уже с
вклеенной надписью; она единственный НАСТОЯЩИЙ положительный пример, всё
остальное положительное получено вклейкой ассета в вычисленную рамку тем же
composite_tattoo, которым работает конвейер.

  класс                                n     совпадение с формой   медиана
  голое запястье                      11     -0.074 … +0.020       +0.000
  вклейка, сдвинутая на 0.06 кадра    11     -0.074 … +0.020       +0.000
  надпись, нарисованная диффузией      2     -0.056 … +0.006       +0.006
  вклейка непрозрачностью 0.30        11     +0.000 … +0.295       +0.110
  СДАННЫЙ КАДР С ВКЛЕЕННОЙ НАДПИСЬЮ    1               +0.237
  вклейка в вычисленную рамку         11     +0.262 … +0.538       +0.370

Щель между голой кожей (до +0.020) и настоящей вклейкой (от +0.237) — это
разница в двенадцать раз, а не подобранный порог. `INK_MIN` = 0.12 стоит
внутри неё, с запасом примерно вшестеро в обе стороны.

ПОЧЕМУ ТЕМНОТА ОТНОСИТЕЛЬНАЯ, А НЕ В УРОВНЯХ. Сначала «чернилом» считался
пиксель, который темнее локальной кожи на N уровней 0-255. Замер на тех же 12
рамках показал, что так не разделить вовсе:

  порог в уровнях     6     10     14     18
  щель            +0.042 +0.011 -0.014 -0.024

Причина видна на кадрах: ресторанная ячейка снята при свечах (яркость кожи
0.31), кухонная — у окна (0.64), и одно и то же чернило даёт там перепад в
13 и в 20 уровней. Абсолютный порог мерил освещение. Доля от локальной
яркости кожи (0.05 = «на 5% темнее того, что вокруг») от света не зависит:

  доля             0.05   0.07   0.09   0.12
  щель           +0.242 +0.182 +0.114 +0.039

ЧТО СЧИТАТЬ ФОНОМ — ТОЖЕ ЗАМЕРЕНО. Проверены три определения: всё, что дальше
3 px от штриха; узкое кольцо вокруг штриха; широкое кольцо. Кольцо казалось
правильнее (местный контраст, а не контраст полосы), но оно съедает сигнал:
при темноте 0.09 щель у кольца +0.038 против +0.114 у «всего вне штриха».
Так вышло потому, что вклейка кладёт под букву ореол (`composite_tattoo`
HALO_SPREAD), и кольцо попадает ровно в него — фон считается по чернилу.

ЧТО ЭТИ ВОРОТА НЕ ЛОВЯТ И НЕ ПРИТВОРЯЮТСЯ, ЧТО ЛОВЯТ.
  НАДПИСЬ, НАРИСОВАННУЮ ДИФФУЗИЕЙ (scripts/detail_tattoo.py), они объявляют
  отсутствующей: -0.056 и +0.006 на двух прогонах. Глазами надпись там есть и
  читается. Но лежит она НЕ ТАМ: проход рисует «Manolo Blahnik» примерно вдвое
  длиннее объявленной и выше объявленной оси, то есть ровно то расхождение
  места и размера, из-за которого проект и держит вклейку. Ворота считают это
  провалом честно — заявленное место пустое, — но называть их «детектором
  тату» после этого нельзя: они ворота ВКЛЕЙКИ.
  ВЫЦВЕТШУЮ ВКЛЕЙКУ они делят пополам: при непрозрачности 0.30 вместо рабочих
  0.95 одиннадцать копий дали +0.000 … +0.295, то есть часть проходит, часть
  нет. Это не дефект порога, а его смысл: ворота меряют ЧИТАЕМОСТЬ чернила, и
  надпись, которую едва видно, честно стоит на границе.

НЕЗАМЕР ЗДЕСЬ ЧАСТЫЙ И ЭТО НОРМА, А НЕ ПОЛОМКА. Тату легла на 4 кадра из 100
(projects/bridget/wrist_axes.json → _why), и узкое место — не нанесение, а то,
что нужная поверхность не попадает в кадр. Поэтому «тыльной стороны запястья
не видно» — это NOT_MEASURED, а не FAIL: мерить нечего. Из-за этого же ворота
НЕ ОБЯЗАТЕЛЬНЫЕ (gates.REQUIRED): обязательными они блокировали бы 96 кадров
из 100 за то, что модель не показала руку.

ЦЕНА ПРОГОНА. Разметка поверхностей — круг по GPU, 9-44 секунды на кадр
(замер на 17 кадрах). Сорок кадров с флагом tattoo_visible — это до десяти
минут на прогон ворот, после чего ворота выключат и будут правы. Поэтому
карта кусков КЭШИРУЕТСЯ на диск по (путь, размер, время правки): повторный
прогон по тем же кадрам не ходит на воркер вовсе.
"""
import sys, os, glob, math, hashlib

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _util import setup_console, manifest, work_dir, imread, imwrite  # noqa: E402
from metrics.verdict import PASS, FAIL, gate, not_measured  # noqa: E402

# Чернило — пиксель, который темнее локальной кожи на эту ДОЛЮ её яркости.
# Не уровни: см. таблицу в шапке, в уровнях щель схлопывается.
INK_DEPTH = 0.05
# Порог ворот: совпадение формы найденного чернила с формой ассета.
INK_MIN = 0.12
# Рамка приводится к этой длине. Нужна не «крупность», а одинаковая толщина
# штриха в пикселях у кадра 1280 и у кадра 2560: иначе морфология ниже
# стирала бы надпись на одном и не доставала бы до неё на другом.
CANON = 512
# Сторона закрытия, которым восстанавливается «кожа без надписи», в долях
# ВЫСОТЫ рамки. Должна быть заметно толще штриха и заметно тоньше руки.
BG_KERNEL = 0.09
# Ниже этого уровня альфа ассета — сглаживание края, а не штрих.
ASSET_INK = 0.35
# Фон отступает от штриха на столько пикселей канонической рамки: вплотную к
# букве лежит её же сглаживание, и оно считалось бы кожей.
BG_GAP = 3

_ALPHA = {}


def _root():
    return os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))


def asset_path(asset=None, char=None):
    """Файл ассета надписи. Возвращает путь или None.

    ТРИ ПОПЫТКИ, И ЭТО НЕ ПЕРЕСТРАХОВКА. `gates.py` склеивает путь из карточки
    с папкой ПРОЕКТА: `projects/bridget` + `assets/tattoo_manolo_blahnik.png`.
    Ассет лежит не там, а в корне репозитория, и такой путь не существует —
    проверено, файла по нему нет. Метрика, которая на этом просто отказалась
    бы, дала бы вечный NOT_MEASURED со словами «ассет не найден», и виноватым
    выглядел бы ассет. Поэтому имя из карточки пробуется и от корня тоже.
    """
    cand = []
    if asset:
        cand.append(asset)
        cand.append(os.path.join(_root(), os.path.basename(asset)))
        # …и от корня целиком: в карточке путь записан относительно репозитория.
        tail = asset.replace("\\", "/").split("/")
        if "assets" in tail:
            cand.append(os.path.join(_root(), *tail[tail.index("assets"):]))
    card = ((char or {}).get("tattoo") or {}).get("asset")
    if card:
        cand.append(os.path.join(_root(), *card.replace("\\", "/").split("/")))
    cand.append(os.path.join(_root(), "assets", "tattoo_manolo_blahnik.png"))
    for p in cand:
        if p and os.path.exists(p):
            return p
    return None


def asset_alpha(path, shape=None):
    """Альфа ассета, при нужде растянутая на канонический размер рамки."""
    if path not in _ALPHA:
        from PIL import Image
        with Image.open(path) as im:
            a = np.asarray(im.convert("RGBA"))[..., 3].astype(np.float32) / 255.0
        _ALPHA[path] = a
    a = _ALPHA[path]
    if shape is None or a.shape[:2] == tuple(shape):
        return a
    return cv2.resize(a, (shape[1], shape[0]), interpolation=cv2.INTER_AREA)


def plate(img, at, rot, length, height, canon=CANON):
    """Площадка под надписью, развёрнутая по строке и приведённая к канону.

    Одним аффинным преобразованием, а не «повернуть кадр целиком и вырезать»:
    поворот полного кадра 2560x3200 ради полоски 400x96 стоит полсекунды на
    кадр и добавляет ещё одну интерполяцию поверх той, что и так будет.
    """
    a = math.radians(rot)
    # Тот же вектор, которым `wrist.measure` строит рамку вклейки, и знак у
    # него тот же. Разъедется знак — площадка ляжет зеркально, чернило
    # окажется «не той формы», и ворота начнут валить исправные кадры.
    e = np.array([math.cos(a), -math.sin(a)])
    p = np.array([-e[1], e[0]])
    s = canon / float(max(length, 1e-6))
    ch = max(8, int(round(height * s)))
    o = np.asarray(at, np.float64) - e * (length / 2.0) - p * (height / 2.0)
    m = np.array([[e[0] / s, p[0] / s, o[0]],
                  [e[1] / s, p[1] / s, o[1]]], np.float64)
    return cv2.warpAffine(img, m, (canon, ch),
                          flags=cv2.INTER_AREA | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE)


def ink_depth(pat):
    """Насколько каждый пиксель темнее ЛОКАЛЬНОЙ кожи, в долях её яркости.

    Кожа без надписи получается закрытием по светлому — тем же приёмом, каким
    ассет когда-то вынимали из фотографии референса (`tattoo_from_photo`).
    Деление на восстановленную кожу, а не на среднее по рамке: рука бывает
    освещена неровно, и на затенённом конце тот же штрих даёт вдвое меньший
    перепад в уровнях.
    """
    g = cv2.cvtColor(pat, cv2.COLOR_BGR2GRAY).astype(np.float32)
    k = max(3, int(pat.shape[0] * BG_KERNEL) | 1)
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    skin = cv2.morphologyEx(g, cv2.MORPH_CLOSE, ker)
    return np.clip(skin - g, 0, None) / np.maximum(skin, 1.0)


def shape_match(pat, alpha, depth=INK_DEPTH):
    """Совпадение чернила с формой ассета: доля на штрихе минус доля на коже.

    Вычитание обязательно. Без него «долю чернила на штрихе» набирает любая
    равномерно тёмная площадка — ремешок часов через всё запястье даёт 1.00,
    и ворота объявили бы часы татуировкой.
    """
    d = ink_depth(pat)
    a = asset_alpha(alpha, d.shape) if isinstance(alpha, str) else alpha
    ink = a > ASSET_INK
    if not ink.any():
        return None
    k = np.ones((BG_GAP * 2 + 1,) * 2, np.uint8)
    skin = cv2.dilate(ink.astype(np.uint8), k) == 0
    if not skin.any():
        return None
    hit = d > depth
    on = float(hit[ink].mean())
    off = float(hit[skin].mean())
    return {"match": on - off, "on_ink": on, "on_skin": off,
            "median_depth": float(np.median(d[ink]))}


def part_map(src):
    """Карта кусков тела с кэшем на диске. (карта|None, откуда|причина).

    Кэш по (путь, размер, время правки), а не по одному пути: кадр
    перегенерируют под тем же именем, и карта от прошлой версии легла бы на
    новую руку молча — это худший вид кэша, потому что ошибка выглядит как
    измерение.
    """
    from metrics import wrist
    try:
        st = os.stat(src)
    except OSError as e:
        return None, f"кадр не читается: {e}"
    key = hashlib.sha1(("%s|%d|%d" % (os.path.abspath(src), st.st_size,
                                      int(st.st_mtime))).encode("utf-8"))
    path = os.path.join(work_dir("_cache", "densepose"),
                        key.hexdigest()[:16] + ".png")
    if os.path.exists(path):
        return imread(path, cv2.IMREAD_GRAYSCALE), "кэш"
    try:
        idx = wrist.part_map(src)
    except Exception as e:
        return None, f"разметка поверхностей недоступна: {type(e).__name__}: {e}"
    if idx is None:
        return None, "воркер не отдал карту кусков"
    imwrite(path, idx)
    return idx, "воркер"


def placement(src, char=None, face=None, place=None):
    """Где на этом кадре объявлена надпись. (запись|None, причина отказа|None).

    Записью считается либо готовая разметка (`wrist.record`), либо свежий
    разбор кадра. Первое даром, второе — круг по GPU.
    """
    if place and place.get("at") and place.get("size"):
        return {"at": place["at"], "size": float(place["size"]),
                "rot": float(place.get("rot", 0.0)), "source": "запись"}, None
    from metrics import wrist
    try:
        side, surface = wrist.from_card(char or {})
    except BaseException:
        # from_card поднимает SystemExit, а он НЕ Exception: раннер ворот ловит
        # только Exception, и голый отказ карточки унёс бы весь прогон по сорока
        # кадрам вместе с уже посчитанными метриками.
        return None, ("карточка не говорит, где тату (tattoo.placement) — "
                      "проверять нечего")
    idx, why = part_map(src)
    if idx is None:
        return None, why
    m = wrist.measure(src, side=side, idx=idx, surface=surface,
                      ipd=(face or {}).get("ipd_px"),
                      # Занятость площадки — ВТОРОЙ круг по GPU, и воротам он
                      # не нужен: вопрос ворот не «можно ли вклеить», а «лежит
                      # ли чернило». Часы поверх надписи метрика и так увидит —
                      # формы под ними не будет.
                      check_occluders=False)
    if not m.get("back_visible"):
        return None, m.get("why", "разметка не нашла площадку под надпись")
    m["source"] = "разметка"
    return m, None


def tattoo(src, char=None, gates=None, face=None, asset=None, visible=None,
           place=None):
    """Ворота тату. Результат в формате `verdict.gate`.

    `visible=False` — кадр не обещал запястья, ворота к нему НЕПРИМЕНИМЫ. Это
    не то же самое, что незамер: в таблице ворот такая клетка стоит пустой
    (n/a), и обязательной для этого кадра метрика не считается. Раннер
    (`gates.py`) решает применимость по флагу реестра и метрику просто не
    зовёт; параметр нужен тем, кто зовёт её напрямую.
    """
    g = gates or manifest()["gates"]
    # Порог живёт здесь, а не в манифесте, ровно до тех пор, пока манифест его
    # не объявит: assets.json → gates._no_tattoo_no_detector сам записал, что
    # порогов этих ворот там нет, потому что не было и метрики. Манифест
    # перекрывает — иначе перекалибровка требовала бы правки кода.
    lo = float(g.get("tattoo_ink_min", INK_MIN))
    depth = float(g.get("tattoo_ink_depth", INK_DEPTH))

    if visible is False:
        return not_measured("tattoo", "кадр не обещал тыльной стороны запястья",
                            applicable=False)
    if not (char or {}).get("tattoo"):
        return not_measured("tattoo", "карточка персонажа не объявляет тату",
                            applicable=False)

    art = asset_path(asset, char)
    if art is None:
        return not_measured("tattoo", f"файла надписи нет: {asset or '—'}")

    place, why = placement(src, char=char, face=face, place=place)
    if place is None:
        # Площадки в кадре нет — мерить нечего. Именно НЕЗАМЕР, а не провал:
        # 96 кадров из 100 не показывают нужную сторону запястья, и объявлять
        # их бракованными значило бы браковать раскадровку, а не кадр.
        return not_measured("tattoo", why or "место надписи не определено")

    img = imread(src)
    if img is None:
        return not_measured("tattoo", f"кадр не прочитан: {src}")
    h, w = img.shape[:2]
    a = asset_alpha(art)
    length = float(place["size"]) * w
    height = length * (a.shape[0] / float(a.shape[1]))
    at = (float(place["at"][0]) * w, float(place["at"][1]) * h)
    pat = plate(img, at, float(place.get("rot", 0.0)), length, height)
    res = shape_match(pat, asset_alpha(art, pat.shape[:2]), depth)
    if res is None:
        return not_measured("tattoo", "площадка вырождена: в рамке нет ни "
                                      "штриха, ни кожи")

    note = ""
    if res["match"] < lo:
        note = ("в объявленном месте чернила нет — либо надпись не вклеена, "
                "либо легла мимо" if res["on_ink"] < 2 * res["on_skin"] else
                "чернило есть, но формой на надпись не похоже")
    return gate("tattoo", res["match"], lo=lo, note=note,
                on_ink=round(res["on_ink"], 4), on_skin=round(res["on_skin"], 4),
                median_depth=round(res["median_depth"], 4),
                place=[round(float(place["at"][0]), 4),
                       round(float(place["at"][1]), 4)],
                size=round(float(place["size"]), 4),
                rot=round(float(place.get("rot", 0.0)), 2),
                length_px=round(length), source=place.get("source"),
                surface_frac=(round(place["surface_frac"], 3)
                              if place.get("surface_frac") is not None else None),
                asset=os.path.basename(art), ink_depth=depth)


def measure(src, char=None, gates=None, face=None, asset=None, visible=None,
            place=None):
    """Второе имя тех же ворот: раннер ищет метрику по списку кандидатов.

    Синоним, а не отдельный расчёт — по той же причине, что и в sharpness.py:
    обёртка, отдающая голые числа, лишила бы результат поля `state`, и раннер
    объявил бы живую метрику незамером на всём наборе.
    """
    return tattoo(src, char=char, gates=gates, face=face, asset=asset,
                  visible=visible, place=place)


def _card():
    """Карточка проекта, на котором эта метрика откалибрована."""
    from _util import read_json
    p = os.path.join(_root(), "projects", "bridget", "character.json")
    return read_json(p) if os.path.exists(p) else {}


def _frames(argv):
    if argv:
        return list(argv)
    return sorted(glob.glob(os.path.join(_root(), "deliverables", "bridget",
                                         "part1_profile", "0*.jpg")))


def main():
    """Самотест: та же процедура, которой подобран порог.

    Проверяются НЕ АБСОЛЮТНЫЕ ЧИСЛА, а существование щели между голой кожей и
    вклейкой и положение порога внутри неё — ровно как в sharpness.py и по той
    же причине: числа едут вместе с рендером и с ассетом, а щель обязана
    оставаться. Кадры, на которых разметка не нашла площадку, из калибровки
    выпадают и называются вслух: это не расхождение, а честный отказ метрики.
    """
    setup_console()
    files = _frames(sys.argv[1:])
    if not files:
        raise SystemExit("нечего мерить: передайте пути к кадрам")
    import composite_tattoo as ct

    char = _card()
    g = manifest()["gates"]
    lo = float(g.get("tattoo_ink_min", INK_MIN))
    art = asset_path(None, char)
    tmp = work_dir("_tmp", "tattoo_selftest")
    print(f"порог совпадения формы: {lo} · чернило темнее кожи на "
          f"{INK_DEPTH:.0%} · ассет {os.path.basename(art or '—')}\n")
    print(f"{'кадр':26} {'вариант':16} {'совпад':>8} {'штрих':>7} {'кожа':>7}  вердикт")

    bare, inked, skipped = [], [], 0
    for path in files:
        name = os.path.basename(path)
        base = tattoo(path, char=char)
        if base["state"] not in (PASS, FAIL):
            print(f"{name:26} {'вне калибровки':16} {base['note']}")
            skipped += 1
            continue
        place = {"at": base["place"], "size": base["size"], "rot": base["rot"]}
        pasted = os.path.join(tmp, os.path.splitext(name)[0] + "_inked.png")
        ct.composite(path, place["at"], place["size"], place["rot"], out=pasted,
                     asset=art)
        variants = [("как сдан", path), ("вклейка поверх", pasted)]
        for tag, p in variants:
            r = tattoo(p, char=char, place=place)
            v = "—" if r["value"] is None else f"{r['value']:8.3f}"
            print(f"{name:26} {tag:16} {v:>8} {r.get('on_ink', 0):7.3f} "
                  f"{r.get('on_skin', 0):7.3f}  {r['state']}"
                  f"{'  — ' + r['note'] if r['note'] else ''}")
            (bare if tag == "как сдан" else inked).append((r["value"], name))
        print()

    if not inked:
        raise SystemExit(
            "до калибровки не дошёл ни один кадр: разметка не нашла тыльной "
            "стороны запястья ни на одном из них. Это штатный ответ "
            "инструмента, но откалибровать по нему нечего — дайте кадры, "
            "где запястье на виду.")

    # Кадр, сданный УЖЕ с надписью, — не «голая кожа», и в нижнюю границу щели
    # его брать нельзя. Отделяется по собственному вердикту метрики, а не по
    # списку имён: список разошёлся бы со сдачей на первой же перегенерации.
    skin = [v for v, n in bare if v is not None and v < lo]
    already = [(v, n) for v, n in bare if v is not None and v >= lo]
    top = [v for v, n in inked if v is not None]
    for v, n in already:
        print(f"  {n}: сдан уже с надписью (совпадение {v:.3f}) — в нижнюю "
              f"границу щели не идёт")
    if skipped:
        print(f"  вне калибровки {skipped} кадр(ов): площадки под надпись нет")
    if not skin:
        raise SystemExit("не осталось ни одного кадра с голым запястьем — "
                         "верхнюю границу голой кожи считать не по чему")

    bad = 0
    hi_skin, lo_ink = max(skin), min(top)
    print(f"\nголая кожа до {hi_skin:+.3f} · вклейка от {lo_ink:+.3f} · "
          f"порог {lo}")
    if hi_skin >= lo_ink:
        bad += 1
        print("  ЩЕЛИ НЕТ: голое запястье и вклейка перекрылись — порогом их\n"
              "  не разделить ни при каком значении. Смотреть надо не на\n"
              "  число, а на то, туда ли легла рамка: печатайте place/rot.")
    elif not (hi_skin < lo < lo_ink):
        bad += 1
        print(f"  ПОРОГ ВНЕ ЩЕЛИ: перенести внутрь ({hi_skin:.3f}, "
              f"{lo_ink:.3f}) — сейчас он либо пропускает голую кожу, либо\n"
              f"  валит вклеенную надпись.")
    else:
        # Запас В ЕДИНИЦАХ СОВПАДЕНИЯ, а не в разах. Верх щели у голой кожи
        # уходит в ноль и в минус (кожа темнее «штриха» ровно настолько же,
        # насколько и вокруг), и отношение к нему давало «запас x120» там, где
        # честно надо писать «0.14».
        print(f"  порог внутри щели: до голой кожи {lo - hi_skin:.3f}, "
              f"до слабейшей вклейки {lo_ink - lo:.3f}")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
