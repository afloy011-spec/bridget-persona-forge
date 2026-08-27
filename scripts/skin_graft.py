#!/usr/bin/env python3
"""Прививка НАСТОЯЩЕЙ кожи: структура пор с фотографии — на сгенерированное лицо.

  py -3 skin_graft.py <кадр.png> [--plate <фото_кожи.png>] [--out <файл>]
                      [--strength 2.0] [--plate-scale <px на мм>] [--preview]
  py -3 skin_graft.py --dir <папка> --out-dir <папка> [--plate <фото>]
  py -3 skin_graft.py --measure <кадр|папка>                    только замер

ЧТО ИМЕННО ЧИНИТСЯ. Кадр krea2-эдита на кропе 1:1 читается как нарисованный:
каждый план щеки отмоделирован своим бликом, морщинки идут ровными штрихами,
кожа всюду одного качества. Прививка заменяет собственный микрошум генерации
структурой кожи с НАСТОЯЩЕЙ фотографии — мультипликативно, то есть как
модуляцию собственной освещённости лица.

ЧЕСТНО О ТОМ, ЧЕГО ЧИСЛА НЕ ПОКАЗЫВАЮТ. Разница видна глазами на кропе 1:1 и
почти не видна в статистике: sigma высоких частот на щеке идёт 18.6 -> 23.8,
эксцесс 0.83 -> 1.24. Замеры, которые удалось поставить, говорят одно и то же
и против ожидания:

  чистая кожа настоящей фотографии, масштаб приведён к IPD 200 px:
                                       sigma 13.6   эксцесс 0.70
  гладкий рендер базы персонажа:       sigma 11.7   эксцесс 0.02
  наши кадры (эдит krea2):             sigma 16.6-18.6  эксцесс 0.80-0.95

То есть по микростатистике наши кадры УЖЕ не глаже настоящей кожи — они чуть
шумнее её. «Нейросетевость» живёт не в количестве высоких частот, а в их
устройстве, и ни одна из проверенных сводных величин (sigma, эксцесс,
асимметрия, пестрота цвета на 3-8 мм) её не ловит. Поэтому судья этому шагу —
глаз на кропе 1:1, а числа печатаются как контроль побочных эффектов: если
после прививки уехал тон или подскочила sigma втрое, шаг делает не своё дело.

ОШИБКА, КОТОРАЯ ЧУТЬ НЕ СТАЛА ОСНОВАНИЕМ ЭТОГО ФАЙЛА, записана нарочно. Первый
замер дал у настоящей кожи эксцесс 24.9 против 0.8 у генерации, и это выглядело
как найденный различитель: «редкие сильные детали против ровного шума». Число
оказалось артефактом — в кусок фотографии попала сама надпись тату, и тяжёлые
хвосты дали её штрихи, а не поры. Скан ЧИСТЫХ кусков кожи (без чернил, без
границы руки с фоном) вернул эксцесс 0.70. Разница между «нашли метрику
живости» и «нашли край объекта в кадре» — один непроверенный кроп.

МАСШТАБ ПРИВОДИТСЯ К ФИЗИЧЕСКОМУ РАЗМЕРУ, а не к пикселям. Пора имеет размер в
десятых долях миллиметра, и «перенести как есть» означало бы налепить на лицо
поры размером с ноздрю или стереть их в шум. Плотность цели считается по
межзрачковому расстоянию (63 мм у взрослого — та же константа, на которой стоят
все прочие масштабы конвейера), плотность источника задаётся --plate-scale.

ПЛИТКА ОБЯЗАНА БЫТЬ ЧИСТОЙ КОЖЕЙ. Первый прогон брал фотографию целиком, и
эффект вышел втрое слабее: в плитку попали фон, расфокус и та же надпись, а
после нормировки они дают ноль и разбавляют структуру. Плитка отбирается сканом
по сетке с двумя условиями — доля пикселей телесной цветности выше 0.985 и ни
одного тёмного пикселя (чернила, волос, край кадра).

ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО. Ни повышения резкости, ни осветления, ни изменения
цвета. Прививка обязана быть незаметной по всему, кроме микрорельефа.
"""
import os
import sys
import glob

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import setup_console, cli_opt, imread, imwrite, ROOT  # noqa: E402
from metrics import faces  # noqa: E402
from metrics.verdict import PASS  # noqa: E402

