#!/usr/bin/env python3
"""Признаки «нейросетевого» кадра, которые ловятся числом: волосы, фон, взгляд.

  py -3 scripts/metrics/artifacts.py <кадр|папка> [--md <файл.md>]

Три отдельных замера, потому что три разных дефекта, и каждый бракует кадр
самостоятельно:

  ВОЛОСЫ-ЛЕНТЫ. Диффузия рисует волосы длинными когерентными прядями с ровными
  параллельными бликами: направление внутри пряди почти не меняется, и соседние
  пряди идут строго параллельно. У снятых камерой волос направление всё время
  сбивается — отдельные волоски, завихрения, разная глубина. Меряется
  СОГЛАСОВАННОСТЬ структурного тензора по маске волос: у ленты она высокая и
  ровная, у настоящих волос ниже и с разбросом.

  ФОН-КАША. Настоящее боке — это диски от точечных источников с ОЧЕРЧЕННЫМ
  краем и заметная зернистость; «нейрофон» — сплошная плавная размазня без
  единого края. Меряется доля площади фона, занятая заметными перепадами
  яркости, и разброс этой доли по плитками: у каши она около нуля везде.

  РАЗЪЕЗЖАЮЩИЙСЯ ВЗГЛЯД. Самый заметный глазу дефект: один глаз смотрит в
  объектив, другой мимо. Меряется положение радужки ВНУТРИ своей глазной щели
  по 106 точкам, отдельно для каждого глаза, и берётся расхождение. У живого
  лица оба глаза смещены одинаково — они смотрят в одну точку.

ПОЧЕМУ ЭТО ОТДЕЛЬНО ОТ ВОРОТ КАЧЕСТВА. Ворота (цвет, резкость, кожа) судят
кадр как фотографию: не мыло ли, не сепия ли. Здесь судится другое — не выдаёт
ли кадр, что он нарисован. Кадр может быть безупречен по всем воротам и при
этом иметь волосы-ленты; в датасет он не годится, потому что лора выучит
именно их.

ПОРОГИ СТАВЯТСЯ ПО РАЗМЕТКЕ ГЛАЗАМИ, а не из головы: пять кадров, забракованных
человеком за «нейрослоп волосы и фон», против остального пула. Пока разметки
нет, метрика печатает числа и НЕ бракует — три состояния, как везде.
"""
import os
import sys
import glob

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _util import setup_console, imread  # noqa: E402
from metrics import faces  # noqa: E402
from metrics.verdict import PASS  # noqa: E402

# Масштаб структуры волос: прядь толще поры и тоньше локона. В долях IPD.
HAIR_SIGMA = 0.012
# Сколько плиток фона брать по каждой стороне.
BG_TILES = 6
# Межзрачковое расстояние, ниже которого расхождение взгляда НЕ МЕРЯЕТСЯ.
# Замер уменьшением одного кадра: 123 → 0.164, 86 → 0.223, 61 → 0.290,
# 43 → 0.306, 31 → 0.470 — метрика уползает на +0.31 от одного разрешения.
# 90 стоит там, где отход ещё меньше 0.06. Подробнее — в gaze_split.
MIN_GAZE_IPD = 90.0


def _structure_tensor(g, sigma):
    """Согласованность и направление структуры. Возвращает (coherence, angle)."""
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    jxx = cv2.GaussianBlur(gx * gx, (0, 0), sigma)
    jyy = cv2.GaussianBlur(gy * gy, (0, 0), sigma)
    jxy = cv2.GaussianBlur(gx * gy, (0, 0), sigma)
    tmp = np.sqrt((jxx - jyy) ** 2 + 4.0 * jxy ** 2)
    lam1 = 0.5 * (jxx + jyy + tmp)
    lam2 = 0.5 * (jxx + jyy - tmp)
    coh = (lam1 - lam2) / np.clip(lam1 + lam2, 1e-6, None)
    ang = 0.5 * np.arctan2(2.0 * jxy, jxx - jyy)
    return coh, ang


