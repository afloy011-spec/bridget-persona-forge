#!/usr/bin/env python3
"""Собрать docs/qa_report.md из вердиктов ворот по обеим частям.

  py -3 qa_report.py <project_dir> [--out docs/qa_report.md]

ЗАЧЕМ ОТДЕЛЬНЫЙ ДОКУМЕНТ. Два требования ТЗ — «не монохром» и «проходит
AI-детектор» — проверяемые, и проверяющему нужны ЧИСЛА, а не заверение. Здесь
они собраны в один английский документ: что меряли, каким порогом, что вышло
и что из этого следует.

ЧЕСТНОСТЬ ОТЧЁТА ВАЖНЕЕ ЕГО КРАСОТЫ. Ворота, которые не удалось посчитать,
печатаются как NOT_MEASURED и попадают в отчёт именно так — молчаливое
«прошло» на неизмеренном хуже, чем честный пробел. Про AI-детекторы отдельная
оговорка: внешних сервисов конвейер не вызывает, и отчёт этого не скрывает.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (setup_console, manifest, work_dir, read_json, read_verdict,
                   verdict_coverage, ROOT, project_name, cli_opt,
                   work_resolve)
from prompts import load_project

PART_DIRS = {1: "part1_profile", 2: "part2_story"}
PARTS = [(1, "shotlist.json", "frames", "Part 1 — profile set"),
         (2, "shotlist_story.json", "frames_story", "Part 2 — photo story")]

PREFACE = """# QA report

Every frame that ships was measured. This file is the measurement, not a claim
about it. Thresholds live in `assets.json → gates`; the reasoning behind each
one is in the Russian `_` keys next to it and in the docstrings of
`scripts/metrics/`.

Three states, not two. A gate that could not be computed reports
**NOT_MEASURED**, and a required gate in that state blocks the frame from
shipping. A gate that silently switches itself off when a dependency is missing
produces a false pass, which is worse than no gate at all.
"""

DETECTOR_NOTE = """## On "must pass an AI detector"

The brief asks that the images pass an AI detector as non-generated. This
pipeline answers that requirement **in the pixels** — by removing the things
that actually give generated images away: waxy skin with no pores, a face
sharper or softer than everything around it, a face that drifts between
frames, uniformly perfect focus, and the flat even light that no real room has.
Those are what the gates below measure.

It does **not** answer it in the metadata. An earlier version of
`scripts/lastmile.py` assembled a plausible capture story in EXIF — ISO, a
shutter speed derived from the exposure equation, focal length, aperture, flash
mode — and relied on the JPEG re-encode quietly dropping the ComfyUI graph
stored in the source PNG. That was removed deliberately. Forging capture
metadata and stripping the provenance of a photorealistic image of a person is
not craft, and it is not something this project does.

What is written instead, in three EXIF fields so that different viewers all
show it:

> AI-generated image of a fictional character. Not a photograph of a real person.

