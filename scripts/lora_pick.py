#!/usr/bin/env python3
"""Выбор чекпоинта персонажной лоры ЗАМЕРОМ, а не по номеру шага.

  py -3 lora_pick.py <project_dir> --job <имя> --ref <лицо.png>
                     [--cells P1,P4] [--seeds 2] [--strength 1.0]
                     [--md docs/<id>/lora_pick.md] [--dry]

ЗАЧЕМ ЭТО ОТДЕЛЬНЫЙ ШАГ. Обучение сохраняет несколько чекпоинтов (у нас на
250, 500, 750 и 1000 шагах), и «брать последний» — не решение, а привычка.
Персонажная лора на длинной дистанции переучивается: лицо садится всё точнее,
а вместе с ним запоминаются и обстоятельства датасета — свет, кадрирование,
одежда, — и лора перестаёт слушаться промпта. Ранний чекпоинт наоборот держит
гибкость, но лицо ещё гуляет. Между этими двумя бедами и надо выбрать, а
выбрать можно только замерив обе.

ЧТО МЕРЯЕТСЯ НА КАЖДОМ ЧЕКПОИНТЕ:
  КОСИНУС К БАЗЕ — то же лицо или нет. Растёт с обучением.
  ПОСЛУШНОСТЬ — насколько кадры разных ячеек ОТЛИЧАЮТСЯ друг от друга.
    Считается как средний косинус между кадрами РАЗНЫХ ячеек по цвету и
    композиции, а не по лицу: переученная лора рисует одно и то же вне
    зависимости от указания, и это видно как схлопывание разброса.
  ПРИЗНАКИ РИСОВАННОСТИ — волосы-ленты, фон-каша, разъезжающийся взгляд
    (metrics/artifacts.py). Обучение может их и починить, и усилить.
  ВОЗРАСТ — детектор genderage. У этой модели он проседает, и лора обязана
    его держать, а не молодить.

ГЕНЕРАЦИЯ ИДЁТ ОБЫЧНЫМ t2i, БЕЗ РЕФЕРЕНСА, И ЭТО СУТЬ ПРОВЕРКИ. Эдит-ветка
подставляет лицо с картинки; если проверять чекпоинт ею, замер покажет работу
эдита, а не лоры. Лора нужна ровно затем, чтобы лицо держалось БЕЗ референса —
на этом её и проверяем.

ЧЕКПОИНТЫ ИЩУТСЯ НА ВОРКЕРЕ, А НЕ НА ЭТОЙ МАШИНЕ. Обучение пишет их в выход
тулкита на удалённой машине, ComfyUI читает свою папку лор — там же. Копирует
их между этими папками человек (одной командой на воркере), а скрипт берёт
СПИСОК ЛОР У САМОГО ComfyUI и работает только с тем, что воркер видит. Так
сделано намеренно: скрипт, лезущий по SSH, тянет за собой пароли и ключи в
код, который задуман переносимым, а «лора не найдена» на воркере выглядит для
глаза как «лора не помогла».
"""
import os
import sys
import random
import statistics

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (setup_console, cli_opt, manifest, work_dir, write_json,
                   project_name)                      # noqa: E402
from prompts import load_project, build_cell          # noqa: E402
import comfy_client as cc                             # noqa: E402
import generate as G                                  # noqa: E402


def checkpoints(prefix):
    """Чекпоинты, ВИДИМЫЕ ВОРКЕРУ, отсортированные по шагу: [(шаг, имя), …].

    Список берётся у самого ComfyUI: то, чего нет в его списке лор, он не
    загрузит, каким бы файлом это ни было на диске. Шаг вынимается из имени —
    ai-toolkit пишет его числом в конце (…_000000250.safetensors).
    """
    try:
        info = cc.object_info("LoraLoaderModelOnly")
        names = list(info["LoraLoaderModelOnly"]["input"]["required"]
                     ["lora_name"][0])
    except Exception as e:
        raise SystemExit(f"не удалось спросить у воркера список лор: {e}")
    # ШАГ БЕРЁТСЯ ТОЛЬКО ИЗ ДОПОЛНЕННОГО НУЛЯМИ ХВОСТА _000000NNN, который
    # пишет ai-toolkit. Наивный «последняя группа цифр в имени» назвал
    # финальный файл bridget_edit_v2.safetensors шагом 2 — цифру он взял из
    # «v2» в имени задания, и финальный чекпоинт встал первым в списке.
    # Файл БЕЗ такого хвоста — это финал, и сортироваться он обязан последним.
    import re
    out = []
    for n in names:
        base = os.path.basename(n)
        if not base.lower().startswith(prefix.lower()):
            continue
        m = re.search(r"_(\d{6,})\.safetensors$", base, re.I)
        out.append((int(m.group(1)) if m else 10 ** 9, n))
    return sorted(out)


