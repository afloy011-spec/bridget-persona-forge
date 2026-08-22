#!/usr/bin/env python3
"""Датасет персонажной лоры ИЗ РЕФЕРЕНСА: эдит вместо генерации по описанию.

  py -3 edit_dataset.py <project_dir> --ref <файл|план=сцена.png|лицо.png,…>
                        [--seeds N] [--only D01,D05] [--axes <файл>] [--dry]
  py -3 edit_dataset.py <project_dir> --screen [--ref <файл>] [--md <файл.md>]
  py -3 edit_dataset.py <project_dir> --pick --trigger <слово>
                        [--per-plan 5] [--min-cos <число>] [--out <папка>]

Три шага, и разделены они намеренно: между ними человек смотрит глазами.
СБОРКА гоняет эдит-граф по осям разнообразия, СКРИН меряет каждый кадр на
совпадение с референсом, ОТБОР складывает выживших в папку для обучения.

ЗАЧЕМ ЭДИТ, А НЕ ТЕКСТ. Замерено на этом же проекте: одна карточка даёт пять
разных женщин одного типажа — текст задаёт типаж, а не человека. Лора,
обученная на таком наборе, выучивает типаж, то есть ровно ту проблему, ради
которой её и заводят. Лицо существует только на референсе, поэтому каждый кадр
датасета — эдит референса, а не генерация по описанию.

ПОЧЕМУ ОТБОР ИДЁТ ВНУТРИ ПЛАНА, А НЕ ПО ВСЕМУ НАБОРУ. Косинус ArcFace растёт с
крупностью лица: на портрете он всегда выше, чем на ростовом плане, потому что
лица там больше пикселей. Отбор по общему порогу поэтому оставил бы одни
портреты — и лора, никогда не видевшая это лицо мелким, рисовала бы на общем
плане чужого человека. Порог считается ВНУТРИ каждого плана по его же
медиане, и квота на план задаётся отдельно.

ЗДЕСЬ БЫЛА ВКЛЕЙКА РОДИНКИ, И ЕЁ БОЛЬШЕ НЕТ. Родинку сняли с карточки
14.08.2026; вместе с ней снят и весь её шаг. В датасет теперь уходит то, что
эдит нарисовал сам, плюс прививка настоящей кожи — и ни одного признака,
который мы бы сначала вклеили, а потом требовали от модели обратно.
"""
import os
import sys
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (setup_console, cli_opt, work_dir, read_json, write_json,
                   project_name)          # noqa: E402
import comfy_client as cc                            # noqa: E402

TEMPLATE = "krea2_identity_edit_api.json"

# Ручки шаблона одной таблицей — поменяется шаблон, правится она.
KNOB = {
    "ref": "5.image",
    "ref_b": "15.image",
    "prompt": "9.prompt",
    "seed": "12.seed",
    "steps": "12.steps",
    "cfg": "12.cfg",
    "width": "11.width",
    "height": "11.height",
    "prefix": "14.filename_prefix",
    "ref_boost": "8.ref_boost",
    "lora": "4.lora_name",
}

RAW = "dataset_raw"
LEDGER = "frames.json"


def parse_refs(spec):
    """`--ref` → {план: файл}. Либо один путь, либо список `план=путь`.

    РЕФЕРЕНС ЗАВИСИТ ОТ ПЛАНА, И ЭТО НЕ УДОБСТВО, А ТОЧНОСТЬ. Портрету нужен
    кроп лица: там лицо занимает тысячу пикселей, и зрячий энкодер видит форму
    век, губ и бровей. Ростовому плану нужна вся фигура: с одного кроп-портрета
    модель придумает и рост, и сложение, и посадку плеч — то есть половину
    внешности человека. Один референс на все планы означает, что одну из этих
    половин мы отдаём на выдумку.
    """
    if not spec:
        return {}
    if "=" not in spec:
        return {"*": spec}
    out = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise SystemExit(
                f"в --ref кусок {part!r} без знака «=». Либо один путь на все "
                f"планы, либо список\n  вида portrait=лицо.png,full=фигура.png "
                f"— смешивать нельзя, иначе непонятно, что чему.")
        plan, path = part.split("=", 1)
        # `фигура.png|лицо.png` — два референса: сцена первой, субъект вторым,
        # в том порядке, в каком лора обучена. Один путь = один референс.
        pair = [p.strip() for p in path.split("|") if p.strip()]
        if len(pair) > 2:
            raise SystemExit(f"у плана {plan.strip()} больше двух референсов: "
                             f"{path!r}. Их ровно два — сцена и субъект.")
        out[plan.strip()] = tuple(pair) if len(pair) == 2 else pair[0]
    return out


