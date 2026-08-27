#!/usr/bin/env python3
"""Кадры, снятые руками на холсте, — в реестр проекта.

  py -3 adopt_canvas.py <проект> --cell P1 [--shotlist ...] [--last 10] [--dry]

СНАЧАЛА --dry. История сервера общая и длинная: в ней лежат и вчерашние
опыты, и соседние замеры. Всухую видно поимённо, что будет принято, и можно
подобрать --last под то, что действительно снято сейчас.

ЗАЧЕМ ЭТО ВООБЩЕ НУЖНО. Холст (PERSONA_CHARACTER_FROM_REFERENCE) заканчивается
превью, и снятое живёт только во временной папке сервера. А ворота, отбор и
выдача читают РЕЕСТР: `<work_root>/<проект>/frames/frames.json`. Правило
generate.py — «кадр без записи в реестре считается мусором и в вердикт не
попадает» — относится и к ручным кадрам. Без этого моста холст был отдельным
инструментом рядом с конвейером, а не его частью: что бы на нём ни сняли, до
ворот оно не доходило.

ПОЧЕМУ НЕ SaveImage В ГРАФЕ. Так было бы проще, но машина общая, и запись в
output/ там запрещена — удалить оттуда по API нечем (см. шапку comfy_client).
Поэтому кадры забираются из /history: там лежит и сам граф, и ссылки на файлы
в temp. Ничего лишнего на сервере не остаётся.

ЧТО БЕРЁТСЯ ИЗ ГРАФА, А ЧТО ИЗ ПОЛКИ. Сид и промпт — из графа, они там есть
буква в букву. Всё остальное (метка, класс сцены, уровень раздетости, ждём ли
тату) — из клетки шотлиста по --cell: ворота судят кадр ПО ЕГО ЗАДАНИЮ, и
выдумывать задание за снявшего нельзя. Клетка `free` — для кадров вне
шотлиста; такие получают самые строгие умолчания, чтобы случайно не проехать
ворота, рассчитанные на другое.

ПОВТОРНЫЙ ЗАПУСК БЕЗОПАСЕН: в записи хранится prompt_id прогона, и уже
принятое пропускается. Иначе каждый вызов плодил бы дубли одного кадра.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import comfy_client as cc
from _util import (project_name, read_json, setup_console, work_dir,
                   write_json)

# ПАПКА ВЫЧИСЛЯЕТСЯ ИЗ ИМЕНИ РАСКАДРОВКИ, КАК ВЕЗДЕ. Здесь стояла карта из
# двух частей — {1: "frames", 2: "frames_story"}, — и это был третий способ
# сказать то же самое: generate, gates и select_set давно берут `--shotlist` и
# выводят папку из его имени. Любая третья раскадровка (а они появляются)
# просто не имела бы номера части, и мост оказался бы единственным шагом
# конвейера, который её не видит.
def frames_sub(shotlist):
    if shotlist == "shotlist.json":
        return "frames"
    return "frames_" + os.path.splitext(shotlist)[0].replace("shotlist_", "")


def sibling_shotlists(project_dir):
    """Все раскадровки проекта: дубль ищется по всем, а не по своей."""
    import glob
    return sorted(os.path.basename(p) for p in
                  glob.glob(os.path.join(project_dir, "shotlist*.json")))

# Признак холста в двух частях, и вторая важнее первой.
#
# ПЕРВАЯ — связка грунтованного энкодера с патчем модели: это ровно то, что
# делает ветку эдита эдитом, и по ней прогон отличается от чужих задач,
# крутящихся на общем сервере.
#
# ВТОРАЯ — прогон заканчивается ПРЕВЬЮ, а не сохранением. На общей машине
# писать в output/ нельзя, поэтому и холст, и наши батчи идут превью
# (comfy_client.ephemeral переписывает SaveImage). Проверка отсекает лишь
# чужой прогон, который сохраняет, — и сама по себе НЕ отличает холст от
# батча.
SIGNATURE = ("Krea2EditGroundedEncode", "Krea2EditModelPatch", "PreviewImage")
BATCH_ONLY = "SaveImage"

# ОТЛИЧАТЬ ХОЛСТ ОТ БАТЧА ПО ГРАФУ НЕЛЬЗЯ, И ЭТО ВЫЯСНИЛОСЬ ЖИВЫМ ПРОГОНОМ.
# Сначала признаком служило «холст показывает, батч сохраняет» — на синтетике
# это работало, а на сервере оказалось, что ephemeral() приводит оба к превью,
# и мост потянул в реестр все 16 кадров соседнего замера.
#
# Поэтому дубли ловятся не по происхождению, а по СОДЕРЖАНИЮ: сид плюс промпт
# однозначно задают кадр. Если такая пара в реестре уже есть, кадр снят
# конвейером и записан им же — принимать его второй раз значит дать одному
# кадру несколько голосов при отборе набора.


def _graph_of(item):
    """Граф прогона из записи истории. Формат /history менялся, поэтому оба."""
    p = item.get("prompt")
    if isinstance(p, list):
        for el in p:
            if isinstance(el, dict) and el and all(
                    isinstance(v, dict) and "class_type" in v
                    for v in el.values()):
                return el
        return {}
    return p if isinstance(p, dict) else {}


def _pick(graph, cls, key):
    """Значение виджета первой ноды класса cls. None, если её нет."""
    for node in graph.values():
        if node.get("class_type") == cls:
            v = (node.get("inputs") or {}).get(key)
            if not isinstance(v, list):     # список = связь, а не значение
                return v
    return None


def canvas_runs(history):
    """Прогоны холста, новые первыми."""
    out = []
    for pid, item in history.items():
        g = _graph_of(item)
        types = {n.get("class_type") for n in g.values()
                 if isinstance(n, dict)}
        if not all(s in types for s in SIGNATURE):
            continue
        if BATCH_ONLY in types:
            continue
        if not (item.get("outputs") or {}):
            continue
        out.append((pid, item, g))
    return out


def _cell_meta(project_dir, shotlist, cell_id):
    """Задание кадра. `free` — строгие умолчания, а не пустые."""
    if cell_id == "free":
        return {"id": "free", "label": "снято на холсте",
                "scene_class": "indoor", "nudity_level": "clothed",
                "tattoo_visible": False, "caption": "", "mirror_selfie": False}
    shots = read_json(os.path.join(project_dir, shotlist))
    for c in shots["cells"]:
        if c["id"] == cell_id:
            return c
    have = ", ".join(c["id"] for c in shots["cells"])
    raise SystemExit(f"клетки {cell_id} нет в {shotlist}; есть: {have}")


def adopt(project_dir, project, shotlist, cell_id, last, dry=False):
    out_root = work_dir(project, frames_sub(shotlist))
    ledger_path = os.path.join(out_root, "frames.json")
    ledger = read_json(ledger_path) if os.path.exists(ledger_path) else []
    seen = {e.get("prompt_id") for e in ledger if e.get("prompt_id")}
    # Реестры ВСЕХ раскадровок проекта: кадр, снятый для другой части и
    # принятый сюда, — такой же дубль.
    known = set()
    for _sl in sibling_shotlists(project_dir):
        _p = os.path.join(work_dir(project, frames_sub(_sl)), "frames.json")
        if os.path.exists(_p):
            for e in read_json(_p):
                known.add((e.get("seed"), e.get("prompt")))
    cell = _cell_meta(project_dir, shotlist, cell_id)

    hist = cc._req(f"/history?max_items={int(last)}")
    runs = canvas_runs(hist)
    if not runs:
        print("в истории сервера нет прогонов холста")
        return ledger
    fresh = [r for r in runs if r[0] not in seen]
    print(f"прогонов холста: {len(runs)}, из них новых: {len(fresh)}")
    if not fresh:
        return ledger

    os.makedirs(out_root, exist_ok=True)
    added = 0
    for pid, item, g in fresh:
        prompt = _pick(g, "Krea2EditGroundedEncode", "prompt")
        seed = _pick(g, "KSampler", "seed")
        w = _pick(g, "EmptyLatentImage", "width")
        h = _pick(g, "EmptyLatentImage", "height")
        if prompt is None or seed is None:
            print(f"  ! {pid[:8]}: в графе нет промпта или сида, пропуск")
            continue
        if (seed, prompt) in known:
            print(f"  = {pid[:8]} сид {seed}: такой кадр уже в реестре, "
                  f"снят конвейером")
            continue
        known.add((seed, prompt))
        if dry:
            print(f"  ~ {pid[:8]} сид {seed}: {str(prompt)[:60]}...")
            added += 1
            continue
        files = cc.fetch(item, out_root)
        if not files:
            print(f"  ! {pid[:8]}: сервер не отдал кадр (temp подчищен)")
            continue
        for f in files:
            ledger = [e for e in ledger if e.get("file") != f]
            ledger.append({
                "file": f, "cell": cell["id"], "label": cell.get("label", ""),
                "seed": seed, "prompt": prompt,
                "tattoo_visible": bool(cell.get("tattoo_visible")),
                "scene_class": cell.get("scene_class", "indoor"),
                "caption": cell.get("caption", ""),
                "nudity_level": cell.get("nudity_level", "clothed"),
                "mirror_selfie": bool(cell.get("mirror_selfie")),
                "size": [w, h] if w and h else None,
                "source": "edit",
                # ОТКУДА КАДР — чтобы отчёт не выдавал ручную съёмку за батч.
                "origin": "canvas", "prompt_id": pid,
                "ref": None, "ref_subject": None,
            })
            print("  →", f)
            added += 1
        write_json(ledger_path, ledger)

    if dry:
        print(f"\nвсухую: принял бы {added}")
    else:
        write_json(ledger_path, ledger)
        print(f"\nреестр: {ledger_path} (+{added}, всего {len(ledger)})")
    return ledger


def main():
    setup_console()
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("project_dir")
    ap.add_argument("--cell", required=True,
                    help="клетка шотлиста, чьё задание получат кадры, "
                         "или free")
    ap.add_argument("--shotlist", default="shotlist.json",
                    help="какая раскадровка задаёт клетку и куда писать "
                         "(как у generate.py)")
    ap.add_argument("--last", type=int, default=10,
                    help="сколько ПОСЛЕДНИХ прогонов смотреть в истории "
                         "(по умолчанию 10; сначала стоит позвать --dry)")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    adopt(a.project_dir, project_name(a.project_dir), a.shotlist, a.cell,
          a.last, a.dry)


if __name__ == "__main__":
    main()
