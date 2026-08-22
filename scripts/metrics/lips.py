#!/usr/bin/env python3
"""Губы: во сколько раз нижняя губа полнее верхней. Толщины — в долях IPD.

  py -3 scripts/metrics/lips.py [<кадр> … | <папка> …]

Без аргументов проходит по `<work_root>/bridget/frames`. Самотест портит каждый
кадр известным способом (двигает шов рта, сжимает кадр по горизонтали), печатает
таблицу, зазор между «признак есть» и «признака нет» и падает НЕнулевым кодом,
если порог из зазора вышел. Числа замеров печатает он, а не эта шапка.

ЗАЧЕМ. Карточка персонажа объявляет «thin upper lip and fuller lower lip» — один
из признаков, по которым героиню опознают. Косинус ArcFace к нему равнодушен: он
меряет общее устройство лица, а не пропорцию двух полосок в четверть носа
шириной. Обещание было объявлено и не проверялось ничем.

РАЗМЕТКА 106 ТОЧЕК, УСТАНОВЛЕННАЯ ЭКСПЕРИМЕНТОМ. Соответствие индексов частям
лица нигде не записано; оно получено так: точки с номерами нарисованы поверх
кадра и прочитаны глазами, а деление внутреннего контура на верхний и нижний
проверено на кадре с ОТКРЫТЫМ ртом — на закрытом обе половины лежат друг на
друге и неразличимы.

  0-32    контур лица: 0 — центр подбородка, 1 и 17 — у висков, 9…16 и 25…32
          спускаются по щекам, 2…8 и 18…24 идут по челюсти к подбородку;
  33-42   глаз СЛЕВА ОТ ЗРИТЕЛЯ (её правый);      43-51  бровь над ним;
  87-96   глаз СПРАВА ОТ ЗРИТЕЛЯ (её левый);      97-105 бровь над ним;
  72-86   нос: 72 переносица, 73-74 спинка, 75 и 81 внутренние углы глаз,
          76/82 верх крыльев, 77/83 наружные края, 78/84 низ крыльев,
          79/85 основания ноздрей, 80 подносовая точка, 86 кончик;
  52-71   рот:
            52, 61          наружные углы (52 — слева от зрителя);
            64, 63, 71, 67, 68   наружный верх: 63 и 67 — вершины лука
                            Купидона, 71 — впадина между ними;
            55, 56, 53, 59, 58   наружный низ, 53 — центр;
            65, 69          внутренние углы;
            66, 62, 70      ВНУТРЕННИЙ край ВЕРХНЕЙ губы (62 — центр);
            54, 60, 57      ВНУТРЕННИЙ край НИЖНЕЙ губы (60 — центр).

ПОЧЕМУ ТОЛЩИНА СЧИТАЕТСЯ ПО ПИКСЕЛЯМ, А НЕ ПО ЭТОМУ ЖЕ КОНТУРУ. Первая редакция
брала толщину прямо из точек: верхняя губа = 62 минус 71, нижняя = 53 минус 60.
Замер это отверг. Если на настоящем кадре сдвинуть шов рта вниз — оставив
наружный контур губ на месте, то есть ровно перевернув признак карточки, — то
глазами верхняя губа становится толще нижней, а контур 2d106det этого почти не
замечает: он держит форму рта, заученную моделью, и отвечает сдвигом вдвое
меньше настоящего, причём отношение уезжает В ОБРАТНУЮ СТОРОНУ. То есть контур
меряет не кадр, а представление детектора о том, как выглядит рот. Самотест
печатает обе колонки рядом на одной и той же мутации, и разницу видно.

Поэтому точки задают ГДЕ смотреть (система координат лица, положение шва,
ширина рта и колонки поперёк него), а толщину даёт изображение: на каждой
колонке берётся профиль поперёк губ, и кайма отделяется от кожи собственной
разделяющей функцией ЭТОГО кадра. Образцы каймы берутся вплотную к шву, где
она есть всегда, образцы кожи — заметно выше и ниже рта; по ним строится
линейный разделитель в (L*, a*, b*). Ни помада, ни загар, ни свет не задают
общего порога — он свой на каждом кадре.

МАСШТАБ — В ДОЛЯХ МЕЖЗРАЧКОВОГО РАССТОЯНИЯ, как в sharpness.py и skin.py: в
пикселях «толстая губа» означала бы разное на портрете и на ростовом плане, и
метрика мерила бы крупность плана. Само отношение к масштабу безразлично вдвойне
— оно частное двух длин, — но толщины отдаются наружу и в долях IPD сравнимы.

ПОВОРОТ ГОЛОВЫ КОМПЕНСИРОВАТЬ НЕ НАДО, И ЭТО ЗАМЕР, А НЕ ДОПУЩЕНИЕ. Отношение
— частное двух ВЕРТИКАЛЬНЫХ длин, а поворот вокруг вертикальной оси сжимает
кадр по ГОРИЗОНТАЛИ; в частном сжатие сокращается. Самотест проверяет это
прямо: он сжимает кадр по горизонтали (что для плоского лица и есть поворот в
ортогональной проекции) и требует, чтобы отношение осталось прежним, — при том
что IPD, а с ним и обе толщины в его долях, честно уезжают. Ловится не поворот,
а НАКЛОН: когда рот виден под углом сверху или снизу, верхняя и нижняя губы
укорачиваются по-разному, и частное перестаёт сокращаться. Отдельного порога по
углу наклона у метрики нет — вместо него стоит проверка на согласие колонок
(ниже), которая ловит и наклон, и тень, и перекрытие, и делает это по самому
замеру, а не по оценке позы.

ПОРОГ ВОРОТ ЖИВЁТ В МАНИФЕСТЕ — `assets.json` → `gates.lip_ratio_min`, во
сколько раз нижняя губа обязана быть толще верхней; пол по размеру лица там же
и общий с резкостью и кожей — `gates.min_face_ipd_px`. Запасных значений в коде
нет намеренно: запасное значение — это второй, невидимый порог, который
продолжает судить после того, как манифест поправили. Перекалибровка — тот же
самотест: он двигает шов рта на настоящих кадрах, печатает зазор между копиями
с признаком и без и падает, если порог из зазора вышел.

ТРИ СОСТОЯНИЯ. Метрика отказывается считать и говорит почему:
  * лица нет, или оно мельче `gates.min_face_ipd_px`;
  * рот не закрыт — внутренние контуры разошлись больше `MOUTH_GAP_MAX`. На
    приоткрытом рте профиль упирается не в кайму, а в зубы и в темноту, и
    отношение сваливается ниже порога на кадрах, где глазами признак на месте.
    Это был бы брак на ровном месте, поэтому здесь NOT_MEASURED;
  * кайма не отделяется от кожи (широкая улыбка, губы вне фокуса, свет в упор);
  * КОЛОНКИ НЕ СОГЛАСНЫ: отношение, посчитанное на разных колонках поперёк рта,
    разъезжается сильнее `MAX_IQR`. Так выглядят наклон головы, тень от носа на
    половину рта и перекрытый угол рта — то есть все случаи, когда одна цифра
    на весь рот врёт. Порог этой проверки калиброван по кадрам, размеченным
    глазами: он поставлен в зазор между кадрами, где замер сходится с глазами,
    и кадрами, где он им противоречит.

ЧТО ЭТА МЕТРИКА НЕ ДЕЛАЕТ. Она НЕ опознаёт человека. На пуле кастинга —
другие женщины по тому же описанию — отношение лежит в той же полосе, что у
героини: модель рисует полную нижнюю губу почти всем. Ворота отвечают на вопрос
«обещанный карточкой признак в этом кадре виден?», а не «это она?». Разброс по
обоим пулам печатает самотест.
"""
import sys, os, glob, math

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _util import setup_console, manifest
from metrics import load_bgr
from metrics.verdict import FAIL, NOT_MEASURED, PASS, gate, not_measured

