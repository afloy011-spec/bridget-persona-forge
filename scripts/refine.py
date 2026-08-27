#!/usr/bin/env python3
"""Проход фактуры: модель дорисовывает поры и зерно ПОВЕРХ увеличенного кадра.

  py -3 refine.py <кадр|папка> --out-dir <папка> [--denoise 0.12]
                  [--prompt "..."] [--sampler euler] [--steps 8]

ЗАЧЕМ. ESRGAN наводит резкость на то, что уже есть, и придумать не умеет
ничего: на коже без пор он делает воск резче. Диффузионный проход детали
ПРИДУМЫВАЕТ — на кропе 1:1 появляются поры, веснушки, вертикальные штрихи на
губах, отдельные ресницы и зерно на плоском фоне. Замер лапласиана внутри
овала лица на четырёх кадрах: 5.3 → 11.5, 11.2 → 20.6, 6.2 → 12.8, 6.0 → 13.8,
то есть фактура удваивается.

ЭТО НАДСТРОЙКА НАД АПСКЕЙЛЕРОМ, А НЕ ЗАМЕНА ЕМУ, И ЭТО ИСПРАВЛЕНИЕ ПО ЖАЛОБЕ.
Первая редакция взяла из чужого воркфлоу схему целиком — «bicubic x2 -> малый
denoise» — и поставила её ВМЕСТО ESRGAN. Заказчик посмотрел и сказал: «очень
плохое качество». Прав: бикубика ничего не придумывает, она размывает, а
лёгкий диффузионный проход структуру назад не приносит — он сыплет зерно
поверх мыла. Замер лапласиана ВНЕ лица: у ESRGAN 206 / 86 / 76 / 138, у
бикубики с дорисовкой 44 / 24 / 24 / 40 — потеря в пять раз. На кропе 1:1 у
рубашки пропало переплетение ткани, у волос слиплись пряди.
Поэтому масштаб здесь 1.0: увеличивает ESRGAN, а этот проход только кладёт
фактуру поверх готового разрешения. При scale=1.0 потеря вне лица 15% вместо
80%, и на 1:1 ткань и волосы держат структуру.

Схема прохода из ND_Krea2_Ultimate_TI2I v1.1 (разбор — docs/ND_WORKFLOW_REVIEW.md):
масштаб -> малый denoise -> ColorMatch обратно к входу. ColorMatch не
украшение: проходу разрешено вернуть фактуру и запрещено увести грейд.

ЧЕМ ЗА ЭТО ПЛАТЯТ. Фактура и сходство ходят вместе монотонно, потому что это
одно действие: придуманная деталь есть деталь, которой в источнике не было.
Косинус к эталону персонажа, кадр D01: ESRGAN 0.883, +проход 0.08 → 0.792,
0.12 → 0.728, 0.18 → 0.639. Гипотеза «виноват SDE-сэмплер, он доливает шум»
ПРОВЕРЕНА И НЕ ПОДТВЕРДИЛАСЬ: euler и dpmpp_2m дают тот же обмен, просто в
других точках кривой. Ручки, дающей фактуру бесплатно, нет.

Чинит это не настройка, а сборка из трёх кусков — см. produce.finish: лицо
возвращается из ESRGAN целиком, а из этого прохода в овал попадают только
высокие частоты (texture_back ниже). Итог 0.858 против 0.856 у чистого ESRGAN.

DENOISE 0.12 ВЫБРАН ГЛАЗАМИ на 1:1, а не по числу — четвёртый случай в проекте,
когда метрика растёт от самой болезни, список в шапке upscale.py.
"""
import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (setup_console, cli_opt, work_dir, imread,  # noqa: E402
                   imwrite)
import comfy_client as cc  # noqa: E402

TEMPLATE = "nd_refine_api"
DENOISE = 0.12
SAMPLER = "euler"
SCHEDULER = "simple"
STEPS = 8
# МАСШТАБ 1.0 — ЭТО НЕ ЗАГЛУШКА. Увеличивает ESRGAN, здесь только фактура;
# scale=2.0 означал бы бикубику вместо апскейлера, и это ровно тот брак, из-за
# которого заказчик сказал «очень плохое качество». См. шапку модуля.
SCALE = 1.0


SEED = 42
# СИД ВЫНЕСЕН В АРГУМЕНТ, И ЭТО НЕ КОСМЕТИКА. В шаблоне он был зашит числом,
# поэтому проход был однозначен: один вход, один промпт — один и тот же выход
# навсегда. Для доводки кадра это ровно то, что нужно (повтор обязан
# повторяться), а вот для detail_tattoo оказалось потолком: тату рисуется
# диффузией, у неё есть удачные и неудачные росчерки, и выбирать было НЕ ИЗ
# ЧЕГО — оставалось крутить denoise, то есть менять силу вместо варианта.
# Умолчание сохранено прежним, так что всё, что звало refine раньше, отдаёт
# те же пиксели.


