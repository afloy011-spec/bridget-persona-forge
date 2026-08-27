"""Ворота цвета радужки: что метрика обязана уметь и в чём обязана сознаваться.

  py -3 -m pytest -q tests/test_iris.py

Карточка персонажа объявляет «green-hazel eyes» признаком узнаваемости, а
косинус ArcFace к пигменту радужки равнодушен: он одинаково доволен кадром с
зелёными глазами и с голубыми. `scripts/metrics/iris.py` превращает это
обещание в число. Здесь под замком лежат четыре свойства, без которых число
было бы бесполезным или вредным.

ПЕРВОЕ — СВЕТ. Тёплая лампа уводит всё в жёлтый, и наивная метрика мерила бы
лампу, а не человека. Метрика отбивает баланс по белку глаза — почти идеальной
белой карте, лежащей в паре пикселей от радужки. Тест подменяет освещение на
том же кадре и требует, чтобы тон не уехал.

Одного потолка на уход тона для этого МАЛО, и это проверено, а не предположено:
отбивку по белку выключали нарочно, и половина кадров прошла проверку насквозь —
без компенсации свет уводит тон примерно на столько же, на сколько стоит
потолок. Поэтому рядом стоит контрольный прогон (`balance=False`), где белой
точкой берётся серый той же яркости, что белок, и тест требует, чтобы БЕЗ
отбивки тон уходил кратно сильнее. Так проверяется механизм, а не везение
материала.

ВТОРОЕ — ТРИ СОСТОЯНИЯ. Лица нет, лицо мелкое, радужка обесцвечена — это
NOT_MEASURED С ПРИЧИНОЙ, а не «цвет не тот». Метрика, которая при отсутствии
данных отвечает FAIL, отправляет годный кадр в брак; проект уже платил за это
на воротах возраста.

ТРЕТЬЕ — ПОЛОСА ПОД ОДИН ЦВЕТ. У второго и третьего персонажей репозитория
глаза карие. Полоса, откалиброванная под зелёно-ореховый, провалила бы их самим
фактом их существования — ровно та ошибка, которую манифест уже разбирает в
`gates._age_band`. Метрика обязана отказаться судить чужой цвет, а не судить.

ЧЕТВЁРТОЕ — ПРИЗНАННОЕ БЕССИЛИЕ. Светло-карий и янтарный от зелёно-орехового
эта метрика НЕ отделяет: золотое кольцо вокруг зрачка орехового глаза по
пигменту то же самое, что светло-карая радужка. Это записано в шапке модуля, и
тест держит признание и факт вместе: пока перекрашенный в янтарь глаз ворота
проходит, оговорка обязана оставаться в шапке. Убрать её, не починив метрику,
не выйдет.

Разметка 2d106det, на которой всё держится, нигде не документирована и
установлена экспериментом. Тест проверяет её на настоящих кадрах: если
insightface переставит порядок точек, метрика начнёт мерить бровь и не скажет
об этом ни слова.
"""
import ast
import glob
import os

import pytest

from conftest import MANIFEST, ROOT, work_root

METRICS_DIR = os.path.join(ROOT, "scripts", "metrics")
IRIS_PY = os.path.join(METRICS_DIR, "iris.py")

pytestmark = pytest.mark.skipif(not os.path.exists(IRIS_PY),
                                reason="метрика радужки ещё не написана")


def _source():
    with open(IRIS_PY, encoding="utf-8") as fh:
        return fh.read()


def _header():
    """Докстринг модуля — из исходника, а не из __doc__: под -OO его нет."""
    return ast.get_docstring(ast.parse(_source())) or ""


@pytest.fixture(scope="module")
def iris_mod():
    pytest.importorskip("cv2", reason="радужка считается OpenCV")
    pytest.importorskip("numpy")
    import metrics.iris as mod
    return mod


# ОБЯЗАТЕЛЬНЫЕ ключи. `iris_hue_min` сюда НЕ входит и входить не должен: нижняя
# граница тона удалена намеренно (см. «ПОЧЕМУ ПОЛОСА ОДНОСТОРОННЯЯ» в шапке
# метрики) — перекрашенный в карий кадр даёт тон ВЫШЕ настоящего, и разделить
# классы этим числом нельзя ни при каком значении. Ворота односторонние.
IRIS_KEYS = ("iris_hue_max", "iris_chroma_min",
             "iris_min_ipd_px", "iris_expect")
