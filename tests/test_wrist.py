#!/usr/bin/env python3
"""Тату вклеивается только туда, где видна ТЫЛЬНАЯ сторона запястья.

Правило поставлено заказчиком и заменяет собой всю прежнюю ручную разметку:
надпись набита на одной конкретной поверхности руки, и на кадре, где рука
повёрнута ладонью или запястья не видно вовсе, её не может быть видно. Кадр
без тату — нормальный кадр; тату не на своём месте — брак.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ И ЧТО НЕТ. Разметку поверхностей считает воркер, и
дёргать его из тестов нельзя. Но разбор карты кусков — своя, целиком локальная
работа: geometry() получает готовую карту индексов и отвечает, где запястье,
куда и под каким углом ложится строка. Карта здесь рисуется руками, зато
рисуется ТАК, чтобы отличать верное поведение от правдоподобного: рука лежит
под углом, кисть с одной стороны, а половины предплечья разложены вдоль неё
по-разному в разных случаях.

Замер на живых кадрах — в шапке scripts/metrics/wrist.py; сюда он не
переносится, потому что число, которое нельзя пересчитать командой, в тестах
живёт ещё хуже, чем в манифесте.
"""
import os
import sys

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from metrics import wrist  # noqa: E402

L = wrist.SIDE_PARTS["left"]
# Запас над порогом ворот: подмена «полосы у запястья» на «всю руку» обязана
# не просто изменить число, а перевести его через порог — иначе мутант живёт.
BACK_MIN_MARGIN = wrist.BACK_MIN
ARM_W = 150       # ширина предплечья в фикстуре, px
CANVAS = 768      # сторона синтетического кадра, px
# РУКА В ФИКСТУРЕ ДЛИННАЯ НАРОЧНО: 480 на 150 даёт вытянутость 3.2 — как у
# годных кадров живого прогона (3.17-3.45). Первая редакция была 300 на 150,
# то есть ровно на пороге 2.0, и поворот фикстуры на 25° уводил её под порог:
# тест падал не на дефекте, а на собственной геометрии.

# Межзрачковое расстояние для синтетики. Кадр здесь — ровная заливка без лица,
# а масштаб надписи считается ОТ ЛИЦА: ширина руки с разметки оказалась
# невоспроизводимой (144 и 88 px на двух версиях одного кадра). Подставляется
# то значение, при котором надпись выходит примерно в ширину руки фикстуры —
# как на референсе, где 1.19 IPD и 1.20 ширины предплечья почти совпадают.
TEST_IPD = ARM_W * wrist.LEN_OVER_W / wrist.LEN_OVER_IPD


