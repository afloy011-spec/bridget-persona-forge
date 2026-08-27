"""Асимметрия бровей: геометрия, три состояния и знак стороны.

  py -3 -m pytest -q -k brows

Детектор здесь не поднимается НИ РАЗУ. Проверяется то, что можно проверить
точно: на синтетическом лице с ЗАРАНЕЕ ИЗВЕСТНОЙ асимметрией метрика обязана
вернуть именно её — при наклоне головы, при повороте, при повороте с кивком, в
зеркале и в любом масштабе. Кадры для этого не нужны, а buffalo_l поднимается
три секунды и на машине рецензента может отсутствовать вовсе: сьют, зелёный
только там, где скачаны веса, не проверяет ничего.

Реальные кадры проверяет самотест метрики — `py -3 scripts/metrics/brows.py`,
он же калибрует порог. Здесь — контракт.
"""
import ast

import numpy as np
import pytest

from conftest import MANIFEST

from metrics import brows as B
from metrics.verdict import PASS, FAIL, NOT_MEASURED

IPD = 200.0                 # межзрачковое расстояние синтетического лица, px
GATES = {"brow_asymmetry_min": 0.020, "brow_max_yaw": 0.15,
         "brow_noise_max": 0.022, "min_face_ipd_px": 100,
         "brow_higher_side": "left"}

# КАРТА ТОЧЕК ПОВТОРЕНА ЗДЕСЬ ЛИТЕРАЛОМ, А НЕ ВЗЯТА ИЗ МОДУЛЯ, И ЭТО НЕ
# ДУБЛИРОВАНИЕ. Синтетическое лицо строится по этим номерам, а метрика читает
# СВОИ; строй тест по её же спискам — и любая ошибка в карте оказалась бы
# согласованной сама с собой, а тест зелёным. Числа установлены экспериментом:
# точки с номерами нарисованы поверх настоящего кадра и прочитаны глазами.
BROW_R_IDX = (43, 44, 45, 46, 47, 48, 49, 50, 51)
BROW_L_IDX = (101, 100, 99, 97, 98, 105, 104, 102, 103)   # зеркальные к ним
EYE_R_IDX = (33, 35, 36, 37, 39, 40, 41, 42)
EYE_L_IDX = (87, 93, 91, 90, 89, 94, 96, 95)              # зеркальные к ним
PUPIL_R_IDX, PUPIL_L_IDX, NOSE_IDX = 38, 88, 86


# ------------------------------------------------------------ синтетика лица

def face3d(lift_left=0.0):
    """Схематическое лицо в 3D, единица длины — IPD. Ось X — в её ЛЕВУЮ сторону.

    Строится ЗЕРКАЛЬНО-СИММЕТРИЧНЫМ, а затем её левая бровь поднимается на
    lift_left. Так «правильный ответ» известен точно, и метрике есть что не
    угадать. Глубины (z) не декоративны: без них поворот головы был бы просто
    сжатием по X и ничего бы не проверял — весь смысл в том, что нос вынесен
    вперёд, а брови и виски уходят назад.
    """
    pts = np.zeros((106, 3), np.float64)
    # зрачки: её правый при отрицательном X, её левый при положительном
    pts[PUPIL_R_IDX] = (-0.5, 0.0, 0.0)
    pts[PUPIL_L_IDX] = (+0.5, 0.0, 0.0)
    pts[34] = pts[PUPIL_R_IDX]              # 34 и 38 — одна и та же точка,
    pts[92] = pts[PUPIL_L_IDX]              # 88 и 92 тоже
    # контуры глаз: восемь точек вокруг своего зрачка, зеркально
    ring = [(-0.22, 0.02), (-0.11, 0.06), (0.11, 0.06), (0.22, -0.01),
            (0.11, -0.07), (-0.11, -0.07), (0.0, 0.07), (0.0, -0.07)]
    for j, (dx, dy) in enumerate(ring):
        pts[EYE_R_IDX[j]] = (-0.5 - dx, dy, -0.05)
        pts[EYE_L_IDX[j]] = (+0.5 + dx, dy, -0.05)
    # брови: девять точек дугой над своим глазом; z уходит назад к вискам
    arc = [(-0.42, -0.26), (-0.28, -0.31), (-0.14, -0.34), (0.28, -0.28),
           (0.10, -0.32), (-0.30, -0.38), (-0.14, -0.41), (0.28, -0.35),
           (0.08, -0.39)]
    for j, (dx, dy) in enumerate(arc):
        z = -0.10 - 0.15 * max(0.0, -dx)
        pts[BROW_R_IDX[j]] = (-0.5 - dx, dy, z)
        pts[BROW_L_IDX[j]] = (+0.5 + dx, dy - lift_left, z)
    pts[NOSE_IDX] = (0.0, 0.55, 0.35)
    # Точки, которые метрика не использует, лежат далеко от лица: если она
    # вдруг начнёт их читать, ответ уедет так, что это будет видно, а не
    # утонет в четвёртом знаке.
    for i in range(106):
        if not pts[i].any() and i not in (0,):
            pts[i] = (0.0, 9.0, 0.0)
    return pts


