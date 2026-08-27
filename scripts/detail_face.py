#!/usr/bin/env python3
"""Доводка лица В МАСШТАБЕ ЛИЦА: кроп -> 1024 -> диффузия -> назад в кадр.

  py -3 detail_face.py <кадр|папка> --out-dir <папка> [--denoise 0.25]
                       [--prompt "..."] [--pad 1.6] [--size 1024]

ЗАЧЕМ, И ПОЧЕМУ ВСЁ ПРЕДЫДУЩЕЕ БЫЛО ЛЕЧЕНИЕМ СЛЕДСТВИЙ. Заказчик сказал:
«проблему с качеством нужно чинить у корня», — и был прав, потому что до этого
момента чинились следствия. ESRGAN мылит -> ставим диффузию по кадру; диффузия
уводит лицо -> возвращаем овал; овал восковой -> подмешиваем высокие частоты.
Четыре ступени, каждая лечит вред предыдущей.

КОРЕНЬ. Диффузия рисует детали в масштабе ХОЛСТА. На кадре 1792x2304 лицо
занимает 305 px межзрачкового, то есть остаётся мелкой деталью, и проход по
всему кадру физически не может положить на него поры — он кладёт детали в
масштабе всего кадра. Замер на одном кадре, дисперсия лапласиана по кропу
лица: проход по кадру 5.3 -> 11.5, тот же проход ПО КРОПУ ЛИЦА 52.7 -> 71.3.
На 1:1 разница не требует комментариев: появляются поры на носу и щеках,
отдельные ресницы, тонкие морщины.

И ВТОРОЙ КОРЕНЬ ТАМ ЖЕ. В самой генерации у лица 72-161 px межзрачкового
(медианы по планам: в рост 72, по пояс 120, погрудный 146, портрет 161). Поры
негде рисовать не только на доводке, но и на съёмке. Кроп с увеличением до
1024 даёт лицу собственный холст и снимает оба ограничения разом.

ЧЕМ ПЛАТИМ И ЧЕМ ЭТО ЗАКРЫВАЕТСЯ. Доводка на своей силе уводит личность —
как и любая дорисовка, потому что придуманная деталь есть деталь, которой в
источнике не было. Пока личность держится свапом inswapper_128, это лечится
только слабым denoise. По-настоящему закрывает лора персонажа: тогда лицо
рисует сама модель, свап уходит целиком, и детейлеру можно дать полную силу.
"""
import os
import sys
import glob

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import setup_console, cli_opt, work_dir, imread, imwrite  # noqa: E402
from metrics import faces  # noqa: E402
import refine as rf  # noqa: E402

DENOISE = 0.25
PAD = 1.6        # половина стороны кропа в межзрачковых
SIZE = 1024      # холст, который получает лицо
FEATHER = 0.10   # растушёвка вклейки, в долях стороны кропа


