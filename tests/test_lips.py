"""Ворота пропорции губ: `scripts/metrics/lips.py`.

  py -3 -m pytest -q tests/test_lips.py

КАДРЫ ЗДЕСЬ РИСОВАННЫЕ, И ЭТО НЕ ЛЕНЬ. Набор обязан быть зелёным там, где нет
ни рабочей папки, ни весов buffalo_l (см. шапку conftest.py), поэтому метрике
подсовывается синтетический кадр с ИЗВЕСТНОЙ ТОЧНО толщиной губ и готовая
разметка. Тогда проверяется не «похоже на правду», а равенство: нарисовали
нижнюю губу вдвое толще верхней — метрика обязана сказать «вдвое».

Настоящие кадры и настоящая порча — дело самотеста
`py -3 scripts/metrics/lips.py`: он поднимает детектор, портит кадры и
печатает зазор. Здесь же ловится то, что должно ломаться беззвучно: подмена
единиц, потеря третьего состояния, запасное значение порога в коде.
"""
import numpy as np
import pytest

from conftest import MANIFEST

from metrics import lips as mod
from metrics.verdict import FAIL, NOT_MEASURED, PASS

# Порог в манифесте появляется отдельным шагом (см. integration), поэтому
# тесты не берут его оттуда: они проверяют поведение метрики, а не число
# проекта. Число проекта проверяет самотест.
GATES = {"lip_ratio_min": 1.20, "min_face_ipd_px": 100}

SKIN = (150, 170, 200)      # BGR: кожа
LIP = (112, 112, 196)       # BGR: кайма — заметно краснее кожи
SEAM = (84, 84, 147)        # шов: та же краснота, но темнее


def frame(upper=14, lower=28, ipd=200.0, gap=1, lip=LIP, seam=SEAM,
          upper_right=None, size=(620, 480), rng=None):
    """Кадр с губами известной толщины и разметка к нему.

    upper/lower — толщина верхней и нижней каймы В ПИКСЕЛЯХ, gap — насколько
    разведены внутренние контуры (0 или 1 — рот закрыт). upper_right задаёт
    другую толщину верхней губы у правого края рта: так строится кадр, на
    котором колонки заведомо не согласны.
    """
    rng = rng or np.random.default_rng(20260811)
    w, h = size
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = SKIN
    my = h // 2
    cx = w // 2
    x0, x1 = int(cx - 0.35 * ipd), int(cx + 0.35 * ipd)

    for x in range(x0, x1):
        t = (x - x0) / max(x1 - x0 - 1, 1)
        u = upper if upper_right is None else \
            int(round(upper + t * (upper_right - upper)))
        img[my - u:my, x] = lip
        img[my:my + 1 + gap, x] = seam
        img[my + 1 + gap:my + 1 + gap + lower, x] = lip
    img = np.clip(img.astype(np.int16)
                  + rng.integers(-3, 4, img.shape), 0, 255).astype(np.uint8)

    ey = my - int(0.9 * ipd)
    kps = [[cx - ipd / 2, ey], [cx + ipd / 2, ey], [cx, my - 0.35 * ipd],
           [x0, my], [x1, my]]
    k106 = np.tile(np.array([cx, my], np.float32), (106, 1))
    k106[52] = [x0, my]
    k106[61] = [x1, my]
    for i, f in zip(mod.IN_UP, (-0.25, 0.0, 0.25)):
        k106[i] = [cx + f * (x1 - x0), my]
    for i, f in zip(mod.IN_LO, (-0.25, 0.0, 0.25)):
        k106[i] = [cx + f * (x1 - x0), my + gap]
    # наружный контур — только для порчи в самотесте, замер его не читает
    for i, f in zip((63, 71, 67), (-0.25, 0.0, 0.25)):
        k106[i] = [cx + f * (x1 - x0), my - upper]
    for i, f in zip((56, 53, 59), (-0.25, 0.0, 0.25)):
        k106[i] = [cx + f * (x1 - x0), my + gap + lower]

    face = {"gate": "face", "state": PASS, "note": "", "kps": kps,
            "kps106": k106.tolist(), "ipd_px": float(ipd),
            "bbox": [x0 - ipd, ey - ipd, x1 + ipd, my + ipd]}
    return img, face


def measure(**kw):
    gates = kw.pop("gates", GATES)
    img, face = frame(**kw)
    return mod.lips(img, face=face, gates=gates)


# ------------------------------------------------------- метрика меряет кадр

def test_value_is_the_ratio_of_the_thicknesses_drawn():
    """Нарисовали 1:2 — метрика обязана сказать 2, а не «примерно больше»."""
    r = measure(upper=14, lower=28)
    assert r["state"] == PASS, r["note"]
    assert r["value"] == pytest.approx(2.0, abs=0.15), r


@pytest.mark.parametrize("upper,lower,want", [(10, 30, 3.0), (14, 28, 2.0),
                                              (20, 28, 1.4), (24, 24, 1.0),
                                              (30, 15, 0.5)])