ABSENT = [k for k in IRIS_KEYS if k not in MANIFEST["gates"]]

# Пока ключей нет в манифесте, КРАСНЕЕТ РОВНО ОДИН тест — тот, что их и
# перечисляет. Остальные пропускаются с этой же причиной: тридцать одинаковых
# KeyError не сообщают ничего сверх первого, зато прячут настоящие поломки.
# Пропуск виден: pytest.ini печатает причины пропусков (-ra).
needs_manifest = pytest.mark.skipif(
    bool(ABSENT), reason="в assets.json → gates ещё нет " + ", ".join(ABSENT))


@pytest.fixture(scope="module")
def gates():
    if ABSENT:
        pytest.skip("в assets.json → gates ещё нет " + ", ".join(ABSENT))
    return MANIFEST["gates"]


def _sample_frames():
    """По одному настоящему кадру на ячейку: разный свет обязан быть в выборке.

    Ячейки сняты при окне, днём, в помещении и вечером в ресторане — то есть
    выборка сама по себе и есть проверка «не скачет ли число от света сильнее,
    чем от человека».
    """
    out = {}
    root = work_root()
    if not os.path.isdir(root):
        return []
    for path in sorted(glob.glob(os.path.join(root, "*", "frames", "*", "*.png"))):
        out.setdefault(os.path.basename(os.path.dirname(path)), path)
    return sorted(out.items())


FRAMES = _sample_frames()
needs_frames = pytest.mark.skipif(not FRAMES, reason="настоящих кадров нет")


@pytest.fixture(scope="module")
def measured(iris_mod, gates):
    """Кадры, на которых метрика ЗАМЕРИЛА радужку: (ячейка, путь, лицо, ворота).

    Кадр, где метрика отказалась считать по своей же объявленной причине (лицо
    мельче порога, радужка обесцвечена), из выборки выпадает: законный отказ —
    не повод краснеть. Отказ ПРОВЕРЯЕТСЯ отдельным тестом, на нарочно
    уменьшенном кадре, где причина известна заранее.
    """
    from metrics.faces import detect
    from metrics.verdict import NOT_MEASURED
    out = []
    for cell, path in FRAMES:
        img = iris_mod.load_bgr(path)
        face = detect(img)
        if face["state"] != "PASS" or not face.get("kps106"):
            continue
        r = iris_mod.iris(img, face=face, gates=gates)
        if r["state"] != NOT_MEASURED:
            out.append((cell, img, face, r))
    return out


# ------------------------------------------------------------------- разметка

@needs_frames
def test_landmark_map_in_the_header_still_matches_the_detector(iris_mod, measured):
    """Разметка в 106 точек установлена экспериментом и нигде не гарантирована.

    Проверяется то, что от порядка точек не зависит: центр глаза лежит внутри
    контура века и рядом со зрачком пятиточечного детектора, а контур этот
    центр окружает. Переставит insightface точки — метрика начнёт мерить бровь,
    и вернёт при этом честное на вид число.
    """
    if not measured:
        pytest.skip("ни на одном кадре радужка не замерена")
    for cell, img, face, _ in measured:
        assert iris_mod.landmark_check(face) == [], (
            f"{cell}: разметка 106 точек разошлась с шапкой iris.py")


@needs_frames
def test_header_writes_the_landmark_map_down(iris_mod):
    """Карта индексов обязана лежать в шапке: гадать её нельзя, а без неё
    ни прочитать код, ни перепроверить его невозможно."""
    doc = _header()
    for idx in (iris_mod.EYES["левый"]["centre"], iris_mod.EYES["правый"]["centre"]):
        assert str(idx) in doc, f"шапка не называет индекс центра глаза {idx}"
    assert "2d106det" in doc, "шапка не говорит, чья это разметка"
    assert "py -3 scripts/metrics/iris.py" in doc, (
        "шапка не говорит, чем пересчитать числа калибровки")


# ---------------------------------------------------------------------- свет