def hair_mask(img, face):
    """Маска волос: над и вокруг овала лица, но не лицо и не фон.

    Строится геометрически от овала: волосы — это то, что примыкает к голове
    сверху и сбоку и не является кожей лица. Цветовой маски здесь не хватает:
    у нашего персонажа волосы того же тона, что кожа на тёплом свете.
    """
    k = face.get("kps106")
    if k is None:
        return None
    k = np.asarray(k, np.float32)
    ipd = float(face["ipd_px"])
    h, w = img.shape[:2]
    oval = cv2.convexHull(k[0:33].astype(np.int32))
    head = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(head, oval, 255)
    # Голова с волосами примерно вдвое выше овала лица и шире его в полтора.
    M = cv2.moments(head)
    if M["m00"] == 0:
        return None
    cx, cy = M["m10"] / M["m00"], M["m01"] / M["m00"]
    big = np.zeros((h, w), np.uint8)
    cv2.ellipse(big, (int(cx), int(cy - ipd * 0.35)),
                (int(ipd * 1.7), int(ipd * 2.1)), 0, 0, 360, 255, -1)
    face_grown = cv2.dilate(head, np.ones((3, 3), np.uint8),
                            iterations=max(1, int(ipd * 0.05)))
    m = cv2.bitwise_and(big, cv2.bitwise_not(face_grown))
    return m


def hair_ribbon(img, face):
    """Насколько волосы похожи на ленту. Больше — хуже."""
    m = hair_mask(img, face)
    if m is None or (m > 0).sum() < 4000:
        return None
    ipd = float(face["ipd_px"])
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    coh, _ = _structure_tensor(g, max(1.0, HAIR_SIGMA * ipd))
    v = coh[m > 0]
    # Доля площади, где направление держится почти идеально. У снятых волос
    # такие места есть, но их немного; у ленты — почти всюду.
    return float((v > 0.75).mean())


def background_mush(img, face):
    """Насколько фон — сплошная размазня без структуры. Больше — хуже."""
    k = face.get("kps106")
    if k is None:
        return None
    k = np.asarray(k, np.float32)
    ipd = float(face["ipd_px"])
    h, w = img.shape[:2]
    person = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(person, cv2.convexHull(k[0:33].astype(np.int32)), 255)
    person = cv2.dilate(person, np.ones((3, 3), np.uint8),
                        iterations=max(1, int(ipd * 0.9)))
    bg = cv2.bitwise_not(person)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    edges = np.abs(cv2.Laplacian(g, cv2.CV_32F, ksize=3))
    th, tw = h // BG_TILES, w // BG_TILES
    flat = []
    for i in range(BG_TILES):
        for j in range(BG_TILES):
            sl = (slice(i * th, (i + 1) * th), slice(j * tw, (j + 1) * tw))
            msk = bg[sl] > 0
            if msk.mean() < 0.85:
                continue
            e = edges[sl][msk]
            if e.size < 500:
                continue
            # Плитка считается «кашей», если заметных перепадов в ней почти нет.
            flat.append(float((e > 6.0).mean()))
    if len(flat) < 4:
        return None
    return float(np.mean([1.0 - x for x in flat]))