def measure_frame(path, ref_emb):
    """Числа одного кадра: сходство, возраст, три признака рисованности."""
    from metrics import faces, artifacts
    f = faces.detect(path)
    if f["state"] != "PASS":
        return None
    a = artifacts.measure(path, face=f)
    return {"cos": faces.cosine(f["embedding"], ref_emb), "age": f["age"],
            "hair": a["hair"], "background": a["background"], "gaze": a["gaze"]}


def obedience(paths):
    """Насколько кадры РАЗНЫХ ячеек отличаются друг от друга. Больше — лучше.

    Считается по цвету и композиции, а не по лицу: лицо обязано совпадать, это
    и есть цель. Переученная лора схлопывает всё остальное — рисует один и тот
    же кадр на любое указание, — и это видно как падение расстояния между
    гистограммами.
    """
    import numpy as np, cv2
    from _util import imread
    hists = []
    for p in paths:
        im = imread(p)
        if im is None:
            continue
        small = cv2.resize(im, (64, 64), interpolation=cv2.INTER_AREA)
        h = cv2.calcHist([cv2.cvtColor(small, cv2.COLOR_BGR2HSV)], [0, 1],
                         None, [24, 24], [0, 180, 0, 256])
        hists.append(cv2.normalize(h, h).flatten())
    if len(hists) < 2:
        return None
    d = [float(np.linalg.norm(hists[i] - hists[j]))
         for i in range(len(hists)) for j in range(i + 1, len(hists))]
    return float(statistics.mean(d))