@needs_frames
def test_white_balance_on_the_sclera_survives_a_change_of_light(iris_mod, gates,
                                                                measured):
    """ГЛАВНОЕ СВОЙСТВО. Смена цветовой температуры не должна двигать тон.

    Освещение подменяется диагональю в линейном свете — это и есть смена
    температуры и экспозиции. Баланс по белку обязан её съесть. Потолок берётся
    из самого модуля (`LIGHT_TOL`), а не выдумывается тестом: иначе тест и
    метрика разъехались бы по разным числам.

    Что именно запрещено — то же, что и в самотесте. Превратить проходной кадр
    в ПРОВАЛ свет не вправе. Превратить замер в ОТКАЗ — вправе: свеча честно
    гасит насыщенность, и радужка, стоявшая у порога хромы, под ней перестаёт
    читаться; требовать иного значило бы требовать видеть то, чего в кадре уже
    нет. Чтобы послабление не выродилось в «всегда отказываю», отказы считаются
    и большинством быть не могут.
    """
    if not measured:
        pytest.skip("ни на одном кадре радужка не замерена")
    from metrics.verdict import FAIL
    total = refused = 0
    for cell, img, face, base in measured:
        for name in iris_mod.ILLUMINANTS:
            r = iris_mod.iris(iris_mod.relight(img, name), face=face, gates=gates)
            total += 1
            assert r["state"] != FAIL, (
                f"{cell}: «{name}» превратил проходной кадр в провал — "
                f"{r['note']}")
            if r["value"] is None:
                refused += 1
                continue
            drift = abs(r["value"] - base["value"])
            assert drift <= iris_mod.LIGHT_TOL, (
                f"{cell}: «{name}» увёл тон на {drift:.1f}° при потолке "
                f"{iris_mod.LIGHT_TOL}° — баланс по белку не держит, и метрика "
                f"меряет лампу, а не человека")
    assert refused * 2 < total, (
        f"под подменённым освещением метрика отказалась считать {refused} раз "
        f"из {total} — послабление превратилось в отказ мерить вообще")


@needs_frames
def test_it_is_the_sclera_that_makes_the_number_light_proof(iris_mod, gates,
                                                            measured):
    """ВКЛАД БЕЛОЙ КАРТЫ, а не просто «число не уехало».

    Абсолютный потолок сам по себе слаб: выключи отбивку по белку насовсем, и
    на этом материале свет уведёт тон примерно на столько же, на сколько стоит
    потолок, — половина кадров пройдёт проверку насквозь. Замерено, а не
    предположено: отбивку выключали нарочно.

    Поэтому сравниваются два прогона по ОДНОМУ кадру и ОДНОМУ свету: обычный и
    контрольный, где белая точка — серый той же яркости, что белок. Разница
    между ними и есть весь вклад белка, и он обязан быть кратным.
    """
    if not measured:
        pytest.skip("ни на одном кадре радужка не замерена")
    with_wb, without = [], []
    for cell, img, face, base in measured:
        raw0 = iris_mod.iris(img, face=face, gates=gates, balance=False)
        if raw0["value"] is None:
            continue
        for name in iris_mod.ILLUMINANTS:
            lit = iris_mod.relight(img, name)
            r = iris_mod.iris(lit, face=face, gates=gates)
            raw = iris_mod.iris(lit, face=face, gates=gates, balance=False)
            if r["value"] is None or raw["value"] is None:
                continue
            with_wb.append(abs(r["value"] - base["value"]))
            without.append(abs(raw["value"] - raw0["value"]))
    if not with_wb:
        pytest.skip("контрольный прогон нигде не сошёлся")
    import statistics
    a, b = statistics.median(with_wb), statistics.median(without)
    assert b > 2 * a, (
        f"без отбивки по белку тон уходит на {b:.1f}°, с отбивкой — на "
        f"{a:.1f}°. Белая карта не даёт ничего: либо она берётся не с белка, "
        f"либо подмена света перестала быть подменой света")


@needs_frames
def test_the_number_moves_less_from_light_than_from_pigment(iris_mod, gates,
                                                            measured):
    """Метрика бесполезна, если от света она скачет сильнее, чем от человека.

    Сравниваются две величины на ОДНОМ кадре: уход тона от подмены света и уход
    от подмены пигмента. Второй обязан быть кратно больше первого — иначе
    измеряется сцена, а не радужка.
    """
    if not measured:
        pytest.skip("ни на одном кадре радужка не замерена")
    for cell, img, face, base in measured:
        light = max(
            abs(iris_mod.iris(iris_mod.relight(img, n), face=face,
                              gates=gates)["value"] - base["value"])
            for n in iris_mod.ILLUMINANTS)
        pigment = min(
            abs(iris_mod.iris(iris_mod.recolour(img, face, p), face=face,
                              gates=gates)["value"] - base["value"])
            for p in ("карий", "голубой"))
        assert pigment > 2 * light, (
            f"{cell}: свет двигает тон на {light:.1f}°, пигмент — на "
            f"{pigment:.1f}°. Метрика меряет освещение, а не радужку")


