#!/usr/bin/env python3
"""Датасет для обучения персонажной LoRA — из ПЛОТНОГО ЯДРА пула.

  py -3 lora_dataset.py <project_dir> --trigger <слово> [--threshold auto|0.65]
                        [--min-size 8] [--max-size 20] [--min-worst <косинус>]
                        [--shotlist shotlist.json] [--part 1] [--pool produce]
                        [--out <папка>] [--md <файл.md>] [--dry]

  --pool produce  брать пул не из раскадровки generate.py, а из сетки
                  produce.py (dataset_axes.json, 63 ячейки). Подпись при этом
                  берётся из `prompt` ячейки: он описывает ровно то, что в
                  кадре меняется, а блок опознавания личности лежит отдельно
                  в axes["base"] и в подпись не идёт.

Как модуль:
  from lora_dataset import build, report, star_cluster, caption_for

ЗАЧЕМ ОТДЕЛЬНЫЙ СБОРЩИК, А НЕ «ВОЗЬМИ СДАЧУ». Сдача собрана ОТБОРОМ по одному
кадру на ячейку (select_set.py): она максимизирует худшую пару НАБОРА ИЗ РАЗНЫХ
СЦЕН, и этого хватает, чтобы человек читался как один, но не хватает, чтобы
учить на нём лицо. Обучение усредняет то, что ему дали: набор, внутри которого
худшая пара низкая, выучивает ТИПАЖ — женщину, похожую на всех пятерых сразу,
— а не конкретного человека. Числа обоих наборов печатает этот скрипт внизу
отчёта и кладёт в docs/<проект>/lora_dataset.md; в прозе их здесь нет
намеренно, это подписная ошибка репозитория (см. assets.json →
gates._identity_erratum).

КАК ИЩЕТСЯ ЯДРО. Для каждого кадра берутся его соседи с косинусом не ниже
порога — это «звезда» вокруг кадра-центра. Из сорока звёзд берётся самая
крупная. Звезда, а не клика: клика (все со всеми выше порога) — задача
NP-полная и на пуле в сорок кадров даёт горстку, а нам нужна связная группа
вокруг одного лица. Плата за это названа вслух: внутри звезды худшая пара МОЖЕТ
быть ниже порога, потому что порогом связан только центр. Поэтому худшая пара
внутри группы считается отдельно и сверяется с порогом годности — см. ниже.

ПОРОГ ПО УМОЛЧАНИЮ НЕ КОНСТАНТА, А ЛЕСТНИЦА. --threshold auto идёт сверху
вниз с шагом STEP и останавливается на первом пороге, где самая крупная звезда
набрала --min-size кадров. Размер звезды монотонно растёт при снижении порога,
поэтому первый подошедший порог — это самая ПЛОТНАЯ группа нужного размера, а
не первая попавшаяся. Вся лестница печатается: выбор порога — это торговля
«плотность против разнообразия», и решать её вслепую по одному числу нельзя.

ПОРОГ ГОДНОСТИ — ЭТО СДАЧА, А НЕ ВЫДУМАННОЕ ЧИСЛО. Датасет обязан быть НЕ
РЫХЛЕЕ уже сданного набора: если худшая пара внутри датасета ниже, чем худшая
пара сдачи, то обучение на нём даст разброс, который отбор и так уже даёт —
учить нечему. Поэтому по умолчанию порог годности считается с диска: берётся
deliverables/<проект>/<часть>/selection.json и её худшая пара. Задать своё
число можно ключом --min-worst.

ТРИ СОСТОЯНИЯ, А НЕ ДВА. Нет детектора лиц, нет сдачи и не задан --min-worst,
кадр без лица — это отказ с названной причиной, а не «собрали что было».
Датасет, собранный без проверки плотности, неотличим от проверенного, и
единственное место, где эта разница вылезет, — обученная лора через два часа
GPU.

ЧТО ПИШЕТСЯ. Папка в формате AI Toolkit: кадр и рядом одноимённый .txt с
подписью (caption_ext: txt в конфиге обучения). Подпись — триггер плюс то, что
в кадре МЕНЯЕТСЯ: кадрирование, взгляд, гардероб, сцена, свет, камера. Блок
внешности из промпта в подпись НЕ идёт намеренно: описанное словами модель
выучит на слова, а нам нужно, чтобы лицо село на триггер.
"""
import glob
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (setup_console, work_dir, read_json, write_json, ROOT,
                   project_name, cli_opt, manifest, work_resolve)
from prompts import load_project, _clean
from gates import cosine, pairwise
from identity_calibration import PART_DIRS

# Лестница порогов для --threshold auto. Шаг мельче 0.01 не имеет смысла:
# косинус ArcFace на этом материале шумит сильнее, чем на третьем знаке.
HI, LO, STEP = 0.90, 0.30, 0.01

# Поля ячейки, которые попадают в подпись. Порядок — от кадра к технике, тот
# же, что в prompts.build_cell; блоки внешности и возраста сюда не входят
# намеренно (см. докстринг). trait/label/function/notes не входят тоже: первые
# два описывают человека, вторые два написаны по-русски и в обучающую подпись
# им нельзя.
CAPTION_FIELDS = ("framing", "gaze", "wardrobe", "set", "light", "camera")

CYRILLIC = re.compile("[а-яёА-ЯЁ]")


def default_out(project):
    """Папка датасета по умолчанию — в рабочем корне, а не в репозитории.

    Named-функция, а не строка по месту: раунд 6 показал, что путь, собранный
    лямбдой в тесте, сверяется с самим собой и остаётся зелёным, когда имя
    проекта убирают из рабочего кода.
    """
    return os.path.join(work_dir(project), "lora_dataset")


def default_md(project):
    return os.path.join(ROOT, "docs", project, "lora_dataset.md")