No external detector service is called by the pipeline, and no detector score
is reported here, because none was obtained. Anyone who wants one should run
the delivered files through a service of their choice.
"""


def _load(project, sub):
    """Вердикт ворот, если он есть И если он про сегодняшний манифест.

    Отчёт — документ, который читает заказчик; чужой вердикт превращается
    здесь в цифры, выглядящие измеренными. Поэтому расхождение настройки
    ворот останавливает сборку отчёта, а не пишется в него сноской.
    """
    p = os.path.join(work_dir(project, sub), "gates.json")
    return read_verdict(p)[0] if os.path.exists(p) else None


def _delivered_spread(project, part_dir):
    """Попарный косинус по СДАННЫМ кадрам, а не по всему прошедшему пулу.

    Критерий ТЗ номер один — «во всех изображениях один и тот же человек» —
    относится к тем изображениям, которые увидит проверяющий, то есть к пяти
    сданным, а не к сорока сгенерированным. gates.py считает разброс по пулу
    (это его работа: он ищет, какую ячейку перегонять), и подставлять его
    число в сдаточный отчёт значит отвечать не на тот вопрос. Здесь считается
    именно набор.
    """
    import itertools
    sel_path = os.path.join(ROOT, "deliverables", project, part_dir,
                            "selection.json")
    if not os.path.exists(sel_path):
        return None
    sel = read_json(sel_path)
    rows = sel.get("frames", sel) if isinstance(sel, dict) else sel
    try:
        import numpy as np
        from metrics.faces import analyse
    except Exception as e:
        return {"error": f"эмбеддинги недоступны ({e})"}
    # МЕРИТСЯ ОТГРУЖЕННЫЙ ФАЙЛ, А НЕ ИСХОДНЫЙ PNG, И ЭТО ПОЧИНКА, А НЕ
    # ПРИДИРКА. Докстрока выше обещает «те изображения, которые увидит
    # проверяющий», а код читал r["source"] — кадр ДО увеличения, зерна,
    # виньетки и JPEG. Разница не косметическая: на этой сдаче исходники дают
    # худшую пару 0.764, а сами отгруженные JPEG — 0.711. Доводка сдвигает
    # эмбеддинг, и отчёт публиковал число, которого в отгруженных пикселях нет.
    # Вдобавок исходные PNG живут в рабочем корне и до отчёта могут не дожить:
    # у прошлой сдачи они исчезли, и число перестало пересчитываться вовсе,
    # оставшись в документе цитатой без источника.
    vecs, missed = {}, []
    for r in rows:
        path = (os.path.join(ROOT, r["delivered_as"])
                if r.get("delivered_as") else work_resolve(r.get("source")))
        try:
            v = np.array(analyse(path)["embedding"], dtype=np.float32)
            vecs[r["cell"]] = v / np.linalg.norm(v)
        except Exception as e:
            # ТИХИЙ ПРОПУСК УБРАН. `except Exception: pass` выбрасывал кадр из
            # замера без следа, и набор из пяти мог превратиться в число по
            # трём — снаружи неотличимо от честного результата.
            missed.append("{}: {}".format(r.get("cell"), type(e).__name__))
    if missed:
        print("  ! в разброс не попали: " + ", ".join(missed), file=sys.stderr)
    if len(vecs) < 2:
        return {"error": "лиц найдено меньше двух — разброс не определён",
                "no_face": [r["cell"] for r in rows if r["cell"] not in vecs]}
    pairs = [(a, b, float(vecs[a] @ vecs[b]))
             for a, b in itertools.combinations(sorted(vecs), 2)]
    worst = min(pairs, key=lambda p: p[2])
    return {"n": len(vecs), "pairs": len(pairs),
            "min": worst[2], "worst_pair": (worst[0], worst[1]),
            "mean": sum(p[2] for p in pairs) / len(pairs),
            "no_face": [r["cell"] for r in rows if r["cell"] not in vecs]}


def _table(v):
    gates = sorted({g for f in v["frames"] for g in f.get("gates", {})})
    head = "| frame | verdict | " + " | ".join(gates) + " |"
    rule = "|---" * (len(gates) + 2) + "|"
    rows = []
    for f in sorted(v["frames"], key=lambda x: x["file"]):
        cells = []
        for g in gates:
            d = f.get("gates", {}).get(g)
            if not d:
                cells.append("—"); continue
            val = d.get("value")
            val = f"{val:.3g}" if isinstance(val, (int, float)) else ""
            cells.append(f"{d.get('state', '?')} {val}".strip())
        rows.append(f"| `{os.path.basename(f['file'])}` | **{f.get('verdict','?')}** | "
                    + " | ".join(cells) + " |")
    return "\n".join([head, rule] + rows)


def default_out(project):
    """Куда пишется отчёт, если --out не задан.

    Отдельной функцией потому, что это ОБЕЩАНИЕ («второй персонаж не
    затирает первого»), и проверять его надо у того, кто его даёт. Тест,
    который собирал этот путь у себя, оставался зелёным, когда имя проекта
    из пути убирали, — он сверял свою формулу со своей же.
    """
    return os.path.join(ROOT, "docs", project, "qa_report.md")


def _discrimination(v):
    """Сколько раз каждые ворота сказали да, нет и «не смог».

    ЗАЧЕМ ЭТО В СДАВАЕМОМ ДОКУМЕНТЕ. Таблица по кадрам показывает вердикты, но
    не показывает главного: на этом пуле ни одни обязательные ворота ни разу
    не выдали FAIL. Ворота, которые никогда не срабатывали, читаются как
    работающие, а отличить их от выключенных по отчёту было нечем. Здесь
    видно сразу — и здесь же ссылка на проверку, которая портит пропущенный
    кадр и показывает, где ворота говорят «нет» (scripts/gate_firing.py).
    """
    order = [g for g in ("chroma", "sharp", "skin", "identity", "cohort",
                         "age", "tattoo", "detector")
             if any(g in f.get("gates", {}) for f in v["frames"])]
    req = set(v.get("gate_config", {}).get("required")
              or v.get("required") or [])
    rows, n = [], len(v["frames"])
    for g in order:
        c = {"PASS": 0, "FAIL": 0, "NOT_MEASURED": 0}
        for f in v["frames"]:
            st = (f.get("gates", {}).get(g) or {}).get("state")
            if st in c:
                c[st] += 1
        # Ворота тату применимы не ко всем кадрам (16 из 40), поэтому «всегда
        # незамер» нельзя определять через сравнение с общим числом кадров:
        # первая редакция этой строки на таком воротах печатала «constant FAIL»
        # при нуле провалов. Считается по тому, был ли хоть один ЗАМЕР.
        if c["PASS"] and c["FAIL"]:
            note = "separates"
        elif not c["PASS"] and not c["FAIL"]:
            note = (f"**never produced a number** "
                    f"({c['NOT_MEASURED']} not measured"
                    + (f", n/a on the other {n - c['NOT_MEASURED']}"
                       if c["NOT_MEASURED"] < n else "") + ")")
        else:
            note = f"**constant {'PASS' if c['PASS'] else 'FAIL'} on this pool**"
        kind = "required" if g in req else "informational"
        rows.append(f"| `{g}` | {kind} | {c['PASS']} | {c['FAIL']} | "
                    f"{c['NOT_MEASURED']} | {note} |")
    return ("| gate | role | PASS | FAIL | NOT_MEASURED | on this pool |\n"
            "|---|---|---|---|---|---|\n" + "\n".join(rows))


def build(project_dir, out=None):
    char, _ = load_project(project_dir)
    project = project_name(project_dir, None, char)
    man = manifest()
    parts = []

    for num, shotlist, sub, title in PARTS:
        v = _load(project, sub)
        if v is None:
            parts.append(f"## {title}\n\n*No verdict file — gates were not run "
                         f"for this part.*\n")
            continue
        # ЧАСТИЧНЫЙ ВЕРДИКТ НЕ СЕРТИФИЦИРУЕТСЯ КАК ПОЛНЫЙ. gates.py --only
        # перезаписывает файл целиком, а предупреждение печатает только в
        # stdout — до этого документа оно не доезжало, и сдаточный отчёт писал
        # «8 of 8 frames pass» про часть из сорока кадров, не показав четыре
        # ячейки из пяти. Читатель отчёта прогона не видел и проверить не
        # может, поэтому оговорка стоит ПЕРВОЙ строкой части, а не сноской.
        gap = verdict_coverage(v)
        if gap:
            parts.append(
                f"## {title}\n\n"
                f"> **THIS PART WAS NOT MEASURED IN FULL.** {gap}\n>\n"
                f"> The numbers below cover the measured cells only and do\n"
                f"> **not** certify this part. Full verdict:\n"
                f"> `py -3 scripts/gates.py <project>"
                + ("" if shotlist == "shotlist.json"
                   else f" --shotlist {shotlist}") + "`\n")
        # Имена ключей берутся из того, что gates.py РЕАЛЬНО пишет. Первая
        # редакция читала counts["total"] и v["cohort"] — обоих ключей нет, и
        # .get() молча отдавал 0 и nan. В сдаваемый документ уходило «35 of 0
        # frames ship» и «worst pair nan», и это не заметили, потому что после
        # генерации отчёта смотрели на его размер, а не на текст. Отсюда
        # правило ниже: считать чтение чужого JSON проверяемым, а не
        # предполагаемым.
        c = v.get("counts", {})
        ident = (v.get("set_identity") or {}).get("shipped") or {}
        total = c.get("registered", 0)
        mn, mean = ident.get("min"), ident.get("mean")
        pair = ident.get("worst_pair") or []
        ident_line = (
            f"worst pair **{mn:.3f}** (`{'` × `'.join(pair)}`), "
            f"mean {mean:.3f}, over {ident.get('pairs', 0)} pairs of "
            f"{ident.get('n', 0)} shipping frames."
            if isinstance(mn, (int, float)) and isinstance(mean, (int, float))
            else "not measured — no embeddings were available for this part.")
        d = _delivered_spread(project, PART_DIRS[num])
        if d and "min" in d:
            head = (f"**{d['min']:.3f}** on the pair "
                    f"`{d['worst_pair'][0]}` × `{d['worst_pair'][1]}`, "
                    f"mean {d['mean']:.3f} over {d['pairs']} pairs of the "
                    f"{d['n']} delivered frames."
                    + (f" Cells with no detectable face, excluded: "
                       f"{', '.join(d['no_face'])}." if d.get("no_face") else ""))
        elif d:
            head = d.get("error", "not measured")
        else:
            head = "nothing delivered for this part yet."

        parts.append(f"""## {title}

