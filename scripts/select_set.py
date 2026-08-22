#!/usr/bin/env python3
"""Собрать набор из одного кадра на ячейку так, чтобы это был ОДИН человек.

  py -3 select_set.py <project_dir> [--shotlist shotlist.json] [--top 3]

ЗАЧЕМ ЭТО ВМЕСТО ПЕРЕНОСА ЛИЦА. Замерено на этом проекте, попарный косинус
ArcFace по набору из разных ячеек:

    чистая генерация, кадр наугад            ~0.40-0.60   кожа эталонная
    krea2_identity_edit + референс            0.272       кожа эталонная
    Krea2EditModelPatch, ref_boost 2.0        0.467       кожа эталонная
    ReActor своп + второй проход              0.855       КОЖА ПЛАСТИК

Ни один механизм переноса лица не даёт идентичность без потери кожи: своп
синтезирует лицо в 128x128 и вклеивает его в кадр 1152x1440, а всё, что это
чинит, либо заглаживает кожу, либо тянет лицо обратно к типажу. Зато между
кадрами одной и той же карточки разброс большой — а значит среди сорока
сгенерированных кадров ЕСТЬ пятёрка, которая и так читается как один человек.
Её и надо найти. Это ровно то, что раскадровка называет «генерируем 40, сдаём
5; ремесло — в отборе», просто отбор здесь делает не глаз, а метрика.

ЧТО ОПТИМИЗИРУЕТСЯ. Максимизируется МИНИМАЛЬНЫЙ попарный косинус по набору, а
не средний. Проверяющий смотрит десять фотографий и видит худшую пару; среднее
её прячет. Перебор полный, если вариантов немного, иначе жадный старт с лучшей
пары и достройка.

ЧТО ЭТО НЕ ДЕЛАЕТ. Не отменяет глаз. Скрипт выдаёт --top лучших наборов, между
ними выбирают по кадру: метрика ловит «не тот человек», но не ловит «скучно».
"""
import os, sys, itertools

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (setup_console, work_dir, read_json, read_verdict,
                   verdict_coverage, project_name, cli_opt)
from prompts import load_project

FRAMES_SUB = {"shotlist.json": "frames"}


def _sub(shotlist):
    return FRAMES_SUB.get(shotlist,
                          "frames_" + os.path.splitext(shotlist)[0]
                          .replace("shotlist_", ""))


def embeddings(files):
    """{файл: нормированный вектор}. Кадры без лица выбывают из отбора."""
    import numpy as np
    from metrics.faces import analyse
    out = {}
    for f in files:
        try:
            e = np.array(analyse(f)["embedding"], dtype=np.float32)
            out[f] = e / np.linalg.norm(e)
        except Exception:
            print(f"  лицо не найдено, кадр вне отбора: {os.path.basename(f)}",
                  file=sys.stderr)
    return out


def best_sets(by_cell, emb, top=3, budget=200000):
    """Наборы по одному кадру на ячейку, отсортированные по худшей паре."""
    cells = sorted(by_cell)
    # Ни одной ячейки — значит ворота отбраковали всё. Раньше отсюда падал
    # ValueError: min() iterable argument is empty из недр перебора, и человек
    # видел трассировку вместо ответа «перегонять надо всё».
    if not cells:
        raise SystemExit(
            "после ворот не осталось ни одного кадра — набирать не из чего. "
            "Смотреть вердикт: gates.py, колонка провалов.")
    pools = [[f for f in by_cell[c] if f in emb] for c in cells]
    if any(not p for p in pools):
        empty = [c for c, p in zip(cells, pools) if not p]
        raise SystemExit(f"в ячейках {empty} нет ни одного кадра с лицом")
    if len(cells) < 2:
        raise SystemExit(
            f"ячейка всего одна ({cells[0]}) — попарного разброса не бывает. "
            f"Отбор набора имеет смысл от двух ячеек.")

    total = 1
    for p in pools:
        total *= len(p)

    if total <= budget:
        scored = []
        for combo in itertools.product(*pools):
            scored.append(_score(combo, emb))
        scored.sort(key=lambda x: (-x[0], -x[1]))
        return cells, scored[:top]

    # ПОЛНЫЙ ПЕРЕБОР НЕ ВЛЕЗАЕТ — ИДЁМ ЖАДНО. Здесь стояло «урезать пулы до
    # шести центральных» и следом ВСЁ РАВНО itertools.product по урезанным
    # пулам. На пяти ячейках это 6^5 = 7776 и работало, поэтому дефект не
    # замечали. На двадцати ячейках это 6^20 ≈ 3.7e15: процесс не кончается
    # никогда и молча съедает память, накапливая `scored`. Докстринг всё это
    # время обещал «жадный старт с лучшей пары и достройка» — обещание не было
    # выполнено ни строчкой.
    print(f"вариантов {total} — полный перебор не влезает, идём жадно "
          f"({len(cells)} ячеек)")
    return cells, _greedy(cells, pools, emb, top)


