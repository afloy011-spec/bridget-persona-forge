#!/usr/bin/env python3
"""Отбор финальных кадров и раскладка их в deliverables/ под сдачу.

  py -3 deliver.py <project_dir> --pick P1=<file> P2=<file> ...  [--part 1]
  py -3 deliver.py <project_dir> --auto [--part 1]
  py -3 deliver.py <project_dir> --list [--part 1]

Вместо `--part` можно указать `--shotlist <файл>`, как у generate.py: часть —
это имя раскадровки, а не номер из двух. Сдача такого набора ложится в
deliverables/<id>/<имя без «shotlist_»>/.

ЗАЧЕМ ОТДЕЛЬНЫЙ ШАГ. Кадров сгенерировано сорок на часть, сдаётся пять. Между
ними — отбор, и он должен быть ЗАПИСАН: какой сид выбран, из какой ячейки, под
каким именем ушёл в сдачу. Иначе через день невозможно ответить, откуда взялся
файл в презентации, и повторить его нечем.

--auto выбирает по вердикту ворот: в каждой ячейке берётся прошедший кадр с
наибольшим ЗАПАСОМ по худшим своим воротам. Это ЧЕРНОВИК отбора, а не замена
глазам: ворота ловят брак, но не ловят скуку и не смотрят на набор целиком.
Поэтому --auto ничего не сдаёт, а печатает готовую строку --pick.

Имена файлов в сдаче осмысленные (01_hero_portrait.jpg), а не P1_s1524445015:
ревьюер открывает папку, а не реестр.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (setup_console, work_dir, read_json, read_verdict,
                   verdict_coverage, write_json, ROOT, project_name, cli_opt, work_relative)
from prompts import load_project

import re


def delivery_name(cell, index):
    """Имя файла сдачи: номер по порядку + сцена ячейки.

    СТРОИТСЯ ИЗ РАСКАДРОВКИ, А НЕ ИЗ ТАБЛИЦЫ. Раньше здесь лежал словарь
    P1→01_hero_portrait … P5→05_restaurant_evening, зашитый под сцены Бриджит:
    у персонажа без корта и без собаки сдача всё равно называлась
    03_paddle_court.jpg и 04_living_room_dog.jpg, а шестая ячейка получала имя
    p6.jpg и уезжала в конец сортировки. Ячейка знает про себя всё нужное —
    delivery_name (если автор хочет назвать сам) или label.
    """
    raw = cell.get("delivery_name") or cell.get("label") or cell["id"]
    # СЛАГ ПРИМЕНЯЕТСЯ КО ВСЕМУ, включая явный delivery_name. Раньше он
    # подставлялся дословно, и "../../../pwned" писал файл ВНЕ каталога части,
    # съедая заодно префикс индекса, а кириллица уезжала прямо в имя файла —
    # оба случая вопреки обещанию этой же докстроки.
    slug = re.sub(r"[^a-z0-9]+", "_", str(raw).lower()).strip("_")
    if not slug:
        # Кириллическая метка без delivery_name даёт пустой слаг. Молча
        # откатываться к id — значит сдать «03_zz.jpg» клиенту; лучше сказать.
        print(f"  ! {cell['id']}: из «{raw}» не получается латинское имя файла "
              f"— задайте delivery_name в раскадровке", file=sys.stderr)
        slug = cell["id"].lower()
    return f"{index:02d}_{slug}"

PART_DIRS = {1: "part1_profile", 2: "part2_story"}
PART_SHOTLIST = {1: "shotlist.json", 2: "shotlist_story.json"}


# ЧАСТЬ — ЭТО ИМЯ РАСКАДРОВКИ, А НЕ НОМЕР ИЗ ДВУХ. Карты выше писались, когда
# частей было ровно две, и превращали `--part` в потолок: третья раскадровка
# (а они появляются — `shotlist_trends.json` на 20 клеток) не имела номера, и
# СДАТЬ её было нечем, хотя снять, отсудить и отобрать — уже было чем.
# generate, gates и select_set давно берут `--shotlist`; здесь то же самое,
# а `--part` оставлен псевдонимом, чтобы ранбук не переписывать.
def shotlist_of(part):
    return PART_SHOTLIST.get(part, part) if not isinstance(part, str) else part


def frames_sub(part):
    sl = shotlist_of(part)
    if sl == "shotlist.json":
        return "frames"
    return "frames_" + os.path.splitext(sl)[0].replace("shotlist_", "")


def out_sub(part):
    """Куда складывать сдачу. Имя выводится из раскадровки, если она не из
    исходных двух: `shotlist_trends.json` → `trends`."""
    if part in PART_DIRS:
        return PART_DIRS[part]
    sl = shotlist_of(part)
    return os.path.splitext(sl)[0].replace("shotlist_", "") or "set"
PART_FRAMES = {1: "frames", 2: "frames_story"}


def _ledger(project, part):
    p = os.path.join(work_dir(project, frames_sub(part)), "frames.json")
    if not os.path.exists(p):
        raise SystemExit(f"реестра нет: {p} — сначала generate.py")
    return read_json(p), p


def list_frames(project_dir, part=1):
    char, shots = load_project(project_dir, shotlist_of(part))
    project = project_name(project_dir, shots, char)
    led, _ = _ledger(project, part)
    by_cell = {}
    for e in led:
        by_cell.setdefault(e["cell"], []).append(e)
    for cid in sorted(by_cell):
        print(f"\n--- {cid} · {by_cell[cid][0]['label']} ({len(by_cell[cid])} кадров)")
        for e in by_cell[cid]:
            print(f"    {os.path.basename(e['file'])}   сид {e['seed']}")
    return by_cell


def _gate_verdict(project, part, src):
    """Вердикт ворот по конкретному кадру, если ворота вообще прогоняли."""
    p = os.path.join(work_dir(project, frames_sub(part)), "gates.json")
    if not os.path.exists(p):
        return None
    for row in read_verdict(p)[0].get("frames", []):
        if os.path.basename(row.get("file", "")) == os.path.basename(src):
            return row
    return None


def default_out(project, part=1):
    """Куда пишется сдача части, если путь не задан.

    Отдельной функцией потому, что это ОБЕЩАНИЕ («второй персонаж не
    затирает первого»), и проверять его надо у того, кто его даёт. Тест,
    который собирал этот путь у себя, оставался зелёным, когда имя
    проекта из пути убирали: он сверял свою формулу со своей же.
    """
    return os.path.join(ROOT, "deliverables", project, out_sub(part))

def auto_picks(project_dir, part=1):
    """Черновой выбор по вердикту ворот: лучший прошедший кадр каждой ячейки.

    ЭТОТ РЕЖИМ БЫЛ ОБЪЯВЛЕН В СПРАВКЕ И НЕ СУЩЕСТВОВАЛ. `--auto` печатал ровно
    то же, что и опечатка `--zzz` («нечего сдавать: укажи --pick»), то есть
    справка скрипта рекламировала поведение, которого нет. Написанное в справке
    — обещание того же веса, что и код.

    ЧЕРНОВИК, А НЕ ЗАМЕНА ГЛАЗАМ. Ворота ловят брак, но не ловят скуку и не
    смотрят на набор целиком; ранжирование здесь — «худшие ворота этого кадра
    как можно выше», а не «самый красивый». Поэтому --auto печатает готовую
    строку --pick и НЕ сдаёт сам: подтверждение остаётся ручным шагом.
    """
    char, shots = load_project(project_dir, shotlist_of(part))
    project = project_name(project_dir, shots, char)
    led, _ = _ledger(project, part)
    p = os.path.join(work_dir(project, frames_sub(part)), "gates.json")
    if not os.path.exists(p):
        raise SystemExit(f"вердикта ворот нет: {p}\n"
                         f"  --auto выбирает ПО ВЕРДИКТУ. Сначала:\n"
                         f"    py -3 scripts/gates.py {project_dir}"
                         + ("" if part == 1
                            else f" --shotlist {shotlist_of(part)}"))
    data = read_verdict(p)[0]
    gap = verdict_coverage(data)
    if gap:
        raise SystemExit(f"{gap}\n  Выбирать по частичному вердикту нельзя: "
                         f"про неизмеренные ячейки не известно ничего.")
    rows = {os.path.basename(r.get("file", "")): r for r in data.get("frames", [])}

    def rank(entry):
        """Запас кадра по ОБЯЗАТЕЛЬНЫМ воротам; чем больше, тем лучше.

        Число считает gates.py (worst_margin_required) — здесь оно только
        читается. Формула запаса живёт рядом с порогами, и переписывать её у
        потребителя значило бы завести вторую точку правды: первая редакция
        этой функции искала несуществующий ключ margin, получала -inf на всех
        кадрах и «выбирала лучший» первым попавшимся — фиктивный отбор,
        неотличимый снаружи от настоящего.

        Общий worst_margin для этого не годится: он считается и по справочным
        воротам, а identity с cohort провалены у всех кадров и дают почти
        одинаковые -1.7, то есть сортировку по константе.
        """
        r = rows.get(os.path.basename(entry["file"])) or {}
        m = r.get("worst_margin_required")
        if m is None:
            raise SystemExit(
                f"в вердикте нет worst_margin_required у "
                f"{os.path.basename(entry['file'])} — вердикт снят старой "
                f"версией gates.py. Перепрогнать ворота.")
        return m

    picks, skipped = {}, []
    by_cell = {}
    for e in led:
        by_cell.setdefault(e["cell"], []).append(e)
    for cid in sorted(by_cell):
        ok = [e for e in by_cell[cid]
              if (rows.get(os.path.basename(e["file"])) or {}).get("ships")]
        if not ok:
            skipped.append(cid)
            continue
        best = max(ok, key=rank)
        picks[cid] = best["file"]
        print(f"  {cid}  {os.path.basename(best['file'])}  "
              f"(из {len(ok)} прошедших ворота, худший запас {rank(best):.3g})")
    if skipped:
        print(f"\nячейки без единого прошедшего кадра: {', '.join(skipped)} — "
              f"их надо перегенерировать", file=sys.stderr)
    if not picks:
        raise SystemExit("ворота не пропустили ни одного кадра — сдавать нечего")
    print("\nЧЕРНОВИК. Посмотреть глазами, потом сдать этой строкой:\n"
          "  py -3 scripts/deliver.py " + str(project_dir)
          + (f" --part {part}" if part != 1 else "") + " --pick "
          + " ".join(f"{c}={os.path.basename(f)}" for c, f in sorted(picks.items())))
    return picks


def deliver(project_dir, picks, part=1, quality=95, force=False,
            partial=False, dry=False):
    """Сложить выбранные кадры в deliverables/<часть>/ и записать выбор."""
    from PIL import Image
    char, shots = load_project(project_dir, shotlist_of(part))
    project = project_name(project_dir, shots, char)
    led, _ = _ledger(project, part)
    by_file = {os.path.basename(e["file"]): e for e in led}
    cells = {c["id"]: c for c in shots["cells"]}

    # Имя проекта в пути. Без него второй персонаж молча затирал сдачу
    # первого: и selection.json, и — при совпадении id ячеек — сами JPEG.
    out_dir = default_out(project, part)

    # ---- ВСЯ ПРОВЕРКА ДО ПЕРВОЙ ЗАПИСИ НА ДИСК.
    # Первая редакция этой сверки писала JPEG и selection.json, и ТОЛЬКО потом
    # бросала SystemExit. На диске «отказ» и «--force» получались побайтово
    # одинаковыми, кадр лежал в сдаче, попадал в selection.json и оттуда в
    # презентацию; отличался только код возврата, которого при ручном запуске
    # никто не смотрит. То есть проверка была не воротами, а жалобой.
    resolved, blocked = {}, []
    for cid, src in picks.items():
        if cid not in cells:
            raise SystemExit(f"нет ячейки {cid}; есть: {sorted(cells)}")
        if not os.path.exists(src):
            cand = [e["file"] for e in led
                    if os.path.basename(e["file"]) == os.path.basename(src)]
            if not cand:
                raise SystemExit(f"кадр не найден ни на диске, ни в реестре: {src}")
            src = cand[0]
        entry = by_file.get(os.path.basename(src))
        if entry is None:
            # Правило реестра: кадр без записи — мусор. Молча положить такой в
            # сдачу значит потерять сид и промпт, то есть возможность повторить.
            raise SystemExit(f"кадр {os.path.basename(src)} отсутствует в реестре")
        # ФАЙЛ ПРОВЕРЯЕТСЯ ЗДЕСЬ, А НЕ В ЦИКЛЕ ЗАПИСИ. Ветка выше подставляет
        # путь ИЗ РЕЕСТРА, когда указанного файла нет, — и не смотрит, есть ли
        # на диске он сам. Кадры удаляют руками (это штатное «вычистить брак»),
        # реестр при этом не правится, и Image.open падал в середине цикла
        # записи: часть JPEG уже лежала в сдаче со СТАРЫМ selection.json,
        # то есть ровно то, что докстринг обещает не делать.
        if not os.path.isfile(src):
            blocked.append((cid, os.path.basename(src), "ФАЙЛА НЕТ",
                            f"реестр указывает на {src}, на диске его нет"))
        else:
            try:
                with Image.open(src) as probe:
                    probe.verify()
            except Exception as e:
                blocked.append((cid, os.path.basename(src), "НЕ ЧИТАЕТСЯ",
                                f"{type(e).__name__}: {e}"))
        verdict = _gate_verdict(project, part, src)
        if verdict is None:
            print(f"  ! {cid}: вердикта ворот нет — сначала gates.py",
                  file=sys.stderr)
            blocked.append((cid, os.path.basename(src), "НЕТ ВЕРДИКТА",
                            "gates.py по этой части не прогонялся"))
        elif not verdict.get("ships"):
            bad = ", ".join(verdict.get("missing") or verdict.get("failed") or [])
            print(f"  ! {cid}: вердикт {verdict.get('verdict')} — {bad}",
                  file=sys.stderr)
            blocked.append((cid, os.path.basename(src), verdict.get("verdict"), bad))
        resolved[cid] = (src, entry)

    if blocked and not force:
        raise SystemExit(
            "\nНЕ ПРОПУЩЕНО " + str(len(blocked)) + " из выбранных кадров:\n"
            + "\n".join(f"    {c} {f} — {v}: {b}" for c, f, v, b in blocked)
            + "\n  На диск не записано НИЧЕГО. Либо перегнать ячейку, либо "
              "сдать осознанно через --force.")

    # ПОКРЫТИЕ ЯЧЕЕК СВЕРЯЕТСЯ ДО ПЕРВОЙ ЗАПИСИ, И ЭТО ПОЧИНКА ГЛАВНОЙ
    # НЕПРАВДЫ РЕПОЗИТОРИЯ. Проверялось `for cid, src in picks.items()`, то
    # есть только то, что человек НАЗВАЛ; набор ячеек раскадровки с выбором не
    # сравнивался нигде. Поэтому часть 2 уехала тремя кадрами при пяти
    # ячейках, selection.json встал с "forced": false и пустым
    # blocked_by_gates — на диске ничто не помечало сдачу частичной, — а
    # README продолжал обещать десять фотографий. Ниже по течению никто не
    # ловит: build_deck читает selection.json как истину, qa_report берёт
    # len(frames) на веру.
    #
    # Частичная сдача остаётся возможной: она бывает осознанной. Но теперь она
    # НАЗЫВАЕТСЯ — ключом --partial и записью в selection.json.
    missing = [c["id"] for c in shots["cells"] if c["id"] not in resolved]
    if missing and not partial:
        raise SystemExit(
            "выбор не покрывает раскадровку: нет ячеек {}.\n"
            "  Сдача из {} кадров при {} ячейках — это то, из-за чего README "
            "обещал десять фотографий, а в папке лежало восемь.\n"
            "  Либо доснять и сдать целиком, либо сказать это вслух: "
            "--partial.".format(", ".join(missing), len(resolved),
                                len(shots["cells"])))

    # ЧТО БУДЕТ ПЕРЕЗАПИСАНО — ГОВОРИТСЯ ДО ЗАПИСИ, А НЕ ПОСЛЕ. Предупреждение
    # об осиротевших файлах внизу печатается, когда JPEG уже на месте, и этого
    # мало: шаг пишет прямо в отслеживаемое дерево сдачи, то есть любой пробный
    # прогон молча заменяет главный артефакт портфолио. Проверено на живом
    # репозитории: три кадра сдачи ушли под тестовые за один вызов, вернуть их
    # смог только git. У человека без git это необратимо.
    doomed = sorted(f for f in (os.listdir(out_dir) if os.path.isdir(out_dir) else [])
                    if f.lower().endswith(".jpg") and "contact_sheet" not in f.lower())
    if doomed:
        print("в папке сдачи уже лежат кадры, они будут заменены: "
              + ", ".join(doomed), file=sys.stderr)
    if dry:
        print("\nСУХОЙ ПРОГОН: проверено всё, не записано ничего.")
        for cid in sorted(resolved, key=lambda c: [x["id"] for x in shots["cells"]].index(c)
                          if c in [x["id"] for x in shots["cells"]] else 99):
            print(f"  {cid} → {os.path.basename(resolved[cid][0])}")
        return

    os.makedirs(out_dir, exist_ok=True)
    # Порядок и нумерация — из раскадровки: она и есть порядок кадров в серии.
    order = [c["id"] for c in shots["cells"]]
    chosen, staged = [], []
    for cid in sorted(resolved, key=lambda c: order.index(c) if c in order else 99):
        src, entry = resolved[cid]
        cell = cells[cid]
        name = delivery_name(cell, order.index(cid) + 1 if cid in order else 99)
        dst = os.path.join(out_dir, f"{name}.jpg")
        # ЗАПИСЬ ИДЁТ ЧЕРЕЗ ПРОМЕЖУТОЧНЫЕ ФАЙЛЫ и переезжает на место одним
        # проходом в самом конце. Проверка «всё до первой записи» защищает от
        # ИЗВЕСТНЫХ причин отказа, а от неизвестных — только это: место на
        # диске, потерянная сетевая папка, битый исходник, который прошёл
        # verify и упал на decode. Половина сданной серии рядом со старым
        # selection.json — состояние, которое не читается как поломка.
        tmp = dst + ".part"
        with Image.open(src) as im:
            # EXIF исходника переносится: если кадр уже прошёл последнюю милю,
            # в нём лежит пометка о происхождении, и терять её пересохранением
            # нельзя — «не снимать пометку о генерации» это правило проекта.
            # format задаётся явно: PIL выводит его из расширения, а у
            # промежуточного файла расширение .part, и без этого сохранение
            # падает с «unknown file extension».
            im.convert("RGB").save(tmp, format="JPEG", quality=quality,
                                   subsampling=0,
                                   exif=im.getexif().tobytes()
                                   if im.getexif() else b"")
        staged.append((tmp, dst))
        chosen.append({
            "cell": cid, "label": cell["label"], "function": cell.get("function", ""),
            "delivered_as": os.path.relpath(dst, ROOT).replace("\\", "/"),
            # ОТ РАБОЧЕГО КОРНЯ, А НЕ ОТ ДИСКА: selection.json едет в
            # репозиторий, а абсолютный путь несёт имя пользователя машины.
            "source": work_relative(src), "seed": entry["seed"],
            "prompt": entry["prompt"],
            "caption": cell.get("caption", ""), "caption_ru": cell.get("caption_ru", ""),
            # АНГЛИЙСКИЕ ПОЛЯ ЕДУТ В СДАЧУ, потому что дека читает selection.json,
            # а не раскадровку. Пока их здесь не было, build_deck.py падал на
            # русский `function` и печатал режиссёрскую заметку подписью в
            # документе, объявленном <html lang="en">.
            "function_en": cell.get("function_en", ""),
            "alt": cell.get("alt", ""),
            "nudity_level": cell.get("nudity_level", "clothed"),
            "mirror_selfie": bool(cell.get("mirror_selfie")),
            "tattoo_visible": bool(cell.get("tattoo_visible")),
            # ЗАПРОС ЯЧЕЙКИ И ФАКТ — РАЗНЫЕ ПОЛЯ. `tattoo_visible` говорит
            # «мы хотим здесь тату»; `tattoo_applied` — легла ли она. Пока
            # поле было одно, дека три раза подписывала «Manolo tattoo» на
            # кадрах без единого пикселя чернила. Композит проставит True сам;
            # по умолчанию — честное False.
            "tattoo_applied": bool(cell.get("tattoo_applied")),
            # СЦЕНА ЗАПИСЫВАЕТСЯ В СДАЧУ. Она задаёт ISO, то есть силу зерна
            # последней мили, и до сих пор человек подставлял её в шаг 10
            # руками по памяти — при том что конвейер знает её точно с шага 3.
            # Один неверный ключ делает ночной кадр гладким, как дневной, и
            # заметить это можно только глазами.
            "scene_class": entry.get("scene_class"),
            "size": entry.get("size"),
        })
        print(f"  {cid} → {os.path.basename(dst)}   (сид {entry['seed']})")

    # ВСЕ КАДРЫ ЗАПИСАЛИСЬ — только теперь они переезжают на свои имена.
    # os.replace атомарна в пределах тома; тома здесь один, потому что .part
    # лежит рядом с целью. Сорваться на середине этого цикла можно только
    # физически, а не по причине, которую можно предвидеть выше.
    for tmp, dst in staged:
        os.replace(tmp, dst)

    # Осиротевшие файлы прошлой сдачи. Частичный --pick переписывал
    # selection.json целиком, а JPEG прежних ячеек оставались на диске: в папке
    # шесть картинок, в реестре одна, и build_deck собирал деку из одной.
    keep = {os.path.basename(c["delivered_as"]) for c in chosen}
    orphans = [f for f in os.listdir(out_dir)
               if f.lower().endswith(".jpg") and f not in keep
               and "contact_sheet" not in f.lower()]
    if orphans:
        print(f"\nВ папке сдачи остались файлы прошлого прогона, не входящие "
              f"в этот выбор: {', '.join(sorted(orphans))}\n"
              f"  --pick перечисляет ВЕСЬ набор; лишнее удалить руками или "
              f"пересдать целиком.", file=sys.stderr)

    sel = os.path.join(out_dir, "selection.json")
    # forced пишется В ФАЙЛ, а не только в stderr: иначе сдача вопреки воротам
    # неотличима от чистой при любом последующем чтении, и build_deck молча
    # кладёт брак в презентацию.
    # `partial` и `missing_cells` пишутся В ФАЙЛ, зеркально к `forced`, и по
    # той же причине: без записи неполная сдача неотличима от полной при любом
    # последующем чтении. Ровно это и случилось с частью 2 — три кадра при
    # пяти ячейках, и ни одного следа в selection.json.
    write_json(sel, {"project": project, "part": part, "forced": bool(blocked),
                     "partial": bool(missing), "missing_cells": missing,
                     "frames": chosen, "blocked_by_gates": blocked})
    print(f"\n{len(chosen)} кадров в {out_dir}\nвыбор записан: {sel}")
    if blocked:
        print("\nСДАНО ВОПРЕКИ ВЕРДИКТУ ВОРОТ (--force): "
              + ", ".join(c for c, _, _, _ in blocked)
              + "\n  selection.json помечен forced=true.", file=sys.stderr)
    return chosen


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__); raise SystemExit(1)

    def opt(k, d=None):
        return cli_opt(args, k, d)

    # `--shotlist` — основной ключ, как у остальных шагов; `--part` остаётся
    # коротким псевдонимом для двух исходных частей.
    sl = opt("--shotlist")
    part = sl if sl else int(opt("--part", 1))
    if "--list" in args:
        list_frames(args[0], part); return
    if "--auto" in args:
        auto_picks(args[0], part); return

    picks = {}
    if "--pick" in args:
        for a in args[args.index("--pick") + 1:]:
            if a.startswith("-") or "=" not in a:
                break
            cid, _, f = a.partition("=")
            picks[cid] = f
    if not picks:
        raise SystemExit("нечего сдавать: укажи --pick P1=<файл> ... или --list")
    deliver(args[0], picks, part, force="--force" in args,
            partial="--partial" in args, dry="--dry" in args)


if __name__ == "__main__":
    main()
