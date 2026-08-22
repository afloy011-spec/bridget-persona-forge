#!/usr/bin/env python3
"""Отвечает ли ArcFace на вопрос «это один человек» на ЭТОМ материале.

  py -3 identity_calibration.py <project_dir> [--part 1] [--draws 20000]
                                [--seed 0] [--out docs/<проект>/…json]

ЗАЧЕМ ЭТОТ СКРИПТ СУЩЕСТВУЕТ. В манифесте дважды стояло прозой утверждение о
том, что косинус говорит про идентичность набора, и дважды оно было неверным —
оба раза потому, что сравнивались РАЗНЫЕ статистики. Первая редакция брала
медиану косинусов к якорю (0.637) против минимума по парам набора (0.541) и
делала вывод «наш человек похож на себя хуже случайных». Вторая брала минимум
по 105 парам кастинга (0.442) против минимума по 10 парам сдачи и делала вывод
обратный. Минимум — крайняя порядковая статистика: чем больше пар, тем он ниже,
поэтому сравнивать можно только при РАВНОМ числе пар.

Отсюда правило, ради которого файл и заведён: число, которое нельзя пересчитать
командой, в манифесте не живёт. Здесь оно считается.

КАК СЧИТАЕТСЯ. Берётся сданный набор из N кадров (N*(N-1)/2 пар) и его худшая
пара. Затем много раз разыгрывается набор из N СЛУЧАЙНЫХ кандидатов кастинга —
это заведомо разные женщины, сгенерированные по одному описанию, — и у каждого
розыгрыша берётся его худшая пара. Сравниваются распределения при одинаковом
N. Доля розыгрышей, которые оказались ХУЖЕ нашего набора, и есть ответ: если
она близка к половине, метрика не различает «наш человек» и «разные люди».

КОНТРОЛЬ СЦЕНЫ, И ЭТО ВТОРАЯ ПОЛОВИНА ЗАМЕРА. Сравнение выше несимметрично, и
раньше про это молчали: сданный набор — по кадру из РАЗНЫХ сцен (портрет,
улица, корт, комната, ресторан), а отрицательный класс — кастинг, снятый весь
в одной. Разброс кадрирования, ракурса и света у нашего набора заведомо
больше, поэтому «метрика не разделяет» могло быть свойством сравнения, а не
метрики — и на этом выводе стоит статус ворот идентичности. Поэтому тот же
розыгрыш повторяется при контроле сцены: худшая пара ВНУТРИ одной ячейки (одна
сцена, все её кадры, отличаются только сидом) против случайных наборов
кастинга того же размера — то есть при равном числе пар и равной сцене. Ответ
печатает таблица «КОНТРОЛЬ СЦЕНЫ», решение о статусе ворот принимается не
здесь.

КУДА ПИШЕТСЯ РЕЗУЛЬТАТ. По умолчанию в docs/<проект>/identity_calibration.json
— туда, куда за актуальными числами посылают README, SKILL.md и assets.json →
gates._identity_is_informational («чисел здесь нет намеренно, они там»).
Скрипт этот файл НЕ ПИСАЛ: он печатал в stdout, а файл по ссылке однажды
завели руками, и он устарел ровно так же, как та проза, из которой числа
оттуда и убирали. В файл кладётся всё, что напечатано (ключ report —
построчно, чтобы «в файле есть то же, что на экране» держалось конструкцией),
плюс дата, параметры розыгрыша и путь к разобранной сдаче. Часть 2 пишет в тот
же файл; чья это калибровка, говорит ключ part, а нужны обе рядом — задайте
--out.
"""
import datetime
import glob
import itertools
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (setup_console, work_dir, read_json, project_name, ROOT,
                   cli_opt, write_json, work_resolve)
from prompts import load_project

PART_DIRS = {1: "part1_profile", 2: "part2_story"}

# Доля розыгрышей, ниже которой считаем, что метрика разделяет. Вынесена в имя
# потому, что применяется теперь дважды — к сдаче и к каждой ячейке при
# контроле сцены; две одинаковые константы в разных местах разошлись бы молча,
# и тогда «разделяет» в таблице значило бы не то же самое, что в выводе.
SEPARATES_AT = 0.90


def _emb(path):
    import numpy as np
    from metrics.faces import analyse
    v = np.array(analyse(path)["embedding"], dtype=np.float32)
    return v / np.linalg.norm(v)


def _cached_emb(cache):
    """Тот же _emb, но кадр разбирается один раз.

    Сданные кадры лежат ВНУТРИ своих ячеек, а контроль сцены проходит по всем
    кадрам ячейки — без кэша каждый сданный кадр гнался бы через детектор
    дважды, по секунде процессорного времени на кадр.
    """
    def emb(path):
        if path not in cache:
            cache[path] = _emb(path)
        return cache[path]
    return emb