# Межзрачковое расстояние взрослого человека, мм. Та же константа, что держит
# все масштабы конвейера; здесь она переводит пиксели цели в миллиметры.
IPD_MM = 63.0
# Масштаб высоких частот. 1.6 px на приведённом масштабе — размер поры; ниже
# начинается шум сенсора, выше — уже морщина, а её переносить нельзя: морщина
# принадлежит лицу, а не коже.
HF_SIGMA = 1.6
# Полоса яркости, в которой прививка работает в полную силу. В провале и в
# пересвете рельефа не видно физически, и подмешивать его туда — выдать себя.
LUM_LO, LUM_HI = 0.18, 0.86
# Плитка по умолчанию: чистый кусок настоящей кожи, отобранный сканом и
# лежащий в репозитории. Шаг обязан работать без указания на чужой файл.
DEFAULT_PLATE = os.path.join(ROOT, "assets", "skin_plate_wrist.png")
# Плотность плитки: предплечье шириной ~65 мм занимает ~530 px исходной
# фотографии. Число живёт рядом с плиткой, потому что относится к ней одной.
DEFAULT_PLATE_SCALE = 530.0 / 65.0


def hf_plate(bgr, src_px_per_mm, dst_px_per_mm):
    """Высокочастотный слой фотографии кожи, приведённый к плотности цели.

    Возвращает массив float32 около нуля: относительная модуляция яркости.
    Нормируется на локальную яркость источника, поэтому не тащит за собой ни
    его освещение, ни его тон — только рельеф.
    """
    scale = dst_px_per_mm / src_px_per_mm
    if abs(scale - 1.0) > 0.01:
        interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
        bgr = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=interp)
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    base = np.clip(cv2.GaussianBlur(g, (0, 0), 10.0), 1.0, None)
    hf = (g - cv2.GaussianBlur(g, (0, 0), HF_SIGMA)) / base
    h, w = hf.shape
    m = int(min(h, w) * 0.08)
    return hf[m:h - m, m:w - m]


def tile_to(plate, shape, seed=0):
    """Замостить слой на нужный размер БЕЗ видимого шва.

    Соседние плитки зеркалятся, а не повторяются: повтор одного куска кожи
    даёт регулярную решётку, которую глаз ловит мгновенно, и она выглядит хуже
    гладкости, которую мы лечим.
    """
    h, w = shape
    ph, pw = plate.shape
    ry = int(np.ceil(h / ph)) + 1
    rx = int(np.ceil(w / pw)) + 1
    rows = []
    for i in range(ry):
        cols = []
        for j in range(rx):
            t = plate
            if i % 2:
                t = t[::-1]
            if j % 2:
                t = t[:, ::-1]
            cols.append(t)
        rows.append(np.hstack(cols))
    big = np.vstack(rows)
    rs = np.random.RandomState(seed)
    oy = rs.randint(0, max(1, big.shape[0] - h))
    ox = rs.randint(0, max(1, big.shape[1] - w))
    return big[oy:oy + h, ox:ox + w]


def face_skin_mask(img, face):
    """Маска кожи лица: овал минус глаза, брови, рот и ноздри.

    По 106 точкам, а не по цвету: цветовая маска на тёплом свете хватает и
    волосы, и стену за спиной, и прививка ложится на фон.
    """
    kps = face.get("kps106")
    if kps is None:
        return None
    k = np.asarray(kps, np.float32)
    h, w = img.shape[:2]
    m = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(m, cv2.convexHull(k[0:33].astype(np.int32)), 255)
    ipd = float(face["ipd_px"])
    for idx, grow in ((range(33, 43), 0.16), (range(87, 97), 0.16),
                      (range(43, 52), 0.13), (range(97, 106), 0.13),
                      (range(52, 72), 0.14), (range(72, 87), 0.10)):
        pts = k[list(idx)].astype(np.int32)
        if len(pts) < 3:
            continue
        hull = cv2.convexHull(pts)
        cv2.fillConvexPoly(m, hull, 0)
        cv2.drawContours(m, [hull], -1, 0, int(max(2, grow * ipd)))
    m = cv2.erode(m, np.ones((3, 3), np.uint8), iterations=2)
    return cv2.GaussianBlur(m, (0, 0), max(2.0, ipd * 0.03))