def run(project_dir, job, ref, cells=None, seeds=2, strength=1.0,
        md=None, dry=False):
    from metrics import faces
    char, shots = load_project(project_dir, "shotlist.json")
    project = project_name(project_dir, shots, char)
    man = manifest()

    cks = checkpoints(job)
    if not cks:
        raise SystemExit(
            f"воркер не видит ни одной лоры с именем на «{job}».\n"
            f"  Чекпоинты лежат в выходе тулкита и в папку лор ComfyUI сами не "
            f"попадают.\n  Скопировать их НА ВОРКЕРЕ:\n"
            f'    copy "D:\\ai-toolkit\\output\\{job}\\*.safetensors" '
            f'"D:\\ComfyUI_Models\\loras\\"\n'
            f"  Если файлов нет и там — обучение не дошло до первого сохранения "
            f"либо пишет\n  папкой diffusers: ComfyUI читает однофайловый "
            f"safetensors.")

    want = [c.strip() for c in (cells or "P1,P3,P4").split(",") if c.strip()]
    cell_list = [c for c in shots["cells"] if c["id"] in want]
    if not cell_list:
        raise SystemExit(f"ячейки {want} не найдены в раскадровке")
    seed_list = [random.randint(1, 2 ** 31 - 1) for _ in range(int(seeds))]

    print(f"чекпоинтов {len(cks)}: {', '.join(str(s) for s, _ in cks)}")
    print(f"ячеек {len(cell_list)}, сидов {len(seed_list)} → "
          f"{len(cks) * len(cell_list) * len(seed_list)} кадров\n")
    if dry:
        for step, p in cks:
            print(f"  шаг {step:5}  {os.path.basename(p)}")
        return None

    ref_face = faces.detect(ref)
    if ref_face["state"] != "PASS":
        raise SystemExit(f"на референсе лица нет: {ref_face['note']}")

    rows = []
    for step, name in cks:
        print(f"--- шаг {step}: лора {name}")
        frames = []
        for cell in cell_list:
            prompt = build_cell(char, cell)
            size = cell.get("size") or shots.get("size")
            for seed in seed_list:
                loras = [{"name": name, "strength": float(strength),
                          "role": "персонаж"}]
                loras += list(man["models"]["realism_loras"])
                graph = G._apply_loras(cc.load_template(G.TEMPLATE), loras)
                base = man["models"]["base"]
                cc.apply_sets(graph, {
                    G.KNOB["unet"]: base["unet"], G.KNOB["prompt"]: prompt,
                    G.KNOB["seed"]: seed, G.KNOB["steps"]: base["steps"],
                    G.KNOB["cfg"]: base["cfg"],
                    G.KNOB["sampler"]: base["sampler"],
                    G.KNOB["scheduler"]: base["scheduler"],
                    G.KNOB["width"]: int(size[0]),
                    G.KNOB["height"]: int(size[1]),
                    G.KNOB["prefix"]: f"ck{step}/{cell['id']}_s{seed}",
                })
                out_dir = work_dir(project, os.path.join("lora_pick",
                                                         f"ck{step}"))
                files = cc.run_graph(graph, out_dir)
                frames += files
        vals = [m for m in (measure_frame(p, ref_face["embedding"])
                            for p in frames) if m]
        if not vals:
            print("   ни на одном кадре лица не нашлось")
            continue
        med = lambda k: statistics.median([v[k] for v in vals
                                           if v[k] is not None])
        row = {"step": step, "n": len(vals), "cos": med("cos"),
               "age": med("age"), "hair": med("hair"),
               "background": med("background"), "gaze": med("gaze"),
               "obedience": obedience(frames), "lora": name}
        rows.append(row)
        print(f"   косинус {row['cos']:+.3f}  возраст {row['age']:.0f}  "
              f"волосы {row['hair']:.3f}  фон {row['background']:.3f}  "
              f"взгляд {row['gaze']:.3f}  послушность "
              f"{row['obedience']:.3f}" if row["obedience"] else "")

    if not rows:
        raise SystemExit("ни один чекпоинт не дал измеримых кадров")

    print(f"\n{'шаг':>6} {'косинус':>8} {'возраст':>8} {'волосы':>7} "
          f"{'фон':>6} {'взгляд':>7} {'послушность':>12}")
    for r in rows:
        print(f"{r['step']:6} {r['cos']:+8.3f} {r['age']:8.0f} {r['hair']:7.3f} "
              f"{r['background']:6.3f} {r['gaze']:7.3f} "
              f"{(r['obedience'] or float('nan')):12.3f}")

    # ВЫБОР НЕ ПО ОДНОМУ ЧИСЛУ. Лучший чекпоинт — тот, где сходство уже
    # набрано, а послушность ещё не схлопнулась. Порог сходства берётся от
    # лучшего достигнутого: требовать абсолютное число нечестно, потолок
    # зависит от датасета.
    best_cos = max(r["cos"] for r in rows)
    ok = [r for r in rows if r["cos"] >= best_cos * 0.95]
    pick = max(ok, key=lambda r: (r["obedience"] or 0))
    print(f"\nрекомендация: шаг {pick['step']} — сходство {pick['cos']:+.3f} "
          f"(не хуже 5% от лучшего {best_cos:+.3f}) при самой высокой "
          f"послушности {pick['obedience']:.3f}")
    print(f"  вписать в assets.json → models.character_lora:\n"
          f'    "name": "{pick["lora"]}", "trigger": "<слово датасета>"')

    write_json(os.path.join(work_dir(project, "lora_pick"), "picks.json"), rows)
    if md:
        os.makedirs(os.path.dirname(os.path.abspath(md)), exist_ok=True)
        with open(md, "w", encoding="utf-8") as fh:
            fh.write(f"# Выбор чекпоинта: {project}\n\nПишет "
                     f"`scripts/lora_pick.py`. Строки — чекпоинты.\n\n"
                     f"| шаг | косинус | возраст | волосы | фон | взгляд | "
                     f"послушность |\n|---|---|---|---|---|---|---|\n")
            for r in rows:
                fh.write(f"| {r['step']} | {r['cos']:+.3f} | {r['age']:.0f} | "
                         f"{r['hair']:.3f} | {r['background']:.3f} | "
                         f"{r['gaze']:.3f} | {r['obedience']:.3f} |\n")
            fh.write(f"\nВыбран шаг {pick['step']}.\n")
        print(f"отчёт: {md}")
    return rows


def main():
    setup_console()
    args = sys.argv[1:]
    if not args or args[0].startswith("--"):
        print(__doc__)
        raise SystemExit(1)
    job = cli_opt(args, "--job")
    ref = cli_opt(args, "--ref")
    if not job or not ref:
        raise SystemExit("нужны --job <имя задания> и --ref <файл лица базы>")
    run(args[0], job, ref, cli_opt(args, "--cells"),
        cli_opt(args, "--seeds", "2"), float(cli_opt(args, "--strength", "1.0")),
        cli_opt(args, "--md"), "--dry" in args)


if __name__ == "__main__":
    main()