# Индексы разметки 106 точек — см. карту в шапке. Внутренние края верхней и
# нижней губы идут парами по одним и тем же колонкам: 66-54, 62-60, 70-57.
IN_UP = (66, 62, 70)
IN_LO = (54, 60, 57)
CORNERS = (52, 61)

BAND = 0.30        # полполосы профиля поперёк губ, доли IPD: за неё уходит
                   # заведомо кожа, на ней и берутся образцы «не губа»
MAX_LIP = 0.22     # предельная толщина ОДНОЙ губы, доли IPD. Кайма шире —
                   # значит разделитель поймал не губу, а тень или бороду
SKIN_AT = 0.26     # где брать образцы кожи, доли IPD от шва
LIP_AT = 0.015     # где брать образцы каймы: вплотную к шву, там она есть
                   # всегда — даже у самой тонкой верхней губы
CLOSE = 0.018      # заращивание дырки в кайме, доли IPD: блик на мокрой губе
                   # рвёт её надвое, и нижняя губа читалась бы вдвое тоньше
COLS = 11          # колонок поперёк рта
SPAN = 0.42        # доля полуширины рта, дальше которой колонки не ставятся:
                   # к углам обе губы сходятся в точку и отношение вырождается
MIN_COLS = 0.6     # доля колонок, которая обязана сойтись

MOUTH_GAP_MAX = 0.045   # рот считается закрытым, доли IPD
MIN_SEP = 2.0           # разделимость каймы и кожи, в сигмах
MAX_IQR = 0.30     # разброс отношения по колонкам (межквартильный). Стоит в
                   # зазоре между кадрами, где замер сходится с глазами, и
                   # кадрами, где он им противоречит, — и заодно ниже точки,
                   # после которой отношение перестаёт переживать сжатие по
                   # горизонтали (самотест печатает и то, и другое)

INV_TOL = 0.15     # допуск инвариантности к сжатию по горизонтали (самотест)