# ------------------------------------------------------------------- пигмент

@needs_frames
def test_blue_iris_fails_and_the_order_of_pigments_holds(iris_mod, gates,
                                                         measured):
    """Голубая радужка обязана валиться, а порядок — держаться.

    Порядок (карий теплее исходного, голубой холоднее) от поколения кадров не
    зависит и проверяется на каждом кадре; абсолютные числа зависят, и их
    печатает самотест.
    """
    if not measured:
        pytest.skip("ни на одном кадре радужка не замерена")
    from metrics.verdict import FAIL, PASS
    for cell, img, face, base in measured:
        assert base["state"] == PASS, (
            f"{cell}: настоящий кадр обязан проходить ворота — {base['note']}")
        warm = iris_mod.iris(iris_mod.recolour(img, face, "карий"),
                             face=face, gates=gates)
        cold = iris_mod.iris(iris_mod.recolour(img, face, "голубой"),
                             face=face, gates=gates)
        assert warm["value"] < base["value"], (
            f"{cell}: перекрашенный в карий обязан быть теплее исходного")
        assert cold["value"] > base["value"], (
            f"{cell}: перекрашенный в голубой обязан быть холоднее исходного")
        assert cold["state"] == FAIL, (
            f"{cell}: голубая радужка прошла ворота цвета глаз "
            f"({cold['value']:.1f}°)")


@needs_frames
def test_amber_is_not_separated_and_the_header_says_so(iris_mod, gates, measured):
    """ПРИЗНАННОЕ БЕССИЛИЕ, а не забытая дыра.

    Золотое кольцо орехового глаза по пигменту то же, что светло-карая радужка,
    и метрика их не различает. Тест держит признание и факт вместе: пока хоть
    один янтарный проходит ворота, шапка обязана про это говорить. Починят
    метрику — тест покраснеет и потребует убрать оговорку; уберут оговорку, не
    починив, — покраснеет тоже.
    """
    if not measured:
        pytest.skip("ни на одном кадре радужка не замерена")
    from metrics.verdict import PASS
    passed = [c for c, img, face, _ in measured
              if iris_mod.iris(iris_mod.recolour(img, face, "янтарный"),
                               face=face, gates=gates)["state"] == PASS]
    doc = _header()
    if passed:
        assert "янтарн" in doc.lower(), (
            f"янтарная радужка проходит ворота на {passed}, а шапка про это "
            f"молчит — это уже не оговорка, а дыра")
        assert "янтарный" in iris_mod.BORDERLINE, (
            "янтарь проходит ворота, но не объявлен пограничным — самотест "
            "потребует от него провала и будет красным навсегда")
    else:
        assert "янтарный" not in iris_mod.BORDERLINE, (
            "янтарь больше не проходит ворота — оговорку из шапки и из "
            "BORDERLINE пора убирать, она стала неправдой")


# ------------------------------------------------------------- три состояния

def test_no_face_is_not_measured_not_failed(iris_mod, gates):
    """Лица нет — это незамер с причиной, а не «цвет глаз не тот»."""
    from metrics.verdict import NOT_MEASURED
    import numpy as np
    blank = np.zeros((256, 256, 3), np.uint8)
    r = iris_mod.iris(blank, face={"state": NOT_MEASURED, "note": "лица не найдено"},
                      gates=gates)
    assert r["state"] == NOT_MEASURED and r["value"] is None
    assert r["note"], "у незамера обязана быть причина"


def test_missing_106_landmarks_is_not_measured(iris_mod, gates):
    """Детектор без разметки в 106 точек радужку найти не может — и говорит это."""
    from metrics.verdict import NOT_MEASURED, PASS
    import numpy as np
    face = {"state": PASS, "kps106": None, "kps": [[0, 0], [10, 0]],
            "ipd_px": 500.0, "note": ""}
    r = iris_mod.iris(np.zeros((64, 64, 3), np.uint8), face=face, gates=gates)
    assert r["state"] == NOT_MEASURED
    assert "106" in r["note"]