def _crop_box(shape, cx, cy, ipd, pad):
    """Квадрат вокруг лица, целиком внутри кадра."""
    half = int(round(ipd * pad))
    half = min(half, shape[0] // 2, shape[1] // 2)
    x = int(round(min(max(cx - half, 0), shape[1] - 2 * half)))
    y = int(round(min(max(cy - half, 0), shape[0] - 2 * half)))
    return x, y, 2 * half


def _feathered(side, frac):
    """Мягкая маска квадрата: край гасится, чтобы вклейка не дала шва."""
    b = max(1, int(side * frac))
    m = np.ones((side, side), np.float32)
    ramp = np.linspace(0.0, 1.0, b, dtype=np.float32)
    m[:b, :] *= ramp[:, None]
    m[-b:, :] *= ramp[::-1, None]
    m[:, :b] *= ramp[None, :]
    m[:, -b:] *= ramp[None, ::-1]
    return m


def detail(src, out_dir, prompt="", denoise=DENOISE, pad=PAD, size=SIZE,
           feather=FEATHER):
    """Довести лицо в его собственном масштабе. Возвращает путь к кадру."""
    im = imread(src)
    if im is None:
        raise RuntimeError(f"не читается кадр: {src}")
    f = faces.detect(src)
    if not f:
        raise RuntimeError("лицо не найдено — доводить нечего")
    cx, cy = f["kps"][2]
    x, y, side = _crop_box(im.shape, cx, cy, f["ipd_px"], pad)
    crop = im[y:y + side, x:x + side]

    # ШАГ НИКОГДА НЕ УМЕНЬШАЕТ КРОП, И ЭТО ИСПРАВЛЕНИЕ ПО ЖАЛОБЕ.
    # Смысл прохода — дать лицу СВОЙ холст: при съёмке ему достаётся 72-161 px
    # межзрачкового, и на кропе, растянутом до 1024, диффузия наконец рисует
    # поры. Но после того как перед ним встал двукратный апскейл, кроп стал
    # приходить уже размером около 1470 px — и приведение к 1024 превратило
    # увеличение в УМЕНЬШЕНИЕ. Замер на кадре T01_r00 (кроп 1470 px):
    #   без прохода          косинус 0.655, фактура 190.0
    #   проход denoise 0.10  косинус 0.596, фактура  78.8
    #   проход denoise 0.25  косинус 0.523, фактура  67.2
    # То есть шаг портил ОБЕ оси сразу: выбрасывал разрешение, которое дал
    # апскейл, и попутно уводил лицо. Заказчик увидел это раньше метрик и
    # сказал: «при приближении женщина неестественная и не похожа на нашу».
    # Холст берётся не меньше кропа; если кроп уже крупнее заданного размера,
    # работаем в его собственном разрешении, а не режем до константы.
    canvas = max(int(size), side)
    canvas -= canvas % 8
    if canvas > side:
        base_img = cv2.resize(crop, (canvas, canvas),
                              interpolation=cv2.INTER_LANCZOS4)
    else:
        canvas = side - side % 8
        base_img = crop[:canvas, :canvas]
    size = canvas
    tmp = os.path.join(out_dir, "_crop")
    os.makedirs(tmp, exist_ok=True)
    base = os.path.join(tmp, os.path.basename(src))
    imwrite(base, base_img)
    done = rf.refine(base, tmp, prompt, denoise=denoise, scale=1.0)

    got = imread(done)
    if got is None or got.shape[0] != size or got.shape[1] != size:
        # Размер проверяется, как у переноса и апскейла: воркер уже возвращал
        # чёрную заглушку 512x512, и она уходила дальше молча.
        raise RuntimeError(
            f"детейлер вернул {None if got is None else got.shape[:2]} "
            f"вместо {(size, size)}")
    back = (got if got.shape[0] == side else
            cv2.resize(got, (side, side), interpolation=cv2.INTER_AREA))
    if back.shape[0] != side:
        pad = np.zeros((side, side, 3), np.uint8)
        pad[:back.shape[0], :back.shape[1]] = back
        back = pad

    m = _feathered(side, feather)[..., None]
    out = im.astype(np.float32).copy()
    patch = out[y:y + side, x:x + side]
    out[y:y + side, x:x + side] = patch * (1 - m) + back.astype(np.float32) * m
    # Суффикс обязателен: доводка часто зовётся с приёмником, равным папке
    # входа, и без него шаг писал бы поверх собственного исходника.
    dst = os.path.join(out_dir,
                       os.path.splitext(os.path.basename(src))[0] + "_det.png")
    imwrite(dst, np.clip(out, 0, 255).astype(np.uint8))
    return dst


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
    out_dir = cli_opt(args, "--out-dir") or work_dir("_tmp", "detailed")
    if os.path.isdir(args[0]) and \
            os.path.abspath(args[0]) == os.path.abspath(out_dir):
        raise SystemExit(f"приёмник совпадает с папкой входа: {out_dir}")
    os.makedirs(out_dir, exist_ok=True)
    prompt = cli_opt(args, "--prompt", "")
    denoise = float(cli_opt(args, "--denoise", str(DENOISE)))
    pad = float(cli_opt(args, "--pad", str(PAD)))
    size = int(cli_opt(args, "--size", str(SIZE)))
    ok = 0
    for src in _frames(args[0]):
        try:
            detail(src, out_dir, prompt, denoise, pad, size)
        except Exception as e:
            print(f"{os.path.basename(src):32s} сбой: {type(e).__name__}: {e}")
            continue
        ok += 1
        print(f"{os.path.basename(src):32s} лицо доведено, denoise {denoise}")
    print(f"\nдоведено {ok} → {out_dir}")


if __name__ == "__main__":
    main()