def _worst_pair(vecs):
    return min(float(a @ b) for a, b in itertools.combinations(vecs, 2))


def _median(values):
    return sorted(values)[len(values) // 2] if values else None


def _random_worst_pairs(pool, n, draws, seed):
    """Худшие пары `draws` случайных наборов по n лиц из пула, отсортированы.

    Отдельной функцией потому, что розыгрыш нужен дважды: для сдачи и для
    каждой ячейки при контроле сцены. Он обязан быть ОДИН И ТОТ ЖЕ — равное
    число пар и равный сид и есть то единственное, ради чего этот скрипт
    написан. Вторая копия разошлась бы по числу розыгрышей или по сиду, и
    сравнение снова оказалось бы сравнением разных статистик.
    """
    rnd = random.Random(seed)
    keys = list(pool)
    return sorted(_worst_pair([pool[k] for k in rnd.sample(keys, n)])
                  for _ in range(draws))


def _spread(dist):
    return {"median": round(dist[len(dist) // 2], 4),
            "p05": round(dist[int(0.05 * len(dist))], 4),
            "p95": round(dist[int(0.95 * len(dist))], 4)}


def _share_worse(dist, value):
    return sum(1 for d in dist if d <= value) / len(dist)


def _scene_control(rows, pool, draws, seed, emb):
    """Тот же розыгрыш при равной сцене: ячейка против кастинга.

    Ячейка — это одна сцена, один свет и одно кадрирование: её кадры
    отличаются только сидом. Если при таком контроле метрика начинает
    разделять, значит вывод основного сравнения держался на разбросе сцен
    сданного набора, а не на лицах.

    Кадры ячейки берутся из папки, ОТКУДА ПРИШЁЛ сданный кадр, а не собираются
    по имени ячейки в work_root: у второй части кадры лежат в другом каталоге
    (frames_story), и сборка пути по шаблону молча промахнулась бы мимо неё.

    Розыгрыш кэшируется по размеру набора: у всех ячеек он обычно один, а
    пул и сид общие — значит и распределение сравнения общее, считать его
    заново на каждую ячейку значит только жечь время.
    """
    cells, cell_vecs, skipped, dists, seen = [], [], [], {}, set()
    for row in rows:
        cell = row.get("cell")
        folder = os.path.dirname(work_resolve(str(row.get("source") or "")))
        if not cell or cell in seen:
            continue
        seen.add(cell)
        if not os.path.isdir(folder):
            skipped.append((cell, f"папки кадров нет: {folder}"))
            continue
        vecs = []
        for f in sorted(glob.glob(os.path.join(folder, "*.png"))):
            try:
                vecs.append(emb(f))
            except Exception:
                pass
        n = len(vecs)
        if n < 2:
            skipped.append((cell, "меньше двух кадров с лицом — пары нет"))
            continue
        if len(pool) <= n:
            skipped.append((cell, f"в пуле кастинга {len(pool)} лиц, "
                                  f"случайный набор из {n} не разыграть"))
            continue
        if n not in dists:
            dists[n] = _random_worst_pairs(pool, n, draws, seed)
        dist = dists[n]
        worst = _worst_pair(vecs)
        share = _share_worse(dist, worst)
        cells.append({
            "cell": cell, "folder": folder, "n": n, "pairs": n * (n - 1) // 2,
            "worst_pair": round(worst, 4),
            "random_worst_pair": _spread(dist),
            "share_of_random_sets_worse": round(share, 4),
            "separates": bool(share >= SEPARATES_AT),
        })
        cell_vecs.append(vecs)

    # Тот же человек в РАЗНЫХ ячейках против разных людей в ОДНОЙ сцене. Без
    # этой пары чисел таблица выше читается как «косинус работает, включайте»,
    # а она про другое: показать, что метрика реагирует на смену сцены, можно
    # только сравнив её с тем, как она реагирует на смену человека.
    cross = [float(a @ b)
             for x, y in itertools.combinations(cell_vecs, 2)
             for a in x for b in y]
    separating = sum(1 for c in cells if c["separates"])
    return {
        "cells": cells,
        "skipped": [list(s) for s in skipped],
        "cells_measured": len(cells),
        "cells_separating": separating,
        # Флаг — по большинству ячеек, чтобы одна удачная не решала за все;
        # что произошло на самом деле, говорят два счётчика выше.
        "separates_under_scene_control": bool(cells and
                                              separating > len(cells) / 2),
        "same_person_across_cells_median":
            None if not cross else round(_median(cross), 4),
        "different_people_same_scene_median":
            round(_median([float(a @ b) for a, b
                           in itertools.combinations(pool.values(), 2)]), 4),
    }


def calibrate(project_dir, part=1, draws=20000, seed=0):
    char, shots = load_project(project_dir)
    project = project_name(project_dir, shots, char)

    sel_path = os.path.join(ROOT, "deliverables", project, PART_DIRS[part],
                            "selection.json")
    if not os.path.exists(sel_path):
        raise SystemExit(f"сдачи нет: {sel_path} — сначала deliver.py")
    sel = read_json(sel_path)
    rows = sel.get("frames", sel) if isinstance(sel, dict) else sel

    emb = _cached_emb({})
    ours = []
    for r in rows:
        try:
            ours.append(emb(work_resolve(r["source"])))
        except Exception:
            print(f"  лицо не найдено, кадр вне замера: {r['cell']}",
                  file=sys.stderr)
    if len(ours) < 2:
        raise SystemExit("в сдаче меньше двух кадров с лицом — сравнивать нечего")
    n = len(ours)
    our_min = _worst_pair(ours)

    # Отрицательный класс: кандидаты кастинга. Это заведомо РАЗНЫЕ люди,
    # сгенерированные по одному и тому же описанию, то есть самый тяжёлый
    # возможный отрицательный класс — именно с ним и надо сравниваться.
    pool = {}
    for f in sorted(glob.glob(os.path.join(work_dir(project, "casting"),
                                           "*.png"))):
        try:
            pool[f] = emb(f)
        except Exception:
            pass
    if len(pool) <= n:
        raise SystemExit(
            f"в {work_dir(project, 'casting')} меньше {n + 1} кадров с лицом — "
            f"отрицательный класс не набрать. Нужен пул разных лиц, "
            f"сгенерированных по тому же описанию.")

    got = _random_worst_pairs(pool, n, draws, seed)
    worse = _share_worse(got, our_min)

    res = {
        "project": project, "part": part, "n": n, "pairs": n * (n - 1) // 2,
        "delivered_worst_pair": round(our_min, 4),
        "negative_pool": len(pool), "draws": draws,
        "random_worst_pair": _spread(got),
        "share_of_random_sets_worse_than_ours": round(worse, 4),
        "separates": bool(worse >= SEPARATES_AT),
        "scene_control": _scene_control(rows, pool, draws, seed, emb),
        # Дата и параметры розыгрыша лежат в файле не для порядка: без них
        # нельзя отличить свежую калибровку от прошлогодней, а именно на
        # незамеченной несвежести этот замер и погорел четыре раза подряд.
        # Путь к сдаче — по той же причине: числа описывают КОНКРЕТНЫЙ набор.
        "seed": seed,
        "selection": sel_path,
        "generated_at": datetime.datetime.now().astimezone()
                                .isoformat(timespec="seconds"),
    }
    return res


def _num(value):
    return "—" if value is None else f"{value:.3f}"


def report(res):
    """Печатает отчёт И возвращает его построчно.

    Возвращает потому, что ровно эти строки уходят в файл (ключ report):
    «в файле лежит то же, что на экране» — не обещание в документации, а одна
    и та же переменная. Второй копией формул в записывающем коде обещание
    держалось бы ровно до первой правки печати.
    """
    out = [
        f"сдано кадров {res['n']}, пар {res['pairs']}",
        f"наш набор, худшая пара: {res['delivered_worst_pair']:.3f}",
    ]
    r = res["random_worst_pair"]
    out.append(f"случайные {res['n']} лиц из пула {res['negative_pool']} "
               f"({res['draws']} розыгрышей, столько же пар):")
    out.append(f"   медиана {r['median']:.3f}   p05 {r['p05']:.3f}   "
               f"p95 {r['p95']:.3f}")
    out.append(f"доля случайных наборов ХУЖЕ нашего: "
               f"{res['share_of_random_sets_worse_than_ours']:.0%}")

    sc = res["scene_control"]
    out += ["", "КОНТРОЛЬ СЦЕНЫ: то же сравнение внутри одной ячейки — одна "
                "сцена, кадры отличаются только сидом."]
    if sc["cells"]:
        out.append(f"   {'ячейка':8} {'кадров':>6} {'пар':>4} {'худшая':>7} "
                   f"{'случ. медиана':>14} {'ХУЖЕ нашей':>11}  разделяет")
    for c in sc["cells"]:
        out.append(f"   {c['cell']:8} {c['n']:6d} {c['pairs']:4d} "
                   f"{c['worst_pair']:7.3f} "
                   f"{c['random_worst_pair']['median']:14.3f} "
                   f"{c['share_of_random_sets_worse']:11.0%}  "
                   f"{'да' if c['separates'] else 'НЕТ'}")
    for cell, why in sc["skipped"]:
        out.append(f"   {cell:8} не замерена: {why}")
    out.append(f"   тот же человек в РАЗНЫХ ячейках, медиана пар: "
               f"{_num(sc['same_person_across_cells_median'])}")
    out.append(f"   разные люди в ОДНОЙ сцене (кастинг), медиана пар: "
               f"{_num(sc['different_people_same_scene_median'])}")

    out.append("")
    if res["separates"]:
        out.append("ВЫВОД: метрика различает наш набор и набор разных людей — "
                   "порог по ней ставить можно.")
    else:
        out.append("ВЫВОД: метрика НЕ различает наш набор и набор разных "
                   "людей. Ставить по ней блокирующий порог нельзя: он "
                   "отбраковывал бы случайно. Косинус остаётся справочным "
                   "числом, идентичность принимается по контакт-шиту глазами.")

    if sc["cells"]:
        k, m = sc["cells_separating"], sc["cells_measured"]
        # ТЕКСТ И МАШИННЫЙ ФЛАГ ГОВОРЯТ ОДНО И ТО ЖЕ. Прежняя редакция ставила
        # эту ветку на `if k:` — хоть одна ячейка, — а флаг
        # separates_under_scene_control считался по БОЛЬШИНСТВУ. На одной
        # разделяющей ячейке из трёх отчёт заявлял «сравнивалось несравнимое»,
        # а поле в JSON стояло false: частичный результат, прочитанный как
        # полный, — тот же дефект, который раунд 6 чинил в вердикте ворот,
        # только внутри одного файла.
        cell_word = "ячейке" if k % 10 == 1 and k % 100 != 11 else "ячейках"
        if sc["separates_under_scene_control"]:
            out.append(f"НО СРАВНИВАЛОСЬ НЕСРАВНИМОЕ: при контроле сцены "
                       f"метрика разделяет в {k} {cell_word} из {m} — внутри "
                       f"одной сцены худшая пара нашего человека выше, чем у "
                       f"случайного набора кастинга того же размера. Значит "
                       f"вывод выше получен и на разбросе сцен сданного "
                       f"набора тоже, а не только на лицах.")
        elif k:
            out.append(f"КОНТРОЛЬ СЦЕНЫ МЕНЯЕТ КАРТИНУ ЛИШЬ МЕСТАМИ: метрика "
                       f"разделяет в {k} {cell_word} из {m}, то есть меньше "
                       f"чем в половине. Этого мало, чтобы объявить вывод "
                       f"выше артефактом разных сцен, и достаточно, чтобы не "
                       f"считать вопрос закрытым: смотреть надо на счётчики, "
                       f"а не на слово.")
        else:
            out.append(f"КОНТРОЛЬ СЦЕНЫ НИЧЕГО НЕ МЕНЯЕТ: метрика не "
                       f"разделяет ни в одной из {m} ячеек, то есть вывод "
                       f"выше — не артефакт сравнения разных сцен с одной.")
        same = sc["same_person_across_cells_median"]
        other = sc["different_people_same_scene_median"]
        if same is not None and other is not None and same < other:
            out.append("ЧЕГО ЭТО НЕ ОТМЕНЯЕТ: тот же человек в РАЗНЫХ сценах "
                       "похож на себя ХУЖЕ, чем разные люди в одной сцене "
                       "похожи друг на друга (две медианы выше). Косинус "
                       "здесь мерит сцену не меньше, чем лицо, а сдача "
                       "собирается из разных сцен — на ней порога всё ещё "
                       "нет.")
        elif same is not None and other is not None:
            out.append("И ЕЩЁ: тот же человек в разных сценах держится выше, "
                       "чем разные люди в одной (две медианы выше), то есть "
                       "на сданном наборе метрика материалу не противоречит.")
        out.append("Что из этого следует для статуса ворот идентичности, "
                   "решается не здесь: этот скрипт меряет.")
    for line in out:
        print(line)
    return out


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__); raise SystemExit(1)

    def opt(k, d=None):
        return cli_opt(args, k, d)

    res = calibrate(args[0], int(opt("--part", 1)), int(opt("--draws", 20000)),
                    int(opt("--seed", 0)))
    res["report"] = report(res)
    # --json — прежнее имя ключа. Понимается до сих пор потому, что молча
    # проигнорировать его значило бы записать файл не туда, куда просили, и
    # ничего об этом не сказать.
    out = opt("--out") or opt("--json") or os.path.join(
        ROOT, "docs", res["project"], "identity_calibration.json")
    write_json(out, res)
    print(f"числа: {out}")


if __name__ == "__main__":
    main()