def face_frame(kps):
    """Начало координат, единица длины и оси лица по пяти точкам детектора.

    Возвращает (центр между зрачками, IPD, «вправо у зрителя», «вниз по лицу»).
    Оси строятся по линии глаз, а не по краям кадра: голова наклонена почти
    всегда, и профиль, взятый по вертикали кадра, резал бы губы наискось.
    """
    k = np.asarray(kps, np.float32)
    eyes = k[:2][np.argsort(k[:2, 0])]
    centre = eyes.mean(axis=0)
    ex = eyes[1] - eyes[0]
    ipd = float(np.hypot(*ex))
    if ipd <= 0:
        return None
    ux = ex / ipd
    uy = np.array([-ux[1], ux[0]], np.float32)
    # «Вниз» сверяется по носу: у зеркального или перевёрнутого кадра знак иной,
    # и профиль искал бы губы на лбу.
    if float((k[2] - centre) @ uy) < 0:
        uy = -uy
    return centre, ipd, ux, uy


def yaw_ratio(kps):
    """Поворот головы как асимметрия носа между глазами: 0 анфас, ±1 профиль.

    Наружу отдаётся справочно. Ворота по нему НЕ ставятся: отношение толщин —
    частное вертикальных длин, и горизонтальное сжатие в нём сокращается (см.
    шапку и проверку «сжат по X» в самотесте).
    """
    f = face_frame(kps)
    if f is None:
        return None
    centre, ipd, ux, _ = f
    x = (np.asarray(kps, np.float32) - centre) @ ux / ipd
    dl, dr = abs(x[0] - x[2]), abs(x[1] - x[2])
    if x[0] > x[1]:
        dl, dr = dr, dl
    return float((dl - dr) / (dl + dr)) if (dl + dr) else 0.0