def project(pts3, yaw=0.0, pitch=0.0, roll=0.0, scale=IPD, mirror=False):
    """Спроецировать лицо на кадр: повороты в градусах, знак Y — вниз."""
    a, b, c = np.radians([yaw, pitch, roll])
    ry = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    rx = np.array([[1, 0, 0], [0, np.cos(b), -np.sin(b)], [0, np.sin(b), np.cos(b)]])
    rz = np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0], [0, 0, 1]])
    p = pts3 @ ry.T @ rx.T @ rz.T
    xy = p[:, :2] * scale + np.array([900.0, 700.0])
    if mirror:
        # Зеркало кадра отражает X И МЕНЯЕТ НОМЕРА МЕСТАМИ. Детектор нумерует
        # точки по тому, что видит: на отражённом кадре её левая бровь лежит
        # слева от зрителя, и номера ей достанутся «левые у зрителя» — 43-51.
        # Отразить одни координаты, оставив нумерацию, значило бы проверять
        # то, чего в жизни не бывает.
        xy[:, 0] = 1800.0 - xy[:, 0]
        swapped = xy.copy()
        for a, b in (list(zip(BROW_R_IDX, BROW_L_IDX))
                     + list(zip(EYE_R_IDX, EYE_L_IDX))
                     + [(PUPIL_R_IDX, PUPIL_L_IDX), (34, 92)]):
            swapped[a], swapped[b] = xy[b], xy[a]
        xy = swapped
    return xy


def face_of(pts2, ipd_px=IPD, det=0.9):
    """Результат detect() в том виде, в каком его отдаёт metrics.faces."""
    return {"gate": "face", "state": PASS, "value": det, "min": None, "max": None,
            "note": "", "kps106": [[float(x), float(y)] for x, y in pts2],
            "ipd_px": float(ipd_px), "det_score": det}


def asym_of(**kw):
    lift = kw.pop("lift_left", 0.0)
    return B.asymmetry(project(face3d(lift), **kw))["asym"]


# --------------------------------------------------------- геометрия и знаки

def test_landmark_map_is_the_one_the_experiment_established():
    """Карта индексов — крест всей метрики, и проверить её больше нечем.

    Она не задокументирована у insightface и получена экспериментом: точки с
    номерами нарисованы поверх настоящего кадра, прочитаны глазами и сверены
    отражением относительно средней линии. Ошибка здесь не падает и не шумит —
    она даёт правдоподобные числа ни о чём, потому что «бровь» окажется веком
    или переносицей. Поэтому набор сверяется поимённо.

    Проверяются НАБОРЫ, а не порядок: высота брови — среднее по её точкам, и
    порядок внутри списка на ответ не влияет. Влияет состав.
    """
    assert set(B.BROW_R) == set(BROW_R_IDX)
    assert set(B.BROW_L) == set(BROW_L_IDX)
    assert set(B.EYE_R) == set(EYE_R_IDX)
    assert set(B.EYE_L) == set(EYE_L_IDX)
    assert (B.PUPIL_R, B.PUPIL_L, B.NOSE_TIP) == (PUPIL_R_IDX, PUPIL_L_IDX,
                                                  NOSE_IDX)
    # Сколько точек у одной брови, столько и у другой: набор из восьми против
    # девяти сдвинул бы среднее и показал асимметрию на ровном лице.
    assert len(B.BROW_R) == len(B.BROW_L) == 9
    assert len(B.EYE_R) == len(B.EYE_L) == 8
    # Ни одна точка не попала в два набора сразу.
    groups = [set(B.BROW_R), set(B.BROW_L), set(B.EYE_R), set(B.EYE_L)]
    assert len(set().union(*groups)) == sum(len(x) for x in groups)