@needs_frames
def test_small_face_is_not_measured_not_failed(iris_mod, gates):
    """Мелкое лицо — незамер. Кольцо радужки там в единицы пикселей.

    Кадр уменьшается нарочно: причина отказа известна заранее, и проверяется
    именно она, а не «что-нибудь не посчиталось».
    """
    import cv2
    from metrics.faces import detect
    from metrics.verdict import NOT_MEASURED
    cell, path = FRAMES[0]
    img = iris_mod.load_bgr(path)
    small = cv2.resize(img, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    face = detect(small)
    if face["state"] != "PASS":
        pytest.skip("на уменьшенном кадре лицо не нашлось — проверять нечего")
    r = iris_mod.iris(small, face=face, gates=gates)
    assert r["state"] == NOT_MEASURED, (
        f"{cell}: на лице IPD {face['ipd_px']:.0f} px метрика выдала "
        f"{r['state']} вместо отказа")
    assert "IPD" in r["note"]


@needs_frames
def test_faded_iris_is_not_measured_not_failed(iris_mod, gates, measured):
    """Обесцвеченная радужка — «не видно, какого цвета», а не «цвет не тот».

    FAIL здесь означал бы, что ночная сцена и дымка — брак персонажа.

    ОБЕСЦВЕЧИВАНИЕ ДЕЛАЕТСЯ НАСЫЩЕННОСТЬЮ КАДРА, А НЕ ПЕРЕКРАСКОЙ ПИГМЕНТА, и
    прежняя редакция путала именно это. Она звала `recolour(img, face,
    "серый")`, то есть ПЕРЕКРАШИВАЛА радужку в пигмент из таблицы — а «серый»
    там задан как (0.85, 0.88, 0.92), то есть голубоватый. Перекрашенный глаз
    сохраняет свой разброс цвета (хрома 13.6 по медиане десяти кадров против
    16.9 у нетронутых) и честно читается воротами как ГОЛУБОЙ: тон 220-266°,
    FAIL. Ворота были правы, неверен был инструмент — «не тот цвет» подавался
    под видом «цвета не видно». Нейтральный пигмент (0.90, 0.90, 0.90) дела не
    меняет: хрома 11.8, перекраска двигает медиану, но не убирает разброс.

    ЗАМЕР НА НАСТОЯЩЕМ ОБЕСЦВЕЧИВАНИИ, десять сданных кадров с измеренной
    радужкой, множитель насыщенности в HSV:

        1.00   хрома 16.9   PASS 10 из 10
        0.50   хрома  6.7   NOT_MEASURED 3
        0.30   хрома  3.3   NOT_MEASURED 10 из 10
        0.15   хрома  1.5   NOT_MEASURED 10 из 10
        0.00   хрома  0.0   NOT_MEASURED 10 из 10

    Разделение полное и порог (`iris_chroma_min` = 5.0) лежит внутри перехода,
    а не подобран по краю. Тест берёт 0.30 — первую ступень, где незамер даёт
    ВЕСЬ набор: на 0.50 ответ зависит от кадра, и такой тест мигал бы.
    """
    if not measured:
        pytest.skip("ни на одном кадре радужка не замерена")
    import cv2
    import numpy as np
    from metrics.verdict import NOT_MEASURED
    states = []
    for cell, img, face, _ in measured:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 1] *= 0.30
        faded_img = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8),
                                 cv2.COLOR_HSV2BGR)
        r = iris_mod.iris(faded_img, face=face, gates=gates)
        states.append((cell, r["state"], r["note"]))
    wrong = [s for s in states if s[1] != NOT_MEASURED]
    assert not wrong, (
        "обесцвеченный кадр получил вердикт вместо незамера: порог хромы "
        f"перестал отличать «не видно» от «не тот цвет» — {wrong}")
    for cell, _, note in states:
        assert "хрома" in note, f"{cell}: у незамера нет внятной причины: {note}"


# ------------------------------------------------ полоса откалибрована под цвет

def test_band_refuses_to_judge_a_character_of_another_eye_colour(iris_mod, gates):
    """Карточка объявляет карие глаза — метрика обязана отказаться, а не валить.

    Полоса, зашитая под одного персонажа, это не ворота системы: у второго и
    третьего персонажей репозитория глаза карие, и та же полоса провалила бы
    каждый их кадр. Так уже было с полосой возраста.
    """
    from metrics.verdict import NOT_MEASURED
    import numpy as np
    brown = {"identity_core": "a 34-year-old woman, dark brown eyes set wide"}
    r = iris_mod.iris(np.zeros((64, 64, 3), np.uint8), gates=gates, char=brown)
    assert r["state"] == NOT_MEASURED
    assert str(gates["iris_expect"]) in r["note"], (
        f"отказ не называет цвет, под который считалась полоса: {r['note']}")


