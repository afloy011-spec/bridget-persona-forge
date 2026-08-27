#!/usr/bin/env python3
"""Контакт-шит: много кадров одним листом.

  py -3 contactsheet.py <папка|frames.json> --out <файл.jpg> [--cols 4]
                        [--label] [--width 2400]

ЗАЧЕМ. Отбор идёт по НАБОРУ, а не по кадру. Пять хороших по отдельности
портретов пяти разных женщин — это провал главного критерия ТЗ, и увидеть это
можно только положив кадры рядом. То же на кастинге: лицо выбирается сравнением,
а не последовательным просмотром.

--label подписывает каждую клетку именем файла: без подписи найти в папке
понравившийся кадр невозможно.
"""
import os, sys, json, glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import setup_console, cli_opt


def collect(src):
    """Папка → отсортированный список PNG/JPG; frames.json → порядок реестра."""
    if os.path.isdir(src):
        files = sorted(glob.glob(os.path.join(src, "**", "*.png"), recursive=True)
                       + glob.glob(os.path.join(src, "**", "*.jpg"), recursive=True))
        # Свой же лист прошлого прогона лежит в той же папке и попадал в набор
        # шестым кадром — контакт-шит внутри контакт-шита.
        return [f for f in files
                if "contact_sheet" not in os.path.basename(f).lower()]
    with open(src, encoding="utf-8") as fh:
        return [e["file"] for e in json.load(fh) if os.path.exists(e["file"])]


def _fit_cols(n):
    """Колонок по умолчанию — СТОЛЬКО, СКОЛЬКО КАДРОВ, если их немного.

    Жёсткая четвёрка оставляла у сдачи из пяти кадров вторую строку с одним
    кадром и чёрной дырой на три четверти листа — в файле, который README
    обещает ревьюеру как «contact_sheet.jpg в каждой папке части». Лист для
    того и нужен, чтобы кадры лежали РЯДОМ и сравнивались одним взглядом;
    перенос пятого вниз ровно это и ломает. Пять — предел читаемости на
    2400 px по ширине, дальше кадры мельчают.
    """
    return n if n <= 5 else 4


def sheet(files, out, cols=4, width=2400, label=False):
    from PIL import Image, ImageDraw
    if not files:
        raise SystemExit("нечего класть на лист")
    rows = (len(files) + cols - 1) // cols
    cw = width // cols
    # Клетка по САМОМУ ВЫСОКОМУ кадру набора, а кадры вписываются в неё с
    # сохранением пропорций. Раньше высота бралась у первого кадра и все
    # остальные принудительно масштабировались в неё: кадр 1024x1536 среди
    # 1152x1440 приезжал сплющенным — то самое «враньё про кадрирование»,
    # против которого стоял соседний комментарий.
    ratios = []
    for f in files:
        with Image.open(f) as im:
            ratios.append(im.height / im.width)
    ch = int(cw * max(ratios))
    pad = 24 if label else 0
    canvas = Image.new("RGB", (width, rows * (ch + pad)), (18, 18, 18))
    draw = ImageDraw.Draw(canvas)
    for i, f in enumerate(files):
        with Image.open(f) as im:
            im = im.convert("RGB")
            w = min(cw, int(ch * im.width / im.height))
            h = min(ch, int(cw * im.height / im.width))
            im = im.resize((max(w, 1), max(h, 1)), Image.LANCZOS)
            x = (i % cols) * cw + (cw - im.width) // 2
            y = (i // cols) * (ch + pad) + (ch - im.height) // 2
            canvas.paste(im, (x, y))
            if label:
                draw.text((x + 8, y + ch + 5), os.path.basename(f)[:44],
                          fill=(190, 190, 190))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    # Пометка о происхождении. Контакт-шит лежит в той же папке сдачи и
    # уходит клиенту так же, как кадры, — он был единственным файлом сдачи
    # без неё.
    ex = Image.Exif()
    ex[0x0131] = "persona-forge (AI-generated imagery)"
    ex[0x010E] = ("Contact sheet of AI-generated images of a fictional "
                  "character. Not photographs of a real person.")
    canvas.save(out, quality=92, exif=ex.tobytes())
    print(f"{len(files)} кадров → {out} ({canvas.width}x{canvas.height})")
    return out


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__); raise SystemExit(1)

    def opt(k, d=None):
        return cli_opt(args, k, d)

    files = collect(args[0])
    sheet(files, opt("--out", "contact_sheet.jpg"),
          int(opt("--cols", 0)) or _fit_cols(len(files)),
          int(opt("--width", 2400)), "--label" in args)


if __name__ == "__main__":
    main()
