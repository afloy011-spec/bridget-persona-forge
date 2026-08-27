#!/usr/bin/env python3
"""Проверка того, что ворота умеют говорить «нет».

  py -3 scripts/gate_firing.py <project>            все обязательные ворота
  py -3 scripts/gate_firing.py <project> --gate skin
  py -3 scripts/gate_firing.py <project> --md docs/<проект>/gate_firing.md

ЗАЧЕМ. На пуле из сорока кадров ни одни обязательные ворота ни разу не выдали
FAIL: chroma 40/40 PASS, sharp и skin 35 PASS и 5 незамеров. Ворота, которые
никогда не срабатывали, неотличимы от ворот, которые не работают, — ровно та
же болезнь, что и зелёный тест на сломанной починке, только дороже: он
пропускает брак в сдачу.

КАК ЭТО ПРОВЕРЯЕТСЯ. Берём кадр, который ворота пропустили, и портим его
ИМЕННО ТЕМ, ради чего эти ворота стоят: обесцвечиваем (chroma), размываем
(sharp), заглаживаем кожу билатеральным фильтром (skin). Порча идёт лесенкой,
и печатается ступень, на которой ворота впервые сказали «нет». Из этого видно
сразу три вещи: ворота срабатывают; срабатывают на своей причине, а не на
чём попало; и какой запас у сданного кадра до порога.

Ступень, на которой ворота молчат до конца лесенки, — это находка, а не
формальность: значит порог выбран так, что до него не дотягивается даже
намеренная порча.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (setup_console, manifest, read_json, read_verdict,  # noqa: E402
                   work_root, imwrite, cli_opt)
import gates as G  # noqa: E402


def _degradations():
    """Лесенки порчи: ворота → [(подпись, функция над BGR), ...].

    Порча делается над ПИКСЕЛЯМИ и сохраняется во временный файл, потому что
    метрики принимают путь. Считать «в памяти» было бы быстрее, но тогда
    проверялся бы не тот путь кода, которым ходит gates.py.
    """
    import cv2

    def desat(k):
        def f(img):
            g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            g = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
            return cv2.addWeighted(img, 1 - k, g, k, 0)
        return f

    def blur(sigma):
        return lambda img: cv2.GaussianBlur(img, (0, 0), sigma)

    def smooth(d):
        # Билатеральный фильтр — это и есть «аэрограф»: он стирает микрорельеф
        # и оставляет края, поэтому кадр не выглядит размытым и мимо ворот
        # резкости проходит. Ровно тот дефект, ради которого стоят ворота кожи.
        return lambda img: cv2.bilateralFilter(img, d, d * 6, d * 6)

    return {
        "chroma": [(f"обесцвечен на {int(k * 100)}%", desat(k))
                   for k in (0.3, 0.5, 0.7, 0.85, 1.0)],
        "sharp": [(f"размыт σ={s}", blur(s)) for s in (1.0, 1.5, 2.0, 3.0, 5.0)],
        "skin": [(f"заглажен d={d}", smooth(d)) for d in (5, 9, 15, 25, 41)],
    }


def _measure(gate, path, ctx):
    V = G._verdict_api()
    r = G._metric_gate(V, gate, path, ctx)
    return r.get("state"), r.get("value"), r.get("note") or ""


def check(project_dir, only=None, out_md=None):
    import cv2  # noqa: F401  — ранний импорт, чтобы отказ был внятным

    man = manifest()
    required = list(man["gates"].get("required") or G.REQUIRED)
    ladders = _degradations()
    project = os.path.basename(str(project_dir).rstrip("/\\"))
    frames = os.path.join(work_root(), project, "frames", "frames.json")
    if not os.path.isfile(frames):
        raise SystemExit(f"реестра нет: {frames}\n  Сначала generate.py.")

    # Берём кадр, который ворота ПРОПУСТИЛИ: смысл проверки в том, чтобы
    # показать расстояние от сданного кадра до порога, а не от случайного.
    # Сверка по ИМЕНИ ФАЙЛА, а не по пути: реестр и вердикт пишутся разными
    # прогонами, и один и тот же кадр лежит в них как 'D:/a\\b\\f.png' и
    # 'D:\\a\\b\\f.png'. Сравнение строк давало пустое пересечение и отказ
    # «нет ни одного отгружаемого кадра» на наборе, где отгружаются 35.
    verdicts = {}
    gpath = os.path.join(os.path.dirname(frames), "gates.json")
    if os.path.isfile(gpath):
        for row in read_verdict(gpath)[0].get("frames", []):
            verdicts[os.path.basename(row.get("file", ""))] = row
    pool = [e["file"] for e in read_json(frames)
            if os.path.isfile(e["file"])
            and (not verdicts
                 or verdicts.get(os.path.basename(e["file"]), {}).get("ships"))]
    if not pool:
        raise SystemExit("нет ни одного отгружаемого кадра — сначала gates.py")
    src = pool[0]

    tmp = os.path.join(work_root(), project, "gate_firing")
    os.makedirs(tmp, exist_ok=True)
    face, _ = G._call("faces", src, {})
    ctx = {"face": face if isinstance(face, dict) else None, "asset": None,
           "scene_class": None, "gates": man["gates"], "char": None}

    lines, blind = [], []
    print(f"кадр-образец: {os.path.basename(src)}\n")
    for gate in required:
        if only and gate != only:
            continue
        ladder = ladders.get(gate)
        if not ladder:
            blind.append((gate, "лесенки порчи для этих ворот нет"))
            print(f"{gate}: ПРОПУСК — нечем портить, проверка не написана")
            continue
        state0, val0, _ = _measure(gate, src, ctx)
        print(f"{gate}: оригинал {state0} {G._num(val0)}")
        lines.append(f"### `{gate}`\n\n| вариант | значение | ворота |\n"
                     f"|---|---|---|\n| оригинал | {G._num(val0)} | **{state0}** |")
        if state0 != "PASS":
            blind.append((gate, f"образец и без порчи не PASS ({state0})"))
        fired = None
        img = G.load_bgr(src) if hasattr(G, "load_bgr") else None
        if img is None:
            from metrics.sharpness import load_bgr
            img = load_bgr(src)
        for tag, fn in ladder:
            p = os.path.join(tmp, f"{gate}_{tag.replace(' ', '_')}.png")
            imwrite(p, fn(img))
            state, val, note = _measure(gate, p, ctx)
            mark = "  <- впервые «нет»" if state == "FAIL" and fired is None else ""
            print(f"  {tag:22} {state:12} {G._num(val)}{mark}")
            lines.append(f"| {tag} | {G._num(val)} | {state} |")
            if state == "FAIL" and fired is None:
                fired = tag
        lines.append("")
        if fired is None:
            blind.append((gate, "не сработали ни на одной ступени лесенки"))
            print("  ВОРОТА НЕ СРАБОТАЛИ НИ РАЗУ — порог недостижим порчей\n")
        else:
            print(f"  срабатывают начиная с «{fired}»\n")

    if out_md:
        os.makedirs(os.path.dirname(os.path.abspath(out_md)), exist_ok=True)
        head = ("# Ворота: где именно они говорят «нет»\n\n"
                "Кадр, который ворота пропустили, портится ровно тем дефектом,\n"
                "ради которого эти ворота стоят. Печатается ступень, на которой\n"
                "ворота впервые сказали «нет», и запас пропущенного кадра до неё.\n"
                "Собрано `scripts/gate_firing.py`; образец — "
                f"`{os.path.basename(src)}`.\n\n")
        with open(out_md, "w", encoding="utf-8") as fh:
            fh.write(head + "\n".join(lines))
        print(f"отчёт: {out_md}")

    if blind:
        print("\nВОРОТА БЕЗ ДОКАЗАННОГО СРАБАТЫВАНИЯ:")
        for gate, why in blind:
            print(f"  {gate}: {why}")
        raise SystemExit(1)
    print("все обязательные ворота сработали на своей причине")
    return 0


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)

    def opt(k, d=None):
        return cli_opt(args, k, d)

    check(args[0], opt("--gate"), opt("--md"))


if __name__ == "__main__":
    main()