def resolve_trigger(cli_trigger, man=None):
    """Слово-триггер. Возвращает (слово, откуда). Пусто — это отказ.

    ПОЧЕМУ НЕЛЬЗЯ ПРИДУМАТЬ ЕГО МОЛЧА. Триггер живёт в двух местах: в подписях
    датасета (здесь) и в промпте генерации (prompts._character_trigger читает
    assets.json → models.character_lora.trigger). Разойдись они — лора обучится
    на слово, которого конвейер никогда не произнесёт, и тихо не включится; а
    тихо не включившаяся лора неотличима от отсутствующей, это записано в самом
    манифесте. Поэтому слово либо задано ключом, либо уже лежит в манифесте, а
    третьего варианта нет.
    """
    if cli_trigger:
        return cli_trigger, "--trigger"
    ch = ((man or manifest())["models"].get("character_lora") or {})
    if ch.get("trigger"):
        return ch["trigger"], "assets.json → models.character_lora.trigger"
    return None, None


def cell_index(shots):
    return {c["id"]: c for c in shots.get("cells", [])}


def caption_for(cell, trigger, entry=None):
    """Подпись кадра: триггер + то, что в кадре меняется.

    Готовая подпись из реестра (поле caption) имеет приоритет: если генерация
    когда-нибудь начнёт её заполнять, собранная здесь версия обязана уступить,
    иначе у одного кадра появятся две правды.

    Склейка — тем же _clean, что и промпт: он выбрасывает пустые поля и
    повторы. Своя склейка через ", ".join(…) на пустом поле light даёт двойную
    запятую, а обучение таких мелочей не прощает — они попадают в токены.
    """
    ready = (entry or {}).get("caption")
    body = ready.strip() if isinstance(ready, str) and ready.strip() else \
        _clean([cell.get(f, "") for f in CAPTION_FIELDS])
    # КРУПНОСТЬ ДОПИСЫВАЕТСЯ, ЕСЛИ ЕЁ НЕТ В ТЕКСТЕ. В сетке датасета 29 из 63
    # промптов не называют план ни одним словом — там сказано «she leans against
    # the doorframe», и крупность известна только из поля plan. Неназванная
    # крупность становится свойством персонажа: лора выучит, что этого человека
    # снимают по пояс, и на «в полный рост» отдаст поясной кадр.
    plan_words = {"portrait": "a close head-and-shoulders portrait",
                  "bust": "a chest-up shot", "half": "a waist-up shot",
                  "full": "a full-length shot"}
    plan = (entry or {}).get("plan") or cell.get("plan")
    hint = plan_words.get(plan)
    if hint and not any(w in body.lower() for w in
                        ("head and shoulders", "head-and-shoulders", "chest-up",
                         "waist-up", "full-length", "full length",
                         "three-quarter", "close-up", "macro")):
        body = _clean([hint, body])
    text = _clean([trigger, body])
    bad = CYRILLIC.search(text)
    if bad:
        # Кириллица в подписи — это чей-то русский label или notes, доехавший
        # до обучающего текста. Токенизатор её проглотит, и лора выучит
        # мусорное слово, которое в промпте никто не напишет.
        raise SystemExit(f"кириллица в подписи ячейки {cell.get('id')}: "
                         f"{text[max(0, bad.start() - 30):bad.start() + 30]!r}\n"
                         f"  подпись собирается из полей {CAPTION_FIELDS} — "
                         f"они обязаны быть английскими")
    return text


def embeddings(paths):
    """{путь: вектор} и список (путь, причина) для тех, где лица нет.

    Причина возвращается наружу, а не печатается: кадр без лица — это НЕ
    измерено, и вердикт о том, можно ли собирать датасет без него, принимает
    вызывающий, а не эта функция. Вектор — обычный список float, без numpy:
    вся арифметика ядра ниже — стдлиб, и модуль обязан импортироваться там, где
    метрик не поставили.
    """
    from metrics.faces import detect
    from metrics.verdict import PASS
    vecs, misses = {}, []
    for p in paths:
        res = detect(p)
        emb = res.get("embedding") if res.get("state") == PASS else None
        if emb:
            vecs[p] = [float(x) for x in emb]
        else:
            misses.append((p, res.get("note") or "лицо не найдено"))
    return vecs, misses


def star_cluster(vecs, threshold, mat=None):
    """Самая крупная «звезда»: (центр, список кадров) при данном пороге.

    Центр входит в свою звезду всегда — косинус к самому себе равен единице, но
    полагаться на это нельзя: вектор с нулевой нормой дал бы None, и центр
    выпал бы из собственной группы, а размер группы стал бы на единицу меньше
    молча.

    Ничьи разрешаются по имени центра, иначе одна и та же лестница на одном и
    том же пуле выдаёт разный порог от запуска к запуску — на словаре из сорока
    путей порядок обхода стабилен, но зависеть от этого нельзя.
    """
    names = sorted(vecs)
    mat = matrix(vecs) if mat is None else mat
    best = (0, "", [])
    for centre in names:
        near = [n for n in names
                if n == centre or _pair(mat, centre, n) >= threshold]
        if len(near) > best[0]:
            best = (len(near), centre, near)
    return best[1], best[2]


def _cos(a, b):
    """Косинус, у которого «не с чем сравнивать» — это минус бесконечность.

    gates.cosine на пустом или разноразмерном векторе отдаёт None, а None в
    сравнении с числом на python 3 бросает TypeError изнутри генератора
    списка — то есть падает не там, где ошибка. Здесь такой кадр просто не
    попадает ни в одну звезду.
    """
    c = cosine(a, b)
    return float("-inf") if c is None else c


