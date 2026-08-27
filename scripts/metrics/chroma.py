#!/usr/bin/env python3
"""Цветность кадра: разброс тона + колорфулность. Ловит ч/б, сепию и дуотон.

  py -3 scripts/metrics/chroma.py [<папка с кадрами>]

Самотест прогоняет каждый реальный кадр и его ч/б, сепийную и дуотонную копии
и печатает разделение. Без аргумента берётся `<work_root>/bridget/frames`.

ЧТО НЕ РАБОТАЛО. Первая версия ворот мерила среднюю и 90-й перцентиль хромы
C* в LAB (пороги 12 / 22). Это метрика НАСЫЩЕННОСТИ, а не монохромности:
сепия — это яркость, умноженная на один фиксированный цвет, и хрома у неё
ровно такая же, как у цветного оригинала, а местами выше. Замер: сепийные
копии 45 реальных кадров дали C* mean 11.6-17.7 и p90 20.7-27.5, и 37 из 45
прошли порог 12/22 насквозь. Прямо запрещённая в ТЗ сепия проходила ворота
в 82 % случаев, а восемь оставшихся отсеялись не как сепия, а как случайно
малонасыщенные кадры.

ЧТО МЕРИМ ТЕПЕРЬ. Две величины по одному и тому же кадру:

  hue_entropy — нормированная круговая энтропия тона h = atan2(b*, a*),
    гистограмма 36 корзин, вес пикселя = его хрома, маска L* ∈ [15, 90] и
    C* > 5. Монотон любой насыщенности даёт один пик и энтропию около нуля;
    настоящий кадр всегда несёт несколько тонов. Именно это, а не
    насыщенность, отличает сепию от цветного снимка.
  colourfulness — колорфулность Хаслера-Зюстранка по (R−G) и (R+G)/2−B.
    Работает не как второй порог, а как УСЛОВИЕ ОСМЫСЛЕННОСТИ первого: у ч/б и
    вылинявшего кадра тон формально «разбросан» (0.39-0.51 у обесцвеченного на
    75 %), но разбрасывать там нечего — это разброс шума. Если колорфулность
    ниже порога, энтропия тона не определена и отдаётся нулём, ровно как для
    кадра, где цветных пикселей не нашлось совсем.

Наружу поэтому выходит ОДНО судимое число `hue_entropy` с одним порогом, а
сырое значение остаётся рядом под именем `hue_entropy_raw` — иначе потребитель
с единственным порогом (`gates.py` берёт из метрики ровно одно число) судил бы
по половине метрики и пропускал бы обесцвеченный кадр.

ПОДГОТОВКА КАДРА обязательна и не косметическая: кадр ужимается по длинной
стороне до 256 px и проходит медиану 5×5. Зерно — попиксельно независимый
шум, он размазывает тон по всем корзинам и надувает энтропию монотона. Без
подготовки сепия с зерном σ=8 (а последняя миля добавляет зерно сама, см.
`lastmile.grain_iso_map`) давала энтропию 0.40 и проходила ворота. После
подготовки та же сепия даёт 0.06-0.14, а реальный кадр с тем же зерном —
0.42-0.73, то есть зерно перестало быть лазейкой.

ЗАМЕРЫ (45 реальных кадров `<work_root>/bridget/frames`, hue_entropy / colourfulness):

  оригиналы           0.407-0.721 / 23.9-42.5   ← проходят все 45
  оригинал + зерно σ8 0.420-0.725 / 24.0-42.4   ← проходят все 45
  сепия               0.000-0.015 / 23.1-31.9   ← падает по энтропии
  сепия + зерно σ=8   0.061-0.136 / 23.1-31.7   ← падает по энтропии
  сепия + зерно σ=24  0.209-0.303 / 23.3-30.8   ← падает по энтропии
  ч/б                 0.000       /  0.0        ← падает по колорфулности
  дуотон (синь→охра)  0.263-0.379 / 10.8-16.9   ← падает по колорфулности
  обесцвечен на 75%   0.394-0.511 /  7.0-9.4    ← падает по колорфулности

Пороги стоят посередине разрывов: 0.303 → 0.407 по энтропии (порог 0.34) и
16.9 → 23.9 по колорфулности (порог 18.0). На следующем поколении тех же ячеек
(перегенерация с другой моделью и стеком лор) разделение устояло без правки
порогов: оригиналы 0.474-0.767 / 22.7-36.8, сепия с зерном σ=24 до 0.316,
дуотон до 13.5. В отличие от резкости и микрорельефа, обе величины здесь
ограничены сверху по построению (энтропия — долей от log 36, колорфулность —
уровнями 0-255), и шкала с рендером не едет.

Дуотон — единственный случай, где
энтропия одна не справляется: два далёких тона дают ей 0.26-0.38, то есть
местами выше порога, и валит его именно колорфулность. Отсюда «И», а не «ИЛИ».

Тёмный кадр метрике не мешает: P5 — ресторан при свечах, самый «атмосферный»
кадр набора — даёт 0.468 / 37.1, одну из лучших колорфулностей набора.
"""
import sys, os, math, glob

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _util import setup_console, manifest
from metrics import load_bgr
from metrics.verdict import gate