def gaze_split(img, face):
    """Расхождение взгляда двух глаз в долях ширины глазной щели. Больше — хуже.

    Радужка ищется как самое тёмное пятно внутри контура века, а не берётся из
    центра щели: у отвёрнутого взгляда центр щели и центр радужки не совпадают
    — в этом и смысл замера.

    МЕЛКОЕ ЛИЦО НЕ МЕРЯЕТСЯ ВОВСЕ, И ЭТО ЗАМЕР, А НЕ ОСТОРОЖНОСТЬ. Один и тот
    же кадр, просто уменьшенный, даёт: IPD 123 → 0.164, 86 → 0.223, 61 → 0.290,
    43 → 0.306, 31 → 0.470. Взгляд никуда не уезжал — уползает САМА МЕТРИКА, на
    +0.31 от одного лишь разрешения. Для сравнения, соседние признаки на том же
    ряду стоят на месте: волосы 0.741 → 0.771, фон 0.524 → 0.461.
    Цена этой дыры замерена на сдаче: все четыре ростовых кадра (IPD 43-46)
    улетели в брак, два из них именно по взгляду — 0.487 и 0.431 при пороге
    прогона 0.35. Детектор выкашивал ЦЕЛЫЙ ПЛАН, а бриф требует «подтянутую
    стильную фигуру», которую иначе как в рост не показать.
    Порог стоит там, где отход ещё меньше 0.06 — пятой части типичного
    разброса. Прежняя защита была «щель уже 12 px» и пропускала всё это.
    """
    k = face.get("kps106")
    if k is None:
        return None
    if float(face.get("ipd_px") or 0.0) < MIN_GAZE_IPD:
        return None
    k = np.asarray(k, np.float32)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    offs = []
    for idx in (range(33, 43), range(87, 97)):
        pts = k[list(idx)]
        x0, y0 = pts.min(0)
        x1, y1 = pts.max(0)
        wdt = x1 - x0
        if wdt < 12:
            return None
        pad = int(wdt * 0.1)
        xs, ys = int(x0) - pad, int(y0) - pad
        xe, ye = int(x1) + pad, int(y1) + pad
        if xs < 0 or ys < 0 or xe >= img.shape[1] or ye >= img.shape[0]:
            return None
        patch = g[ys:ye, xs:xe]
        m = np.zeros(patch.shape, np.uint8)
        cv2.fillConvexPoly(m, (pts - [xs, ys]).astype(np.int32), 255)
        vals = patch[m > 0]
        if vals.size < 40:
            return None
        thr = np.percentile(vals, 12)
        dark = ((patch <= thr) & (m > 0)).astype(np.uint8)
        M = cv2.moments(dark)
        if M["m00"] == 0:
            return None
        ix, iy = M["m10"] / M["m00"] + xs, M["m01"] / M["m00"] + ys
        cx, cy = pts.mean(0)
        offs.append(((ix - cx) / wdt, (iy - cy) / wdt))
    return float(np.hypot(offs[0][0] - offs[1][0], offs[0][1] - offs[1][1]))


def measure(src, face=None):
    """Все три числа разом. Никогда не бросает."""
    f = face or faces.detect(src)
    if f["state"] != PASS or f.get("kps106") is None:
        return {"state": "NOT_MEASURED", "why": f.get("note", "нет разметки"),
                "hair": None, "background": None, "gaze": None}
    img = imread(src) if isinstance(src, str) else src
    return {"state": PASS, "why": "",
            "hair": hair_ribbon(img, f),
            "background": background_mush(img, f),
            "gaze": gaze_split(img, f)}


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    target = args[0]
    paths = (sorted(glob.glob(os.path.join(target, "**", "*.png"), recursive=True)
                    + glob.glob(os.path.join(target, "**", "*.jpg"), recursive=True))
             if os.path.isdir(target) else [target])
    if not paths:
        raise SystemExit(f"нечего мерить: {target}")
    print(f"{'кадр':34} {'волосы':>8} {'фон':>7} {'взгляд':>8}")
    rows = []
    for p in paths:
        r = measure(p)
        if r["state"] != PASS:
            print(f"{os.path.basename(p):34}   {r['why'][:40]}")
            continue
        rows.append((os.path.basename(p), r))
        print(f"{os.path.basename(p):34} "
              + " ".join(f"{(r[k] if r[k] is not None else float('nan')):8.3f}"
                         for k in ("hair", "background", "gaze")))
    if len(rows) > 3:
        print("\nразброс по пулу (медиана / худшие 3):")
        for k, name in (("hair", "волосы"), ("background", "фон"),
                        ("gaze", "взгляд")):
            v = sorted((r[k], n) for n, r in rows if r[k] is not None)
            if not v:
                continue
            med = v[len(v) // 2][0]
            worst = ", ".join(f"{n} {x:.3f}" for x, n in v[-3:])
            print(f"  {name:8} медиана {med:.3f}   худшие: {worst}")


if __name__ == "__main__":
    main()