def _norm(path):
    """Ключ пути для сверки списков, пришедших из РАЗНЫХ файлов.

    Реестр пишет кадр как 'D:/…work\\bridget\\frames\\P1\\x.png', а сдача тот
    же кадр как 'D:/…work/bridget/frames/P1/x.png' — обе строки настоящие, обе
    указывают на один файл, и словарь по сырой строке их не сводит. Порог
    годности при этом не падает, а МОЛЧА становится незамеренным: «в сдаче
    меньше двух кадров с лицом», хотя лица на месте.
    """
    return os.path.normcase(os.path.abspath(path))


def matrix(vecs):
    """Все попарные косинусы ОДИН раз: {(a, b): косинус}, a < b.

    Лестница щупает шесть десятков порогов, и каждый порог перебирает все
    сорок звёзд — без общей матрицы одни и те же полсотни тысяч косинусов
    считались бы заново на каждой ступени. Считается сразу, потому что порядок
    кадров на всех ступенях один и тот же.
    """
    names = sorted(vecs)
    return {(a, b): _cos(vecs[a], vecs[b])
            for i, a in enumerate(names) for b in names[i + 1:]}


def _pair(mat, a, b):
    return 1.0 if a == b else mat[(a, b) if a < b else (b, a)]


def _worst(mat, members):
    """Худшая пара внутри группы. None, если пар нет."""
    pairs = [_pair(mat, a, b) for i, a in enumerate(sorted(members))
             for b in sorted(members)[i + 1:]]
    return min(pairs) if pairs else None


def ladder(vecs, max_size, hi=HI, lo=LO, step=STEP, mat=None,
           entries=None, floors=None):
    """Все ступени сверху вниз: [{threshold, centre, members, n, worst}, …].

    ЛЕСТНИЦА ПРОХОДИТСЯ ЦЕЛИКОМ, А НЕ ДО ПЕРВОЙ ПОДХОДЯЩЕЙ СТУПЕНИ. Первая
    редакция останавливалась на первом пороге, набравшем нужный размер, — по
    рассуждению «размер звезды монотонно растёт, значит первый подходящий порог
    даёт самую плотную группу». Рассуждение неверно, и это видно в таблице,
    которую печатает сам скрипт: соседние ступени дают группы ОДНОГО размера с
    разной худшей парой внутри, потому что порогом связан только центр звезды, а
    не пары внутри неё. Более высокий порог при равном размере может дать группу
    РЫХЛЕЕ. Плотность группы — то самое, что судят ворота годности, — поэтому
    считается на каждой ступени и выбирается по ней, а не по порогу.
    """
    mat = matrix(vecs) if mat is None else mat
    rows, t = [], hi
    while t >= lo - 1e-9:
        th = round(t, 4)
        centre, members = star_cluster(vecs, th, mat)
        members = trim(vecs, centre, members, max_size, mat,
                        entries, floors)
        rows.append({"threshold": th, "centre": centre, "members": members,
                     "n": len(members), "worst": _worst(mat, members)})
        t -= step
    return rows


def choose(rows, min_size, max_size):
    """Ступень с самой ПЛОТНОЙ группой в разрешённом размере. (строка, почему).

    Порядок предпочтений: худшая пара внутри → размер группы → порог. Первым
    именно то, что потом судят ворота годности; размер вторым, потому что при
    равной плотности больше кадров лучше для обучения; порог последним, как
    признак, не имеющий собственной ценности.

    Ни одна ступень не попала в размер — берётся самая крупная группа, какая
    вообще есть. Это не молчаливая замена критерия: отчёт печатает, что размер
    не набрался, а ворота годности всё равно судят результат.
    """
    fit = [r for r in rows if min_size <= r["n"] <= max_size]
    if fit:
        best = max(fit, key=lambda r: (r["worst"] if r["worst"] is not None
                                       else float("-inf"),
                                       r["n"], r["threshold"]))
        return best, f"самая плотная группа размера {min_size}-{max_size}"
    best = max(rows, key=lambda r: (r["n"], r["threshold"]))
    return best, (f"ни одна ступень не дала {min_size}-{max_size} кадров — "
                  f"взята самая крупная группа")


def trim(vecs, centre, members, max_size, mat=None, entries=None, floors=None):
    """Обрезать группу до max_size кадров. Ближайшие к центру, но с полами.

    Обрезка, а не отказ: группа крупнее заказанной — это удача пула, а не
    ошибка, и терять её из-за верхней границы глупо. Ближайшие к центру, потому
    что центр — единственный кадр, которым группа связана вся целиком.

    ПОЛЫ ПО ПЛАНАМ — ЭТО ЗАЩИТА ОТ ЧЕСТНОГО, НО ВРЕДНОГО ОТБОРА. Косинус растёт
    с крупностью лица (медианы по планам: портрет 0.710, погрудный 0.686, по
    пояс 0.651, в рост 0.615), поэтому «взять ближайших к центру» систематически
    выбрасывает ростовые кадры и горизонтали. На первой сборке вышло
    portrait 10 / bust 11 / half 21 / full 8 — 84% кадров крупнее пояса. Лора,
    не видевшая мелкое лицо, на ростовом плане рисует чужого; не видевшая
    горизонталь — заваливает композицию.
    Поэтому сначала добираются полы (минимум кадров каждого вида, лучшие по
    близости к центру), и только остаток заполняется общим порядком.
    """
    if len(members) <= max_size:
        return list(members)
    mat = matrix(vecs) if mat is None else mat
    ranked = sorted(members, key=lambda n: (-_pair(mat, centre, n), n))
    if not floors or not entries:
        return sorted(ranked[:max_size])

    def kind(p):
        e = entries.get(p) or {}
        return e.get("plan"), ("wide" if (e.get("w") or 0) > (e.get("h") or 1)
                               else "tall")

    picked, used = [], set()
    for key, need in floors.items():
        got = 0
        for p in ranked:
            if p in used or got >= need:
                continue
            plan, orient = kind(p)
            if key == plan or key == orient:
                picked.append(p)
                used.add(p)
                got += 1
    for p in ranked:
        if len(picked) >= max_size:
            break
        if p not in used:
            picked.append(p)
            used.add(p)
    return sorted(picked[:max_size])