def test_value_follows_the_drawn_thickness(upper, lower, want):
    """Ответ ведёт КАДР, а не форма рта, заученная детектором.

    Первая редакция метрики брала толщину прямо из точек 2d106det и на
    настоящей порче почти не двигалась — это и есть проверяемое свойство.
    Разметка здесь одна и та же по построению, меняются только пиксели.
    """
    r = measure(upper=upper, lower=lower)
    assert r["state"] in (PASS, FAIL), r["note"]
    assert r["value"] == pytest.approx(want, rel=0.12), r


def test_a_lying_outer_contour_does_not_move_the_answer():
    """Наружный контур 2d106det в замер НЕ входит, и это главное свойство.

    Замер показал, что на настоящей порче контур держит заученную форму рта и
    отвечает единицами процентов от того, на что меняются пиксели. Поэтому
    здесь наружный контур переставлен как попало — верх ниже низа, — а ответ
    обязан остаться прежним: его дают пиксели, точки задают только, где
    смотреть и где искать шов.
    """
    img, face = frame(upper=14, lower=28)
    honest = mod.lips(img, face=face, gates=GATES)
    k = np.asarray(face["kps106"], np.float32)
    k[[63, 71, 67], 1] += 40      # «верх губ» уехал на подбородок
    k[[56, 53, 59], 1] -= 40      # «низ губ» — на нос
    face["kps106"] = k.tolist()
    lying = mod.lips(img, face=face, gates=GATES)
    assert lying["value"] == pytest.approx(honest["value"], rel=0.02)


def test_equal_lips_fail_the_gate():
    """Признака карточки на равных губах нет — это FAIL, а не PASS."""
    r = measure(upper=24, lower=24)
    assert r["state"] == FAIL
    assert r["value"] < GATES["lip_ratio_min"]


def test_thick_upper_lip_fails_the_gate():
    r = measure(upper=30, lower=15)
    assert r["state"] == FAIL
    assert r["value"] < 1.0


# ------------------------------------------------------- масштаб и ракурс

def test_ratio_does_not_depend_on_the_size_of_the_face():
    """Отношение не должно мерить крупность плана.

    Тот же рот, снятый вдвое крупнее: и толщины, и IPD растут вместе, поэтому
    и доли IPD, и отношение обязаны остаться прежними.
    """
    small = measure(upper=14, lower=28, ipd=200.0)
    big = measure(upper=21, lower=42, ipd=300.0)
    assert big["value"] == pytest.approx(small["value"], rel=0.10)
    assert big["upper_ipd"] == pytest.approx(small["upper_ipd"], rel=0.10)


def test_ratio_survives_horizontal_squeeze_but_thickness_does_not():
    """Поворот головы сжимает кадр по горизонтали, а не по вертикали.

    Отношение — частное двух ВЕРТИКАЛЬНЫХ длин, и сжатие в нём сокращается;
    сами толщины в долях IPD при этом честно растут, потому что IPD уменьшился.
    Метрика, которая мерила бы толщины и сравнивала их с абсолютным порогом,
    провалила бы повёрнутую голову — эта не должна.
    """
    face_on = measure(upper=10, lower=20, ipd=200.0)
    turned = measure(upper=10, lower=20, ipd=120.0)
    assert turned["state"] == PASS, turned["note"]
    assert turned["value"] == pytest.approx(face_on["value"], rel=0.10)
    assert turned["upper_ipd"] > face_on["upper_ipd"] * 1.4


# --------------------------------------------- третье состояние, а не провал

def test_open_mouth_is_not_measured_and_not_failed():
    """На приоткрытом рте профиль упирается в зубы, а не в кайму.

    Отдать здесь FAIL значило бы забраковать годный кадр за то, что героиня
    говорит: замера не было, а не признака не было.
    """
    r = measure(gap=int(0.06 * 200))
    assert r["state"] == NOT_MEASURED
    assert "рот не закрыт" in r["note"]


def test_small_face_is_not_measured():
    r = measure(ipd=80.0)
    assert r["state"] == NOT_MEASURED
    assert "мелк" in r["note"]


def test_missing_face_is_not_measured():
    for face in (None, {"state": NOT_MEASURED, "note": "лица не найдено"}):
        r = mod.lips(np.zeros((10, 10, 3), np.uint8), face=face, gates=GATES)
        assert r["state"] == NOT_MEASURED
        assert r["value"] is None


def test_five_point_landmarks_alone_are_not_enough():
    """Без разметки 106 точек контур губ строить не из чего.

    Пять точек детектора — зрачки, нос и УГЛЫ рта; ни верхней границы губы, ни
    шва среди них нет. Молча посчитать что-нибудь по ним — худший исход.
    """
    img, face = frame()
    face["kps106"] = None
    r = mod.lips(img, face=face, gates=GATES)
    assert r["state"] == NOT_MEASURED
    assert "106" in r["note"]


def test_lips_that_do_not_differ_from_skin_are_not_measured():
    """Губы цвета кожи — это «не видно», а не «признака нет»."""
    r = measure(lip=SKIN, seam=SKIN)
    assert r["state"] == NOT_MEASURED
    assert r["value"] is None