def _arm(angle=0.0, surface="back", size=CANVAS, wrist_at_start=True,
         far_surface=None, length=480, far_at=140, w=ARM_W):
    """Карта кусков: кисть, за ней предплечье, всё под углом `angle`.

    Рука строится в своих осях и поворачивается целиком, поэтому ни ось, ни
    сторона не могут «сойтись» из-за того, что всё лежит по строкам матрицы.
    `far_surface` задаёт другую поверхность ДАЛЬШЕ `far_at` пикселей от
    запястья — так выглядит скрученная рука, у которой у локтя видно одно, а у
    запястья другое.
    """
    m = np.zeros((size, size), np.uint8)
    cy = size // 2
    hand = int(w * 1.4)
    x0 = (size - length) // 2 + hand // 2        # оставить место кисти слева
    near = wrist.SIDE_PARTS["left"][surface]
    m[cy - w // 2:cy + w // 2, x0:x0 + length] = near
    if far_surface:
        m[cy - w // 2:cy + w // 2, x0 + far_at:x0 + length] = \
            wrist.SIDE_PARTS["left"][far_surface]
    m[cy - hand // 2:cy + hand // 2, max(0, x0 - hand):x0] = L["hand"]
    if not wrist_at_start:                      # кисть с другого конца
        m = m[:, ::-1].copy()
    if angle:
        M = cv2.getRotationMatrix2D((size // 2, cy), angle, 1.0)
        m = cv2.warpAffine(m, M, (size, size), flags=cv2.INTER_NEAREST)
    return m


def test_the_palm_side_never_gets_the_tattoo():
    """Ладонная сторона к камере — вклейки нет, и причина названа.

    Это главное правило целиком: надписи на ладонной стороне не существует, и
    нарисовать её там значит выдать брак, который потом никто не отличит от
    настоящей тату не на том месте.
    """
    back = wrist.geometry(_arm(surface="back"))
    palm = wrist.geometry(_arm(surface="inner"))
    assert back["back_frac"] > 0.99, back
    assert palm["back_frac"] < 0.01, palm


def test_side_is_decided_in_the_band_next_to_the_hand():
    """Сторону решает запястье, а не вся рука.

    Рука крутится: у локтя может быть видна одна поверхность, у кисти другая.
    Считать долю по ВСЕМУ предплечью значит позволить дальнему концу решать за
    ближний — и на скрученной руке вклейка сядет на ладонную сторону, имея при
    этом бодрое большинство «тыльных» пикселей у локтя.
    """
    # Рука длинная, скрутка близко к запястью: у локтя тыльной поверхности
    # БОЛЬШИНСТВО, а в полосе у кисти её нет вовсе. Первая редакция фикстуры
    # была мягче — 0.40 при пороге 0.40, — и мутационный прогон показал на ней
    # СЛЕПОТУ: дефект вносился, тест оставался зелёным.
    m = _arm(surface="inner", far_surface="back", size=2000, length=1600,
             far_at=int(wrist.NEAR_W * ARM_W) + 20)
    g = wrist.geometry(m)
    whole = g["back_px"] / float(g["back_px"] + g["inner_px"])
    # Сначала — что фактура вообще ловит подмену: по всей руке тыльной
    # поверхности БОЛЬШИНСТВО, а у запястья её нет. Без этой проверки тест
    # зелен потому, что различать нечего.
    assert whole > BACK_MIN_MARGIN, (
        f"по всей руке доля тыльной {whole:.2f} — фактура перестала быть "
        f"контрпримером, и тест больше не проверяет то, ради чего написан")
    assert g["back_frac"] < 0.05, (
        f"сторону решил дальний конец руки: у запястья ладонная поверхность, "
        f"а доля тыльной вышла {g['back_frac']:.2f}")


@pytest.mark.parametrize("angle", [0, 25, -25, 90, 140, -140])
def test_lettering_runs_from_the_wrist_towards_the_elbow(angle, tmp_path):
    """Строка идёт ОТ ЗАПЯСТЬЯ К ЛОКТЮ под любым наклоном руки.

    Направление здесь не выбирается, а следует из анатомии: надпись набита по
    коже в эту сторону. Первая версия брала угол от оси, направленной к КИСТИ,
    и на кадре с собакой выдала +174.7° — место верное, строка задом наперёд.
    По рамке такую ошибку не видно вовсе, поэтому проверяется вектор.
    """
    f = _frame(tmp_path)
    for flip in (True, False):
        m = wrist.measure(f, ipd=TEST_IPD,
                          idx=_arm(angle=angle, wrist_at_start=flip),
                          check_occluders=False)
        assert m.get("at") and m.get("wrist"), m
        at = np.array(m["at"]) * CANVAS
        wr = np.array(m["wrist"]) * CANVAS
        # Куда, по мнению разбора, смотрит строка.
        a = np.radians(m["rot"])
        e = np.array([np.cos(a), -np.sin(a)])
        step = at - wr                       # от запястья к месту надписи
        assert np.linalg.norm(step) > 1e-6
        cos = float(e @ step / np.linalg.norm(step))
        assert cos > 0.98, (
            f"наклон {angle}°, кисть {'слева' if flip else 'справа'}: строка "
            f"развёрнута не к локтю (косинус {cos:+.2f})")


@pytest.mark.parametrize("angle", [0, 25, -25, 90, 140, -140])
def test_the_wrist_is_the_end_next_to_the_hand(angle):
    """Запястье — тот конец предплечья, что примыкает к кисти.

    Без кисти ось из PCA — просто прямая, и оба её конца равноправны. Кисть и
    делает из прямой направление; если конец выберется не тот, надпись уедет к
    локтю и развернётся.
    """
    for flip in (True, False):
        m = _arm(angle=angle, wrist_at_start=flip)
        g = wrist.geometry(m)
        hand = np.stack(np.nonzero(m == L["hand"])[::-1], 1).mean(0)
        arm = np.stack(np.nonzero((m == L["back"]) | (m == L["inner"]))[::-1],
                       1).mean(0)
        wr = np.array(g["wrist_px"])
        assert np.linalg.norm(wr - hand) < np.linalg.norm(arm - hand), (
            f"наклон {angle}°: «запястье» дальше от кисти, чем центр "
            f"предплечья — выбран не тот конец")


def test_a_blob_with_no_axis_is_refused():
    """Почти квадратный кусок отвергается: у него нет главной оси.

    ЖИВОЙ ДЕФЕКТ, И ОН СТОИЛ ВИДИМОГО БРАКА. На кадре, где рука поднята к
    волосам, кусок предплечья вышел 247 на 160 px. Главная ось такого облака —
    шум: она легла вверх-влево, тогда как рука шла вверх-вправо; запястье село
    у ЛОКТЕВОГО конца, и надпись встала вверх ногами. По рамке всё выглядело
    правдоподобно. Проверка была в прежней метрике предплечья и потерялась при
    переписывании.

    Порог 2.0 стоит в пустом промежутке замера: у годных кадров прогона
    вытянутость 3.17-3.45, у бракованных 1.16-1.54.
    """
    ok = wrist.geometry(_arm(length=300))
    assert ok["elongation"] > 2.0, ok
    assert "back_frac" in ok

    # Квадратный кусок: длина сравнима с шириной.
    square = wrist.geometry(_arm(length=int(ARM_W * 1.2)))
    assert square["elongation"] < 2.0, square
    assert "back_frac" not in square, square
    assert "не вытянут" in square.get("why", ""), square


def test_no_hand_means_no_answer_rather_than_a_guess():
    """Без кисти метрика молчит, а не угадывает конец предплечья.

    Угадать тут нечего: у прямой два конца, и ошибка стоит перевёрнутой
    надписи у локтя. Молчание — правильный ответ, потому что кадр без тату
    нормален, а кадр с тату не на месте — нет.
    """
    m = _arm()
    m[m == L["hand"]] = 0
    g = wrist.geometry(m)
    assert "back_frac" not in g and "кисти" in g.get("why", ""), g


def test_the_wrong_arm_in_frame_is_named_as_such():
    """«Модель взяла не ту руку» — это диагноз, и он обязан быть в отказе.

    Живой прогон: клетка просит показать ЛЕВОЕ запястье, модель поднимает к
    волосам ПРАВУЮ руку. Отказ читался как «кисти в кадре нет» — при кисти на
    самом виду, — и выглядел поломкой детектора. Разница между «сцена не та» и
    «детектор не нашёл» это разница между «перепиши промпт» и «чини код».
    """
    R = wrist.SIDE_PARTS["right"]
    only_right = _arm()
    only_right[only_right == L["back"]] = R["back"]
    only_right[only_right == L["hand"]] = R["hand"]
    why = wrist.geometry(only_right, "left").get("why", "")
    assert "левой" in why and "не ту руку" in why, why

    # А когда чужой руки в кадре тоже нет — про неё и не говорим.
    empty = np.zeros_like(only_right)
    why2 = wrist.geometry(empty, "left").get("why", "")
    assert "левой" in why2 and "не ту руку" not in why2, why2


def test_geometry_follows_the_measured_reference_proportions():
    """Длина и место строки взяты из обмера фотографии, а не назначены.

    1.20 ширины предплечья в длину и 0.88 ширины от запястья — это то, что
    видно на референсе. Проверяется, что разбор действительно ими пользуется,
    а не приблизительно похожими числами: подмена пропорции не ломает ничего
    заметного, надпись просто становится чужого размера.
    """
    m = _arm()
    g = wrist.geometry(m)
    w = g["arm_width_px"]
    # Ожидается НЕ ровно ARM_W: длина и ширина берутся по квантилям 2%..98%,
    # чтобы одна крайняя точка облака не задавала размер. На ровном
    # прямоугольнике это срезает ровно 4% ширины, и такая недостача — свойство
    # правила, а не погрешность.
    want = ARM_W * 0.96
    assert abs(w - want) <= 3, (
        f"ширина предплечья измерена как {w:.1f} вместо {want:.1f}")
    # МЕСТА НАДПИСИ В geometry() БЫТЬ НЕ ДОЛЖНО. Оно считается от лица, а не от
    # руки; второй, «почти такой же» ответ здесь означал бы два источника
    # правды, из которых один тихо неверен.
    assert "at_px" not in g and "len_px" not in g, (
        "геометрия снова считает место надписи по ширине руки — а она "
        "невоспроизводима (144 и 88 px на двух версиях одного кадра)")


def _frame(tmp_path, size=CANVAS):
    """Кадр под карту: ровная кожа, размер тот же, что у карты кусков."""
    from _util import imwrite
    p = str(tmp_path / "f.png")
    imwrite(p, np.full((size, size, 3), (150, 168, 196), np.uint8))
    return p


def test_the_palm_side_never_gets_the_tattoo_end_to_end(tmp_path):
    """Тот же запрет, но на ВЕРДИКТЕ, а не на разборе геометрии.

    Разбор может считать долю правильно, а вердикт её не спрашивать — ровно
    так выглядит выключенная проверка. Поэтому проверяется поле, по которому
    конвейер и решает вклеивать: back_visible.
    """
    f = _frame(tmp_path)
    back = wrist.measure(f, ipd=TEST_IPD, idx=_arm(surface="back"), occ=None,
                         check_occluders=False)
    palm = wrist.measure(f, ipd=TEST_IPD, idx=_arm(surface="inner"), occ=None,
                         check_occluders=False)
    assert back["back_visible"] is True, back
    assert palm["back_visible"] is False, palm
    assert "ладонная" in palm.get("why", ""), palm


def test_an_object_on_the_wrist_cancels_the_composite(tmp_path):
    """Часы на запястье отменяют вклейку, даже когда сторона верная.

    Карточка разводит металл и тату по разным рукам, но кадр рисует модель, и
    на обоих сданных кадрах с открытым тыльным запястьем часы оказались на
    левой руке. Надпись поверх ремешка — видимый брак; проверка стоит между
    «сторона верная» и «вклеиваем».
    """
    f = _frame(tmp_path)
    idx = _arm(surface="back")
    clean = wrist.measure(f, ipd=TEST_IPD, idx=idx, occ=np.zeros((CANVAS, CANVAS), np.uint8))
    assert clean["back_visible"] is True and clean["occluded"] == 0.0, clean

    # Предмет ставится ровно на площадку под надписью, найденную же замером.
    occ = np.zeros((CANVAS, CANVAS), np.uint8)
    cx, cy = int(clean["at"][0] * CANVAS), int(clean["at"][1] * CANVAS)
    r = max(6, int(0.06 * clean["size"] * CANVAS))
    cv2.circle(occ, (cx, cy), r, 1, -1)
    busy = wrist.measure(f, ipd=TEST_IPD, idx=idx, occ=occ)
    assert busy["occluded"] > wrist.OCCLUDE_MAX, busy
    assert busy["back_visible"] is False, busy
    assert "часы" in busy.get("why", ""), busy


def test_the_place_comes_from_the_card_and_never_from_a_default():
    """Рука и сторона читаются из карточки, а молчание карточки — отказ.

    Умолчание здесь дороже отказа: тату не на той руке выглядит настоящей и
    проходит все прочие ворота. У трёх карточек проекта три разных места, и
    молчаливое «слева сзади» подставило бы двух персонажей из трёх.
    """
    assert wrist.from_card({"tattoo": {"placement": "back of the left wrist"}}) \
        == ("left", "back")
    assert wrist.from_card({"tattoo": {"placement": "inner right forearm"}}) \
        == ("right", "inner")
    assert wrist.from_card({"tattoo": {"placement":
                                       "outer left forearm, midway"}}) \
        == ("left", "back")
    for bad in ({}, {"tattoo": {}}, {"tattoo": {"placement": "the wrist"}},
                {"tattoo": {"placement": "left forearm"}},
                {"tattoo": {"placement": "inner forearm"}}):
        with pytest.raises(SystemExit) as e:
            wrist.from_card(bad)
        assert "placement" in str(e.value), str(e.value)


def test_every_project_card_says_where_its_tattoo_is():
    """Карточки проекта проходят это чтение. Иначе доводка встанет на первом
    же кадре — и правильно встанет, но узнать об этом лучше здесь."""
    import glob as _g
    from _util import read_json
    cards = _g.glob(os.path.join(ROOT, "projects", "*", "character.json"))
    assert cards, "карточек не нашлось — тест смотрит не туда"
    for c in cards:
        side, surface = wrist.from_card(read_json(c))
        assert side in ("left", "right") and surface in ("back", "inner")


def test_the_wanted_surface_is_the_one_the_card_asks_for(tmp_path):
    """Ворота считают долю НУЖНОЙ поверхности, а не всегда тыльной.

    Число считается одно, читается с двух сторон; подмена «нужной» на
    «тыльную» не ломает Бриджит и ломает обоих остальных персонажей — то есть
    ровно тот дефект, который на своём проекте не виден.
    """
    f = _frame(tmp_path)
    idx = _arm(surface="inner")
    as_back = wrist.measure(f, ipd=TEST_IPD, idx=idx, surface="back", check_occluders=False)
    as_inner = wrist.measure(f, ipd=TEST_IPD, idx=idx, surface="inner", check_occluders=False)
    assert as_back["back_visible"] is False, as_back
    assert as_inner["back_visible"] is True, as_inner
    assert as_inner["surface_frac"] > 0.99


def test_lettering_too_small_to_read_is_not_pasted(tmp_path):
    """Мелкая надпись не вклеивается вовсе.

    Живой прогон девяти кадров дал один с вклейкой шириной 49 px: «Manolo
    Blahnik» в 49 пикселей — это серое пятно на запястье, читается грязью.
    Порог на размер стоял на глаз (0.035 ширины кадра) и такое пропускал;
    теперь он считается по самому ассету — наименьшая ширина, при которой пик
    альфы ещё держится (замер: 0.99 в натуральную величину, 0.89 при 209 px,
    0.43 при 49).
    """
    need = wrist.min_paste_px()
    assert 60 < need < 500, f"порог {need} px выглядит выдуманным"

    f = _frame(tmp_path)
    zero = np.zeros((CANVAS, CANVAS), np.uint8)
    idx = _arm(surface="back")
    near = wrist.measure(f, ipd=TEST_IPD, idx=idx, occ=zero)
    assert near["back_visible"] is True, near
    assert near["size"] * CANVAS >= need

    # ЧЕЛОВЕК ДАЛЬШЕ ОТ ОБЪЕКТИВА — МЕЛЬЧЕ ЛИЦО, МЕЛЬЧЕ И ТАТУ. Масштаб идёт от
    # межзрачкового расстояния, поэтому «слишком мелко» задаётся именно им, а
    # не толщиной руки: рука с разметки для этого недостаточно устойчива.
    far = wrist.measure(f, ipd=TEST_IPD * 0.5, idx=idx, occ=zero)
    assert far["back_frac"] > 0.99, far
    assert far["back_visible"] is False, far
    assert "грязью" in far.get("why", ""), far


def test_the_hand_must_belong_to_this_forearm(tmp_path):
    """Кисть одной руки не сшивается с предплечьем другой.

    ЖИВОЙ ДЕФЕКТ. На кадре в кафе одна рука поднята к лицу, вторая лежит на
    столе; разметка назвала кисть поднятой руки левой, предплечье той же руки
    — правым, а левым предплечьем — руку на столе. Код брал самый крупный
    кусок каждого рода и молча их соединял. Место вклейки выходило
    правдоподобным — ошибку выдали только числа, прыгавшие на 39% между двумя
    версиями одного кадра. Здесь проверяется, что далёкая кисть отвергается, а
    ближняя — берётся, даже если она мельче далёкой.
    """
    far = _arm()
    far[far == L["hand"]] = 0                 # своей кисти нет
    far[10:110, 10:110] = L["hand"]           # чужая, в дальнем углу кадра
    g = wrist.geometry(far)
    assert "back_frac" not in g, g
    assert "не сходятся" in g.get("why", ""), g

    # Ближняя кисть мельче далёкой — и всё равно должна победить.
    both = _arm()
    both[10:160, 10:160] = L["hand"]          # чужая, крупнее своей
    g2 = wrist.geometry(both)
    assert "back_frac" in g2, g2
    assert g2["hand_gap_px"] < wrist.HAND_GAP_W * g2["arm_width_px"], g2


def test_the_scale_comes_from_the_face_not_from_the_arm(tmp_path):
    """Размер надписи задаёт межзрачковое расстояние, а не ширина руки.

    Ширина руки с разметки невоспроизводима: на двух версиях ОДНОГО кадра
    (эдит руки не касался, размер тот же) вышло 144 и 88 px, то есть разброс
    39%. Через ворота читаемости это проходило как «надпись 207 px» против
    «126 px» — один кадр получал тату, другой нет. IPD такой болезнью не
    страдает: он и есть единица масштаба всего проекта.
    """
    f = _frame(tmp_path)
    thick = wrist.measure(f, ipd=TEST_IPD, idx=_arm(surface="back"),
                          check_occluders=False)
    thin = wrist.measure(f, ipd=TEST_IPD, idx=_arm(surface="back", w=90),
                         check_occluders=False)
    assert abs(thick["size"] - thin["size"]) < 1e-9, (
        f"размер поехал вслед за рукой: {thick['size']:.4f} против "
        f"{thin['size']:.4f} при одном и том же лице")
    # А вслед за лицом — обязан.
    small = wrist.measure(f, ipd=TEST_IPD * 0.8, idx=_arm(surface="back"),
                          check_occluders=False)
    assert abs(small["size"] / thick["size"] - 0.8) < 1e-6, small


def test_a_face_and_an_arm_at_odds_cancel_the_composite(tmp_path):
    """Расхождение двух масштабов отменяет вклейку.

    Лицо и рука бывают на разном расстоянии от объектива, и небольшое
    расхождение законно. Сильное значит либо вытянутую к объективу руку, либо
    провал сегментации — и в обоих случаях размер надписи будет неверным, а
    неверно крупная тату на запястье выглядит наклейкой.
    """
    f = _frame(tmp_path)
    zero = np.zeros((CANVAS, CANVAS), np.uint8)
    ok = wrist.measure(f, ipd=TEST_IPD, idx=_arm(surface="back"), occ=zero)
    assert ok["back_visible"] is True, ok
    # Лицо втрое крупнее, чем позволяет рука в кадре.
    bad = wrist.measure(f, ipd=TEST_IPD * 3, idx=_arm(surface="back"), occ=zero)
    assert bad["back_visible"] is False, bad
    assert "разошлись" in bad.get("why", ""), bad


def test_a_sleeve_is_not_a_wrist(tmp_path):
    """Надпись не ложится на рукав, хотя разметка зовёт его предплечьем.

    ЖИВОЙ БРАК, ПОПАВШИЙ В КАДР. На кадре, где она лежит с книгой в кашемировом
    свитере, «Manolo Blahnik» легла прямо на рукав. Все прочие ворота его
    пропустили и были правы по-своему: сторона тыльная 1.00, вытянутость 2.82,
    ширина 170 px. Разметка поверхностей размечает ТЕЛО, в том числе под
    одеждой, и рукав она честно называет предплечьем.

    Эта проверка в метрике БЫЛА, и я её сняла — за то, что она не различает
    часы (2.5 раза). Вывод «правило не работает» был неверен: металл она ловит
    плохо, ТКАНЬ отлично. Замер: рукав 1.000, чистая кожа 0.000.
    """
    from _util import imwrite
    W = H = CANVAS
    idx = _arm(surface="back")
    # Кадр: кисть телесная, предплечье — серая шерсть.
    img = np.full((H, W, 3), (150, 168, 196), np.uint8)
    L_ = wrist.SIDE_PARTS["left"]
    img[cv2.resize((idx == L_["back"]).astype(np.uint8), (W, H),
                   interpolation=cv2.INTER_NEAREST) > 0] = (150, 150, 150)
    p = str(tmp_path / "sleeve.png")
    imwrite(p, img)
    m = wrist.measure(p, ipd=TEST_IPD, idx=idx, check_occluders=False)
    assert m["cloth"] > wrist.CLOTH_MAX, m
    assert m["back_visible"] is False, m
    assert "рукав" in m.get("why", ""), m

    # Та же геометрия, но рука телесная — вклейка проходит.
    skin = str(tmp_path / "skin.png")
    imwrite(skin, np.full((H, W, 3), (150, 168, 196), np.uint8))
    ok = wrist.measure(skin, ipd=TEST_IPD, idx=idx, check_occluders=False)
    assert ok["cloth"] < wrist.CLOTH_MAX, ok
    assert ok["back_visible"] is True, ok


def test_the_colour_table_decodes_every_part_exactly():
    """Разбор карты кусков точный, а не приблизительный.

    Нода красит индекс i как i*255/24 палитрой cv2; таблица строится тем же
    cv2, поэтому совпадение обязано быть побайтным. Если оно разъедется —
    например, от смены палитры в шаблоне, — половины предплечья начнут
    путаться между собой, и метрика будет уверенно давать неверный ответ
    вместо отказа.
    """
    lut = wrist._lut()
    img = np.zeros((1, 25, 3), np.uint8)
    for i in range(25):
        img[0, i] = lut[i][::-1]              # BGR, как читает imread
    got = wrist.decode(img)[0]
    assert list(got) == list(range(25)), list(got)
    # Чужой цвет не притягивается к ближайшему куску молча.
    assert wrist.decode(np.full((1, 1, 3), 128, np.uint8))[0, 0] == 0