def composition(vecs, members, entries):
    """Состав группы числами: сколько кадров, из каких ячеек, худшая пара."""
    stats = pairwise([(p, vecs[p]) for p in members])
    cells = {}
    for p in members:
        cells[entries[p].get("cell")] = cells.get(entries[p].get("cell"), 0) + 1
    return {"n": len(members),
            "cells": dict(sorted(cells.items(), key=lambda kv: str(kv[0]))),
            "worst_pair": stats["min"], "mean_pair": stats["mean"],
            "worst_pair_files": stats["worst_pair"], "pairs": stats["pairs"]}


def delivery_worst_pair(project, part, vec_of):
    """Худшая пара СДАННОГО набора — порог годности по умолчанию.

    Считается по тем же исходникам пула (frames[].source), а не по jpg сдачи:
    сдаточный файл прошёл последнюю милю (кроп, грейд, EXIF), и его эмбеддинг —
    это уже другое число. Сравнивать датасет со сдачей можно только на одном и
    том же материале.

    Возвращает (значение|None, путь к selection.json, причина отказа|None).
    """
    path = os.path.join(ROOT, "deliverables", project, PART_DIRS.get(part, ""),
                        "selection.json")
    if not os.path.exists(path):
        return None, path, f"сдачи нет: {path}"
    sel = read_json(path)
    rows = sel.get("frames", sel) if isinstance(sel, dict) else sel
    items, missing = [], []
    for r in rows:
        src = work_resolve(r.get("source"))
        v = vec_of(src) if src else None
        (items.append((src, v)) if v else missing.append(r.get("cell")))
    stats = pairwise(items)
    if stats["min"] is None:
        return None, path, (f"в сдаче меньше двух кадров с лицом "
                            f"(не нашлись в пуле: {missing or '—'})")
    return stats["min"], path, None


def _fitness(worst, floor):
    """PASS / FAIL / NOT_MEASURED по худшей паре и порогу годности.

    ТРИ СОСТОЯНИЯ, А НЕ ДВА, И ИМЕННО ЗДЕСЬ. Группа из одного кадра пар не
    имеет, худшая пара у неё None — и двузначная проверка (worst >= floor)
    записала бы такую группу в FAIL, то есть в «плотность измерена и плоха».
    Это разные вещи: FAIL чинится другим порогом, NOT_MEASURED — другим пулом
    или зависимостью, и подменять второе первым значит посылать человека
    крутить ручку, которая ни на что не влияет.
    """
    if floor is None:
        return "NOT_MEASURED"
    if worst is None:
        return "NOT_MEASURED"
    return "PASS" if worst >= floor else "FAIL"


def produce_pool(project_dir, project):
    """Реестр и ячейки из пула produce.py, а не из раскадровки generate.py.

    ЗАЧЕМ ВТОРОЙ ИСТОЧНИК. Сборщик писался под раскадровку из пяти-шести
    ячеек, где подпись собирается из полей framing/gaze/wardrobe/…, и под
    датасет в 8-20 кадров. Пул, из которого учится персонажная лора, снят
    другим инструментом: produce.py гоняет сетку dataset_axes.json на 63
    ячейки, и у ячейки там один цельный `prompt` вместо полей.

    Подпись при этом собирается ПРАВИЛЬНО и тем же правилом: `prompt` ячейки
    описывает ровно то, что в кадре МЕНЯЕТСЯ (кадрирование, поза, свет, фон,
    гардероб), а блок опознавания личности лежит отдельно в axes["base"] и в
    подпись не попадает. Это то же разделение, ради которого заведены
    CAPTION_FIELDS, только сделанное на съёмке, а не на сборке. Поэтому
    подпись кладётся в поле `caption` записи — caption_for отдаёт готовой
    подписи приоритет.
    """
    from edit_dataset import load_axes
    # ВСЕ файлы осей проекта, а не только основной. Пул снимался двумя сетками:
    # dataset_axes.json (63 ячейки датасета) и task_axes.json (10 ячеек сдачи),
    # и кадры обеих лежат в одних и тех же plan*.json. Читать одну сетку
    # значило бы объявить половину пула «снятой по чужой раскадровке» и
    # отказаться собирать датасет — что и произошло с первой редакцией.
    cells = {}
    for path in sorted(glob.glob(os.path.join(project_dir, "*axes*.json"))):
        for c in load_axes(project_dir, path)["cells"]:
            cells.setdefault(c["id"], c)
    entries, seen, gone, total = {}, set(), [], 0
    for p in sorted(glob.glob(os.path.join(work_dir(project, "produce"),
                                           "plan*.json"))):
        for it in read_json(p).get("items", []):
            f = it.get("file")
            if not f or f in seen:
                continue
            seen.add(f)
            total += 1
            if not os.path.exists(f):
                gone.append(f)
                continue
            cell = cells.get(it.get("cell"))
            entries[f] = {
                "file": f, "cell": it.get("cell"), "seed": it.get("seed"),
                "plan": it.get("plan") or (cell or {}).get("plan"),
                # Размер кадра нужен полам разнообразия: горизонталь от
                # вертикали отличается только им, а в первой сборке горизонталей
                # оказалось 2 из 50.
                "w": (cell or {}).get("w"), "h": (cell or {}).get("h"),
                "caption": (cell or {}).get("prompt", ""),
            }
    return entries, cells, gone, total