def test_columns_that_disagree_are_not_measured():
    """Рот под углом, тень от носа, перекрытый угол — одна цифра на весь рот
    там врёт, и метрика обязана это заметить по себе самой."""
    r = measure(upper=6, lower=28, upper_right=30)
    assert r["state"] == NOT_MEASURED
    assert "колонки не согласны" in r["note"]
    # число разброса остаётся в отчёте: без него причина незамера непроверяема
    assert r["column_iqr"] > mod.MAX_IQR


# ------------------------------------------------- пороги только из манифеста

@pytest.mark.parametrize("key", ["lip_ratio_min", "min_face_ipd_px"])
def test_thresholds_have_no_hidden_default_in_the_code(key):
    """Запасное значение у порога — это второй, невидимый порог.

    `g.get("lip_ratio_min", 1.2)` продолжает судить по числу из кода после
    того, как манифест поправили, и разойтись они могут только молча.
    """
    gates = {k: v for k, v in GATES.items() if k != key}
    img, face = frame()
    with pytest.raises(KeyError):
        mod.lips(img, face=face, gates=gates)


def test_manifest_key_is_the_one_the_metric_reads():
    """Ключ ворот назван в шапке — иначе перекалибровку негде начать."""
    import ast
    with open(mod.__file__, encoding="utf-8") as fh:
        doc = ast.get_docstring(ast.parse(fh.read())) or ""
    assert "lip_ratio_min" in doc
    assert "py -3 scripts/metrics/lips.py" in doc
    assert "min_face_ipd_px" in doc


# ------------------------------------------------------------- встройка

def test_manifest_threshold_demands_a_fuller_lower_lip():
    """Порог обязан требовать «полнее», а не «не тоньше».

    Значение 1.0 и ниже пропускало бы кадр с равными губами, то есть ворота
    объявляли бы признак карточки выполненным там, где его нет. Пропускается,
    пока ключа в манифесте нет: его вписывают отдельным шагом (см. integration).
    """
    lo = MANIFEST["gates"].get("lip_ratio_min")
    if lo is None:
        pytest.skip("порог ещё не вписан в assets.json — см. самотест метрики")
    assert float(lo) > 1.0


def test_runner_knows_where_to_find_the_metric():
    """Ворота, которых нет в таблице раннера, не считаются вообще — молча."""
    import gates as runner
    if "lips" not in runner.METRICS:
        pytest.skip("ворота ещё не заведены в gates.py — см. integration")
    modules, funcs = runner.METRICS["lips"]
    assert "metrics.lips" in modules
    assert any(hasattr(mod, f) for f in funcs)
    assert "lips" in dict(runner.COLUMNS)


# ------------------------------------------------------------- форма ответа

def test_result_is_a_gate_the_runner_understands():
    """`gates.py` смотрит на state и value; словарь без них — вечный незамер."""
    r = measure()
    assert r["gate"] == "lips"
    assert set(("gate", "state", "value", "min", "max", "note")) <= set(r)
    assert r["min"] == GATES["lip_ratio_min"] and r["max"] is None


def test_measure_is_the_same_gate_not_a_bare_number():
    img, face = frame()
    a = mod.lips(img, face=face, gates=GATES)
    b = mod.measure(img, face=face, gates=GATES)
    assert b["state"] == a["state"] and b["value"] == pytest.approx(a["value"])


def test_yaw_is_reported_but_does_not_judge():
    """Поворот отдаётся справочно: ворота по нему не ставятся, и полос у него
    в ответе быть не должно."""
    r = measure()
    assert r["yaw"] is not None
    assert r["min"] == GATES["lip_ratio_min"]


# ------------------------------------------------------------- порча кадра

def test_move_seam_changes_the_pixels_it_promises():
    """Порча самотеста обязана двигать шов, а не весь рот.

    Если бы она сдвигала рот целиком, самотест проверял бы, что метрика
    безразлична к переносу — то есть ничего.
    """
    img, face = frame(upper=14, lower=28)
    spoiled = mod.move_seam(img, face, 0.5)
    assert spoiled is not None
    r0 = mod.lips(img, face=face, gates=GATES)
    r1 = mod.lips(spoiled, face=face, gates=GATES)
    assert r1["value"] < r0["value"]
    assert r1["upper_ipd"] > r0["upper_ipd"]
    assert r1["lower_ipd"] < r0["lower_ipd"]


def test_mirror_makes_the_lips_equal():
    """Зеркальная копия — отрицательный класс с ТОЧНОЙ меткой: верхняя губа
    там есть копия нижней, то есть губы равны при любом способе замера."""
    img, face = frame(upper=12, lower=30)
    mirrored = mod.mirror_lower_up(img, face)
    assert mirrored is not None
    r = mod.lips(mirrored, face=face, gates=GATES)
    assert r["state"] == FAIL, r
    assert r["value"] == pytest.approx(1.0, abs=0.25), r


def test_squeeze_x_keeps_the_vertical_size():
    img, _ = frame()
    out = mod.squeeze_x(img, 0.6)
    assert out.shape == img.shape