def test_symmetric_face_reads_zero():
    """Идеально симметричному лицу метрика обязана вернуть ноль.

    Это проверка не арифметики, а того, что в наборы попали анатомически
    зеркальные точки. Достаточно взять в одну бровь точку с чужого места —
    веко, переносицу, соседнюю точку той же брови вместо парной, — и на
    симметричном лице вылезет асимметрия из ничего, причём правдоподобная по
    величине.
    """
    assert abs(asym_of()) < 1e-9


def test_lifting_her_left_brow_is_a_positive_sign():
    """Знак объявлен: плюс — выше ЕЁ ЛЕВАЯ. На нём держится смысл стороны."""
    assert asym_of(lift_left=0.03) == pytest.approx(0.03, abs=1e-9)
    assert asym_of(lift_left=-0.03) == pytest.approx(-0.03, abs=1e-9)


def test_head_tilt_is_compensated_exactly():
    """Наклон головы — главный источник ложной асимметрии в сырых пикселях.

    Брови разнесены больше чем на межзрачковое расстояние, поэтому наклон в
    пару градусов даёт разность высот больше настоящей. Ось по линии зрачков
    обязана вычитать его целиком, при любом угле.
    """
    for roll in (-25, -8, -1.5, 3, 12, 30):
        assert asym_of(lift_left=0.03, roll=roll) == pytest.approx(0.03, abs=1e-9)


def test_scale_and_shift_do_not_matter():
    """Величина объявлена в долях IPD — крупность плана не меряется."""
    for scale in (90.0, IPD, 700.0):
        assert asym_of(lift_left=0.02, scale=scale) == pytest.approx(0.02, abs=1e-9)


def test_mirror_flips_the_sign():
    """Зеркало меняет местами левое и правое и больше ничего.

    Проверка того, что метрика говорит на языке ЕЁ сторон, а не сторон
    зрителя: у зеркального кадра ответ обязан быть ровно противоположным.
    """
    assert asym_of(lift_left=0.025, mirror=True) == pytest.approx(-0.025, abs=1e-9)


def test_yaw_and_pitch_cross_term_cancels():
    """Поворот ВМЕСТЕ с кивком — самая коварная пара.

    По отдельности каждый почти безобиден, а вместе они заваливают линию
    бровей: горизонтальная разность в 1.2 IPD подмешивается в вертикальную.
    Ось по линии зрачков обязана убирать эту связку тождественно — на этом
    построена вся компенсация ракурса, и если она сломается, метрика начнёт
    мерить позу.
    """
    for yaw in (-14, -6, 6, 14):
        for pitch in (-12, -4, 4, 12):
            got = asym_of(lift_left=0.03, yaw=yaw, pitch=pitch)
            assert got == pytest.approx(0.03, abs=0.004), \
                f"поворот {yaw}° с кивком {pitch}° увёл ответ на {got - 0.03:+.4f}"


def test_pure_yaw_inflates_the_value_and_that_is_why_it_is_refused():
    """Чистый поворот всё же раздувает величину — на этом стоит отказ.

    Вертикальная разность при повороте не меняется, а межзрачковое расстояние
    в кадре сжимается, и отношение растёт. Если бы этого не было, ворота
    ракурса были бы перестраховкой; здесь видно, что не были.
    """
    straight = asym_of(lift_left=0.03)
    turned = asym_of(lift_left=0.03, yaw=35)
    assert turned > straight * 1.1


# ------------------------------------------------- три состояния, а не два

def test_no_face_is_not_measured():
    r = B.brows("кадра-нет.png", face={"state": NOT_MEASURED, "note": "лица нет"},
                gates=GATES)
    assert r["state"] == NOT_MEASURED and r["note"]


def test_face_without_106_points_is_not_measured():
    """Старый insightface отдаёт только пять точек — бровей среди них нет."""
    r = B.brows("кадр.png", face={"state": PASS, "kps106": None, "ipd_px": 300.0},
                gates=GATES)
    assert r["state"] == NOT_MEASURED
    assert r["refusal"] == "landmarks"