REF_FLOOR = 0.55
# ПОЛЫ РАЗНООБРАЗИЯ. Косинус растёт с крупностью лица, поэтому честный отбор
# «ближайших к центру» систематически выбрасывает ростовые кадры и горизонтали:
# первая сборка дала portrait 10 / bust 11 / half 21 / full 8, то есть 84%
# кадров крупнее пояса и всего 2 горизонтали из 50. Лора, не видевшая мелкое
# лицо, на ростовом плане рисует чужого; не видевшая горизонталь — заваливает
# композицию. Числа выбраны по составу сетки: в ней 16 ростовых ячеек и 8
# горизонтальных, значит требовать 12 и 6 можно, не выскребая пул досуха.
# ЧИСЛА ЗАМЕРЕНЫ СВОДОМ, А НЕ ВЗЯТЫ ИЗ СОСТАВА СЕТКИ. Цена полов в худшей паре
# набора: 6/4 — 0.512 (бесплатно, столько отбор берёт и сам), 8/5 — 0.492,
# 10/5 — 0.492, 12/6 — 0.467. Первая догадка была «в сетке 16 ростовых ячеек,
# значит можно просить 12» — свод показал, что это самая дорогая точка и что
# после 10 плата растёт скачком.
DIVERSITY_FLOORS = {"full": 8, "wide": 5}


def by_reference(vecs, ref_face, floor=REF_FLOOR):
    """Оставить кадры, чей косинус К ЭТАЛОНУ не ниже пола. (оставшиеся, отсев).

    ПОЧЕМУ ЭТОТ ПОЛ ВАЖНЕЕ ПОПАРНОЙ ПЛОТНОСТИ, ХОТЯ СБОРЩИК ПОСТРОЕН НА НЕЙ.
    Замер отрицательного класса проекта — 15 РАЗНЫХ женщин из кастинга, снятых
    по одному описанию персонажа: попарный косинус между ними медиана 0.588,
    до 0.736. Наш отобранный набор даёт худшую пару 0.570 и среднюю 0.690, то
    есть ПОПАДАЕТ В ТУ ЖЕ ПОЛОСУ. Значит попарная плотность НЕ отличает «один
    человек» от «пятьдесят разных женщин одного типажа»: она мерит типаж.
    Отличает только косинус к эталону — те же 15 женщин дают к нему медиану
    0.245 и максимум 0.316, а наш пул 0.656. Разрыв в два с половиной раза.

    Отсюда пол 0.55: он вдвое выше максимума отрицательного класса (0.316) и
    ниже медианы пула (0.656), то есть режет чужих и не режет своих.
    Попарная плотность остаётся вторым ситом — она ловит уже другое: разброс
    ВНУТРИ своих.
    """
    e_ref = embeddings([ref_face])[0].get(ref_face)
    if e_ref is None:
        raise SystemExit(
            f"на эталоне {ref_face} лица нет — проверять сходство не с чем")
    keep, drop = {}, {}
    for p, v in vecs.items():
        c = _cos(v, e_ref)
        (keep if c >= floor else drop)[p] = v if c >= floor else round(c, 4)
    return keep, {p: f"косинус к эталону {c} < {floor}" for p, c in drop.items()}


CORE_K = 12
CORE_PLANS = ("portrait", "bust")
COHORT_Z = -1.0


def identity_core(vecs, entries, e_ref, k=CORE_K, plans=CORE_PLANS):
    """Ядро личности: усреднённый эмбеддинг k лучших крупных планов.

    ПОЧЕМУ НЕ ОДНА ФОТОГРАФИЯ. Эталон — один снимок, и в нём есть свой шум:
    конкретный поворот головы, конкретный свет, конкретный кадр. Ранжируя по
    нему, мы тащим этот шум в отбор. Ядро из двенадцати лучших крупных планов
    его усредняет.
    Замер на этом пуле при одинаковых квотах: отбор по ядру даёт 5-й процентиль
    пар 0.542 против 0.511 у отбора по эталону, когорту min 0.524 против 0.465,
    разброс вокруг центра 0.046 против 0.054. Ранжирование при этом почти то же
    (корреляция +0.92) — ядро не меняет решение, оно убирает дрожание.

    Крупные планы, потому что у них лицо занимает 135-161 px межзрачкового и
    все признаки опознавания живы; у ростовых 72 px, и они внесли бы в ядро
    силуэт вместо лица.

    ШКАЛА У ЯДРА ДРУГАЯ И С ЭТАЛОННОЙ НЕ СРАВНИМА: медианы по ядру
    portrait 0.832 / bust 0.797 / half 0.763 / full 0.672 против
    0.710 / 0.686 / 0.651 / 0.615 по эталону. Пороги, снятые на одной шкале,
    на другой означают другое.
    """
    big = [p for p in vecs
           if (entries.get(p) or {}).get("plan") in plans]
    if len(big) < 3:
        return None
    top = sorted(big, key=lambda p: -_cos(vecs[p], e_ref))[:k]
    n = len(vecs[top[0]])
    mean = [sum(vecs[p][i] for p in top) / len(top) for i in range(n)]
    norm = sum(x * x for x in mean) ** 0.5
    return [x / norm for x in mean] if norm else None


def drop_outliers(vecs, entries, z=COHORT_Z):
    """Отсев по КОГОРТЕ ВНУТРИ ПЛАНА, а не кластеризацией. (оставшиеся, отсев).

    Для кадра считается средний косинус ко всем остальным кандидатам ТОГО ЖЕ
    плана, затем z-оценка внутри плана. Внутри плана — потому что планы живут
    на разных уровнях: у ростовых когорта всегда ниже, и общий порог выкосил бы
    их целиком, а не выбросы.

    Эта колонка называет виновника поимённо, а не сообщает «набор рыхлый», и
    именно поэтому она стоит здесь, а не в отчёте: кадр, который тянет набор,
    надо убрать, а не описать.
    """
    by = {}
    for p in vecs:
        by.setdefault((entries.get(p) or {}).get("plan") or "half", []).append(p)
    keep, drop = {}, {}
    for plan, paths in by.items():
        if len(paths) < 4:
            keep.update({p: vecs[p] for p in paths})
            continue
        coh = {p: sum(_cos(vecs[p], vecs[q]) for q in paths if q != p)
               / (len(paths) - 1) for p in paths}
        vals = list(coh.values())
        mu = sum(vals) / len(vals)
        sd = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5 or 1e-9
        for p in paths:
            if (coh[p] - mu) / sd < z:
                drop[p] = (f"выброс плана {plan}: когорта {coh[p]:.3f} при "
                           f"средней {mu:.3f} (z {(coh[p] - mu) / sd:.2f})")
            else:
                keep[p] = vecs[p]
    return keep, drop


