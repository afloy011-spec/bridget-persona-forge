#!/usr/bin/env python3
"""Сборка промпта из блоков карточки персонажа и ячейки раскадровки.

  py -3 prompts.py <project_dir> [cell_id ...]        # напечатать промпты
  py -3 prompts.py <project_dir> --casting [N]        # промпты кастинга

Как модуль:
  from prompts import build_cell, build_casting, load_project

ПОЧЕМУ СБОРЩИК, А НЕ РУЧНОЙ ТЕКСТ. Идентичность персонажа держится тем, что
описание лица и возраста ДОСЛОВНО одинаково во всех кадрах. Стоит переписать
его руками в шестой раз — появится синоним, и лицо уедет. Здесь блок физически
один, повторение обеспечено конструкцией.

ПОЧЕМУ ЗАПРЕТОВ НЕТ. krea2 Turbo работает на cfg=1.0, а при cfg=1.0
негативный обусловливатель не влияет на результат вообще. Поэтому в схеме нет
поля negative: всё нежелательное выражено ПОЛОЖИТЕЛЬНЫМ требованием
(character.json → forbidden_as_positive). "no plastic skin" не работает —
работает "visible skin pores".
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import setup_console

VERBOSE = bool(os.environ.get("PERSONA_VERBOSE"))

ORDER_NOTE = """Порядок блоков не косметика. Модель взвешивает начало промпта
сильнее хвоста, поэтому первым идёт действие и человек, а техника и оговорки
про реализм уходят в конец: они должны корректировать кадр, а не определять
его."""


def load_project(project_dir, shotlist="shotlist.json"):
    """Вернуть (character, shotlist). project_dir — папка с обоими файлами.

    Раскадровок у проекта несколько: shotlist.json — профильный набор (Part 1),
    shotlist_story.json — история (Part 2). Карточка персонажа при этом одна на
    все части: в этом весь смысл — идентичность не должна зависеть от того,
    какую серию снимаем.
    """
    def rd(name):
        with open(os.path.join(project_dir, name), encoding="utf-8") as fh:
            return json.load(fh)
    return rd("character.json"), rd(shotlist)


def _clean(parts):
    """Склейка без пустых кусков, без задвоенных запятых и без повторов.

    Дедупликация не косметика: realism_clause и forbidden_as_positive
    пересекаются по смыслу (оба требуют нетронутой кожи), и в собранном промпте
    фраза оказывалась дважды. Повтор — это удвоенный вес требования, из-за него
    кадр уезжает в подчёркнутую фактуру в ущерб остальному.

    Проверка идёт на ВХОЖДЕНИЕ, а не на равенство: 'a half-smile' и 'a
    half-smile rather than a full one' — разные строки, но одно требование, и
    точное сравнение их не ловит. Побеждает то, что встретилось раньше, потому
    что порядок блоков осмыслен (см. ORDER_NOTE) и ранний блок весомее.

    ВХОЖДЕНИЕ СЧИТАЕТСЯ ПО ГРАНИЦАМ СЛОВ И ТОЛЬКО ДЛЯ ФРАЗ ИЗ 2+ СЛОВ. Наивная
    проверка `k in s` съедала осмысленные куски: высота камеры 'low' в P4
    исчезала, потому что буквы l-o-w есть внутри 'fuller lower lip' из блока
    идентичности, который стоит в КАЖДОМ промпте. Однословный кусок теперь
    выбрасывается только при точном совпадении.
    """
    def _swallows(short, long_):
        return (len(short.split()) >= 2
                and re.search(rf"(?<!\w){re.escape(short)}(?!\w)", long_))

    kept, out = [], []
    for p in parts:
        if not p or not str(p).strip():
            continue
        for chunk in str(p).split(","):
            c = chunk.strip().rstrip(",")
            if not c:
                continue
            k = c.lower()
            if any(k == s or _swallows(k, s) or _swallows(s, k) for s in kept):
                if VERBOSE:
                    print(f"  [dedup] выброшено как повтор: {c}", file=sys.stderr)
                continue
            kept.append(k)
            out.append(c)
    return ", ".join(out)


def _character_trigger(man=None, char_id=None):
    """Слово-триггер персонажной лоры, если она настроена. Иначе пусто.

    Отдельной функцией потому, что это ЕДИНСТВЕННАЯ связь между манифестом и
    текстом промпта: остальной промпт собирается из карточки персонажа. Пусто
    — штатный режим (лоры нет, идентичность берётся отбором), поэтому
    молчаливое пустое значение здесь законно и никого не обманывает.

    `char_id` передаётся везде, где он известен: разрешением занимается
    `_util.character_lora`, и оно же отказывает, когда лора обучена на другом
    человеке. Без этого аргумента триггер чужой лоры вставал первым словом
    промпта ЛЮБОГО персонажа — см. замер на projects/marek в его докстроке.
    """
    from _util import character_lora
    return character_lora(char_id, man).get("trigger") or ""


# Блоки карточки, ОПИСЫВАЮЩИЕ ВНЕШНОСТЬ. Их можно попросить не включать —
# см. `omit` у build_cell. Возраст сюда НЕ входит намеренно: он держится не
# описанием лица, а деталями кожи, шеи и кистей, и без него любой источник
# тянет женщину к двадцати семи.
LOOK_BLOCKS = ("identity_core", "hair_rules", "build")


def build_cell(char, cell, omit=()):
    """Полный промпт одной ячейки.

    `omit` — имена блоков карточки, которые НЕ включать (см. LOOK_BLOCKS).
    Нужен эдит-источнику: там внешность приезжает с референса, а те же слова
    в промпте описывают ТИПАЖ и тянут кадр от конкретного человека к нему.

    Порядок: действие/кадр → человек → возраст → сложение (только если тело в
    кадре) → гардероб → сцена → свет → камера → черта характера → хвост
    реализма.
    """
    framing = cell.get("framing", "")
    gaze = cell.get("gaze", "")
    # ВЫРАЖЕНИЕ — ОТДЕЛЬНЫЙ БЛОК, А НЕ ХВОСТ К ВЗГЛЯДУ, И ЭТО НЕ ПЕДАНТИЗМ.
    # Замер docs/variety_axes.md: из трёх осей разнообразия модель слушает
    # только выражение, и пока его не было, двадцать кадров выходили с одним
    # вежливым полуулыбом. Приписанное же к `gaze` оно ДРАЛОСЬ с описанием
    # рта, которое там уже стояло: «маленькая закрытая полуулыбка» и «открытый
    # смех с зубами» в одном промпте при cfg 1.0 получают вес оба. Отдельным
    # блоком выражение стоит сразу за взглядом и описывает ЛИЦО, а взгляд —
    # направление и подбородок.
    expression = cell.get("expression", "")

    # Сложение подмешиваем только когда тело действительно видно: в поясном
    # портрете описание ног и осанки — это шум, который отбирает вес у лица.
    # Решает ячейка (body_in_frame), эвристика по framing — только запасной
    # вариант: угадывание дописывало 'upright posture, strong legs' человеку,
    # скрючившемуся на полу в P4, потому что там встретилось 'seated'.
    body_in_frame = cell.get("body_in_frame")
    if body_in_frame is None:
        body_in_frame = any(k in framing.lower() for k in
                            ("full-length", "full length", "standing",
                             "three-quarter", "three quarter"))

    # Черта характера подбирается по кадру, а не сыпется вся сразу: четыре
    # поведенческих указания в одном промпте гасят друг друга. Черту НАЗНАЧАЕТ
    # раскадровка, а не подстрока в gaze: угадывание ставило в P4 черту guarded
    # ('её внимание в другом месте') поверх задачи кадра — настоящей открытой
    # улыбки, — и две черты из четырёх были недостижимы в принципе.
    # "none" — осознанный отказ от черты, отсутствие поля — ошибка данных.
    traits = {k: v for k, v in char.get("personality_in_frame", {}).items()
              if not k.startswith("_")}
    key = cell.get("trait")
    if key is None:
        raise KeyError(f"{cell.get('id')}: не задано поле trait "
                       f"(допустимо: {sorted(traits)} или \"none\")")
    if key != "none" and key not in traits:
        raise KeyError(f"{cell.get('id')}: черта {key!r} не описана в "
                       f"character.json → personality_in_frame {sorted(traits)}")
    trait = "" if key == "none" else traits[key]

    tail = _clean([char.get("realism_clause", "")]
                  + [v for k, v in char.get("forbidden_as_positive", {}).items()
                     if not k.startswith("_")])

    # Украшения — из библии гардероба, а не из ячейки: «одни и те же вещи в
    # каждом кадре» это самое дешёвое доказательство одного человека, и до
    # ревью оно не доезжало до модели ни разу. jewelry_override — для кадров,
    # которые раздевают шею и уши намеренно (спорт, душ).
    wb = char.get("wardrobe_bible", {})
    jewelry = cell.get("jewelry_override", wb.get("jewelry", ""))

    # Площадка под композит тату требуется явно и только там, где он будет.
    tattoo = char.get("tattoo", {})
    wrist = tattoo.get("prompt_clause", "") if cell.get("tattoo_visible") else ""

    # ТРИГГЕР ПЕРСОНАЖНОЙ ЛОРЫ — САМЫМ ПЕРВЫМ СЛОВОМ. Лора обучена на своём
    # токене и без него не включается; молча не включившаяся лора неотличима
    # от отсутствующей, и весь смысл закреплённого лица пропадает без единого
    # сообщения. Слово берётся из манифеста (models.character_lora.trigger),
    # а не из карточки персонажа: карточка описывает человека, а триггер —
    # свойство ВЕСОВ, и живёт он там же, где имя файла лоры.
    return _clean([
        _character_trigger(char_id=char.get("id")),
        char.get("medium", ""),
        framing,
        gaze,
        expression,
        "" if "identity_core" in omit else char.get("identity_core", ""),
        char.get("age_markers", ""),
        "" if "hair_rules" in omit else char.get("hair_rules", ""),
        "" if "build" in omit or not body_in_frame else char.get("build", ""),
        cell.get("wardrobe", ""),
        jewelry,
        wrist,
        cell.get("set", ""),
        cell.get("light", ""),
        cell.get("camera", "") or char.get("camera_default", ""),
        trait,
        tail,
    ])


CASTING_AXES = [
    "a chest-up portrait in soft window light, looking directly at the lens",
    "a three-quarter portrait in flat overcast daylight, looking slightly away",
    "a close portrait in warm evening lamplight, mid-laugh",
    "a portrait outdoors in raking late-afternoon sun, hair moving",
]

_CASTING_NOTE = """Кастинг меняет ОДНУ ось — свет и ракурс — при неизменном
описании человека. Так отбор идёт по лицу, а не по тому, какой вариант удачнее
освещён. Задача этапа: найти лицо С ХАРАКТЕРОМ (своя асимметрия, конкретный
нос, живые глаза). Обобщённо-красивое лицо читается как AI и человеком, и
детектором — это главная развилка всего проекта."""


def build_casting(char, n=12):
    """Промпты кастинга: только человек, сцены нет."""
    if n > len(CASTING_AXES):
        print(f"ВНИМАНИЕ: осей кастинга всего {len(CASTING_AXES)}, запрошено "
              f"{n} — промпты повторятся дословно. Разнообразие берётся сидом, "
              f"а не n.", file=sys.stderr)
    tail = _clean([char.get("realism_clause", "")]
                  + [v for k, v in char.get("forbidden_as_positive", {}).items()
                     if not k.startswith("_")])
    out = []
    for i in range(n):
        out.append(_clean([
            CASTING_AXES[i % len(CASTING_AXES)],
            char.get("identity_core", ""),
            char.get("age_markers", ""),
            char.get("camera_default", ""),
            tail,
        ]))
    return out


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__); raise SystemExit(1)
    project = args[0]
    char, shots = load_project(project)

    if "--casting" in args:
        i = args.index("--casting")
        n = int(args[i + 1]) if len(args) > i + 1 and args[i + 1].isdigit() else 12
        for k, p in enumerate(build_casting(char, n), 1):
            print(f"\n--- casting {k:02d} ---\n{p}")
        return

    wanted = [a for a in args[1:] if not a.startswith("-")]
    for cell in shots["cells"]:
        if wanted and cell["id"] not in wanted:
            continue
        print(f"\n--- {cell['id']} · {cell['label']} ---")
        print(f"[функция] {cell.get('function','')}")
        print(build_cell(char, cell))


if __name__ == "__main__":
    main()