def _score(combo, emb):
    """(худшая пара, средняя пара, набор). Оптимизируется ПЕРВОЕ.

    Проверяющий смотрит набор целиком и видит худшую пару; среднее её прячет.
    """
    v = [emb[f] for f in combo]
    pw = [float(v[i] @ v[j])
          for i in range(len(v)) for j in range(i + 1, len(v))]
    return (min(pw), sum(pw) / len(pw), tuple(combo))


def _greedy(cells, pools, emb, top, rounds=8):
    """Жадная сборка набора с последующей доводкой заменами.

    СТАРТ С ЛУЧШЕЙ ПАРЫ, а не с первой ячейки: набор держится своей худшей
    парой, и начинать имеет смысл оттуда, где она заведомо высока.

    ДОВОДКА ОБЯЗАТЕЛЬНА. Жадность близорука: кадр, выгодный на четвёртом шаге,
    может оказаться тем самым, кто тянет вниз худшую пару на двадцатом. Поэтому
    после сборки набор обходится по кругу — каждой ячейке подбирается лучшая
    замена при остальных зафиксированных, пока хоть что-то улучшается.

    Возвращает `top` РАЗНЫХ наборов: тот же алгоритм от разных стартовых пар,
    чтобы человеку было из чего выбирать глазами (метрика ловит «не тот
    человек», но не ловит «скучно»).
    """
    idx = list(range(len(cells)))
    starts = []
    for i in idx:
        for j in idx[i + 1:]:
            for a in pools[i]:
                for b in pools[j]:
                    starts.append((float(emb[a] @ emb[b]), i, j, a, b))
    starts.sort(key=lambda x: -x[0])

    seen, out = set(), []
    for _cos, i, j, a, b in starts[:max(top * 4, 8)]:
        chosen = {i: a, j: b}
        for k in idx:                      # достройка
            if k in chosen:
                continue
            best, best_key = None, None
            for f in pools[k]:
                key = _score([chosen[m] for m in sorted(chosen)] + [f], emb)[:2]
                if best_key is None or key > best_key:
                    best, best_key = f, key
            chosen[k] = best

        for _ in range(rounds):            # доводка заменами
            moved = False
            for k in idx:
                cur = _score([chosen[m] for m in idx], emb)[:2]
                for f in pools[k]:
                    if f is chosen[k]:
                        continue
                    trial = dict(chosen)
                    trial[k] = f
                    key = _score([trial[m] for m in idx], emb)[:2]
                    if key > cur:
                        chosen, cur, moved = trial, key, True
            if not moved:
                break

        combo = tuple(chosen[m] for m in idx)
        if combo in seen:
            continue
        seen.add(combo)
        out.append(_score(combo, emb))
        if len(out) >= top:
            break

    out.sort(key=lambda x: (-x[0], -x[1]))
    return out


