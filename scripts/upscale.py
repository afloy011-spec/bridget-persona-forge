#!/usr/bin/env python3
"""Апскейл кадра: пиксели НА ЛИЦО, а не на кадр.

  py -3 upscale.py <кадр|папка> --out-dir <папка> [--model 4x_foolhardy_Remacri]
                   [--scale 0.5]

ЗАЧЕМ. Заказчик посмотрел сдачу и сказал «изображение сильно плывёт по
пикселям, выдаётся ИИ-вайб». Замер на 1:1 подтвердил: у кадра 896x1152 лицо
занимает 124 px межзрачкового, и на этом масштабе у кожи нет пор — только
гладкость, а волосы сливаются в ленты.

СНИМАТЬ ШИРЕ НЕ ПОМОГАЕТ, И ЭТО ЗАМЕРЕНО. Кадр 896x1152 и кадр 1536x1920 дали
ОДИНАКОВЫЕ 124 px межзрачкового: вместе с разрешением росло поле зрения.
Пиксели нужны на лицо, и даёт их только апскейл — после него 204-246 px.

ПОЧЕМУ REMACRI, А НЕ ULTRASHARP. Первый выбор был неверен и его поймал
заказчик («слишком рябь»). Я взяла UltraSharp по дисперсии лапласиана: 297
против 161 у DAT и 132 у Remacri. На волосах при 1:1 видно, что UltraSharp
разбивает пряди на жёсткие проволочные линии, и дисперсия у него высокая
ИМЕННО ИЗ-ЗА ЭТОЙ ПРОВОЛОКИ — число мерило артефакт, а не качество.

Это третий случай в проекте, когда ручка подбиралась по числу, растущему от
самой болезни, и список стоит держать перед глазами:
  сила референса — по косинусу ArcFace, а после свапа он круговой;
  восстановитель — по детализации лица, а её растит дорисованная бровь;
  апскейлер      — по дисперсии лапласиана, а её растит рябь.
Отсюда порядок: числом отсеять заведомо негодное, ВЫБИРАТЬ ГЛАЗАМИ на 1:1, и
смотреть туда, где ломается (волосы, ткань), а не туда, где всё похоже (щека).

ПРИВИВКИ КОЖИ ПОСЛЕ АПСКЕЙЛА НЕТ И БЫТЬ НЕ ДОЛЖНО — см. produce.finish.
"""
import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import setup_console, cli_opt, work_dir, imread  # noqa: E402
import comfy_client as cc  # noqa: E402

TEMPLATE = "upscale_api"
MODEL = "4x_foolhardy_Remacri.safetensors"
# Модели четырёхкратные; 0.5 возвращает к двукратному. Восьмикратный кадр не
# нужен никому, а хруст ESRGAN на нём виден сильнее всего.
SCALE = 0.5


def upscale(src, out_dir, model=MODEL, scale=SCALE):
    """Увеличить кадр. Возвращает путь к результату."""
    g = cc.load_template(TEMPLATE)
    cc.apply_sets(g, {
        "1.image": cc.upload(src),
        "2.model_name": model,
        "4.scale_by": scale,
        "5.filename_prefix": os.path.splitext(os.path.basename(src))[0],
    })
    files = cc.run_graph(g, out_dir)
    if not files:
        raise RuntimeError("воркер не вернул кадр после апскейла")
    a, b = imread(src), imread(files[0])
    # РАЗМЕР ПРОВЕРЯЕТСЯ, как и у переноса лица: воркер уже один раз возвращал
    # чёрную заглушку 512x512 вместо кадра, и она уходила дальше молча.
    want = (round(a.shape[1] * 4 * scale), round(a.shape[0] * 4 * scale))
    if b is None or abs(b.shape[1] - want[0]) > 2 or abs(b.shape[0] - want[1]) > 2:
        raise RuntimeError(
            f"апскейл вернул {None if b is None else (b.shape[1], b.shape[0])} "
            f"вместо {want}")
    return files[0]


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
    out_dir = cli_opt(args, "--out-dir") or work_dir("_tmp", "upscaled")
    if os.path.isdir(args[0]) and \
            os.path.abspath(args[0]) == os.path.abspath(out_dir):
        raise SystemExit(f"приёмник совпадает с папкой входа: {out_dir}")
    os.makedirs(out_dir, exist_ok=True)
    model = cli_opt(args, "--model", MODEL)
    scale = float(cli_opt(args, "--scale", str(SCALE)))
    ok = 0
    for src in _frames(args[0]):
        try:
            dst = upscale(src, out_dir, model, scale)
        except Exception as e:
            print(f"{os.path.basename(src):32s} сбой: {type(e).__name__}: {e}")
            continue
        a, b = imread(src), imread(dst)
        ok += 1
        print(f"{os.path.basename(src):32s} {a.shape[1]}x{a.shape[0]} → "
              f"{b.shape[1]}x{b.shape[0]}")
    print(f"\nувеличено {ok} → {out_dir}")


if __name__ == "__main__":
    main()