def measure(img, face):
    """(sigma, эксцесс) высоких частот на щеке, масштаб приведён к IPD 200 px.

    Числа вспомогательные: они ловят побочные эффекты шага, а не «живость»
    (см. шапку). Эксцесс считается вручную, чтобы не тащить scipy: конвейер
    живёт на стандартной библиотеке плюс numpy и cv2.
    """
    k = np.asarray(face["kps"], np.float32)
    ipd = float(face["ipd_px"])
    c = (k[0] + k[1]) / 2.0
    d = (k[1] - k[0]) / ipd
    n = np.array([-d[1], d[0]], np.float32)
    scale = 200.0 / ipd
    vals = []
    for s in (-0.55, 0.55):
        p = c + d * ipd * s + n * ipd * 0.55
        r = int(ipd * 0.22)
        x0, y0 = int(p[0] - r), int(p[1] - r)
        if x0 < 0 or y0 < 0 or x0 + 2 * r >= img.shape[1] \
                or y0 + 2 * r >= img.shape[0]:
            continue
        patch = img[y0:y0 + 2 * r, x0:x0 + 2 * r]
        if scale != 1.0:
            patch = cv2.resize(patch, None, fx=scale, fy=scale,
                               interpolation=cv2.INTER_AREA)
        gg = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if min(gg.shape) < 40:
            continue
        hf = (gg - cv2.GaussianBlur(gg, (0, 0), HF_SIGMA)) / max(gg.mean(), 1.0)
        v = hf.ravel()
        m2 = float(np.mean((v - v.mean()) ** 2))
        m4 = float(np.mean((v - v.mean()) ** 4))
        vals.append((float(np.std(v) * 1000),
                     m4 / (m2 * m2) - 3.0 if m2 > 0 else 0.0))
    if not vals:
        return None
    return (float(np.mean([x[0] for x in vals])),
            float(np.mean([x[1] for x in vals])))