def run(project_dir, shotlist="shotlist.json", top=3, partial_ok=False):
    char, shots = load_project(project_dir, shotlist)
    project = project_name(project_dir, shots, char)
    root = work_dir(project, _sub(shotlist))
    led_path = os.path.join(root, "frames.json")
    if not os.path.exists(led_path):
        raise SystemExit(f"реестра нет: {led_path}")
    led = read_json(led_path)

    # ОТБОР ИДЁТ ТОЛЬКО ПО ТОМУ, ЧТО ПРОШЛО ВОРОТА. Раньше селектор про
    # gates.json не знал вовсе и во всех трёх рекомендуемых наборах выдавал
    # кадр с ships=false — вместе с готовой строкой --pick, которую человек
    # копировал в сдачу. Починить сдачу и не починить отбор значило чинить
    # следствие: следующий прогон по инструкции воспроизводил тот же брак.
    gates_path = os.path.join(root, "gates.json")
    verdicts, measured = {}, False
    if os.path.exists(gates_path):
        data = read_verdict(gates_path)[0]
        # ЧАСТИЧНЫЙ ВЕРДИКТ — ЭТО ОТКАЗ. gates.py --only перезаписывает файл
        # ЦЕЛИКОМ, и отбор этого не видел: строки других ячеек исчезали, а
        # отсутствие строки читалось как «прошёл». В рекомендованный набор
        # попадал кадр, по которому ворота вообще не считались, — вместе с
        # готовой строкой --pick, которую человек копирует в сдачу. Это тот же
        # дефект, который раунд 4 чинил в deliver.py; починить его в одной
        # точке из двух значило починить следствие.
        gap = verdict_coverage(data)
        if gap and not partial_ok:
            raise SystemExit(
                f"{gap}\n"
                "  Набор отбирается по НАБОРУ: рекомендовать пятёрку по\n"
                "  вердикту одной ячейки нельзя — про остальные не известно\n"
                "  ничего. Перепрогнать целиком:\n"
                f"    py -3 scripts/gates.py {project_dir}"
                + ("" if shotlist == "shotlist.json" else f" --shotlist {shotlist}")
                + "\n  Осознанно посмотреть по неполному: --partial-ok")
        if gap:
            print(f"ВНИМАНИЕ: {gap}\n  идём с --partial-ok: кадры без строки "
                  f"в вердикте помечены «НЕ ИЗМЕРЕН» и в набор не берутся.",
                  file=sys.stderr)
        for row in data.get("frames", []):
            verdicts[os.path.basename(row.get("file", ""))] = row
        measured = True
    else:
        print("ВНИМАНИЕ: вердикта ворот нет — отбор идёт по всему пулу, "
              "включая брак. Сначала gates.py.", file=sys.stderr)

    by_cell, dropped = {}, []
    for e in led:
        if not os.path.exists(e["file"]):
            continue
        v = verdicts.get(os.path.basename(e["file"]))
        # ОТСУТСТВИЕ СТРОКИ — НЕ «ПРОШЁЛ». Когда вердикт есть, кадр без строки
        # в нём не измерялся, и брать его в набор нельзя по той же причине, по
        # которой не берут провалившийся: про него не известно ничего.
        # Прежнее условие (v is not None and not ships) пропускало такие кадры
        # молча — именно так --only и просачивался в готовую строку --pick.
        if measured and v is None:
            dropped.append((e["cell"], os.path.basename(e["file"]), "НЕ ИЗМЕРЕН"))
            continue
        if v is not None and not v.get("ships"):
            dropped.append((e["cell"], os.path.basename(e["file"]),
                            v.get("verdict")))
            continue
        by_cell.setdefault(e["cell"], []).append(e["file"])
    if dropped:
        print(f"не прошли ворота и в отбор не берутся: {len(dropped)}")
        for cell, f, verdict in dropped:
            print(f"    {cell}  {f}  {verdict}")
    print(f"кадров в отборе: {sum(len(v) for v in by_cell.values())} "
          f"по {len(by_cell)} ячейкам")

    emb = embeddings([f for v in by_cell.values() for f in v])
    cells, best = best_sets(by_cell, emb, top)

    for rank, (mn, mean, combo) in enumerate(best, 1):
        print(f"\n--- набор {rank}: худшая пара {mn:.3f}, среднее {mean:.3f}")
        for c, f in zip(cells, combo):
            print(f"    {c}  {os.path.basename(f)}")
        print("    --pick " + " ".join(
            f"{c}={os.path.basename(f)}" for c, f in zip(cells, combo)))
    return cells, best


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__); raise SystemExit(1)

    def opt(k, d=None):
        return cli_opt(args, k, d)

    run(args[0], opt("--shotlist", "shotlist.json"), int(opt("--top", 3)),
        partial_ok="--partial-ok" in args)


if __name__ == "__main__":
    main()