def _profiles(lab, centre, ux, uy, cols_x, seam_y, ts):
    """Полосы поперёк губ: массив (точек профиля, колонок, 3) в L*a*b*."""
    grid = (centre[None, None, :]
            + cols_x[None, :, None] * ux[None, None, :]
            + (seam_y[None, :, None] + ts[:, None, None]) * uy[None, None, :])
    return cv2.remap(lab, grid[..., 0].astype(np.float32),
                     grid[..., 1].astype(np.float32),
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def lips(src, face=None, gates=None):
    """Ворота пропорции губ. Результат в формате `verdict.gate`.

    value — во сколько раз нижняя губа толще верхней.
    """
    g = gates if gates is not None else manifest()["gates"]
    # Порог берётся из манифеста БЕЗ запасного значения: запасное — это второй,
    # невидимый порог, который продолжает судить после того, как манифест
    # поправили. Отсутствие ключа обязано быть слышно — раннер ворот превратит
    # исключение в NOT_MEASURED с причиной.
    lo = float(g["lip_ratio_min"])
    min_ipd = float(g["min_face_ipd_px"])

    if face is None:
        from metrics.faces import detect
        face = detect(src)
    if not face or face.get("state") != PASS:
        why = (face or {}).get("note") or "лицо не передано и не найдено"
        return not_measured("lips", f"пропорция губ не замерена — {why}")
    if face.get("kps106") is None:
        return not_measured("lips", "детектор не отдал разметку 106 точек — "
                                    "по пяти точкам контур губ не построить")
    if face["ipd_px"] < min_ipd:
        return not_measured(
            "lips", f"лицо мелкое: IPD {face['ipd_px']:.0f} px < {min_ipd:.0f} — "
                    f"кайма губы уходит под несколько пикселей",
            ipd_px=face["ipd_px"])

    frame = face_frame(face["kps"])
    if frame is None:
        return not_measured("lips", "зрачки совпали — системы координат "
                                    "лица не построить")
    centre, ipd, ux, uy = frame
    yaw = yaw_ratio(face["kps"])

    img = load_bgr(src)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    k = np.asarray(face["kps106"], np.float32)
    P = (k - centre) @ np.stack([ux, uy], 1)      # координаты лица, пиксели

    gap = float(np.mean(P[list(IN_LO), 1] - P[list(IN_UP), 1])) / ipd
    if gap > MOUTH_GAP_MAX:
        return not_measured(
            "lips", f"рот не закрыт: внутренние контуры разошлись на {gap:.3f} "
                    f"IPD (предел {MOUTH_GAP_MAX}) — профиль упирается в зубы, "
                    f"а не в кайму", mouth_gap=gap, ipd_px=ipd, yaw=yaw)

    inner = np.array(IN_UP + IN_LO)
    order = np.argsort(P[inner, 0])
    xs_in, ys_in = P[inner[order], 0], P[inner[order], 1]
    half = float(P[CORNERS[1], 0] - P[CORNERS[0], 0]) / 2.0
    if half <= 0:
        return not_measured("lips", "углы рта перепутаны местами — "
                                    "разметка не читается", ipd_px=ipd, yaw=yaw)
    cx0 = float(P[list(CORNERS), 0].mean())
    cols_x = cx0 + np.linspace(-SPAN, SPAN, COLS) * half
    seam_y = np.interp(cols_x, xs_in, ys_in)

    n = 241
    step = 2 * BAND * ipd / (n - 1)
    ts = np.linspace(-BAND * ipd, BAND * ipd, n)
    prof = _profiles(lab, centre, ux, uy, cols_x, seam_y, ts)

    # Шов уточняется по самому тёмному пикселю у центра профиля: интерполяция
    # внутреннего контура даёт его с точностью до пары пикселей, а от шва потом
    # отсчитываются обе толщины, и ошибка в нём вычитается из одной губы и
    # прибавляется к другой — то есть входит в отношение дважды.
    w = max(2, int(0.04 * ipd / step))
    seam_i = (n // 2 - w) + np.argmin(prof[n // 2 - w:n // 2 + w + 1, :, 0], axis=0)

    rad = max(1, int(LIP_AT * ipd / step))
    off = int(SKIN_AT * ipd / step)
    lip_s, skin_s = [], []
    for j in range(COLS):
        s = int(seam_i[j])
        lip_s.append(prof[max(0, s - rad):s + rad + 1, j, :])
        skin_s.append(prof[max(0, s - off - 3):max(1, s - off + 4), j, :])
        skin_s.append(prof[min(n - 8, s + off - 3):min(n - 1, s + off + 4), j, :])
    lip_s = np.concatenate(lip_s, 0)
    skin_s = np.concatenate(skin_s, 0)
    if len(lip_s) < 10 or len(skin_s) < 10:
        return not_measured("lips", "полоса профиля вышла за кадр",
                            ipd_px=ipd, yaw=yaw, mouth_gap=gap)

    # Линейный разделитель «кайма / кожа» СВОЙ НА КАЖДОМ КАДРЕ. Общий порог по
    # красноте не годится: помада, загар, тёплый свет и тень от носа двигают его
    # сильнее, чем сама кайма отличается от кожи.
    mu_l, mu_s = lip_s.mean(0), skin_s.mean(0)
    cov = (np.cov(lip_s.T) * len(lip_s) + np.cov(skin_s.T) * len(skin_s)) \
        / (len(lip_s) + len(skin_s)) + np.eye(3)
    wv = np.linalg.solve(cov, mu_l - mu_s)
    pl, ps = lip_s @ wv, skin_s @ wv
    sep = float((pl.mean() - ps.mean()) / (0.5 * (pl.std() + ps.std()) + 1e-6))
    if sep < MIN_SEP:
        return not_measured(
            "lips", f"кайма не отделяется от кожи (разделимость {sep:.1f} < "
                    f"{MIN_SEP}) — губы вне фокуса, в тени или рот открыт",
            separability=sep, ipd_px=ipd, yaw=yaw, mouth_gap=gap)
    thr = 0.5 * (pl.mean() + ps.mean())

    mask = (prof @ wv) > thr
    kclose = max(1, int(CLOSE * ipd / step))
    lim = int(MAX_LIP * ipd / step)
    ups, los, why = [], [], []
    for j in range(COLS):
        m = cv2.morphologyEx(mask[:, j].astype(np.uint8).reshape(-1, 1),
                             cv2.MORPH_CLOSE,
                             np.ones((2 * kclose + 1, 1), np.uint8)).ravel()
        s = int(seam_i[j])
        if not m[s]:
            why.append("шов не попал в кайму")
            continue
        u, l = s, s
        while u > 0 and m[u - 1]:
            u -= 1
        while l < n - 1 and m[l + 1]:
            l += 1
        if s - u >= lim or l - s >= lim or u == 0 or l == n - 1:
            why.append("кайма не кончилась внутри полосы")
            continue
        ups.append((s - u) * step / ipd)
        los.append((l - s) * step / ipd)
    if len(ups) < MIN_COLS * COLS:
        return not_measured(
            "lips", f"колонок сошлось {len(ups)} из {COLS}: "
                    f"{why[0] if why else 'кайма не найдена'}",
            columns=len(ups), separability=sep, ipd_px=ipd, yaw=yaw,
            mouth_gap=gap)

    per_col = np.asarray(los) / np.maximum(np.asarray(ups), 1e-4)
    iqr = float(np.percentile(per_col, 75) - np.percentile(per_col, 25))
    upper, lower = float(np.median(ups)), float(np.median(los))
    value = lower / max(upper, 1e-4)
    if iqr > MAX_IQR:
        # Колонки разъехались — одна цифра на весь рот врёт. Так выглядит
        # наклон головы, тень от носа на половину рта, перекрытый угол.
        return not_measured(
            "lips", f"колонки не согласны: разброс отношения {iqr:.2f} > "
                    f"{MAX_IQR} — рот виден под углом, в тени или перекрыт",
            columns=len(ups), column_iqr=iqr, separability=sep, ipd_px=ipd,
            yaw=yaw, mouth_gap=gap, lip_ratio=value)

    return gate("lips", value, lo=lo, hi=None,
                note="" if value >= lo else
                     "верхняя губа не тоньше нижней — признак карточки в кадре "
                     "не читается",
                upper_ipd=upper, lower_ipd=lower, columns=len(ups),
                column_iqr=iqr, separability=sep, mouth_gap=gap,
                ipd_px=ipd, yaw=yaw)


def measure(src, face=None, gates=None):
    """Второе имя тех же ворот: `gates.py` ищет метрику по списку кандидатов.

    Синоним, а не отдельный расчёт. Обёртка, отдающая голые числа, лишила бы
    результат поля `state`, и раннер объявил бы живую метрику незамером.
    """
    return lips(src, face=face, gates=gates)


def contour_ratio(face):
    """То же отношение, но ПО ТОЧКАМ 2d106det. Нужно только самотесту.

    Первая редакция метрики считала так, и самотест печатает эту колонку рядом
    с пиксельной, чтобы разница была видна на одной и той же мутации, а не
    оставалась утверждением в шапке.
    """
    frame = face_frame(face["kps"])
    if frame is None or face.get("kps106") is None:
        return None
    centre, ipd, ux, uy = frame
    P = (np.asarray(face["kps106"], np.float32) - centre) @ np.stack([ux, uy], 1)
    up = float(P[62, 1] - P[71, 1])
    lowr = float(P[53, 1] - P[60, 1])
    return lowr / up if up > 1e-6 else None


# ---------------------------------------------------------------- порча кадра

def move_seam(img, face, share):
    """Переставить шов рта так, чтобы верхняя губа заняла долю `share` рта.

    Кусочно-линейная растяжка вдоль оси лица с узлами «верх губ → верх губ»,
    «новый шов → старый шов», «низ губ → низ губ»: снаружи рот не меняется,
    меняется только то, какую его часть занимает верхняя губа.

    ДОЛЯ, А НЕ СДВИГ В ДОЛЯХ IPD. Первая редакция двигала шов на фиксированную
    величину, и метка «на этой копии признака уже нет» держалась только на
    кадрах с типичной пропорцией: на кадре, где нижняя губа и без того вдвое
    полнее, тот же сдвиг оставлял признак на месте, и калибровка получала в
    отрицательный класс кадр, на котором глазами признак есть. Доля 0.5 — это
    «губы поровну» на любом кадре, и метка держится на всех.

    Возвращает None, если растяжка перестала бы быть монотонной: порча
    превратилась бы в кашу, и мерить на ней нечего.
    """
    frame = face_frame(face["kps"])
    if frame is None:
        return None
    centre, ipd, ux, uy = frame
    P = (np.asarray(face["kps106"], np.float32) - centre) @ np.stack([ux, uy], 1)
    seam = float(np.mean(P[list(IN_UP + IN_LO), 1]))
    top = float(np.mean(P[[63, 71, 67], 1]))
    bot = float(np.mean(P[[56, 53, 59], 1]))
    d = (top + share * (bot - top)) - seam
    pad = 0.9 * (bot - top)
    y0, y1 = top - pad, bot + pad
    xo = np.array([y0, top, seam + d, bot, y1], np.float32)
    xi = np.array([y0, top, seam, bot, y1], np.float32)
    if not np.all(np.diff(xo) > 1.0):
        return None

    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rel = np.stack([xx - centre[0], yy - centre[1]], -1)
    a, b = rel @ ux, rel @ uy
    src = np.interp(b, xo, xi).astype(np.float32)
    halfx = ipd * 0.55
    t = np.clip((halfx - np.abs(a)) / (0.15 * ipd), 0, 1)
    t *= ((b > y0) & (b < y1)).astype(np.float32)
    src = b + (src - b) * t
    pt = (centre[None, None, :] + a[..., None] * ux + src[..., None] * uy)
    return cv2.remap(img, pt[..., 0].astype(np.float32),
                     pt[..., 1].astype(np.float32), cv2.INTER_CUBIC,
                     borderMode=cv2.BORDER_REPLICATE)


def mirror_lower_up(img, face):
    """Отразить нижнюю губу вверх через шов: на копии губы РАВНЫ ТОЧНО.

    Зачем отдельно от `move_seam`. Ту порчу строит контур 2d106det, а он на
    части кадров вписан в кайму несимметрично: копия, у которой верхняя губа
    занимает ровно половину рта ПО КОНТУРУ, глазами и по пикселям остаётся
    кадром с более полной нижней губой. Метка «признака нет» на такой копии
    держится не всегда, а зазор калибруется именно по меткам.

    Здесь метка точна по построению и ни от какого замера не зависит: верхняя
    губа — это зеркальная копия нижней, то есть они равны, и признак карточки
    на копии отсутствует, каким бы способом его ни мерили.
    """
    frame = face_frame(face["kps"])
    if frame is None:
        return None
    centre, ipd, ux, uy = frame
    P = (np.asarray(face["kps106"], np.float32) - centre) @ np.stack([ux, uy], 1)
    seam = float(np.mean(P[list(IN_UP + IN_LO), 1]))
    bot = float(np.mean(P[[56, 53, 59], 1]))
    # Отражать надо через ТЁМНУЮ ЛИНИЮ шва, а не через её оценку по контуру:
    # промах в пару пикселей входит в отношение дважды (одну губу укорачивает,
    # другую удлиняет), и «точно равные» губы получались бы не точно равными.
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    half = float(P[CORNERS[1], 0] - P[CORNERS[0], 0]) / 2.0
    cx0 = float(P[list(CORNERS), 0].mean())
    probe = np.linspace(-0.36 * ipd, 0.36 * ipd, 145)
    cols = cx0 + np.linspace(-SPAN, SPAN, COLS) * half
    prof = _profiles(lab, centre, ux, uy, cols, np.full(COLS, seam), probe)
    seam += float(np.median(probe[np.argmin(prof[:, :, 0], axis=0)]))
    # С запасом: контурная граница нижней губы вписана внутрь каймы, и полоса
    # ровно до неё срезала бы отражённой верхней губе верхушку — копия
    # получалась бы не «губы равны», а «верхняя чуть тоньше».
    h = max((bot - seam) + 0.05 * ipd, 2.0)

    hgt, w = img.shape[:2]
    yy, xx = np.mgrid[0:hgt, 0:w].astype(np.float32)
    rel = np.stack([xx - centre[0], yy - centre[1]], -1)
    a, b = rel @ ux, rel @ uy
    src = 2 * seam - b
    # Мягкие края: по X — чтобы не рвать щёки, по Y — чтобы отражённый кусок
    # переходил в настоящую кожу над ртом без ступеньки.
    tx = np.clip((ipd * 0.55 - np.abs(a)) / (0.15 * ipd), 0, 1)
    # Переход по Y узкий и в долях IPD, а не в долях полосы: широкий переход
    # смешивал бы отражённую кайму с настоящей кожей над ртом, и разделитель
    # читал бы получившуюся смесь как продолжение губы.
    ty = np.clip((b - (seam - h)) / (0.02 * ipd), 0, 1) * (b <= seam)
    t = tx * ty
    src = b + (src - b) * t
    pt = (centre[None, None, :] + a[..., None] * ux + src[..., None] * uy)
    return cv2.remap(img, pt[..., 0].astype(np.float32),
                     pt[..., 1].astype(np.float32), cv2.INTER_CUBIC,
                     borderMode=cv2.BORDER_REPLICATE)


def squeeze_x(img, factor):
    """Сжать кадр по горизонтали — для плоского лица это и есть поворот головы
    в ортогональной проекции. Вертикальные длины при этом не трогаются, а IPD
    честно уменьшается: отношение толщин обязано выжить, сами толщины — нет."""
    h, w = img.shape[:2]
    small = cv2.resize(img, (max(8, int(w * factor)), h),
                       interpolation=cv2.INTER_AREA)
    out = np.zeros_like(img)
    x0 = (w - small.shape[1]) // 2
    out[:, x0:x0 + small.shape[1]] = small
    out[:, :x0] = small[:, :1]
    out[:, x0 + small.shape[1]:] = small[:, -1:]
    return out


# ------------------------------------------------------------------- самотест

def _frames(argv):
    if argv:
        out = []
        for a in argv:
            if os.path.isdir(a):
                for ext in ("*.png", "*.jpg", "*.jpeg"):
                    out += glob.glob(os.path.join(a, "**", ext), recursive=True)
            else:
                out.append(a)
        return sorted(f for f in out
                      if "sheet" not in os.path.basename(f).lower())
    root = os.path.join(manifest()["paths"]["work_root"], "bridget", "frames")
    return sorted(glob.glob(os.path.join(root, "*", "*.png"))
                  + glob.glob(os.path.join(root, "*.png")))


# Порча и то, чем она обязана обернуться. Метки проверены глазами на кропах губ
# в полном разрешении: на зеркальной копии губы читаются как равные, на копии
# «верх 2/3 рта» верхняя явно толще нижней — признака карточки нет ни там, ни
# там. Доля 1/2 в отрицательный класс НЕ взята намеренно: её задаёт контур
# 2d106det, а он на части кадров вписан в кайму несимметрично, и копия,
# «равная по контуру», глазами остаётся кадром с более полной нижней губой.
VARIANTS = [
    ("оригинал", None, "есть"),
    ("верх 1/3 рта", lambda i, f: move_seam(i, f, 0.33), "есть"),
    ("губы зеркально", mirror_lower_up, "нет"),
    ("верх 2/3 рта", lambda i, f: move_seam(i, f, 0.66), "нет"),
]

# Лесенка сжатия по горизонтали = лесенка поворота головы: cos угла и есть
# множитель. Верхняя граница применимости по повороту не назначается, а
# ЗАМЕРЯЕТСЯ — самотест печатает, до какого угла метрика ещё считает.
SQUEEZE_LADDER = (0.9, 0.8, 0.7, 0.6, 0.5)
SQUEEZE_MUST_HOLD = 0.8   # этот угол обязана держать любая метрика пропорции:
                          # он ещё далёк от того, чтобы дальний угол рта ушёл
                          # из вида, и отношение вертикальных длин здесь просто
                          # обязано сокращать сжатие


def main():
    setup_console()
    files = _frames(sys.argv[1:])
    if not files:
        raise SystemExit("нечего мерить: передайте кадры или папку")
    from metrics.faces import detect

    g = manifest()["gates"]
    print(f"порог из манифеста: нижняя губа толще верхней хотя бы в "
          f"{g['lip_ratio_min']} раза; пол по IPD {g['min_face_ipd_px']} px")
    print(f"пределы применимости (доли IPD, кроме последних двух): рот закрыт "
          f"до {MOUTH_GAP_MAX}, полоса профиля {BAND}, губа не толще {MAX_LIP}, "
          f"колонок {COLS} на {2 * SPAN} ширины рта,\nразделимость каймы и кожи "
          f"от {MIN_SEP} сигм, разброс по колонкам до {MAX_IQR}\n")
    print(f"{'кадр':26} {'вариант':16} {'IPD':>5} {'верх':>6} {'низ':>6} "
          f"{'отн':>6} {'IQR':>5} {'по точкам':>10}  вердикт")

    bad = 0
    yes, no, limits, contour_span = [], [], [], []
    for path in files:
        img = load_bgr(path)
        name = os.path.basename(path)[:25]
        base_face = detect(img)
        if base_face["state"] != PASS:
            # Не расхождение: кадр без найденного лица метрика и обязана
            # отдавать незамером. Считать это провалом самотеста значило бы
            # краснеть на чужой поломке — на детекторе, а не на этих воротах.
            print(f"{name:26} {'вне калибровки':16} {base_face['note']}\n")
            continue
        base = lips(img, face=base_face, gates=g)
        if base["state"] == NOT_MEASURED:
            # Метрика отказалась считать по своей же объявленной причине —
            # это не расхождение, а работа третьего состояния. Кадр выпадает
            # из калибровки целиком, иначе самотест краснел бы там, где всё
            # правильно (открытый рот, мелкое лицо, рот под углом).
            print(f"{name:26} {'вне калибровки':16} {base['note']}\n")
            continue

        vals, cvals = {}, {}
        for tag, spoil, want in VARIANTS:
            v = img if spoil is None else spoil(img, base_face)
            if v is None:
                print(f"{name:26} {tag:16} порча невозможна: сдвиг съедает губу")
                continue
            f = detect(v)
            r = lips(v, face=f, gates=g) if f["state"] == PASS else \
                not_measured("lips", f["note"])
            cr = contour_ratio(f) if f["state"] == PASS else None
            if r["value"] is not None:
                vals[tag] = r["value"]
                cvals[tag] = cr
                (yes if want == "есть" else no).append(r["value"])
            _row(name, tag, r, cr)

        # Лесенка сжатия по горизонтали: проверка того, что поворот головы
        # отношению безразличен, и заодно ЗАМЕР того, до какого угла метрика
        # ещё считает. Ожидается не порядок, а совпадение с оригиналом.
        held, drift = None, []
        if "оригинал" in vals:
            for c in SQUEEZE_LADDER:
                sq = squeeze_x(img, c)
                fs = detect(sq)
                rs = (lips(sq, face=fs, gates=g) if fs["state"] == PASS
                      else not_measured("lips", fs["note"]))
                _row(name, f"сжат по X {c:.2f}", rs, None)
                # Отказ на сжатой копии нарушением НЕ считается: сжатие уводит
                # IPD под пол и уносит лицо из распределения детектора, а
                # метрика на такое обязана отвечать незамером. Проверяется
                # другое — что ТАМ, ГДЕ ОНА СОГЛАСИЛАСЬ СЧИТАТЬ, ответ прежний.
                if rs["value"] is None:
                    continue
                d = abs(rs["value"] - vals["оригинал"]) / vals["оригинал"]
                drift.append((c, d))
                if d <= INV_TOL:
                    held = c
            if held is not None:
                print(f"{'':26} поворот: отношение держится до сжатия {held:.2f} "
                      f"(≈{math.degrees(math.acos(held)):.0f}° поворота головы)")
            limits.append(held)

        need = {t for t, _, _ in VARIANTS}
        if not need <= set(vals):
            print(f"{'':26} вне калибровки: посчитались не все варианты\n")
            continue

        checks = [
            ("тонкая верхняя губа даёт отношение больше оригинала",
             vals["верх 1/3 рта"] > vals["оригинал"]),
            ("равные губы дают меньше оригинала",
             vals["губы зеркально"] < vals["оригинал"]),
            ("толстая верхняя губа даёт меньше, чем равные",
             vals["верх 2/3 рта"] < vals["губы зеркально"]),
            # Ради этого метрика и написана: копия, на которой признака нет,
            # обязана валиться воротами, а не просто иметь число поменьше.
            ("копия с равными губами валится",
             _state(vals["губы зеркально"], g) == FAIL),
            ("копия с толстой верхней губой валится",
             _state(vals["верх 2/3 рта"], g) == FAIL),
        ]
        # Инвариантность к повороту: там, где метрика согласилась считать
        # сжатую копию, ответ обязан остаться прежним. Пустой список — это
        # тоже провал: утверждение о повороте осталось непроверенным.
        how = ("ни одна сжатая копия не замерена — проверять нечем" if not drift
               else f"худший уход {max(d for _, d in drift):.0%} "
                    f"при {min(c for c, _ in drift):.2f}")
        checks.append(("сжатие по X ответ не двигает (" + how + ")",
                       bool(drift) and all(d <= INV_TOL for _, d in drift)))
        for why, ok in checks:
            if not ok:
                bad += 1
                print(f"{'':26} НАРУШЕНО: {why}")

        # Та же мутация по точкам контура. Считается, а не пересказывается:
        # если контур вдруг начнёт следовать за порчей, пиксельный путь можно
        # будет пересмотреть — и узнать об этом надо отсюда.
        # Не «следует ли контур за порчей» (знак совпадает и у шума), а КАКУЮ
        # ДОЛЮ размаха он повторяет: пиксельный замер на этой лесенке меняется
        # в разы, и если контур отвечает единицами процентов — он меряет свою
        # заученную форму рта, а не кадр.
        cv_ = [cvals.get(t) for t, _, _ in VARIANTS]
        if all(v is not None for v in cv_):
            px = [vals[t] for t, _, _ in VARIANTS]
            span = max(px) - min(px)
            if span > 1e-6:
                contour_span.append((max(cv_) - min(cv_)) / span)
        print()

    if not yes or not no:
        raise SystemExit("до калибровки не дошёл ни один кадр: метрика "
                         "отказалась считать на всех (лица, размер, ракурс)")

    lo = float(g["lip_ratio_min"])
    no_hi, yes_lo = max(no), min(yes)
    print(f"«признака нет» (копии с равной и толстой верхней губой) до "
          f"{no_hi:.2f} · «признак есть» (кадр и копия с тонкой верхней) от "
          f"{yes_lo:.2f} · порог lip_ratio_min {lo}")
    if no_hi >= yes_lo:
        bad += 1
        print("  ЗАЗОРА НЕТ: копии с признаком и без перекрылись — одним\n"
              "  порогом их не разделить ни при каком значении")
    elif not (no_hi < lo < yes_lo):
        bad += 1
        print(f"  ПОРОГ ВНЕ ЗАЗОРА: lip_ratio_min надо перенести в "
              f"({no_hi:.2f}, {yes_lo:.2f}) — сейчас он либо пропускает кадр\n"
              f"  без признака, либо валит кадр с признаком.")

    # ПРЕДЕЛ ПО ПОВОРОТУ ГОЛОВЫ — ЗАМЕР, А НЕ ВКУС. Ни одного порога по углу в
    # метрике нет: она либо считает, либо отказывается по собственным причинам,
    # и вот на каком угле отказ наступает.
    ok_lim = [c for c in limits if c is not None]
    if ok_lim:
        print(f"поворот головы: отношение пережило сжатие по горизонтали до "
              f"{math.degrees(math.acos(max(ok_lim))):.0f}°"
              f"…{math.degrees(math.acos(min(ok_lim))):.0f}° на {len(ok_lim)} "
              f"кадрах; дальше метрика отказывается сама, порога по углу в ней "
              f"нет")
    if len(ok_lim) < len(limits):
        bad += 1
        print(f"  на {len(limits) - len(ok_lim)} кадрах отношение не пережило "
              f"даже самое слабое сжатие — поворот в него всё-таки входит")

    if contour_span:
        m = sorted(contour_span)[len(contour_span) // 2]
        print(f"колонка «по точкам»: контур 2d106det повторяет {m:.0%} размаха "
              f"пиксельного замера\nна той же порче ({len(contour_span)} кадров) "
              f"— ради этого толщина и меряется по пикселям,\nа точки задают "
              f"только, где смотреть")
    if bad:
        print(f"\nРАСХОЖДЕНИЙ: {bad}")
    raise SystemExit(1 if bad else 0)


def _state(value, g):
    return PASS if value >= float(g["lip_ratio_min"]) else FAIL


def _row(name, tag, r, contour):
    v = "—" if r["value"] is None else f"{r['value']:6.2f}"
    up = "—" if r.get("upper_ipd") is None else f"{r['upper_ipd']:6.3f}"
    lo_ = "—" if r.get("lower_ipd") is None else f"{r['lower_ipd']:6.3f}"
    ipd = "—" if r.get("ipd_px") is None else f"{r['ipd_px']:5.0f}"
    iqr = "—" if r.get("column_iqr") is None else f"{r['column_iqr']:5.2f}"
    con = "—" if contour is None else f"{contour:10.2f}"
    tail = f"  — {r['note']}" if r["note"] else ""
    print(f"{name:26} {tag:16} {ipd:>5} {up:>6} {lo_:>6} {v:>6} {iqr:>5} "
          f"{con:>10}  {r['state']}{tail}")


if __name__ == "__main__":
    main()
