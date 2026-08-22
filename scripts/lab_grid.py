#!/usr/bin/env python3
"""Стенд: сетка «ось × сид» на одной ячейке, с замером цены каждой оси.

  py -3 lab_grid.py <project_dir> --cell P1 --axis look [--seeds 2] [--dry]
  py -3 lab_grid.py <project_dir> --cell P1 --axis age --seed-list 11,22,33
  py -3 lab_grid.py <project_dir> --cell P1 --axis look --md docs/<id>/lab_look.md

ЗАЧЕМ ОТДЕЛЬНЫЙ СКРИПТ, А НЕ ПРАВКА КОНВЕЙЕРА. Конвейер сдаёт работу, и его
настройки менять можно только с доказательством. Доказательство добывается
здесь: одна ячейка, одни и те же сиды, меняется РОВНО ОДНА вещь — и сразу
считается, что эта вещь стоит. Разговор «этот грейд красивее» не
воспроизводим; таблица «грейд coolblue: идентичность -0.03, кожа +0.01,
возраст +2 года» — воспроизводим.

СИД ФИКСИРОВАН ПО ВСЕЙ СТРОКЕ СЕТКИ. Иначе разница между вариантами
неотличима от разницы между двумя бросками кубика: на этом конвейере один и
тот же промпт с разными сидами даёт разных женщин одного типажа — это
измеренный факт проекта, а не предположение.

ЧТО МЕРЯЕТСЯ. Идентичность считается К ЯКОРНОМУ НАБОРУ (кадры той же ячейки
из сдачи), а не между вариантами: вопрос «стала ли она меньше похожа на себя»
относится к сданному человеку, а не к соседней клетке сетки. Кожа, резкость и
возраст берутся теми же метриками, что и в воротах, — иначе стенд и ворота
разойдутся в определениях.

НА СЕРВЕРЕ НЕ ОСТАЁТСЯ НИЧЕГО: SaveImage подменяется на PreviewImage,
результат забирается из temp/. Машина общая.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (setup_console, manifest, work_dir, read_json, cli_opt,
                   work_resolve,  # noqa: E402
                   project_name, write_json)
from prompts import load_project, build_cell  # noqa: E402
import comfy_client as cc  # noqa: E402
import generate as G  # noqa: E402

# Оси сетки. Каждая — СПИСОК ДОБАВОК к базовому стеку лор, а не замена его:
# вопрос стенда «что даёт эта лора СВЕРХ того, что уже есть», а не «что было
# бы, если бы конвейер собрали заново».
AXES = {
    "look": [
        ("база", []),
        ("coolblue 0.6", [("krea2_coolblue.safetensors", 0.6)]),
        ("warmpastel 0.6", [("krea2_warmpastel.safetensors", 0.6)]),
        ("darkbrush 0.6", [("krea2_darkbrush.safetensors", 0.6)]),
        ("detail-enh 0.5", [("krea-detail-enhancer-exp.safetensors", 0.5)]),
        ("enhancer 0.5", [("krea2_Enhancer.safetensors", 0.5)]),
    ],
    # Возраст — та же механика, но добавка не лора, а хвост промпта. Ось
    # заведена здесь потому, что «усилить возрастные маркеры» — ровно такое же
    # утверждение о цене, как «добавить грейд», и проверяться должно так же.
    # Комбинация: две оси дали прибавку к возрасту по отдельности (промпт +5,
    # enhancer +4). Складываются ли они — вопрос отдельного замера, а не
    # арифметики: лора и текст действуют на одну и ту же голову.
    "combo": [
        ("база", []),
        ("без смягчений + седина", []),
        ("enhancer 0.5", [("krea2_Enhancer.safetensors", 0.5)]),
        ("седина + enhancer 0.5",
         [("krea2_Enhancer.safetensors", 0.5)]),
        ("седина + enhancer 0.8",
         [("krea2_Enhancer.safetensors", 0.8)]),
        ("седина + detail-enh 0.5",
         [("krea-detail-enhancer-exp.safetensors", 0.5)]),
    ],
    "age": [
        ("база", []),
        ("+ маркеры x2", []),
        ("+ маркеры x2, шея и кисти", []),
        ("без смягчений", []),
        ("без смягчений + седина", []),
        ("без смягчений + седина + овал", []),
    ],
}

# ПОЧЕМУ ВАРИАНТЫ ИМЕННО ТАКИЕ. В карточке персонажа возрастные маркеры
# записаны СМЯГЧЁННО: «fine lines», «faint nasolabial folds», «subtle
# horizontal lines». При cfg 1.0 смягчающее прилагательное читается моделью
# как «почти нет» — ровно та же механика, из-за которой в этом проекте
# запреты пришлось переписать в положительные требования. Поэтому лесенка
# идёт от добавления маркеров к СНЯТИЮ СМЯГЧЕНИЙ и дальше к признакам,
# которые модель твёрдо связывает с пятьюдесятью: седина у висков, потеря
# чёткости овала, солнечные пятна.
AGE_SUFFIX = {
    "+ маркеры x2": (
        "deep crow's feet at the outer corners of both eyes, fine vertical "
        "lines above the upper lip, visible nasolabial folds"),
    "+ маркеры x2, шея и кисти": (
        "deep crow's feet at the outer corners of both eyes, fine vertical "
        "lines above the upper lip, visible nasolabial folds, slightly loose "
        "skin on the neck with visible platysma bands, prominent tendons and "
        "raised veins on the backs of the hands, age spots on the forearms"),
    "без смягчений": (
        "she is a woman of fifty-one and looks it: DEEP crow's feet fanning "
        "from both outer eye corners even at rest, PRONOUNCED nasolabial "
        "folds, clearly visible vertical lines above the upper lip, crepey "
        "texture on the lower eyelids, thinner vermilion of the upper lip"),
    "седина + enhancer 0.5": (
        "she is a woman of fifty-one and looks it: DEEP crow's feet fanning "
        "from both outer eye corners even at rest, PRONOUNCED nasolabial "
        "folds, clearly visible vertical lines above the upper lip, crepey "
        "texture on the lower eyelids, thinner vermilion of the upper lip, "
        "scattered grey strands at the temples and along the parting"),
    "седина + enhancer 0.8": (
        "she is a woman of fifty-one and looks it: DEEP crow's feet fanning "
        "from both outer eye corners even at rest, PRONOUNCED nasolabial "
        "folds, clearly visible vertical lines above the upper lip, crepey "
        "texture on the lower eyelids, thinner vermilion of the upper lip, "
        "scattered grey strands at the temples and along the parting"),
    "седина + detail-enh 0.5": (
        "she is a woman of fifty-one and looks it: DEEP crow's feet fanning "
        "from both outer eye corners even at rest, PRONOUNCED nasolabial "
        "folds, clearly visible vertical lines above the upper lip, crepey "
        "texture on the lower eyelids, thinner vermilion of the upper lip, "
        "scattered grey strands at the temples and along the parting"),
    "без смягчений + седина": (
        "she is a woman of fifty-one and looks it: DEEP crow's feet fanning "
        "from both outer eye corners even at rest, PRONOUNCED nasolabial "
        "folds, clearly visible vertical lines above the upper lip, crepey "
        "texture on the lower eyelids, thinner vermilion of the upper lip, "
        "scattered grey strands at the temples and along the parting"),
    "без смягчений + седина + овал": (
        "she is a woman of fifty-one and looks it: DEEP crow's feet fanning "
        "from both outer eye corners even at rest, PRONOUNCED nasolabial "
        "folds, clearly visible vertical lines above the upper lip, crepey "
        "texture on the lower eyelids, thinner vermilion of the upper lip, "
        "scattered grey strands at the temples and along the parting, "
        "softened jawline with slight loss of definition, sun spots on the "
        "cheekbones and décolleté, loose skin on the neck"),
}


def stack_loras(graph, extra):
    """Дописать лоры В КОНЕЦ цепочки шаблона и перецепить сэмплер.

    Шаблон держит пять слотов, и generate._fit_loras лишние ОТБРАСЫВАЕТ с
    предупреждением — сегодня в манифесте ровно пять реализм-лор, то есть
    свободных слотов нет вообще. Стенд не имеет права молча ронять ось,
    которую проверяет, поэтому цепочка наращивается: узлы соединены
    model→model, и добавить звено дешевле, чем выбрать, что выкинуть.
    """
    if not extra:
        return graph
    # ХВОСТ БЕРЁТСЯ У СЭМПЛЕРА, А НЕ ИЗ СПИСКА СЛОТОВ ШАБЛОНА.
    # Здесь стояло G.LORA_NODES[-1] — последний слот шаблона, — и это было
    # верно ровно до тех пор, пока стек умещался в шаблон. Персонажная лора
    # сделала стек длиннее: generate._fit_loras дописывает звенья ЗА последним
    # слотом, и добавка, пришитая к слоту, отрезала всё дописанное вместе с
    # ним. Замер: цепочка росла на 1 вместо 2, из графа молча пропадала лора,
    # и увидел это только тест — в кадре пропажа выглядит как «образ слабее,
    # чем задумано».
    # Настоящий конец цепочки — тот узел, который сейчас питает сэмплер, каким
    # бы он ни был.
    last = graph["7"]["inputs"]["model"][0]
    nxt = max(int(k) for k in graph if k.isdigit()) + 1
    for name, strength in extra:
        nid = str(nxt)
        graph[nid] = {"class_type": "LoraLoaderModelOnly",
                      "inputs": {"model": [last, 0], "lora_name": name,
                                 "strength_model": float(strength)}}
        last, nxt = nid, nxt + 1
    graph["7"]["inputs"]["model"] = [last, 0]
    return graph


def _anchor(project, cell):
    """Кадры этой ячейки из сдачи — якорь идентичности.

    Берутся ИЗ СДАЧИ, а не из пула: сравнивать надо с тем человеком, которого
    заказчик уже видит. Если ячейка не сдана, якоря нет, и идентичность
    честно не считается — врать прочерком дешевле, чем числом не про то.
    """
    import glob
    out = []
    for sel in glob.glob(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "deliverables", project, "*", "selection.json")):
        for r in read_json(sel).get("frames", []):
            src = work_resolve(r.get("source", ""))
            if r.get("cell") == cell and os.path.isfile(src):
                out.append(src)
    return out


def _measure(path, anchor_vecs, gates):
    """Замер одного кадра теми же метриками, что и ворота."""
    import numpy as np
    from metrics.faces import analyse
    from metrics.skin import skin
    from metrics.sharpness import sharpness
    from metrics.chroma import chroma
    res = {"identity": None, "age": None, "skin": None, "sharp": None,
           "chroma": None}
    try:
        face = analyse(path)
    except Exception:
        face = None
    if face and face.get("embedding") is not None:
        v = np.array(face["embedding"], dtype=np.float32)
        v = v / np.linalg.norm(v)
        if anchor_vecs:
            res["identity"] = float(min(v @ a for a in anchor_vecs))
        res["age"] = face.get("age")
    # Цвет не принимает face — у него другая сигнатура (src, gates). Общий
    # вызов с face= молча уходил в except и печатал прочерк во всей колонке:
    # ровно тот «ложный прочерк», который в воротах отличается от незамера
    # только тем, что там про него сказано вслух.
    for key, fn, kw in (("skin", skin, {"face": face, "gates": gates}),
                        ("sharp", sharpness, {"face": face, "gates": gates}),
                        ("chroma", chroma, {"gates": gates})):
        try:
            res[key] = fn(path, **kw).get("value")
        except Exception as e:
            res[key + "_why"] = f"{type(e).__name__}: {e}"
    return res


def run(project_dir, cell_id, axis="look", n_seeds=2, dry=False,
        out_md=None, fixed_seeds=None):
    import numpy as np
    from metrics.faces import analyse

    man = manifest()
    char, shots = load_project(project_dir)
    project = project_name(project_dir, shots, char)
    cells = {c["id"]: c for c in shots["cells"]}
    if cell_id not in cells:
        raise SystemExit(f"нет ячейки {cell_id}; есть: {sorted(cells)}")
    cell = cells[cell_id]
    size = shots.get("size") or man["output"]["profile_size"]
    prompt = build_cell(char, cell)
    variants = AXES[axis]

    # СИДЫ ОБЩИЕ НА ВСЮ СЕТКУ и печатаются: строка сравнима только когда в ней
    # менялась ровно одна вещь, а воспроизвести её потом можно только зная сид.
    import random
    # СИДЫ МОЖНО ЗАКРЕПИТЬ. Без этого второй прогон той же оси — другой опыт:
    # варианты сравнимы между собой внутри прогона, но не с прошлой таблицей,
    # а именно это и нужно, когда лесенку достраивают по результатам первой.
    seeds = ([int(x) for x in fixed_seeds.split(",")] if fixed_seeds
             else [random.randint(1, 2**31 - 1) for _ in range(n_seeds)])
    print(f"ячейка {cell_id} · ось «{axis}» · вариантов {len(variants)} · "
          f"сиды {seeds}")
    if dry:
        for name, extra in variants:
            print(f"  {name:22} +лоры: {[e[0] for e in extra] or '—'}")
        print(f"\nсухой прогон: {len(variants) * n_seeds} кадров не отправлено")
        return

    if not cc.preflight():
        raise SystemExit("воркер не отвечает — сетка не начата")

    anchor_paths = _anchor(project, cell_id)
    anchor_vecs = []
    for p in anchor_paths:
        try:
            v = np.array(analyse(p)["embedding"], dtype=np.float32)
            anchor_vecs.append(v / np.linalg.norm(v))
        except Exception:
            pass
    print(f"якорь идентичности: {len(anchor_vecs)} кадр(ов) из сдачи"
          if anchor_vecs else "якоря нет — идентичность не считается")

    out = work_dir(project, "lab", axis)
    gates = man["gates"]
    rows = []
    for name, extra in variants:
        text = prompt
        if name in AGE_SUFFIX:
            text = prompt + ", " + AGE_SUFFIX[name]
        for seed in seeds:
            graph = G.build_graph(text, seed, size,
                                  f"persona-forge/lab_{axis}",
                                  cell.get("scene_class", "indoor"))
            graph = stack_loras(graph, extra)
            for f in cc.run_graph(graph, out):
                tag = f"{name.replace(' ', '_')}_s{seed}"
                dst = os.path.join(out, f"{tag}.png")
                if os.path.abspath(f) != os.path.abspath(dst):
                    os.replace(f, dst)
                m = _measure(dst, anchor_vecs, gates)
                m.update({"вариант": name, "сид": seed, "файл": dst})
                rows.append(m)
                print(f"  {name:22} s{seed}  "
                      f"иден {_n(m['identity'])}  возр {_n(m['age'], 0)}  "
                      f"кожа {_n(m['skin'])}  резк {_n(m['sharp'], 0)}  "
                      f"цвет {_n(m['chroma'])}")

    _summary(rows, variants, out_md, cell_id, axis, seeds, out)
    return rows


def _n(v, digits=3):
    if v is None:
        return "  —  "
    return f"{v:.{digits}f}" if digits else f"{v:.0f}"


def _summary(rows, variants, out_md, cell_id, axis, seeds, out):
    """Сводка ПО ВАРИАНТУ, усреднённая по сидам, и цена относительно базы."""
    import statistics as st
    keys = ("identity", "age", "skin", "sharp", "chroma")
    agg = {}
    for name, _ in variants:
        got = [r for r in rows if r["вариант"] == name]
        agg[name] = {k: (st.mean([r[k] for r in got if r[k] is not None])
                         if any(r[k] is not None for r in got) else None)
                     for k in keys}
    base = agg.get("база", {})
    head = ("| вариант | идентичность | возраст | кожа | резкость | цвет |\n"
            "|---|---|---|---|---|---|")
    lines = [head]
    print(f"\nсводка по {len(seeds)} сидам (в скобках — разница с базой):")
    for name, _ in variants:
        a = agg[name]
        cells_txt = []
        for k in keys:
            v = a[k]
            if v is None:
                cells_txt.append("—"); continue
            d = ""
            if name != "база" and base.get(k) is not None:
                delta = v - base[k]
                d = f" ({delta:+.3f})" if k != "age" else f" ({delta:+.1f})"
            cells_txt.append((f"{v:.3f}" if k not in ("age", "sharp")
                              else f"{v:.0f}") + d)
        lines.append(f"| {name} | " + " | ".join(cells_txt) + " |")
        print(f"  {name:22} " + "  ".join(cells_txt))
    if out_md:
        os.makedirs(os.path.dirname(os.path.abspath(out_md)), exist_ok=True)
        with open(out_md, "w", encoding="utf-8") as fh:
            fh.write(f"# Стенд: ось «{axis}» на ячейке {cell_id}\n\n"
                     f"Сиды {seeds}, по одному на строку сетки: разница между\n"
                     f"вариантами сравнима только при фиксированном сиде.\n"
                     f"Идентичность — худший косинус к сданным кадрам этой\n"
                     f"ячейки. Кадры: `{out}`.\n\n" + "\n".join(lines) + "\n")
        print(f"\nотчёт: {out_md}")
    write_json(os.path.join(out, "grid.json"),
               {"cell": cell_id, "axis": axis, "seeds": seeds, "rows": rows})


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)

    def opt(k, d=None):
        return cli_opt(args, k, d)

    axis = opt("--axis", "look")
    if axis not in AXES:
        raise SystemExit(f"нет оси {axis!r}; есть: {sorted(AXES)}")
    run(args[0], opt("--cell", "P1"), axis, int(opt("--seeds", 2)),
        "--dry" in args, opt("--md"), opt("--seed-list"))


if __name__ == "__main__":
    main()
