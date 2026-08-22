#!/usr/bin/env python3
"""Лист ЛИЦЕВЫХ КРОПОВ: посмотреть, один ли это человек, глазами.

  py -3 face_sheet.py <папка|файлы...> --out <файл.jpg> [--cols 4] [--px 420]
  py -3 face_sheet.py <папка> --out s.jpg --matrix     # + матрица косинусов

ЗАЧЕМ ОТДЕЛЬНО ОТ contactsheet.py. Обычный контакт-лист показывает КАДРЫ, и на
ростовом плане лицо занимает сотню пикселей — по такому листу «один ли это
человек» не решается, а кажется решённым. Здесь каждый кадр обрезается по
найденному лицу и приводится к одному размеру: лица оказываются рядом в одном
масштабе, и разница в форме носа или посадке глаз видна сразу.

ЗАЧЕМ ЭТО ВООБЩЕ. Датасет для обучения персонажной лоры отбирался КОСИНУСОМ —
той самой метрикой, про которую калибровка этого проекта написала, что между
сценами она не отличает нашу героиню от чужих людей (docs/<id>/
identity_calibration.json). Внутри одной сцены она разделяет, и датасет
собран именно оттуда, — но лицо, попавшее в обучение, станет лицом персонажа
навсегда, и принимать его на веру машине нельзя. Порядок обязан быть: сначала
глаза, потом косинус.

Кадр без найденного лица попадает на лист ЦЕЛИКОМ и подписывается «лица нет» —
молча выбрасывать его значит показать набор чище, чем он есть.
"""
import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import setup_console, cli_opt  # noqa: E402


def collect(args):
    """Пути к кадрам из папки или списка файлов."""
    if len(args) == 1 and os.path.isdir(args[0]):
        out = []
        for ext in ("*.png", "*.jpg", "*.jpeg"):
            out += glob.glob(os.path.join(args[0], "**", ext), recursive=True)
        # Свой же лист прошлого прогона лежит рядом и попадал бы в набор.
        return sorted(f for f in out
                      if "_sheet" not in os.path.basename(f).lower()
                      and "contact_sheet" not in os.path.basename(f).lower())
    return [a for a in args if os.path.isfile(a)]


def face_crop(path, px, pad=0.9):
    """Квадратный кроп по лицу, приведённый к px. (изображение, лицо|None).

    Поле вокруг бокса задано ДОЛЕЙ его размера, а не пикселями: детектор даёт
    разный бокс на портрете и на ростовом плане, и фиксированное поле в
    пикселях обрезало бы одному лоб, а другому оставляло полкадра.
    """
    from PIL import Image
    from metrics.faces import detect
    from metrics.verdict import PASS

    r = detect(path)
    im = Image.open(path).convert("RGB")
    if r.get("state") != PASS:
        # Лица нет — кадр целиком, вписанный в квадрат. Он обязан быть виден.
        w, h = im.size
        s = min(w, h)
        im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
        return im.resize((px, px), Image.LANCZOS), None

    x0, y0, x1, y1 = r["bbox"]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half = max(x1 - x0, y1 - y0) * (1 + pad) / 2
    box = (int(cx - half), int(cy - half), int(cx + half), int(cy + half))
    # Выход за край добивается чёрным, а не сдвигом кропа: сдвиг увёл бы лицо
    # из центра, и лица на листе перестали бы сравниваться между собой.
    canvas = Image.new("RGB", (box[2] - box[0], box[3] - box[1]), (12, 12, 12))
    src = im.crop((max(box[0], 0), max(box[1], 0),
                   min(box[2], im.width), min(box[3], im.height)))
    canvas.paste(src, (max(-box[0], 0), max(-box[1], 0)))
    return canvas.resize((px, px), Image.LANCZOS), r


def sheet(files, out, cols=4, px=420, matrix=False):
    from PIL import Image, ImageDraw

    if not files:
        raise SystemExit("нечего класть на лист")
    crops, faces = [], {}
    for f in files:
        img, r = face_crop(f, px)
        crops.append((f, img, r))
        if r:
            faces[f] = r["embedding"]
        print(f"  {os.path.basename(f):34} "
              f"{'лицо ' + str(round(r['det_score'], 2)) if r else 'ЛИЦА НЕТ'}")

    rows = (len(crops) + cols - 1) // cols
    pad = 26
    canvas = Image.new("RGB", (cols * px, rows * (px + pad)), (18, 18, 18))
    draw = ImageDraw.Draw(canvas)
    for i, (f, img, r) in enumerate(crops):
        x, y = (i % cols) * px, (i // cols) * (px + pad)
        canvas.paste(img, (x, y))
        label = os.path.splitext(os.path.basename(f))[0][:38]
        if r is None:
            label += "  ЛИЦА НЕТ"
        draw.text((x + 6, y + px + 6), label, fill=(200, 200, 200))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    ex = Image.Exif()
    ex[0x0131] = "persona-forge (AI-generated imagery)"
    ex[0x010E] = ("Face crops from AI-generated images of a fictional "
                  "character. Not photographs of a real person.")
    canvas.save(out, quality=94, exif=ex.tobytes())
    print(f"\n{len(crops)} лиц → {out} ({canvas.width}x{canvas.height})")

    if matrix and len(faces) > 1:
        _matrix(faces)
    return out


def _matrix(faces):
    """Полная матрица попарных косинусов — чтобы было видно, КАКАЯ пара худшая.

    Печатается целиком, а не одним минимумом: минимум говорит «где-то плохо»,
    а матрица — «плохо вот у этих двоих», и смотреть надо именно на них.
    """
    import numpy as np
    names = list(faces)
    V = np.array([faces[n] for n in names], dtype=np.float32)
    V /= np.linalg.norm(V, axis=1, keepdims=True)
    S = V @ V.T
    short = [os.path.splitext(os.path.basename(n))[0][-12:] for n in names]
    print("\nпопарный косинус:")
    print("             " + " ".join(f"{s[-6:]:>7}" for s in short))
    for i, s in enumerate(short):
        row = " ".join(f"{S[i, j]:7.3f}" if i != j else "      —"
                       for j in range(len(short)))
        print(f"  {s:>10} {row}")
    iu = [(S[i, j], short[i], short[j])
          for i in range(len(short)) for j in range(i + 1, len(short))]
    worst = min(iu)
    print(f"\n  худшая пара {worst[0]:.3f}: {worst[1]} × {worst[2]}"
          f"   — на неё и смотреть в первую очередь")
    print(f"  средняя пара {sum(x[0] for x in iu) / len(iu):.3f}, "
          f"пар {len(iu)}")


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    positional = []
    skip = False
    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a.startswith("--"):
            skip = a in ("--out", "--cols", "--px")
            continue
        positional.append(a)
    sheet(collect(positional), cli_opt(args, "--out", "face_sheet.jpg"),
          int(cli_opt(args, "--cols", 4)), int(cli_opt(args, "--px", 420)),
          "--matrix" in args)


if __name__ == "__main__":
    main()