def _pair(refs, plan):
    """(сцена, субъект|None) для плана."""
    v = refs.get(plan, refs.get("*"))
    return v if isinstance(v, tuple) else (v, None)


def drop_second_ref(graph):
    """Выкинуть узлы второго референса и ссылки на них.

    ВЫКИНУТЬ, А НЕ ПОДСУНУТЬ ТОТ ЖЕ ФАЙЛ. Второй референс — это не «ещё одна
    подсказка», а второй кадр в позиционном кодировании, на порядок которого
    лора и обучена. Продублировать в него сцену значит сказать модели «субъект
    — это вся сцена целиком», а оставить узел висеть без ссылки значит уронить
    валидацию графа на сервере.
    """
    for node in graph.values():
        for key in ("image_b", "source_image_b"):
            node.get("inputs", {}).pop(key, None)
    for nid in ("15", "16"):
        graph.pop(nid, None)
    return graph


def check_refs(refs, cells):
    """Каждый план знает свой файл, и файл существует. Без умолчаний в коде."""
    plans = sorted({c["plan"] for c in cells})
    if "*" not in refs:
        miss = [p for p in plans if p not in refs]
        if miss:
            raise SystemExit(
                f"в --ref нет референса для планов: {', '.join(miss)}.\n"
                f"  Либо допишите их, либо задайте общий одним путём без "
                f"«=» — но общий кроп\n  лица на ростовом плане означает, что "
                f"фигуру модель придумает сама.")
    for plan in plans:
        for p in _pair(refs, plan):
            if p and not os.path.isfile(p):
                raise SystemExit(f"референс плана {plan} не найден: {p}")


def load_axes(project_dir, path=None):
    """Оси разнообразия. Отдельный файл, а не поле раскадровки: раскадровка —
    это СДАЧА, а датасет к сдаче отношения не имеет и живёт своей жизнью."""
    path = path or os.path.join(project_dir, "dataset_axes.json")
    if not os.path.isfile(path):
        raise SystemExit(
            f"нет файла осей {path}.\n"
            f"  Это список клеток датасета: план, размер кадра и указание "
            f"эдиту. Образец — projects/bridget/dataset_axes.json.")
    ax = read_json(path)
    if not ax.get("cells"):
        raise SystemExit(f"{path}: пустой список cells")
    for c in ax["cells"]:
        miss = [k for k in ("id", "plan", "w", "h", "prompt") if k not in c]
        if miss:
            raise SystemExit(f"{path}: клетка {c.get('id', '?')} без {miss}")
    return ax


def make_plate(plate_prompt, size, seed, out_dir, name):
    """ПОДЛОЖКА: чужой кадр с нужной позой, светом и эмоцией. Возвращает путь.

    ЗАЧЕМ ОНА ПОЯВИЛАСЬ. Ручка сходства ref_boost тянет к референсу не только
    внешность, но и ПОЗУ: на рабочем значении 8.0 кадр сползает к фронтальному
    нейтральному лицу базы, что бы ни было написано в указании. Датасет из
    такого набора учит лору одному ракурсу и одному выражению — то есть ровно
    тому, чего в датасете быть не должно.

    Нода эдита разводит это сама, и я этим не пользовалась: у неё ДВА
    референса, «сцена» и «субъект», в порядке обучения лоры. Сценой я подавала
    ту же фигуру персонажа — и получала его позу. Сценой должна быть отдельная
    подложка: обычный t2i-кадр женщины того же возраста в нужной позе, свете и
    настроении, БЕЗ единого слова о внешности нашего человека. Лицо приезжает
    вторым референсом, и ref_boost тянет только его.

    Подложка — расходник: она нужна ровно на один прогон эдита и в датасет не
    попадает.
    """
    import generate as G
    graph = G.build_graph(plate_prompt, seed, size, f"plate/{name}", "indoor")
    files = cc.run_graph(graph, out_dir)
    if not files:
        raise RuntimeError(f"{name}: воркер не вернул подложку")
    return blank_face(files[0])