def test_band_still_judges_the_character_it_was_calibrated_for(iris_mod, gates):
    """Обратная сторона: своей карточке метрика отказывать не должна.

    Иначе «отказ на чужом цвете» вырождается в отказ на всех, и ворота молча
    перестают работать вообще.
    """
    from metrics.verdict import NOT_MEASURED
    import numpy as np
    own = {"identity_core": f"a 51-year-old woman, {gates['iris_expect']} eyes"}
    r = iris_mod.iris(np.zeros((64, 64, 3), np.uint8), gates=gates, char=own)
    assert r["state"] == NOT_MEASURED, "на пустом кадре лица нет — тут иначе никак"
    assert str(gates["iris_expect"]) not in r["note"], (
        "метрика отказала своему же персонажу: проверка объявленного цвета "
        f"срабатывает не на том — {r['note']}")


# ----------------------------------------------- пороги и договор с раннером

@pytest.mark.parametrize("key", IRIS_KEYS)
def test_thresholds_live_in_the_manifest(key):
    """Порог, которого нет в манифесте, живёт в коде — и правится не там.

    Единственный тест файла, который НЕ пропускается при пустом манифесте: он
    и есть сообщение «ворота ещё не подключены». Остальные без порогов
    проверять нечего, и они честно пропускаются.
    """
    assert key in MANIFEST["gates"], (
        f"в манифесте нет gates.{key} — ворота радужки не подключены; "
        f"значения и пояснение к ним перечислены в integration метрики")


@pytest.mark.parametrize("key", ["iris_hue_max",
                                 "iris_chroma_min", "iris_min_ipd_px"])
def test_thresholds_have_no_hidden_default_in_the_code(key):
    """Запасное значение у порога — это второй, невидимый порог.

    Манифест правят, метрика продолжает считать по числу из кода, и разойтись
    они могут только молча. Ровно так шапка `skin.py` разошлась с
    `face_sharp_min`.
    """
    src = _source()
    assert f'g.get("{key}"' not in src and f"g.get('{key}'" not in src, (
        f"{key} читается с запасным значением — порог обязан браться из "
        f"манифеста без подстраховки, а отсутствие ключа обязано падать вслух")
    assert f'g["{key}"]' in src, f"{key} вообще не читается из манифеста"


@needs_manifest
def test_iris_min_ipd_is_stricter_than_the_shared_floor():
    """У радужки свой пол по крупности, и он выше общего.

    `min_face_ipd_px` заведён под резкость и кожу — под структуры размером с
    лицо. Радужка на порядок мельче, и общий порог для неё означал бы замер по
    единицам пикселей, в которые затекает и белок, и зрачок.
    """
    g = MANIFEST["gates"]
    assert float(g["iris_min_ipd_px"]) > float(g["min_face_ipd_px"]), (
        "пол по крупности у радужки не строже общего — значит, он не про "
        "радужку")


@needs_manifest
def test_band_is_a_band_and_the_upper_edge_is_the_calibrated_one():
    """Полоса обязана быть полосой: нижняя граница, ЕСЛИ ОНА ЕСТЬ, ниже верхней."""
    g = MANIFEST["gates"]
    if g.get("iris_hue_min") is not None:
        assert float(g["iris_hue_min"]) < float(g["iris_hue_max"])


def test_lower_bound_is_absent_on_purpose_and_never_defaults(iris_mod):
    """Нижней границы тона нет — и её отсутствие не подменяется числом.

    Это НЕ ослабление договора «порог живёт в манифесте», а его вторая
    половина. Первая: ключ, который метрика читает, обязан лежать в манифесте
    без запасного значения в коде. Вторая: ключ, который решено НЕ заводить,
    обязан отсутствовать честно — то есть ворота становятся односторонними, а
    не берут число из воздуха. Иначе удаление порога из манифеста тихо включало
    бы дефолт, и «границы нет» означало бы «граница есть, но невидимая».

    Почему её нет — в шапке метрики: перекрашенный в карий кадр даёт тон ВЫШЕ
    настоящего (85.9 против 85.2), классы перекрыты, и разделить их углом тона
    нельзя ни при каком значении.
    """
    src = _source()
    assert 'g.get("iris_hue_min",' not in src and \
           "g.get('iris_hue_min'," not in src, (
        "у iris_hue_min появилось запасное значение — отсутствующий порог "
        "обязан выключать нижнюю границу, а не подставлять число")
    assert "iris_hue_min" not in MANIFEST["gates"], (
        "iris_hue_min вернулся в манифест — если это осознанно, перепишите "
        "шапку метрики: там сказано, что зазора снизу нет и не будет")