ANALYSIS_SIDE = 256      # длинная сторона кадра для анализа, px
CHROMA_DENOISE = 5       # медиана: гасит попиксельное зерно, не трогая цветовые пятна
HUE_BINS = 36            # корзины по 10°
L_RANGE = (15.0, 90.0)   # ниже — шум теней, выше — выбитые света, тон там случаен
C_FLOOR = 5.0            # ниже этой хромы тон не определён


def _prepared(bgr):
    """Кадр, приведённый к масштабу анализа и очищенный от зерна."""
    h, w = bgr.shape[:2]
    s = ANALYSIS_SIDE / max(h, w)
    if s < 1:
        bgr = cv2.resize(bgr, (max(1, int(w * s)), max(1, int(h * s))),
                         interpolation=cv2.INTER_AREA)
    return cv2.medianBlur(bgr, CHROMA_DENOISE)


def hue_entropy(bgr):
    """Разброс тона: нормированная круговая энтропия + доля цветных пикселей.

    Вес корзины — сумма хромы, а не число пикселей: почти серый пиксель имеет
    случайный тон, и по счётчику он весит столько же, сколько красное вино в
    бокале. По хроме — в двадцать раз меньше.
    """
    lab = cv2.cvtColor(bgr.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    C = np.hypot(a, b)
    m = (L >= L_RANGE[0]) & (L <= L_RANGE[1]) & (C > C_FLOOR)
    cov = float(m.mean())
    if int(m.sum()) < 100:
        # Цветных пикселей нет вовсе — это чистое ч/б. Энтропия здесь не
        # «маленькая», а неопределённая; возвращаем 0, чтобы ворота падали
        # на определённом числе, а не на NaN.
        return 0.0, cov, float(C.mean()), float(np.percentile(C, 90))
    h = np.arctan2(b[m], a[m])
    w = C[m]
    idx = ((h + math.pi) / (2 * math.pi) * HUE_BINS).astype(np.int32) % HUE_BINS
    p = np.bincount(idx, weights=w, minlength=HUE_BINS)
    p = p / p.sum()
    nz = p[p > 0]
    ent = float(-(nz * np.log(nz)).sum() / math.log(HUE_BINS))
    return ent, cov, float(C.mean()), float(np.percentile(C, 90))


def colourfulness(bgr):
    """Колорфулность Хаслера-Зюстранка (2003), в единицах уровней 0-255."""
    B, G, R = (bgr[..., i].astype(np.float32) for i in range(3))
    rg = R - G
    yb = 0.5 * (R + G) - B
    return float(math.hypot(rg.std(), yb.std())
                 + 0.3 * math.hypot(rg.mean(), yb.mean()))


def chroma(src, gates=None):
    """Метрика цветности кадра: одно судимое число и сырьё к нему."""
    g = gates or manifest()["gates"]
    ent_min = float(g["hue_entropy_min"])
    col_min = float(g["colourfulness_min"])

    prep = _prepared(load_bgr(src))
    ent_raw, cov, c_mean, c_p90 = hue_entropy(prep)
    col = colourfulness(prep)

    # Разброс тона у кадра, в котором цвета нет, — это разброс шума. Нулём
    # он и объявляется: обесцвеченная копия честно набирает энтропию 0.39-0.51,
    # и без этой отсечки прошла бы ворота как полноцветная.
    no_colour = col < col_min
    ent = 0.0 if no_colour else ent_raw
    why = (f"цвета нет: колорфулность {col:.1f} < {col_min}" if no_colour else
           f"тон однороден: энтропия {ent:.3f} < {ent_min}" if ent < ent_min else "")

    return gate("chroma", ent, lo=ent_min, note=why,
                hue_entropy=ent, hue_entropy_raw=ent_raw, colourfulness=col,
                chromatic_coverage=cov, chroma_mean=c_mean, chroma_p90=c_p90,
                colourfulness_min=col_min)


def measure(src, gates=None):
    """Второе имя тех же ворот — `gates.py` ищет метрику по списку кандидатов.

    Синоним, а не отдельный расчёт: раннер берёт ПЕРВОЕ подходящее имя из
    своего списка, и порядок этого списка живёт в чужом файле. Обёртка,
    возвращающая голые числа, отдала бы `_metric_gate` словарь без поля
    `state` — тот по правилу «число без порога — ещё не ворота» объявил бы
    живую метрику незамером, и весь набор перестал бы отгружаться из-за
    перестановки строк в списке имён.
    """
    return chroma(src, gates)


def _sepia(bgr):
    """Классическая сепия (матрица Microsoft/ImageMagick) — эталонный враг."""
    m = np.array([[0.131, 0.534, 0.272],
                  [0.168, 0.686, 0.349],
                  [0.189, 0.769, 0.393]], np.float32)
    return np.clip(bgr.astype(np.float32) @ m.T, 0, 255).astype(np.uint8)


def _gray(bgr):
    return cv2.cvtColor(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)


def _duotone(bgr):
    """Яркость, натянутая на градиент «холодная тень → тёплый свет»."""
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    lo = np.array([40, 25, 15], np.float32)
    hi = np.array([215, 235, 250], np.float32)
    return np.clip(lo + (hi - lo) * g[..., None], 0, 255).astype(np.uint8)


def _grain(bgr, sd, rng):
    return np.clip(bgr.astype(np.float32) + rng.normal(0, sd, bgr.shape),
                   0, 255).astype(np.uint8)


def main():
    setup_console()
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        manifest()["paths"]["work_root"], "bridget", "frames")
    files = sorted(glob.glob(os.path.join(root, "*", "*.png"))
                   + glob.glob(os.path.join(root, "*.png")))
    if not files:
        raise SystemExit(f"кадров не найдено: {root}")

    rng = np.random.default_rng(0)
    g = manifest()["gates"]
    print(f"пороги: энтропия тона ≥ {g['hue_entropy_min']}, "
          f"колорфулность ≥ {g['colourfulness_min']}\n")
    print(f"{'кадр':22} {'вариант':18} {'энтр.':>7} {'сырая':>7} {'колорф.':>8} "
          f"{'C*mean':>7} {'C*p90':>7}  вердикт")

    bad = 0
    for path in files:
        img = load_bgr(path)
        name = os.path.basename(path)
        variants = [
            ("оригинал", img, True),
            ("+зерно σ8", _grain(img, 8, rng), True),
            ("сепия", _sepia(img), False),
            ("сепия+зерно σ8", _grain(_sepia(img), 8, rng), False),
            ("сепия+зерно σ24", _grain(_sepia(img), 24, rng), False),
            ("ч/б", _gray(img), False),
            ("дуотон", _duotone(img), False),
        ]
        for tag, v, want_pass in variants:
            r = chroma(v, g)
            ok = (r["state"] == "PASS") == want_pass
            bad += not ok
            print(f"{name:22} {tag:18} {r['hue_entropy']:7.3f} "
                  f"{r['hue_entropy_raw']:7.3f} {r['colourfulness']:8.2f} "
                  f"{r['chroma_mean']:7.1f} {r['chroma_p90']:7.1f}  {r['state']:4}"
                  f"{'' if ok else '  ← ОЖИДАЛОСЬ ДРУГОЕ'}")
        print()

    print("разделение подтверждено: цветное проходит, сепия и ч/б — нет"
          if not bad else f"РАСХОЖДЕНИЙ: {bad}")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