def blank_face(path):
    """Стереть ЛИЦО подложки, оставив голову, волосы и позу. Возвращает путь.

    БЕЗ ЭТОГО ДВЕ СТУПЕНИ НЕ РАБОТАЮТ, И ЭТО ЗАМЕРЕНО. Подложка — кадр ЧУЖОЙ
    женщины, и её лицо конкурирует с нашим референсом за одно и то же место в
    обусловливании: косинус к базе падает с 0.713 (одна ступень) до 0.308 (две
    ступени, подложка как есть). Ракурс выигран, человек потерян.

    Стирается ровно овал лица и ровно размытием: заливка плашкой оставила бы
    резкий край, за который эдит цепляется и рисует по нему маску. Волосы,
    шея, плечи и одежда остаются — они и есть поза, причёска и композиция,
    ради которых подложка затевалась. Овал берётся с запасом вниз: подбородок
    и линия челюсти тоже несут внешность.
    """
    import numpy as np, cv2
    from _util import imread, imwrite
    from metrics import faces as F
    img = imread(path)
    f = F.detect(path)
    if img is None or f["state"] != "PASS" or f.get("kps106") is None:
        return path                      # лица нет — стирать нечего
    k = np.asarray(f["kps106"], np.float32)
    ipd = float(f["ipd_px"])
    m = np.zeros(img.shape[:2], np.uint8)
    cv2.fillConvexPoly(m, cv2.convexHull(k[0:33].astype(np.int32)), 255)
    m = cv2.dilate(m, np.ones((3, 3), np.uint8),
                   iterations=max(1, int(ipd * 0.10)))
    m = cv2.GaussianBlur(m, (0, 0), max(2.0, ipd * 0.12)).astype(np.float32) / 255.0
    soft = cv2.GaussianBlur(img, (0, 0), max(3.0, ipd * 0.28))
    out = (img.astype(np.float32) * (1 - m[..., None])
           + soft.astype(np.float32) * m[..., None])
    imwrite(path, np.clip(out, 0, 255).astype(np.uint8))
    return path