def test_one_sided_band_still_refuses_a_blue_iris_and_says_nothing_about_brown(
        iris_mod, gates):
    """Односторонние ворота обязаны остаться воротами, а не отключиться.

    Проверяется на самом вердикте, а не на исходнике: без нижней границы
    голубая радужка обязана падать по верхней, а формулировка «ниже полосы —
    это карий» обязана исчезнуть совсем. Пока она печаталась при lo = None,
    отчёт объяснял бы провал причиной, которой ворота не проверяют.
    """
    hi = float(gates["iris_hue_max"])
    src = _source()
    # Ветка «тон ниже полосы — это карий» обязана быть закрыта проверкой на
    # существование нижней границы. Сравнение hue < lo при lo = None в Python 3
    # бросает TypeError — то есть без охраны метрика не соврала бы, а упала бы
    # на каждом кадре; охрана проверяется дословно, потому что это и есть
    # договор, а не оформление.
    assert "lo is not None and hue < lo" in src, (
        "пропала охрана нижней границы: вердикт снова сравнивает тон с "
        "отсутствующим порогом")
    # ГРАНИЦЫ ЗДЕСЬ ШИРОКИЕ НАМЕРЕННО. Точный зазор зависит от МАТЕРИАЛА, а не
    # от кода: на пуле, снятом текстом, он был (85.2, 197.7), на пуле,
    # переснятом эдитом с референса, — (163.4, 234.8). Оба замеряет самотест
    # metrics/iris.py, и он же краснеет, когда порог из зазора вышел; жёсткое
    # число здесь дублировало бы эту проверку и устаревало бы при каждой смене
    # источника кадров. Проверяется одно: порог остался порогом — выше тёплого
    # края любого правдоподобного зазора и ниже голубого.
    assert 120.0 < hi < 260.0, (
        f"iris_hue_max {hi} за пределами правдоподобного: тёплая радужка "
        f"кончается около 160-200°, голубая начинается около 235-260°")


def test_measure_is_a_synonym_that_keeps_the_state_field(iris_mod, gates):
    """`gates.py` ищет метрику по списку имён и берёт ПЕРВОЕ подходящее.

    Обёртка, отдающая голые числа, лишила бы результат поля `state`, и раннер
    объявил бы живую метрику незамером — молча и на всём наборе, из-за одной
    перестановки строк в чужом файле.
    """
    import numpy as np
    r = iris_mod.measure(np.zeros((64, 64, 3), np.uint8), gates=gates,
                         face={"state": "NOT_MEASURED", "note": "лица нет"})
    assert isinstance(r, dict) and "state" in r and r["gate"] == "iris"


def test_metric_accepts_the_keywords_the_runner_passes(iris_mod):
    """Раннер отбирает аргументы по именам параметров функции.

    Переименуй здесь `face` в `face_data` — и ворота начнут искать лицо заново
    на каждом кадре, а на кадре с прохожим найдут не то. Молча.

    `char` в том же списке: раннер кладёт карточку персонажа в ctx под этим
    именем, и ровно ей метрика отказывается судить чужой объявленный цвет
    глаз. Переименуй параметр — и проверка цвета отключится, не сказав ни
    слова: несовпавшее имя раннер просто не передаёт.
    """
    import inspect
    for fn in (iris_mod.iris, iris_mod.measure):
        params = set(inspect.signature(fn).parameters)
        assert {"face", "gates", "char"} <= params, (
            f"{fn.__name__} не принимает face/gates/char — раннер их не передаст")


def test_scale_is_defined_in_pupil_distance(iris_mod):
    """Кольцо радужки задано в долях IPD, а не в пикселях.

    В пикселях «кольцо радужки» означало бы разное на портрете и на ростовом
    плане, и метрика мерила бы крупность плана. Так же сделано в sharpness.py и
    skin.py, и по той же причине.
    """
    assert 0 < iris_mod.RING_IN < iris_mod.RING_OUT < iris_mod.SCLERA_IN
    src = _source().lower()
    assert "межзрачков" in src or "ipd" in src