def refine(src, out_dir, prompt="", denoise=DENOISE, sampler=SAMPLER,
           scheduler=SCHEDULER, steps=STEPS, scale=SCALE, seed=SEED):
    """Увеличить кадр вдвое диффузией. Возвращает путь к результату."""
    g = cc.load_template(TEMPLATE)
    cc.apply_sets(g, {
        "20.image": cc.upload(src),
        "4.text": prompt,
        "11.scale_by": scale,
        "13.denoise": denoise,
        "13.sampler_name": sampler,
        "13.scheduler": scheduler,
        "13.steps": steps,
        "13.seed": seed,
        "9.filename_prefix": os.path.splitext(os.path.basename(src))[0],
    })
    files = cc.run_graph(g, out_dir)
    if not files:
        raise RuntimeError("воркер не вернул кадр после рефайнера")
    a, b = imread(src), imread(files[0])
    # Размер проверяется так же, как у апскейла и переноса лица: воркер уже
    # возвращал чёрную заглушку 512x512 вместо кадра, и она уходила дальше
    # молча.
    want = (round(a.shape[1] * scale), round(a.shape[0] * scale))
    if b is None or abs(b.shape[1] - want[0]) > 8 or \
            abs(b.shape[0] - want[1]) > 8:
        raise RuntimeError(
            f"рефайнер вернул {None if b is None else (b.shape[1], b.shape[0])}"
            f" вместо {want}")
    return files[0]


HP_SIGMA = 2.0
HP_STRENGTH = 1.0


def texture_back(swapped, refined, out, sigma=HP_SIGMA,
                 strength=HP_STRENGTH):
    """Высокие частоты дорисованного кадра — в овал лица собранного.

    ЗАЧЕМ ЭТОТ ШАГ ВООБЩЕ СУЩЕСТВУЕТ. Проход фактуры уводит лицо (0.883 →
    0.728), поэтому овал возвращается из ESRGAN целиком — и вместе с ним
    возвращается восковая кожа, ради которой всё затевалось. Волосы, шея,
    ткань и фон при этом фактуру сохраняют: маска лица их не касается, — а
    лицо, куда смотрят, снова гладкое.

    ПОЧЕМУ ЭТО РАБОТАЕТ. Оба кадра — один снимок в одном разрешении, они
    попиксельно совмещены. ArcFace живёт на структуре, то есть на низких и
    средних частотах; высокие несут поры, зерно и ресницы. Замер на четырёх
    кадрах: сходство 0.877 → 0.879, 0.859 → 0.857, 0.866 → 0.870, 0.826 →
    0.826, а фактура в овале при этом удваивается: 5.2 → 11.5, 9.6 → 20.6,
    6.1 → 12.8, 5.9 → 13.8.

    ЭТО НЕ ПРИВИВКА КОЖИ ИЗ skin_graft.py, которая давала регулярную сетку по
    щеке и была за это выключена. Там источником была ЧУЖАЯ фотография, и её
    структура ложилась узором поверх чужой геометрии. Здесь источник — тот же
    самый кадр, смещения нет и накладываться нечему.

    СИЛА 1.0 ВЫБРАНА ГЛАЗАМИ. На 1.6 у виска появляется светлый ореол по
    границе волос, на 2.2 он виден отчётливо; косинус при этом не двигается
    вовсе (0.843/0.844/0.847), то есть числом эту границу не найти.
    """
    import numpy as np
    import cv2
    from face_transfer import face_mask

    S = imread(swapped)
    R = imread(refined)
    if S is None or R is None:
        raise RuntimeError("не читается кадр для переноса фактуры")
    S = S.astype(np.float32)
    R = R.astype(np.float32)
    if S.shape != R.shape:
        R = cv2.resize(R, (S.shape[1], S.shape[0]),
                       interpolation=cv2.INTER_AREA).astype(np.float32)
    m = face_mask(swapped)
    if m is None:
        raise RuntimeError("лицо не найдено — фактуру некуда возвращать")
    m = m.astype(np.float32)
    if m.ndim == 2:
        m = m[:, :, None]
    k = int(sigma * 6) | 1
    detail = R - cv2.GaussianBlur(R, (k, k), sigma)
    # imwrite из _util, а не cv2: у проекта пути с кириллицей, и cv2 на них
    # молча пишет мимо.
    imwrite(out, np.clip(S + detail * m * strength, 0, 255).astype("uint8"))
    return out


def _frames(arg):
    if os.path.isdir(arg):
        out = []
        for e in ("*.png", "*.jpg", "*.jpeg"):
            out += glob.glob(os.path.join(arg, e))
        return sorted(p for p in out
                      if "contact_sheet" not in os.path.basename(p).lower())
    return [arg]


def main():
    setup_console()
    args = sys.argv[1:]
    if not args or args[0].startswith("--"):
        print(__doc__)
        raise SystemExit(1)
    out_dir = cli_opt(args, "--out-dir") or work_dir("_tmp", "refined")
    if os.path.isdir(args[0]) and \
            os.path.abspath(args[0]) == os.path.abspath(out_dir):
        raise SystemExit(f"приёмник совпадает с папкой входа: {out_dir}")
    os.makedirs(out_dir, exist_ok=True)
    prompt = cli_opt(args, "--prompt", "")
    denoise = float(cli_opt(args, "--denoise", str(DENOISE)))
    sampler = cli_opt(args, "--sampler", SAMPLER)
    steps = int(cli_opt(args, "--steps", str(STEPS)))
    ok = 0
    for src in _frames(args[0]):
        try:
            dst = refine(src, out_dir, prompt, denoise, sampler,
                         steps=steps)
        except Exception as e:
            print(f"{os.path.basename(src):32s} сбой: {type(e).__name__}: {e}")
            continue
        a, b = imread(src), imread(dst)
        ok += 1
        print(f"{os.path.basename(src):32s} {a.shape[1]}x{a.shape[0]} → "
              f"{b.shape[1]}x{b.shape[0]}  denoise {denoise}")
    print(f"\nдорисовано {ok} → {out_dir}")


if __name__ == "__main__":
    main()