def build(project_dir, ref, axes_path=None, seeds=None, only=None, dry=False):
    """Прогнать эдит-граф по осям. Возвращает реестр собранных кадров."""
    ax = load_axes(project_dir, axes_path)
    project = project_name(project_dir)
    cells = ax["cells"]
    if only:
        want = {s.strip() for s in only.split(",") if s.strip()}
        cells = [c for c in cells if c["id"] in want]
        if not cells:
            raise SystemExit(f"ни одна клетка не совпала с {sorted(want)}; "
                             f"есть: {[c['id'] for c in ax['cells']]}")
    n_seeds = seeds or int(ax.get("seeds_per_cell", 2))
    base = (ax.get("base") or "").strip()
    check_refs(ref, cells)

    out_root = work_dir(project, RAW)
    if dry:
        print(f"план: {len(cells)} клеток x {n_seeds} сидов = "
              f"{len(cells) * n_seeds} кадров\n  приёмник: {out_root}")
        for plan in sorted({c["plan"] for c in cells}):
            scene, subj = _pair(ref, plan)
            print(f"  референс плана {plan:8} сцена {os.path.basename(scene)}"
                  + (f" + субъект {os.path.basename(subj)}" if subj
                     else "  (второго нет)"))
        print()
        for c in cells:
            print(f"  {c['id']:5} {c['plan']:8} {c['w']}x{c['h']}  "
                  f"{c['prompt'][:70]}")
        return None

    cc.preflight()
    ledger_path = os.path.join(out_root, LEDGER)
    ledger = read_json(ledger_path) if os.path.isfile(ledger_path) else []
    ledger = [e for e in ledger if os.path.exists(e.get("file", ""))]

    # Каждый файл заливается ОДИН раз, сколько бы клеток на него ни ссылалось.
    # Референсы — единственное, что конвейер оставляет на чужой машине: кадры
    # забираются из temp и там не оседают.
    plate_base = (ax.get("plate_base") or "").strip()
    uploaded = {}
    for cell in cells:
        for src in _pair(ref, cell["plan"]):
            if src and src not in uploaded:
                uploaded[src] = cc.upload(src)
                print(f"референс на воркере: {uploaded[src]}  "
                      f"({os.path.basename(src)})")

    plate_dir = work_dir(project, "plates")

    for cell in cells:
        src, subj = _pair(ref, cell["plan"])
        # С ПОДЛОЖКАМИ РОЛИ МЕНЯЮТСЯ. Сценой становится сгенерированный кадр, а
        # переданный референс целиком уходит в субъект: тянуть надо ЛИЦО, а
        # позу и свет даёт подложка. Поэтому одиночный путь здесь означает не
        # «сцена», как в прежнем режиме, а «лицо».
        if plate_base and not subj:
            subj = src
        cell_seeds = [random.randint(1, 2 ** 31 - 1) for _ in range(n_seeds)]
        cell_dir = os.path.join(out_root, cell["plan"])
        prompt = ", ".join(x for x in (base, cell["prompt"]) if x)
        for seed in cell_seeds:
            # ДВЕ СТУПЕНИ. Сначала подложка задаёт позу, свет и эмоцию, потом
            # эдит ставит на неё наше лицо. Без подложки сценой служит сам
            # референс, и его поза копируется во все кадры датасета.
            if plate_base and subj:
                plate = make_plate(", ".join([plate_base, cell["prompt"]]),
                                   (cell["w"], cell["h"]), seed, plate_dir,
                                   f"{cell['id']}_s{seed}")
                scene_ref = cc.upload(plate)
            else:
                scene_ref = uploaded[src]
            graph = cc.load_template(TEMPLATE)
            if not subj:
                drop_second_ref(graph)
            else:
                cc.apply_sets(graph, {KNOB["ref_b"]: uploaded[subj]})
            cc.apply_sets(graph, {
                KNOB["ref"]: scene_ref,
                KNOB["prompt"]: prompt,
                KNOB["seed"]: seed,
                KNOB["width"]: int(cell["w"]),
                KNOB["height"]: int(cell["h"]),
                KNOB["prefix"]: f"{cell['id']}_s{seed}",
            })
            files = cc.run_graph(graph, cell_dir)
            for f in files:
                ledger = [e for e in ledger if e.get("file") != f]
                ledger.append({"file": f, "cell": cell["id"],
                               "plan": cell["plan"], "seed": seed,
                               "size": [int(cell["w"]), int(cell["h"])],
                               "prompt": prompt, "ref": os.path.abspath(src),
                               "ref_subject": (os.path.abspath(subj) if subj
                                               else None)})
            print(f"  {cell['id']} s{seed}: {len(files)} кадр(ов)")
        write_json(ledger_path, ledger)

    print(f"\nсобрано {len(ledger)} кадров\n  → {out_root}")
    return ledger


def screen(project_dir, ref=None, md=None):
    """Замер каждого кадра на совпадение с референсом. Ничего не удаляет.

    НЕ УДАЛЯЕТ НАМЕРЕННО: отбор — отдельный шаг с квотой по планам, а между
    замером и отбором обязан быть человек с контактным листом. Автоматическое
    удаление по числу здесь означало бы, что косинусу доверяют больше, чем
    глазу, — а на этом же проекте измерено, что он не отделяет одного человека
    от нескольких похожих.
    """
    from metrics import faces
    from metrics import artifacts
    project = project_name(project_dir)
    root = work_dir(project, RAW)
    ledger_path = os.path.join(root, LEDGER)
    if not os.path.isfile(ledger_path):
        raise SystemExit(f"нет реестра {ledger_path} — сначала соберите кадры")
    ledger = read_json(ledger_path)
    ref = ref or (ledger[0].get("ref") if ledger else None)
    if not ref or not os.path.isfile(ref):
        raise SystemExit(f"референс не найден: {ref!r}; передайте --ref")

    r = faces.detect(ref)
    if r["state"] != "PASS":
        raise SystemExit(f"на референсе лицо не найдено: {r['note']}")
    base_emb = r["embedding"]
    print(f"референс: {os.path.basename(ref)}, возраст детектора {r['age']}, "
          f"IPD {r['ipd_px']:.0f} px\n")

    rows = []
    for e in ledger:
        if not os.path.exists(e["file"]):
            continue
        f = faces.detect(e["file"])
        row = dict(e)
        if f["state"] != "PASS":
            row.update(cos=None, age=None, ipd=None, why=f["note"])
        else:
            # ПРИЗНАКИ РИСОВАННОГО КАДРА меряются здесь же, одним проходом:
            # волосы-ленты, фон-каша, разъезжающийся взгляд. Косинус про них
            # не знает ничего — кадр может быть безупречно похож и при этом
            # выдавать себя волосами, а лора выучит именно их.
            a = artifacts.measure(e["file"], face=f)
            row.update(cos=faces.cosine(f["embedding"], base_emb),
                       age=f["age"], ipd=f["ipd_px"],
                       faces_in_frame=f.get("faces_in_frame", 1), why="",
                       hair=a["hair"], background=a["background"],
                       gaze=a["gaze"])
        rows.append(row)
        print(f"  {os.path.basename(e['file']):40} {e['plan']:8} "
              + (f"косинус {row['cos']:.4f}  возраст {row['age']:2d}  "
                 f"IPD {row['ipd']:4.0f}"
                 + ("  ← ЛИЦ В КАДРЕ "
                    f"{row['faces_in_frame']}" if row.get("faces_in_frame", 1) > 1
                    else "") if row["cos"] is not None
                 else f"НЕ ЗАМЕРЕН — {row['why'][:44]}"))

    write_json(os.path.join(root, "screen.json"), rows)
    _summary(rows, md, project)
    return rows