def one_per_cell(vecs, entries, cap=1, e_ref=None):
    """Не более cap кадров одной ячейки. (оставшиеся, отсев).

    ЗАМЕР, А НЕ ВКУС. Повторы одной ячейки — это тот же свет, тот же фон, тот
    же гардероб и та же поза при другом сиде. Корреляция яркости 16x16 у таких
    пар 0.83-0.95 при медиане 0.029 по всему пулу. Лора считает свойством
    персонажа именно то, что повторяется, поэтому второй кадр ячейки добавляет
    вес обстоятельству съёмки, а не знание о человеке.
    Из повторов остаётся ближайший к эталону, а при отсутствии эталона —
    первый по имени: выбор обязан быть определённым, иначе состав датасета
    меняется от прогона к прогону.
    """
    by = {}
    for p in sorted(vecs):
        by.setdefault((entries.get(p) or {}).get("cell"), []).append(p)
    keep, drop = {}, {}
    for cell, paths in by.items():
        if e_ref is not None:
            paths = sorted(paths, key=lambda p: -_cos(vecs[p], e_ref))
        for i, p in enumerate(paths):
            if i < cap:
                keep[p] = vecs[p]
            else:
                drop[p] = f"повтор ячейки {cell} (оставлено {cap})"
    return keep, drop


def build(project_dir, trigger=None, shotlist="shotlist.json", threshold=None,
          min_size=8, max_size=20, min_worst=None, part=1, out=None, md=None,
          dry=False, pool="shotlist", ref_face=None, ref_floor=REF_FLOOR,
          per_cell=0, floors=None):
    """Собрать датасет. Возвращает словарь отчёта; при отказе бросает SystemExit."""
    char, shots = load_project(project_dir, shotlist)
    project = project_name(project_dir, shots, char)
    trigger, trigger_from = resolve_trigger(trigger)
    if not trigger:
        raise SystemExit(
            "не задан триггер обучения.\n"
            "  Передайте --trigger <слово> ИЛИ впишите его в assets.json →\n"
            "  models.character_lora.trigger. Одно и то же слово обязано\n"
            "  стоять в подписях датасета и в промпте генерации, иначе лора\n"
            "  обучится на слово, которого конвейер не произносит, и тихо не\n"
            "  включится.")

    if pool == "produce":
        entries, cells, gone, n_registered = produce_pool(project_dir, project)
        ledger_path = os.path.join(work_dir(project, "produce"), "plan*.json")
        ledger = [None] * n_registered
        if not entries:
            raise SystemExit(
                f"в {ledger_path} нет ни одного кадра на диске.\n"
                f"  Сначала снимите пул: py -3 produce.py {project_dir} --ref …")
    else:
        sub = "frames" if shotlist == "shotlist.json" else \
            "frames_" + os.path.splitext(shotlist)[0].replace("shotlist_", "")
        ledger_path = os.path.join(work_dir(project, sub), "frames.json")
        if not os.path.exists(ledger_path):
            raise SystemExit(f"реестра нет: {ledger_path}\n"
                             f"сначала py -3 generate.py {project_dir}"
                             + ("" if sub == "frames"
                                else f" --shotlist {shotlist}"))
        ledger = read_json(ledger_path)
        entries = {e["file"]: e for e in ledger if os.path.exists(e["file"])}
        gone = [e["file"] for e in ledger if e["file"] not in entries]
        cells = cell_index(shots)
    # Подписи собираются ДО всякого счёта: ячейка реестра, которой нет в
    # раскадровке, — это рассинхрон, и узнать о нём надо до минуты работы
    # детектора, а не после.
    unknown = sorted({e.get("cell") for e in entries.values()} - set(cells))
    if unknown:
        raise SystemExit(
            f"в реестре есть ячейки, которых нет в {shotlist}: {unknown}\n"
            f"  подпись кадра собирается из полей ячейки — собрать её нечем.\n"
            f"  Похоже, реестр снят по другой раскадровке.")

    vecs, misses = embeddings(sorted(entries))
    if not vecs:
        # Ни одного вектора — это НЕ «пул пустой», это чаще всего отсутствие
        # insightface. Собрать датасет всё равно можно было бы, и он выглядел
        # бы как настоящий: именно такой молчаливый зелёный три состояния и
        # запрещают.
        why = misses[0][1] if misses else "кадров нет"
        raise SystemExit(f"ни у одного кадра не снят эмбеддинг ({why}).\n"
                         f"  Плотность ядра проверить нечем, а датасет без "
                         f"этой проверки собирать нельзя.\n"
                         f"  py -3 -m pip install insightface onnxruntime")

    dropped, core = {}, None
    if ref_face:
        e_ref = embeddings([ref_face])[0].get(ref_face)
        if e_ref is None:
            raise SystemExit(f"на эталоне {ref_face} лица нет")
        vecs, dropped = by_reference(vecs, ref_face, ref_floor)
        print(f"пол по референсу {ref_floor}: осталось {len(vecs)} из "
              f"{len(vecs) + len(dropped)}")
        # ЯДРО СТРОИТСЯ ПОСЛЕ ПОЛА, А НЕ ДО. Ядро — это среднее лучших своих;
        # усреднять до отсева значит впустить в него чужих.
        core = identity_core(vecs, entries, e_ref)
        if core is not None:
            print(f"ядро личности: {CORE_K} лучших крупных планов, "
                  f"косинус ядра к эталону {_cos(core, e_ref):.3f}")
        # Имя НЕ `out`: так называется параметр папки датасета, и локальная
        # переменная его затеняла — сборка падала на записи пути.
        vecs, outliers = drop_outliers(vecs, entries)
        dropped.update(outliers)
        if outliers:
            print(f"отсев выбросов по когорте: убрано {len(outliers)} "
                  f"({', '.join(sorted(os.path.basename(p)[:8] for p in outliers))})")
    if per_cell:
        vecs, dup = one_per_cell(vecs, entries, per_cell, core or (
            ref_face and embeddings([ref_face])[0].get(ref_face)))
        dropped.update(dup)
        print(f"не более {per_cell} кадр(ов) на ячейку: осталось {len(vecs)}")
    if len(vecs) < min_size:
        raise SystemExit(
            f"после отсева осталось {len(vecs)} кадров, а заказано {min_size}.\n"
            f"  Снимите пул шире (produce.py) или опустите --ref-floor.")

    mat = matrix(vecs)
    if threshold is None:
        rows = ladder(vecs, max_size, mat=mat, entries=entries,
                      floors=floors)
        chosen, why_chosen = choose(rows, min_size, max_size)
    else:
        rows = ladder(vecs, max_size, hi=threshold, lo=threshold,
                      mat=mat, entries=entries, floors=floors)
        chosen, why_chosen = rows[0], "порог задан ключом"
    centre, members = chosen["centre"], chosen["members"]
    comp = composition(vecs, members, entries)

    by_norm = {_norm(p): v for p, v in vecs.items()}
    floor, floor_src, floor_why = (
        (min_worst, "--min-worst", None) if min_worst is not None
        else delivery_worst_pair(project, part,
                                 lambda p: by_norm.get(_norm(p))))

    res = {
        "project": project, "shotlist": shotlist, "registry": ledger_path,
        "trigger": trigger, "trigger_from": trigger_from,
        "threshold": chosen["threshold"], "threshold_why": why_chosen,
        "threshold_mode": "auto" if threshold is None else "задан ключом",
        "min_size": min_size, "max_size": max_size,
        "centre": centre, "frames": members,
        "pool": {"registered": len(ledger), "on_disk": len(entries),
                 "with_face": len(vecs), "missing_files": gone,
                 "without_face": [[p, w] for p, w in misses]},
        "composition": comp,
        "single_cell": len(comp["cells"]) == 1,
        "min_size_reached": len(members) >= min_size,
        "fitness": {"floor": floor, "floor_from": floor_src,
                    "floor_why": floor_why,
                    "state": _fitness(comp["worst_pair"], floor)},
        "ladder": [{"threshold": r["threshold"], "n": r["n"],
                    "worst": None if r["worst"] is None else round(r["worst"], 4),
                    "centre": os.path.basename(r["centre"])} for r in rows],
        "out": os.path.abspath(out or default_out(project)),
        "md": os.path.abspath(md or default_md(project)),
        "dry": dry,
        "captions": {},
    }
    for p in members:
        res["captions"][p] = caption_for(cells[entries[p]["cell"]], trigger,
                                         entries[p])

    if res["fitness"]["state"] != "PASS":
        # ОТКАЗ, А НЕ ПРЕДУПРЕЖДЕНИЕ. Отчёт при этом уже посчитан и печатается
        # вызывающим: человеку нужен не «нельзя», а «нельзя, потому что вот
        # это число против вот того, вот лестница, вот какую ручку крутить».
        res["refused"] = (
            f"худшая пара внутри группы {_num(comp['worst_pair'])} "
            f"< порога годности {_num(floor)}"
            if res["fitness"]["state"] == "FAIL" else
            "плотность не измерена: "
            + (floor_why or f"в группе {comp['n']} кадр(ов) — пары нет")
            + "\n  Датасет обязан быть не рыхлее сдачи, а сравнить не с чем.\n"
              "  Задайте порог явно: --min-worst <косинус>")
        return res

    if not dry:
        _write(res)
    return res