def graft(src, plate_path=None, out=None, strength=2.0, plate_px_per_mm=None,
          seed=0, preview=None):
    """Привить рельеф кожи одному кадру. Возвращает (путь, (до, после))."""
    plate_path = plate_path or DEFAULT_PLATE
    plate_px_per_mm = plate_px_per_mm or DEFAULT_PLATE_SCALE
    img = imread(src)
    if img is None:
        raise SystemExit(f"кадр не прочитан: {src}")
    face = faces.detect(src)
    if face["state"] != PASS:
        raise SystemExit(f"{os.path.basename(src)}: {face['note']} — "
                         f"прививать не к чему")
    if face.get("kps106") is None:
        raise SystemExit(f"{os.path.basename(src)}: нет разметки 106 точек")

    plate_img = imread(plate_path)
    if plate_img is None:
        raise SystemExit(
            f"плитка кожи не прочитана: {plate_path}\n"
            f"  Это кусок ФОТОГРАФИИ настоящей кожи. Рисовать структуру самим "
            f"значит получить\n  гауссов шум — ровно то, что этот шаг и лечит.")

    dst_px_per_mm = float(face["ipd_px"]) / IPD_MM
    plate = hf_plate(plate_img, plate_px_per_mm, dst_px_per_mm)
    mask = face_skin_mask(img, face)
    if mask is None or mask.max() == 0:
        raise SystemExit("маска кожи пуста — прививать некуда")

    hf = tile_to(plate, img.shape[:2], seed)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    # ГАШЕНИЕ ПО ЯРКОСТИ. В провале и в пересвете микрорельефа не видно
    # физически: там нет ни падающего света, ни диапазона. Прививка, не
    # знающая об этом, рисует поры в чёрной тени, и кадр сразу читается как
    # обработанный.
    lum = np.clip((g - LUM_LO) / (LUM_HI - LUM_LO), 0.0, 1.0)
    lum = np.minimum(lum, np.clip((1.0 - g) / (1.0 - LUM_HI), 0.0, 1.0))
    w = (mask.astype(np.float32) / 255.0) * lum * float(strength)

    # МУЛЬТИПЛИКАТИВНО, А НЕ СЛОЖЕНИЕМ. Рельеф — это модуляция ОТРАЖЁННОГО
    # света: в тени пора темнее во столько же раз, что и на свету, а не на
    # столько же уровней. Сложение выдало бы себя первым кадром с контровым
    # светом: в тёмной половине лица поры стали бы ярче фона.
    out_img = np.clip(img.astype(np.float32) * (1.0 + (hf * w)[..., None]),
                      0, 255).astype(np.uint8)

    out = out or os.path.splitext(src)[0] + "_skin" + (
        os.path.splitext(src)[1] or ".png")
    if os.path.abspath(out) == os.path.abspath(src):
        raise SystemExit(f"приёмник совпадает с входом: {out}")
    imwrite(out, out_img)

    before, after = measure(img, face), measure(out_img, face)
    if preview:
        imwrite(preview, np.hstack([img, out_img]))
    return out, (before, after)


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)

    plate = cli_opt(args, "--plate") or DEFAULT_PLATE
    ps = cli_opt(args, "--plate-scale")
    scale = float(ps) if ps else DEFAULT_PLATE_SCALE
    strength = float(cli_opt(args, "--strength", "2.0"))

    target = cli_opt(args, "--measure")
    if target:
        paths = (sorted(glob.glob(os.path.join(target, "*.png"))
                        + glob.glob(os.path.join(target, "*.jpg")))
                 if os.path.isdir(target) else [target])
        print(f"{'кадр':34} {'sigma':>8} {'эксцесс':>9}")
        print(f"{'чистая настоящая кожа':34} {13.60:8.2f} {0.70:9.2f}")
        for p in paths:
            f = faces.detect(p)
            if f["state"] != PASS or f.get("kps106") is None:
                print(f"{os.path.basename(p):34}   лица нет")
                continue
            t = measure(imread(p), f)
            print(f"{os.path.basename(p):34} {t[0]:8.2f} {t[1]:9.2f}" if t
                  else f"{os.path.basename(p):34}   щека не попала в кадр")
        return

    src_dir = cli_opt(args, "--dir")
    if src_dir:
        out_dir = cli_opt(args, "--out-dir")
        if not out_dir:
            raise SystemExit("--dir без --out-dir: писать некуда, а писать "
                             "рядом значит перемешать привитые кадры с сырыми")
        files = sorted(glob.glob(os.path.join(src_dir, "*.png"))
                       + glob.glob(os.path.join(src_dir, "*.jpg")))
        if not files:
            raise SystemExit(f"в {src_dir} нет кадров")
        os.makedirs(out_dir, exist_ok=True)
        print(f"{'кадр':30} {'sigma до':>9} {'после':>8}")
        for i, p in enumerate(files):
            _, (b, a) = graft(p, plate,
                              os.path.join(out_dir, os.path.basename(p)),
                              strength, scale, seed=i)
            print(f"  {os.path.basename(p):28} {b[0]:9.2f} {a[0]:8.2f}")
        print(f"\nпривито кадров: {len(files)}\n  → {out_dir}")
        return

    frame = [a for a in args if not a.startswith("--")
             and os.path.splitext(a)[1].lower() in (".png", ".jpg", ".jpeg")]
    if not frame:
        raise SystemExit("не передан кадр")
    dst, (b, a) = graft(frame[0], plate, cli_opt(args, "--out"), strength,
                        scale, preview=cli_opt(args, "--preview"))
    print(f"кадр: {dst}\n  до     sigma {b[0]:6.2f}  эксцесс {b[1]:6.2f}\n"
          f"  после  sigma {a[0]:6.2f}  эксцесс {a[1]:6.2f}\n"
          f"  чистая настоящая кожа  sigma  13.60  эксцесс   0.70")


if __name__ == "__main__":
    main()