def _by_plan(rows):
    out = {}
    for r in rows:
        out.setdefault(r["plan"], []).append(r)
    return out


def _summary(rows, md=None, project=""):
    good = [r for r in rows if r.get("cos") is not None]
    print(f"\nзамерено {len(good)} из {len(rows)}")
    if not good:
        return
    lines = [f"# Датасет из референса: {project}", "",
             "| план | кадров | косинус мин | медиана | макс | возраст |",
             "|---|---|---|---|---|---|"]
    for plan, rs in sorted(_by_plan(good).items()):
        cs = sorted(r["cos"] for r in rs)
        ages = [r["age"] for r in rs if r["age"] is not None]
        med = cs[len(cs) // 2]
        print(f"  {plan:8} n={len(cs):3}  косинус {cs[0]:.3f}…{cs[-1]:.3f}, "
              f"медиана {med:.3f}"
              + (f"  возраст {min(ages)}-{max(ages)}" if ages else ""))
        lines.append(f"| {plan} | {len(cs)} | {cs[0]:.3f} | {med:.3f} | "
                     f"{cs[-1]:.3f} | "
                     + (f"{min(ages)}–{max(ages)} |" if ages else "— |"))
    if md:
        os.makedirs(os.path.dirname(os.path.abspath(md)), exist_ok=True)
        with open(md, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        print(f"\nотчёт: {md}")


def pick(project_dir, trigger, per_plan=5, min_cos=None, out=None):
    """Отобрать выживших по квоте на план, привить кожу, написать подписи."""
    from skin_graft import graft
    project = project_name(project_dir)
    root = work_dir(project, RAW)
    rows = read_json(os.path.join(root, "screen.json"))
    good = [r for r in rows if r.get("cos") is not None]
    if not good:
        raise SystemExit("ни один кадр не замерен — сначала --screen")
    out = out or work_dir(project, "dataset")
    os.makedirs(out, exist_ok=True)

    # КАДР С ДВУМЯ ЛИЦАМИ В ДАТАСЕТ НЕ ИДЁТ. Обучение не знает, кого из них
    # мы называем триггером: второй человек попадает в те же веса, и дальше
    # лора тянет его в кадр — чаще всего как «кто-то на фоне», которого никто
    # не просил. Отсев именно здесь, а не в скрине: скрин ничего не удаляет.
    crowd = [r for r in good if (r.get("faces_in_frame") or 1) > 1]
    good = [r for r in good if (r.get("faces_in_frame") or 1) <= 1]
    for r in crowd:
        print(f"  вне датасета: {os.path.basename(r['file'])} — в кадре "
              f"{r['faces_in_frame']} лица")

    # ХУДШАЯ ПЯТАЯ ЧАСТЬ ПО КАЖДОМУ ПРИЗНАКУ РИСОВАННОСТИ ВЫЛЕТАЕТ. Порог
    # относительный, а не абсолютный, и это осознанно: абсолютное число здесь
    # означало бы, что «нейрослоп» — величина, известная заранее, а он зависит
    # и от сцены, и от плана. Относительный порог всегда бракует худшее, что
    # есть в этом конкретном прогоне, и не может забраковать всё.
    for key, name in (("hair", "волосы-ленты"), ("background", "фон-каша"),
                      ("gaze", "разъезжается взгляд")):
        vals = sorted(r[key] for r in good if r.get(key) is not None)
        if len(vals) < 10:
            continue
        cut = vals[int(len(vals) * 0.8)]
        bad = [r for r in good if r.get(key) is not None and r[key] > cut]
        good = [r for r in good if r not in bad]
        for r in bad:
            print(f"  вне датасета: {os.path.basename(r['file'])} — {name} "
                  f"{r[key]:.3f} при пороге {cut:.3f}")

    taken, dropped = [], 0
    for plan, rs in sorted(_by_plan(good).items()):
        rs.sort(key=lambda r: -r["cos"])
        # Порог считается ВНУТРИ плана: у портрета и ростового кадра косинус
        # живёт на разных уровнях, и общее число выбросило бы весь дальний план.
        floor = min_cos if min_cos is not None else \
            rs[len(rs) // 2]["cos"] * 0.985
        keep = [r for r in rs if r["cos"] >= floor][:per_plan]
        dropped += len(rs) - len(keep)
        print(f"  {plan:8} порог {floor:.3f} → взято {len(keep)} из {len(rs)}")
        taken += keep

    for i, r in enumerate(taken):
        dst = os.path.join(out, f"{r['cell']}_{i:02d}.png")
        # ПРИВИВКА КОЖИ ДО ОБУЧЕНИЯ. Датасет — это то, что лора выучит
        # наизусть, поэтому фактура настоящей кожи обязана быть в НЁМ, а не
        # навешиваться потом на каждый кадр.
        graft(r["file"], out=dst, seed=i)
        with open(os.path.splitext(dst)[0] + ".txt", "w", encoding="utf-8") as fh:
            fh.write(f"{trigger}, {r['prompt']}\n")

    # ПАСПОРТ ДАТАСЕТА рядом с кадрами — тем же именем и с теми же полями, что
    # пишет lora_dataset.py. Не для порядка: по нему lora_train.py сверяет
    # ТРИГГЕР, слово подписей против слова ключа. Без файла сверка честно
    # отвечает NOT_MEASURED, и обучение уходит с триггером, которого в подписях
    # может и не быть, — а лора, обученная не на то слово, не включается, и
    # тихо не включившаяся лора неотличима от отсутствующей.
    write_json(os.path.join(out, "dataset.json"), {
        "project": project, "trigger": trigger, "out": out,
        "source": "edit_dataset.py — эдит референса, а не генерация по тексту",
        "per_plan": per_plan, "min_cos": min_cos,
        "files": sorted(f for f in os.listdir(out) if f != "dataset.json"),
        "frames": [{"file": os.path.basename(r["file"]), "cell": r["cell"],
                    "plan": r["plan"], "cos": r["cos"], "age": r["age"],
                    "ref": r.get("ref"), "ref_subject": r.get("ref_subject")}
                   for r in taken],
    })

    print(f"\nв датасете {len(taken)} кадров (отброшено {dropped})\n"
          f"  → {out}\n"
          f"  дальше: py -3 scripts/lora_train.py create {project_dir} "
          f"--local {out} --trigger {trigger}")
    return out


def main():
    setup_console()
    args = sys.argv[1:]
    if not args or args[0].startswith("--"):
        print(__doc__)
        raise SystemExit(1)
    project_dir = args[0]

    if "--screen" in args:
        screen(project_dir, cli_opt(args, "--ref"), cli_opt(args, "--md"))
        return
    if "--pick" in args:
        trigger = cli_opt(args, "--trigger")
        if not trigger:
            raise SystemExit(
                "--pick без --trigger: подпись кадра начинается с триггера, и "
                "лора, обученная без него,\n  не включается словом в промпте — "
                "а не включившаяся лора неотличима от отсутствующей.")
        mc = cli_opt(args, "--min-cos")
        pick(project_dir, trigger, int(cli_opt(args, "--per-plan", "5")),
             float(mc) if mc else None, cli_opt(args, "--out"))
        return

    refs = parse_refs(cli_opt(args, "--ref"))
    if not refs:
        raise SystemExit("--ref обязателен: эдит-граф без референса — это "
                         "обычная генерация по описанию, а она даёт типаж")
    seeds = cli_opt(args, "--seeds")
    build(project_dir, refs, cli_opt(args, "--axes"),
          int(seeds) if seeds else None, cli_opt(args, "--only"),
          "--dry" in args)


if __name__ == "__main__":
    main()