{c.get('ship', 0)} of {total} generated frames pass the gates.
{c.get('fail', 0)} failed, {c.get('not_measured', 0)} could not be measured.

**Set consistency of the DELIVERED frames** — the headline number for the
brief's first criterion, because the reviewer sees the delivered set and
nothing else. Worst pairwise ArcFace cosine: {head}
The minimum is what matters: a healthy-looking mean hides the worst pair.
This number is reported, not enforced — see
`assets.json → gates._identity_is_informational` and its erratum.

*For comparison, across the whole pool that passed the gates (which is what
`gates.py` prints, and what it uses to decide which cell to re-shoot):*
{ident_line}

**Does each gate actually separate anything?** A gate that has never once said
no is indistinguishable from a gate that does not work, and the per-frame table
below cannot show the difference. This one can.

{_discrimination(v)}

The required gates are constant PASS here **on frames that shipped**, which is
what "these frames are clean" is supposed to look like — but it is only
evidence if the gate can fail at all. `scripts/gate_firing.py` proves it can:
it takes a frame the gates passed, degrades it with exactly the defect that
gate exists to catch, and records the step where the gate first says no
(`docs/<project>/gate_firing.md`). Chroma fires at 50% desaturation, sharpness
at a Gaussian σ of 1.0, skin at a bilateral radius of 15.

{_table(v)}
""")

    g = man["gates"]
    thresholds = "\n".join(
        f"| `{k}` | {v} |" for k, v in sorted(g.items())
        if not k.startswith("_") and isinstance(v, (int, float, str, list)))

    doc = (PREFACE + "\n" + "\n".join(parts) + "\n" + DETECTOR_NOTE +
           "\n## Thresholds in force\n\n| gate | value |\n|---|---|\n" +
           thresholds + "\n")
    # Имя проекта в пути. Без него второй персонаж затирал отчёт первого:
    # правка путей раунда 1 была сделана в deliver.py и НЕ сделана здесь,
    # в build_deck.py и export_docs.py — один дефект, починенный на четверть.
    out = out or default_out(project)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"отчёт: {out} ({len(doc)} символов)")
    return out


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__); raise SystemExit(1)

    def opt(k, d=None):
        return cli_opt(args, k, d)

    build(args[0], opt("--out"))


if __name__ == "__main__":
    main()