def _stale(out):
    """Файлы прошлого прогона в папке датасета: (список, чужие ли).

    ЗАЧЕМ. Второй прогон с другим порогом кладёт в ту же папку ДРУГОЙ набор
    кадров, а старые остаются рядом — и обучение молча идёт по объединению
    двух наборов, то есть ровно по тому рыхлому пулу, от которого весь этот
    скрипт и защищает. Свой прошлый прогон опознаётся по dataset.json, который
    мы сами и пишем; всё остальное в папке — чужое, и стирать его нельзя.
    """
    if not os.path.isdir(out):
        return [], False
    here = sorted(f for f in os.listdir(out) if f != "dataset.json")
    if not here:
        return [], False
    marker = os.path.join(out, "dataset.json")
    if not os.path.exists(marker):
        return here, True
    old = read_json(marker).get("files") or []
    return here, bool(set(here) - set(old))


def _write(res):
    out = res["out"]
    here, alien = _stale(out)
    if alien:
        raise SystemExit(
            f"в папке датасета лежит чужое: {out}\n"
            f"  {', '.join(here[:6])}{' …' if len(here) > 6 else ''}\n"
            f"  Прошлый прогон этого скрипта опознаётся по dataset.json и "
            f"стирается сам;\n  чужие файлы — нет. Уберите папку или задайте "
            f"другую ключом --out.")
    for f in here:
        os.remove(os.path.join(out, f))
    os.makedirs(out, exist_ok=True)

    files = []
    for src in res["frames"]:
        name = os.path.splitext(os.path.basename(src))[0]
        img = name + os.path.splitext(src)[1]
        shutil.copyfile(src, os.path.join(out, img))
        with open(os.path.join(out, name + ".txt"), "w",
                  encoding="utf-8") as fh:
            fh.write(res["captions"][src] + "\n")
        files += [img, name + ".txt"]
    res["files"] = files
    write_json(os.path.join(out, "dataset.json"), res)

    lines = report(res, quiet=True)
    os.makedirs(os.path.dirname(res["md"]), exist_ok=True)
    with open(res["md"], "w", encoding="utf-8") as fh:
        fh.write(f"# Датасет персонажной LoRA: {res['project']}\n\n"
                 f"Пишет `scripts/lora_dataset.py`. Чисел в прозе нет — они "
                 f"здесь.\n\n```\n" + "\n".join(lines) + "\n```\n")


