#!/usr/bin/env python3
"""Тату РИСУЕТ ДИФФУЗИЯ, но только в маленьком окне вокруг запястья.

  py -3 detail_tattoo.py <кадр.png> --at 0.47,0.47 [--pad 0.42]
                         [--denoise 0.42] [--seed 42] [--out <файл>]
                         [--preview <файл>]

ПОЧЕМУ ЭТО ЛУЧШЕ ВКЛЕЙКИ, ХОТЯ ПРОЕКТ ДОЛГО СЧИТАЛ ИНАЧЕ. Против диффузии
стояло одно возражение, и оно было верным: она рисует надпись каждый раз в
другом месте, другого размера и цвета, а набор — про то, что это один и тот же
человек. Но место задаёт ОКНО. Если резать кроп вокруг выбранной точки и
возвращать его туда же, дрейф размещения исчезает по построению, а остаётся
то, ради чего всё и делается: чернило рисует сама модель.

Вклейка воспроизводила это приближённо и упиралась в потолок. Её довели до
холодного тона, плотного ядра, рваного о кожу края и подкожного ореола — и всё
равно она читалась надписью НА коже, потому что графика не знает ни рельефа
под собой, ни того, как пигмент садится в дерму. Диффузия знает: она ведёт
линию по рельефу, растворяет её края в коже и ставит вокруг поры и веснушки,
которых в ассете нет. (Здесь стояло «рисует разнотолщинный штрих» — как
достоинство. Это оказалось её ДЕФЕКТОМ: разнотолщинность и есть нажим пера,
которого у однойгольной работы не бывает, см. промпт ниже.)

ОКНУ ОБЯЗАТЕЛЬНО ДАВАТЬ СВОЙ ХОЛСТ — это половина результата и тот же приём,
что в detail_face.py. На окне 230 px модель рисует надпись в 230 px: мелко и
мыльно. Растянутое до 1024 окно даёт надписи собственный масштаб.

СИЛА ПРОХОДА ЗАМЕРЕНА, лестница на одном окне и одних сидах:

    0.28   чернило едва проступает
    0.35   появляется, но случаются лишние штрихи
    0.42   ЧИТАЕТСЯ, рука не тронута          <- рабочая
    0.50   тоже читается, рука начинает плыть
    0.65+  окно перерисовывается целиком, виден шов

НОСИТЕЛЬ ОБЯЗАН БЫТЬ РЕЗКИМ, и это стоило отдельного урока. Вклейка и проход
одинаково бессильны на расфокусе: у кадра, где запястье снято мягко, резкость
участка 19 против 99 у снятого под вклейку. Скрипт меряет её сам и
предупреждает, потому что раньше это число печаталось в лог и никого не
останавливало.

РАЗМЕР ОКНА ЗАДАЁТ РАЗМЕР НАДПИСИ, и первая редакция этого не знала. Заказчица
посмотрела результат и сказала: «так тату никто не бьют». Крутить надо было не
denoise, а ОКНО: модель рисует надпись в масштабе того, что видит. На окне 0.24
кадра запястье занимает почти весь холст — строка выходит мелкой и ложится
поперёк косточки. Окно 0.42 показывает запястье вместе с куском предплечья, и
строка идёт ВДОЛЬ руки по плоскому месту, как на студийной пластине эталона
(references/tattoo_plate_studio.png). В том же окне надпись выросла с 245 до
405 px, то есть в 1.65 раза.

ЗДЕСЬ СТОЯЛА ТАБЛИЦА «ширина надписи / ширина руки: эталон 1.47, было 0.89,
стало 1.04», И ОНА ОТОЗВАНА. Ширина руки в ней бралась по столбцу кадра, а на
кропе эталона рука обрезана верхом и низом — то есть знаменателем была высота
кропа, а не рука. Числа трёх картинок сняты с разной обрезкой и между собой
несравнимы. Калиброванный размер живёт в metrics/wrist.py (LEN_OVER_W = 1.20,
снято на ПОЛНОЙ пластине, где предплечье видно целиком) — там ему и место,
второй обмер рядом означал бы вторую точку правды.

СИД ТЕПЕРЬ АРГУМЕНТ (refine.SEED). В шаблоне он был зашит числом, и выбирать
было не из чего — оставалось менять силу прохода вместо варианта. Шесть сидов
на одном окне дают шесть разных росчерков при почти одинаковой длине строки:
числа отбирают масштаб, глаз отбирает наклон и место.

ЧТО ИМЕННО ОТГРУЖЕНО И КАК ЭТО ПРОВЕРИТЬ. В references лежит носитель
(tattoo_host_wrist.png), кадр с чернилом (tattoo_host_wrist_inked.png) и холст
прохода (tattoo_canvas_1024.png). Всё три получаются одной командой:

    py -3 scripts/detail_tattoo.py references/tattoo_host_wrist.png         --at 0.47,0.47 --seed 606 --out <файл>

СИД 606 ВЫБРАН ЗАКАЗЧИЦЕЙ из листа восьми, и это стоит того, чтобы записать
отдельно. Она прислала холст файлом, вынутым из временной папки воркера. Он
оказался ВОСПРОИЗВОДИМ: PNG нёс в себе граф прогона, из графа читаются сид 606,
denoise 0.42 и промпт, совпавший с INK ниже символ в символ (879 из 879);
пересъёмка по этим числам дала холст, совпавший с присланным ПОБАЙТНО — 100%
пикселей, максимальная разница по каналу 0.

НО ЭТО ВЕРНО ТОЛЬКО В ПРЕДЕЛАХ ОДНОЙ СЕССИИ СЕРВЕРА, и я это переобещала.
После перезапуска ComfyUI тот же кадр, сид, промпт и окно дали внутри окна
совпадение 22.65% при максимальной разнице по каналу 116. Вне окна совпадение
100.0000% — но это гарантия НАШЕГО кода (вклейка считается из тех же чисел,
что и вырезание), а не модели. Значит воспроизводимы МЕСТО И РАЗМЕР, а
конкретный росчерк — нет; нужен ровно тот же — храните кадр, а не
рассчитывайте пересобрать его из сида.

ВНУТРЕННЯЯ СТОРОНА ЗАПЯСТЬЯ ПРОВЕРЕНА И ОТКЛОНЕНА. Тот же прогон на носителе с
развёрнутой ладонью даёт строку короче тыльного варианта на всех шести сидах, и
садится она на подушку большого пальца. Главное же возражение не в этом:
тыльная сторона следует из самого эталона — на фотографии видны ногти всех
четырёх пальцев, то есть кисть повёрнута тыльной стороной (character.json →
tattoo._placement).
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import refine as rf
from _util import cli_opt, imread, imwrite, setup_console

DENOISE = 0.42
# ОКНО 0.42, А НЕ 0.24 — см. шапку. Узкое окно не показывает модели
# предплечья, и она кладёт строку поперёк косточки вместо того, чтобы вести её
# вдоль руки.
PAD = 0.42
CANVAS = 1024
SHARP_MIN = 40.0        # ниже — носитель мягкий, чернило не станет чётким

# ПРОМПТ ПЕРЕПИСАН ПОД ЭТАЛОН ДВАЖДЫ, и вторая правка важнее первой.
#
# ПЕРВАЯ — про масштаб и место: «running the full width of the wrist from edge
# to edge» и «lying flat along the length of the forearm». Строка была мелкой и
# лежала поперёк косточки.
#
# ВТОРАЯ — ПРО ХАРАКТЕР ШТРИХА, и её потребовала заказчица словами «написано
# перьевой ручкой». Она права, и это видно при сравнении с пластиной эталона:
# модель по умолчанию рисует КАЛЛИГРАФИЮ — толстые нажимные штрихи вниз,
# волосяные вверх, крупные росчерки у прописных M и B. Настоящая однойгольная
# работа так не выглядит: игла идёт одной глубиной, и линия ОДНОЙ ТОЛЩИНЫ по
# всей длине, а буквы — обычный почерк, а не пропись с завитками. Отсюда
# «every stroke exactly the same constant hairline thickness from end to end as
# if traced by one needle at one depth» и «plain everyday cursive… small simple
# and upright with short plain joining strokes».
#
# ТРЕТЬЕ — бледность: «faded pale grey-blue ink sitting low in contrast»,
# «patchy and broken in a few places where it has faded unevenly». Пятнадцать
# лет — это выцветшее чернило, а не свежее.
#
# ЗАПРЕТОВ ЗДЕСЬ НЕТ НАМЕРЕННО: cfg = 1.0, негативный обусловливатель мёртв, и
# «not calligraphy» модель прочитала бы как просьбу нарисовать каллиграфию.
# Всё сказано положительно — тем, ЧТО должно быть, а не тем, чего не должно.
#
# ВЫБИРАТЬ ПРИХОДИТСЯ ГЛАЗАМИ, и это записано честно. Обмер равномерности
# штриха (максимум к медиане расстояния до края) на восьми сидах НЕ РАЗДЕЛИЛ
# каллиграфию и ровную линию: у прежнего кадра 2.9, у новых 4.0-5.0, то есть
# число говорит обратное тому, что видно при сравнении с эталоном. Причина в
# самой мерке — она берёт самые тёмные проценты пикселей, а у тонкой ровной
# линии это другая выборка, чем у нажимной. Числа для этой оси в проекте нет,
# и придумывать его под ответ нельзя; действует общее правило репозитория —
# числом отсечь заведомо негодное, ВЫБИРАТЬ ГЛАЗАМИ на 1:1.
INK = ("an extreme close macro photograph of the back of a woman's left wrist "
       "filling the frame, a small old single-needle tattoo reading Manolo "
       "Blahnik in plain everyday cursive handwriting running the full width "
       "of the wrist, every stroke exactly the same constant hairline "
       "thickness from end to end as if traced by one needle at one depth, "
       "the letters small simple and upright with short plain joining "
       "strokes, faded pale grey-blue ink sitting low in contrast against the "
       "skin, soft and slightly blurred at the edges where the pigment has "
       "spread under the skin over fifteen years, patchy and broken in a few "
       "places where it has faded unevenly, the script lying flat along the "
       "length of the forearm, mature skin around it with open pores, fine "
       "hairs, freckles and faint veins reading over and around the ink, "
       "soft north window light, natural unretouched skin, shot on "
       "film-like digital")


def sharpness(patch):
    g = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(cv2.Laplacian(g, cv2.CV_32F).var())


def window(img, at, pad):
    """Окно вокруг точки. Квадратное: модель рисует на квадратном холсте."""
    h, w = img.shape[:2]
    half = int(min(w, h) * pad / 2)
    cx, cy = int(at[0] * w), int(at[1] * h)
    x0, y0 = max(0, cx - half), max(0, cy - half)
    x1, y1 = min(w, cx + half), min(h, cy + half)
    return x0, y0, x1, y1


def run(src, at, out=None, pad=PAD, denoise=DENOISE, prompt=INK,
        preview=None, seed=rf.SEED, work=None):
    img = imread(src)
    if img is None:
        raise SystemExit("не читается кадр: " + src)
    x0, y0, x1, y1 = window(img, at, pad)
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        raise SystemExit("окно за пределами кадра — проверь --at")

    sh = sharpness(crop)
    print("окно %dx%d в кадре %dx%d, резкость участка %.0f"
          % (crop.shape[1], crop.shape[0], img.shape[1], img.shape[0], sh))
    if sh < SHARP_MIN:
        print("  ВНИМАНИЕ: участок мягкий (%.0f < %.0f). Чернило не станет "
              "чётким\n  ни этим проходом, ни вклейкой — дело в носителе, а "
              "не в настройках." % (sh, SHARP_MIN), file=sys.stderr)

    if preview:
        pv = img.copy()
        cv2.rectangle(pv, (x0, y0), (x1, y1), (0, 220, 255), 3)
        imwrite(preview, pv)
        print("превью окна:", preview)
        return preview

    work = work or os.path.join(os.path.dirname(out or src),
                                "_ink_crop.png")
    imwrite(work, cv2.resize(crop, (CANVAS, CANVAS),
                             interpolation=cv2.INTER_LANCZOS4))
    got = rf.refine(work, os.path.dirname(work) or ".", prompt,
                    denoise=denoise, scale=1.0, seed=seed)
    if not got:
        raise SystemExit("проход не вернул кадр")
    new = imread(got if isinstance(got, str) else got[0])
    new = cv2.resize(new, (crop.shape[1], crop.shape[0]),
                     interpolation=cv2.INTER_LANCZOS4)

    # Перо по краю окна: внутри правим всё, к границе растворяем. Без него шов
    # виден полосой, потому что проход слегка меняет яркость всего окна.
    m = np.zeros(crop.shape[:2], np.float32)
    b = max(4, int(min(m.shape) * 0.14))
    m[b:-b, b:-b] = 1.0
    m = cv2.GaussianBlur(m, (0, 0), b * 0.6)[..., None]

    res = img.copy()
    res[y0:y1, x0:x1] = np.clip(
        crop.astype(np.float32) * (1 - m) + new.astype(np.float32) * m,
        0, 255).astype(np.uint8)

    out = out or os.path.splitext(src)[0] + "_ink.png"
    if os.path.abspath(out) == os.path.abspath(src):
        raise SystemExit("приёмник совпадает с источником: проход не "
                         "идемпотентен, второй прогон нарисует поверх первого")
    imwrite(out, res)
    print("готово:", out)
    return out


def main():
    setup_console()
    args = sys.argv[1:]
    if not args or args[0].startswith("--"):
        print(__doc__)
        raise SystemExit(1)
    at = cli_opt(args, "--at")
    if not at:
        raise SystemExit("нужен --at x,y в долях кадра")
    run(args[0], tuple(float(v) for v in at.split(",")),
        out=cli_opt(args, "--out"),
        pad=float(cli_opt(args, "--pad", str(PAD))),
        denoise=float(cli_opt(args, "--denoise", str(DENOISE))),
        prompt=cli_opt(args, "--prompt", INK),
        seed=int(cli_opt(args, "--seed", str(rf.SEED))),
        preview=cli_opt(args, "--preview"))


if __name__ == "__main__":
    main()
