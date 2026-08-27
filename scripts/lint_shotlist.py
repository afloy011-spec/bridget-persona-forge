#!/usr/bin/env python3
"""Проверить раскадровку на правила, которые ЗАМЕРЕНЫ, а не придуманы.

  py -3 lint_shotlist.py <проект> [shotlist.json ...]

ЗАЧЕМ ОТДЕЛЬНЫМ ШАГОМ. Каждое правило ниже стоило прогонов на GPU, и каждое
легко нарушить, набирая клетку словами: текст выглядит осмысленным, промпт
собирается, батч уходит на воркер — и брак виден только на готовых кадрах,
через два часа и сотню кадров. Дешевле поймать буквой.

Проверяется ровно то, что нельзя увидеть в тексте глазами:

ОТРИЦАНИЯ. При cfg = 1.0 негативный кондиционер мёртв, и отрицание в
положительном промпте читается моделью как ЗАПРОС: «без очков» даёт очки.
Правило записано в карточке (`forbidden_as_positive`) и нарушается чаще
всего — потому что по-русски «не» звучит естественно.

ПОЛНЫЙ РОСТ. Словами он не выпрашивается: на 4:5 модель тянет к портрету, что
ни пиши. Единственный рычаг — форма кадра, и клетка, объявившая `full_figure`,
обязана назначить свою `size`. Флаг `body_in_frame` этого НЕ требует: он про
то, подмешивать ли в промпт сложение, и кадр по колено его показывает.

ЦЕНА РОСТА ЦЕЛИКОМ. Он воюет с измеримостью: чем выше кадр, тем мельче лицо, а
ниже межзрачкового 100 px обязательные ворота резкости и кожи слепнут и кадр
не отгружается вовсе. Замерено на книжной клетке — 2.64 дало фигуру целиком и
лицо 96-97 px, то есть шесть кадров подряд в брак.

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. `tattoo_visible` не проверяется: флаг законный, он
отправляет кадр на отдельный шаг вклейки (диффузия тату не рисует — замерено),
а ворота «тату» в манифесте не значатся обязательными. Ругаться на него значило
бы ругаться на работающий механизм.

ПОВТОР КАРТОЧКИ. `identity_core`, `age_markers`, `build`, `hair_rules` и
`realism_clause` подставляются В КАЖДУЮ клетку автоматически. Написанные ещё
раз в полях клетки, они не усиливают, а разбавляют: тот же смысл занимает
вдвое больше промпта, вытесняя сцену.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _util import read_json, setup_console

TRAITS = ("independent", "flirtatious", "sensitive", "guarded")
# «none» — законный ОТКАЗ от черты, а не опечатка: есть клетка, где состояние
# задаёт сам взгляд, и приписывать ей ещё и черту значит сказать одно дважды.
# Проверено тестом test_trait_none_is_accepted.
TRAIT_OPT = TRAITS + ("none",)
SCENES = ("day", "indoor", "night", "flash")

# Поля, которые едут прямо в промпт. Русские (label, function, notes) сюда не
# входят: их модель не видит, и «не» в них безвредно.
PROMPT_FIELDS = ("framing", "gaze", "wardrobe", "set", "light", "camera")

# Отрицания. `no` и `not` берутся по границе слова, иначе «notebook» и
# «nose» ловятся как нарушения — обе бывают в описании сцены.
NEGATIONS = re.compile(
    r"\b(?:no|not|non|never|without|avoid|avoiding|lacking|lack of|free of|"
    r"devoid|absent|isn't|aren't|doesn't|don't|won't|nothing|neither|nor|"
    r"un-?lit|rather than)\b", re.I)

# Куски карточки, которые подставляются сами. Ищутся по характерным словам, а
# не целиком: клетка перепишет их своими словами, а не скопирует.
CARD_ECHO = re.compile(
    r"\b(?:51[- ]year[- ]old|fifty[- ]one|in her (?:early )?fifties|"
    r"green[- ]hazel|balayage|crow's feet|nasolabial|"
    r"visible pores|skin pores|mid[- ]brown hair|sun[- ]blonde)\b", re.I)

# Полный рост требует ОЧЕНЬ высокого кадра, и порог здесь поднят по замеру.
# Стояло 1.4 — то есть 2:3 считалось достаточным. Прогон 19.08 показал, что
# нет: семь клеток, снятых 1024x1536 (1.50), вышли поясными все до одной.
# Лестница на одной клетке и одних сидах (1.50 / 1.79 / 2.00 / 2.33 / 2.64):
# фигура целиком, с обувью в кадре, появляется от 2.33 и держится на 2.64.
# Порог 2.2 пропускает работающее и отсекает 2:3, которое проходило раньше и
# молча не работало. Замер: docs/full_figure_ratio.md.
TALL = 2.2


def _fields(cell):
    return [(k, cell[k]) for k in PROMPT_FIELDS
            if isinstance(cell.get(k), str)]


def lint_cell(cell, seen_ids, seen_names):
    """Список претензий к одной клетке."""
    bad = []
    cid = cell.get("id", "?")

    for key in ("id", "label", "trait", "body_in_frame", "scene_class",
                "delivery_name"):
        if key not in cell:
            bad.append(f"{cid}: нет обязательного поля «{key}»")

    if cell.get("trait") not in TRAIT_OPT and cell.get("trait") is not None:
        bad.append(f"{cid}: черта «{cell.get('trait')}» не из карточки; "
                   f"есть {', '.join(TRAIT_OPT)}")
    if cell.get("scene_class") not in SCENES:
        bad.append(f"{cid}: класс сцены «{cell.get('scene_class')}» неизвестен; "
                   f"есть {', '.join(SCENES)} — от него зависит сила лоры "
                   f"мыльницы")

    for key, text in _fields(cell):
        for m in NEGATIONS.finditer(text):
            frag = text[max(0, m.start() - 30):m.end() + 30]
            bad.append(f"{cid}.{key}: отрицание «{m.group(0)}» — при cfg 1.0 "
                       f"читается как ЗАПРОС: ...{frag}...")
        for m in CARD_ECHO.finditer(text):
            bad.append(f"{cid}.{key}: «{m.group(0)}» карточка подставляет "
                       f"сама — повтор разбавляет промпт")

    # ФИГУРА ВИДНА И ФИГУРА ЦЕЛИКОМ — РАЗНЫЕ ВЕЩИ, И ЗДЕСЬ ОНИ БЫЛИ СЛИТЫ.
    # `body_in_frame` управляет одним: подмешивать ли в промпт блок сложения.
    # Кадр по колено его показывает и высокого холста не требует. Проверка,
    # завязанная на этот флаг, ругалась на исправную клетку по колено и тем
    # толкала занижать флаг — то есть выбрасывать сложение из промпта, чтобы
    # замолчал линтер. Рост целиком объявляется отдельно, ключом full_figure.
    if cell.get("full_figure"):
        size = cell.get("size")
        if not size:
            bad.append(f"{cid}: рост целиком, но своя size не назначена — "
                       f"словами он не выпрашивается, нужен высокий кадр")
        elif size[1] / float(size[0]) < TALL:
            bad.append(f"{cid}: рост целиком при size {size} "
                       f"({size[1] / float(size[0]):.2f}) — модель на таком "
                       f"кадре тянет к портрету; нужно от {TALL}")

    if cid in seen_ids:
        bad.append(f"{cid}: номер повторяется")
    seen_ids.add(cid)

    name = cell.get("delivery_name", "")
    if name:
        if not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", name):
            bad.append(f"{cid}: delivery_name «{name}» — нужна латиница "
                       f"в snake_case, это имя файла в сдаче")
        if name in seen_names:
            bad.append(f"{cid}: delivery_name «{name}» повторяется — "
                       f"кадры перезапишут друг друга")
        seen_names.add(name)
    return bad


def lint(shots):
    """Претензии ко всей раскадровке плюс сводка по разнообразию."""
    bad, ids, names = [], set(), set()
    for cell in shots["cells"]:
        bad += lint_cell(cell, ids, names)

    return bad


def notes(shots):
    """Заметки: сказать стоит, валить прогон — нет.

    ОХВАТ ЧЕРТ — ПРАВИЛО ПРОЕКТА, А НЕ ОТДЕЛЬНОЙ РАСКАДРОВКИ, и здесь оно
    стояло не в том масштабе. История части 2 — пять кадров одного вечера,
    вместить в них все четыре черты нельзя и не нужно; линтер валил исправную
    раскадровку и подталкивал приписать черту ради тишины. Проектный охват уже
    стережёт tests/test_shotlist.py по ОБЪЕДИНЕНИЮ всех раскадровок.
    """
    used = {c.get("trait") for c in shots["cells"]}
    return ["черта «%s» в этой раскадровке не встречается" % t
            for t in TRAITS if t not in used]


def spread(shots):
    """Разнообразие набора числами. Не претензии — сводка для глаз."""
    cells = shots["cells"]
    out = {}
    for key in ("scene_class", "trait"):
        d = {}
        for c in cells:
            d[c.get(key)] = d.get(c.get(key), 0) + 1
        out[key] = d
    out["полный рост"] = sum(1 for c in cells if c.get("body_in_frame"))
    out["всего"] = len(cells)
    return out


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    project_dir = args[0]
    files = args[1:] or ["shotlist.json"]
    total = 0
    for f in files:
        path = f if os.path.isabs(f) else os.path.join(project_dir, f)
        shots = read_json(path)
        bad = lint(shots)
        print(f"\n=== {os.path.basename(path)}: {len(shots['cells'])} клеток")
        s = spread(shots)
        print(f"  сцены: {s['scene_class']}")
        print(f"  черты: {s['trait']}")
        print(f"  полный рост: {s['полный рост']} из {s['всего']}")
        for n in notes(shots):
            print("   ·", n)
        if bad:
            print(f"  НАРУШЕНИЙ: {len(bad)}")
            for b in bad:
                print("   ✗", b)
        else:
            print("  нарушений нет")
        total += len(bad)
    raise SystemExit(1 if total else 0)


if __name__ == "__main__":
    main()