def _num(v, nd=4):
    return "—" if v is None else f"{v:.{nd}f}"


def report(res, quiet=False):
    """Печатает отчёт И возвращает его построчно.

    Возвращает потому, что ровно эти строки уходят в docs/<проект>/
    lora_dataset.md: «в файле лежит то же, что на экране» держится одной
    переменной, а не обещанием. Вторая копия формул в записывающем коде
    разошлась бы с печатью на первой же правке.
    """
    c, p, f = res["composition"], res["pool"], res["fitness"]
    out = [
        f"проект {res['project']} · раскадровка {res['shotlist']}",
        f"пул: в реестре {p['registered']}, на диске {p['on_disk']}, "
        f"с лицом {p['with_face']}",
    ]
    if p["missing_files"]:
        out.append(f"  реестр обещал, а на диске нет: {len(p['missing_files'])}")
    for path, why in p["without_face"]:
        out.append(f"  лица нет, вне ядра: {os.path.basename(path)} — {why}")

    out.append("")
    out.append(f"{'порог':>7} {'кадров':>7} {'худшая':>8}  центр звезды")
    # Печатаются только ступени, на которых что-то ИЗМЕНИЛОСЬ, плюс выбранная.
    # Полная лестница — шесть десятков строк, из которых пять шестых повторяют
    # предыдущую; выбор «плотность против разнообразия» на таком списке не
    # читается, а он и есть единственное решение, которое тут принимает человек.
    prev = None
    for row in res["ladder"]:
        key = (row["n"], row["worst"])
        pick = row["threshold"] == res["threshold"]
        if key == prev and not pick:
            continue
        prev = key
        out.append(f"{row['threshold']:7.2f} {row['n']:7d} "
                   f"{_num(row['worst']):>8}  {row['centre']}"
                   + ("   ← взято" if pick else ""))
    out.append(f"порог {res['threshold']:.2f} ({res['threshold_mode']}): "
               f"{res['threshold_why']}; размер задан --min-size "
               f"{res['min_size']} / --max-size {res['max_size']}")
    if not res["min_size_reached"]:
        out.append(f"  ВНИМАНИЕ: {res['min_size']} кадров не набралось нигде "
                   f"до порога {LO:.2f} — связного ядра в пуле нет")

    out.append("")
    out.append(f"ДАТАСЕТ: {c['n']} кадров, {c['pairs']} пар")
    out.append("  ячейки: " + ", ".join(f"{k} × {v}"
                                         for k, v in c["cells"].items()))
    out.append(f"  худшая пара внутри {_num(c['worst_pair'])}"
               + (f" на {' × '.join(c['worst_pair_files'])}"
                  if c["worst_pair_files"] else "")
               + f", средняя {_num(c['mean_pair'])}")
    out.append(f"  центр {os.path.basename(res['centre'])}")
    out.append(f"  триггер «{res['trigger']}» ({res['trigger_from']})")
    if res["single_cell"]:
        # Не предупреждение о качестве, а описание того, ЧТО именно выучит
        # лора: один свет, один ракурс, один гардероб. Разнообразие после
        # обучения покупается промптом, но только если оно вообще было в
        # обучении хоть немного.
        out.append("  ВСЯ ГРУППА ИЗ ОДНОЙ ЯЧЕЙКИ: связного «её» между сценами "
                   "в пуле нет.")
        out.append("  Лора выучит лицо вместе со сценой; снизьте --threshold "
                   "или доснимите пул.")

    out.append("")
    out.append(f"годность: худшая пара {_num(c['worst_pair'])} против порога "
               f"{_num(f['floor'])} ({f['floor_from']}) — {f['state']}")
    if f["floor_why"]:
        out.append(f"  {f['floor_why']}")
    if res.get("refused"):
        out.append(f"ОТКАЗ: {res['refused']}")
    elif res["dry"]:
        out.append(f"--dry: ничего не записано. Записал бы {c['n'] * 2 + 1} "
                   f"файлов в {res['out']}")
    else:
        out.append(f"записано: {res['out']}")
        out.append(f"отчёт: {res['md']}")

    if not quiet:
        for line in out:
            print(line)
    return out


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)

    def opt(k, d=None):
        return cli_opt(args, k, d)

    t = opt("--threshold", "auto")
    res = build(args[0],
                trigger=opt("--trigger"),
                shotlist=opt("--shotlist", "shotlist.json"),
                threshold=None if str(t).lower() == "auto" else float(t),
                min_size=int(opt("--min-size", 8)),
                max_size=int(opt("--max-size", 20)),
                min_worst=(None if opt("--min-worst") is None
                           else float(opt("--min-worst"))),
                part=int(opt("--part", 1)),
                out=opt("--out"), md=opt("--md"), dry="--dry" in args,
                pool=opt("--pool", "shotlist"),
                ref_face=opt("--ref"),
                ref_floor=float(opt("--ref-floor", REF_FLOOR)),
                per_cell=int(opt("--per-cell", 0)),
                floors=(None if opt("--no-floors") is not None or
                        "--no-floors" in args else DIVERSITY_FLOORS))
    report(res)
    # Ненулевой код возврата при отказе: оркестратору и CI нужен признак, не
    # требующий разбора stdout.
    raise SystemExit(1 if res.get("refused") else 0)


if __name__ == "__main__":
    main()