def test_small_face_is_not_measured_and_never_failed():
    """Мелкое лицо — это НЕ провал признака.

    FAIL здесь означал бы, что кадр в полный рост бракуется за то, что он
    общий план, и его отправили бы перегонять вместо того, чтобы посмотреть
    глазами.
    """
    # Мелким лицо делается по-настоящему — уменьшением проекции. Подставить
    # маленький ipd_px в словарь лица было бы проверкой заглушки: масштаб
    # метрика берёт из самих точек, той же парой зрачков, что и ось.
    small = project(face3d(0.03), scale=70.0)
    r = B.brows("кадр.png", face=face_of(small, ipd_px=70.0), gates=GATES)
    assert r["state"] == NOT_MEASURED and r["refusal"] == "ipd"
    assert r["state"] != FAIL


def test_turned_head_is_not_measured_and_never_failed():
    """Три четверти — тоже незамер: ближняя бровь кажется выше у любого лица."""
    r = B.brows("кадр.png", face=face_of(project(face3d(0.0), yaw=35)), gates=GATES)
    assert r["state"] == NOT_MEASURED and r["refusal"] == "yaw"
    assert "повёрнут" in r["note"]


def test_measurable_pose_is_actually_measured():
    """Отказ по ракурсу обязан быть узким: фронтальное лицо метрика мерит."""
    r = B.brows("кадр.png", face=face_of(project(face3d(0.03), yaw=5, roll=6)),
                gates=GATES)
    assert r["state"] == PASS


def test_undeclared_side_is_not_measured():
    """Пока не замерено, КАКАЯ бровь выше, ворота молчат — а не угадывают.

    Ворота с угаданной стороной ровно в половине случаев объявляли бы шум
    признаком персонажа, и отличить это от настоящего замера было бы нечем.
    """
    g = dict(GATES, brow_higher_side="")
    r = B.brows("кадр.png", face=face_of(project(face3d(0.03))), gates=g)
    assert r["state"] == NOT_MEASURED and r["refusal"] == "side"
    # число при этом посчитано: отказ судить — не отказ мерить
    assert r["asym"] == pytest.approx(0.03, abs=1e-9)


def test_declared_side_decides_pass_or_fail():
    """Один и тот же кадр: сторона из манифеста решает, признак это или брак."""
    face = face_of(project(face3d(0.03)))
    assert B.brows("к.png", face=face, gates=dict(GATES, brow_higher_side="left")
                   )["state"] == PASS
    assert B.brows("к.png", face=face, gates=dict(GATES, brow_higher_side="right")
                   )["state"] == FAIL


def test_level_brows_fail_the_declared_side():
    """Ровные брови — замеренное отсутствие признака, то есть FAIL, не незамер."""
    r = B.brows("к.png", face=face_of(project(face3d(0.0))), gates=GATES)
    assert r["state"] == FAIL


def test_gate_reports_both_lifts_not_only_the_difference():
    """В отчёт уходят обе высоты: по одной разности не видно, ЧТО уехало."""
    r = B.brows("к.png", face=face_of(project(face3d(0.03))), gates=GATES)
    assert r["lift_left"] - r["lift_right"] == pytest.approx(r["asym"], abs=1e-9)
    assert r["lift_right"] > 0 and r["lift_left"] > 0


def test_measure_is_the_same_gate():
    """`gates.py` ищет метрику по списку имён; синоним обязан быть синонимом."""
    face = face_of(project(face3d(0.03)))
    a = B.brows("к.png", face=face, gates=GATES)
    b = B.measure("к.png", face=face, gates=GATES)
    assert a["state"] == b["state"] and a["value"] == b["value"]


# --------------------------------------------- пороги живут только в манифесте

@pytest.mark.parametrize("key", ["brow_asymmetry_min", "brow_max_yaw",
                                 "min_face_ipd_px"])
def test_thresholds_have_no_hidden_default_in_the_code(key):
    """Запасное значение у порога — это второй, невидимый порог.

    `g.get("brow_asymmetry_min", 0.016)` продолжит судить по числу из кода
    после того, как манифест поправили, и разойтись они смогут только молча.
    Файла намеренно нет: пороги читаются раньше кадра, и до диска дело не
    дойдёт — а если дойдёт, значит порог взят не из манифеста.
    """
    gates = {k: v for k, v in GATES.items() if k != key}
    with pytest.raises(KeyError):
        B.brows("кадра-нет.png", face=None, gates=gates)


def test_no_brow_key_is_read_with_a_fallback_value():
    """То же правило для ключей, которые читает не метрика, а её самотест.

    `brow_noise_max` в ворота не попадает — он живёт в самотесте, — и проверить
    его вызовом нельзя. Но запасное значение опасно ровно так же: самотест
    сверял бы разброс с числом из кода и молчал бы о том, что в манифесте
    обещано другое. Единственное `.get` без значения по умолчанию оставлено
    стороне персонажа: её отсутствие — это NOT_MEASURED, а не порог.
    """
    with open(B.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and node.args):
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant)
                and str(first.value).startswith("brow_")):
            continue
        if len(node.args) > 1:
            bad.append(f"{first.value} со значением по умолчанию")
        elif first.value != "brow_higher_side":
            bad.append(f"{first.value} читается через .get, а не по ключу")
    assert not bad, "; ".join(bad)


def test_manifest_declares_the_keys():
    """Ключи ворот бровей объявлены и не противоречат друг другу.

    Пропускается, пока их не внесли в assets.json: файл манифеста принадлежит
    не этой метрике, и её тесты не имеют права краснеть за чужую правку. Но
    пропуск ВИДЕН (-ra в pytest.ini) и называет, чего не хватает.
    """
    g = MANIFEST["gates"]
    need = ["brow_asymmetry_min", "brow_max_yaw", "brow_noise_max",
            "brow_higher_side"]
    missing = [k for k in need if k not in g]
    if missing:
        pytest.skip(f"в assets.json → gates ещё нет ключей: {', '.join(missing)}")
    assert 0 < float(g["brow_asymmetry_min"]) < 0.1
    assert 0 < float(g["brow_max_yaw"]) < 0.5
    assert 0 < float(g["brow_noise_max"]) < 0.1
    assert (g["brow_higher_side"] or "") in ("", "left", "right"), \
        "сторона персонажа может быть только left, right или пустой"


def test_gate_is_not_allowed_to_block_while_it_is_noisier_than_its_threshold():
    """Ворота, чей разброс не меньше порога, обязаны быть справочными.

    Замерено: тот же кадр под другим наклоном головы меняет ответ примерно на
    столько же, на сколько отличаются «видно» и «не видно». Пока это так,
    место ворот — в gates.informational: иначе они бракуют кадры по шуму
    детектора точек.
    """
    g = MANIFEST["gates"]
    if "brow_noise_max" not in g:
        pytest.skip("ключей ворот бровей ещё нет в assets.json")
    if float(g["brow_noise_max"]) < float(g["brow_asymmetry_min"]):
        return                              # разброс стал меньше порога — можно
    assert "brows" in [n for n in g.get("informational", [])], \
        "brows не объявлены справочными, хотя их разброс не меньше порога"
    assert "brows" not in [n for n in g.get("required", [])]


# ------------------------------------------------------------------- шапка

def _header():
    with open(B.__file__, encoding="utf-8") as fh:
        return ast.get_docstring(ast.parse(fh.read())) or ""


def test_header_carries_the_landmark_map():
    """Карта индексов 106 точек — единственное место, где она записана.

    Она установлена экспериментом (точки с номерами нарисованы поверх кадра и
    прочитаны глазами), нигде у insightface не задокументирована, и без неё
    следующий человек будет угадывать заново — а угаданная карта даёт
    правдоподобные числа ни о чём.
    """
    doc = _header()
    for token in ("43-51", "97-105", "43-101", "2d106det"):
        assert token in doc, f"в шапке нет {token} — карта точек не записана"


def test_header_names_its_manifest_keys_and_selftest():
    """Раз чисел замера в шапке нет, она обязана сказать, чем их получить."""
    doc = _header()
    assert "py -3 scripts/metrics/brows.py" in doc
    for key in ("gates.brow_asymmetry_min", "gates.brow_max_yaw",
                "gates.brow_noise_max"):
        assert key in doc, f"шапка не называет ключ {key}"
