"""Ворота качества: три состояния и метрика, которая действительно ловит монохром.

  py -3 -m pytest tests/test_gates.py -q

Два дефекта, найденных ревью, живут именно здесь.

ПЕРВЫЙ. Ворота цвета мерили среднюю и 90-й перцентиль хромы C* в LAB. Это
метрика НАСЫЩЕННОСТИ, а не монохромности: сепия — это яркость, умноженная на
один фиксированный цвет, её хрома не ниже, чем у цветного оригинала. Замер на
всех настоящих кадрах (45 штук) ниже подтверждает худшее: у сепийной копии C*
составляет 0.82-1.80 от оригинальной по средней и 0.86-1.49 по p90, то есть на
большинстве кадров сепия ПЕРЕБИВАЕТ оригинал по силе цвета. Любой порог по C*,
пропускающий живой кадр, пропускает и его сепийную копию — а на P1 старая пара
(12 / 22) вообще отбраковывала оригинал (11.13 / 19.67) и пропускала сепию
(14.85 / 25.83). Ч/б и монохром бриф запрещает прямым текстом; ловит их разброс
ТОНА, а не его сила.

ВТОРОЙ. Ворота, которые при отсутствии зависимости молча выключаются, дают
ложный PASS: кадр «прошёл» ровно потому, что его никто не померил. Состояний
должно быть три, и незамер обязательных ворот обязан блокировать отгрузку.

Тесты правил вердикта нарочно не зависят от numpy и OpenCV — эти правила чистая
логика, и проверяться они обязаны там, где тяжёлых зависимостей нет вообще
(CI ставит только pytest). Метрика цвета без OpenCV не считается, поэтому её
тесты честно пропускаются, а не притворяются пройденными.
"""
import glob
import importlib.util
import os

import pytest

from conftest import MANIFEST, ROOT, work_root

METRICS_DIR = os.path.join(ROOT, "scripts", "metrics")


def _load_by_path(name, path):
    """Загрузить модуль файлом, минуя пакет.

    `import metrics.verdict` тянет scripts/metrics/__init__.py, а тот — numpy и
    OpenCV. Правила вердикта к ним отношения не имеют и должны проверяться на
    голой стандартной библиотеке, иначе самая важная проверка набора отваливается
    ровно там, где нет тяжёлых колёс.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def effective_thresholds():
    """Пороги в том виде, в каком их видят ворота.

    Числа живут в манифесте, но часть из них может держаться умолчаниями самих
    ворот: когда метрика заменена, старый порог в новой шкале означал бы не то
    же самое, а произвольное число, и его честнее не переносить. Проверять надо
    то, что реально применяется, а не одну из двух половин; манифест сильнее.
    """
    thr = {k: v for k, v in MANIFEST["gates"].items()
           if not k.startswith("_") and isinstance(v, (int, float))}
    try:
        import gates as gates_module
    except Exception:
        return thr                      # ворота ещё не написаны или сломаны
    src = getattr(gates_module, "thresholds", None)
    out = dict(src() if callable(src) else getattr(gates_module, "DEFAULTS", {}))
    out.update(thr)
    return out


def test_colour_gate_measures_hue_dispersion_not_saturation():
    """Порог цвета обязан говорить про РАЗБРОС ТОНА, а не про его силу.

    Пороги вида chroma_mean_min / chroma_p90_min сепию не отсекают в принципе:
    по замеру на всех настоящих кадрах её C* составляет 0.82-1.80 от C*
    оригинала, то есть попадает в ту же полосу значений. Порог, пропускающий
    живой кадр, пропустит и сепийный. Метрика обязана быть другой по смыслу.
    """
    thr = effective_thresholds()
    families = ("entropy", "dispersion", "colourful", "colorful")
    hue = [k for k in thr if any(f in k for f in families)]
    assert hue, (f"ворота цвета описаны только насыщенностью: {sorted(thr)} — "
                 "сепия такие пороги проходит")


def test_sharpness_gate_is_normalised_to_the_face():
    """Один порог резкости на весь кадр не значит ничего.

    Дисперсию лапласиана по кадру ведёт фактура, а не фокус: уличный кадр с
    асфальтом и известняком даёт 248 против 148 у безупречно резкого портрета,
    и мягкое лицо проходит за счёт ткани. Резкость меряется на кропе лица.
    """
    thr = effective_thresholds()
    face = [k for k in thr if "face" in k and "sharp" in k]
    assert face, f"порог резкости не привязан к лицу: {sorted(thr)}"


def test_skin_gate_scale_is_defined_in_pupil_distance():
    """Масштаб детектора микрорельефа — в межзрачковых расстояниях.

    Иначе «доля кожи без микрорельефа» меряет крупность плана: на поясном
    портрете поры физически меньше пикселя, и метрика падает сама собой.
    """
    mods = glob.glob(os.path.join(METRICS_DIR, "skin*.py"))
    if not mods:
        pytest.skip("метрика кожи ещё не написана")
    for path in mods:
        with open(path, encoding="utf-8") as fh:
            src = fh.read().lower()
        assert any(k in src for k in ("межзрачков", "ipd", "pupil")), \
            f"{os.path.basename(path)}: масштаб детектора не задан в единицах IPD"


def test_required_gates_are_declared():
    """Список обязательных ворот обязан существовать и не быть пустым.

    Пустой список означает «блокировать нечем»: любой незамер становится
    безобидным, и вердикт снова перестаёт отличать проверенный кадр от
    непроверенного. Решение о том, что кадр можно отгружать без метрики,
    должно быть записано явно — вычёркиванием имени из этого списка.
    """
    req = MANIFEST["gates"].get("required")
    assert isinstance(req, list) and req, "gates.required пуст или не объявлен"
    assert len(set(req)) == len(req), req


# ------------------------------------------------------------------ вердикт

VERDICT_PY = os.path.join(METRICS_DIR, "verdict.py")
verdict_mod = pytest.mark.skipif(not os.path.exists(VERDICT_PY),
                                 reason="сборка вердикта ещё не написана")


@pytest.fixture(scope="module")
def V():
    return _load_by_path("persona_verdict", VERDICT_PY)


@verdict_mod
def test_all_measured_and_in_range_ships(V):
    gates = {"chroma": V.gate("chroma", 0.47, lo=0.34),
             "identity": V.gate("identity", 0.81, lo=0.75)}
    res = V.verdict(gates, required=["chroma", "identity"])
    assert res["verdict"] == V.PASS and res["ships"]


@verdict_mod
def test_measured_failure_blocks(V):
    gates = {"chroma": V.gate("chroma", 0.10, lo=0.34),
             "identity": V.gate("identity", 0.81, lo=0.75)}
    res = V.verdict(gates, required=["chroma", "identity"])
    assert res["verdict"] == V.FAIL and not res["ships"]
    assert res["failed"] == ["chroma"]


@verdict_mod
def test_unmeasured_required_gate_does_not_ship(V):
    """Главное правило: НЕ ИЗМЕРЕНО среди обязательных — кадр не едет.

    Раньше метрика без зависимости выключалась молча и вердикт считался «по
    остальным»: кадр, у которого не мерили ни идентичность, ни возраст, выходил
    с тем же зелёным PASS, что и полностью проверенный, и отличить их было
    нечем.
    """
    gates = {"chroma": V.gate("chroma", 0.47, lo=0.34),
             "identity": V.not_measured("identity", "insightface недоступен")}
    res = V.verdict(gates, required=["chroma", "identity"])
    assert res["verdict"] == V.NOT_MEASURED
    assert not res["ships"], "непромеренный кадр отгружается как проверенный"
    assert res["missing"] == ["identity"]


@verdict_mod
def test_missing_required_gate_is_not_a_pass(V):
    """Ворот просто нет в отчёте — это тоже незамер, а не «нечего проверять»."""
    res = V.verdict({"chroma": V.gate("chroma", 0.47, lo=0.34)},
                    required=["chroma", "identity"])
    assert res["verdict"] == V.NOT_MEASURED and not res["ships"]


@verdict_mod
def test_unmeasured_optional_gate_still_ships(V):
    """Детектор без ключа в окружении — штатная деградация, а не блокировка."""
    gates = {"chroma": V.gate("chroma", 0.47, lo=0.34),
             "detector": V.not_measured("detector", "нет ключа")}
    res = V.verdict(gates, required=["chroma"])
    assert res["verdict"] == V.PASS and res["ships"]
    assert res["unmeasured_optional"] == ["detector"]


# ------------------------------------------------------- калибровка цвета

def _sample_frames():
    """По одному настоящему кадру на ячейку: P5 (свечи) обязан быть в выборке."""
    out = {}
    for path in sorted(glob.glob(os.path.join(work_root(), "*", "frames",
                                              "*", "*.png"))):
        out.setdefault(os.path.basename(os.path.dirname(path)), path)
    return sorted(out.items())


FRAMES = _sample_frames() if os.path.isdir(work_root()) else []


@pytest.fixture(scope="module")
def chroma_mod():
    pytest.importorskip("cv2", reason="ворота цвета считаются OpenCV")
    pytest.importorskip("numpy")
    if not os.path.exists(os.path.join(METRICS_DIR, "chroma.py")):
        pytest.skip("метрика цвета ещё не написана")
    import metrics.chroma as mod
    return mod


needs_frames = pytest.mark.skipif(not FRAMES, reason="настоящих кадров нет")


@needs_frames
@pytest.mark.parametrize("cell,path", FRAMES, ids=[c for c, _ in FRAMES])
def test_sepia_and_grayscale_lose_to_the_real_frame(chroma_mod, cell, path):
    """Сепия и ч/б обязаны падать, живой кадр — проходить.

    Замер (все 45 кадров на диске, подготовка модуля — 256 px + медиана 5×5):
      оригиналы   энтропия тона 0.407-0.721, колорфулность 23.9-42.5
      сепия       энтропия тона 0.000-0.015, колорфулность 23.1-31.9
      ч/б         энтропия тона 0.000,       колорфулность 0.0
    Сепия валится ТОЛЬКО по разбросу тона: по силе цвета она неотличима от
    оригинала и местами выше него — ровно поэтому старые ворота её пропускали.
    Тёмный кадр при свечах (P5) даёт 0.458 / 38.9, то есть темнота метрике не
    мешает и «атмосферный» кадр не наказан.
    """
    m = chroma_mod
    img = m.load_bgr(path)
    ent_o = m.hue_entropy(m._prepared(img))[0]
    ent_s = m.hue_entropy(m._prepared(m._sepia(img)))[0]
    col_o = m.colourfulness(m._prepared(img))
    col_g = m.colourfulness(m._prepared(m._gray(img)))

    assert ent_s < ent_o / 2, f"{cell}: сепия неотличима по тону ({ent_s:.3f})"
    assert col_g < col_o / 2, f"{cell}: ч/б неотличимо по цвету ({col_g:.2f})"

    # Порогов у ворот цвета два, и проверять надо оба: разброс тона валит
    # сепию, но ч/б он тоже валит «за компанию», а колорфулность — единственное,
    # что отделяет обесцвеченный кадр от живого по силе цвета.
    thr = effective_thresholds()
    ent_min = thr.get("hue_entropy_min")
    if ent_min is not None:
        assert ent_s < ent_min <= ent_o, (
            f"{cell}: порог {ent_min} не разделяет — сепия {ent_s:.3f}, "
            f"оригинал {ent_o:.3f}")
    col_min = thr.get("colourfulness_min")
    if col_min is not None:
        assert col_g < col_min <= col_o, (
            f"{cell}: порог {col_min} не разделяет — ч/б {col_g:.2f}, "
            f"оригинал {col_o:.2f}")


@needs_frames
@pytest.mark.parametrize("cell,path", FRAMES, ids=[c for c, _ in FRAMES])
def test_old_saturation_gate_cannot_tell_sepia_from_the_original(chroma_mod,
                                                                 cell, path):
    """Доказательство от противного: по хроме сепия и живой кадр — одно и то же.

    Тест держит найденный факт под замком. Если ворота цвета когда-нибудь
    вернутся к средней и перцентилю хромы, этот замер объяснит, почему сепия
    снова поедет в сдачу.

    Сравниваются копия и оригинал, а не копия и константа: конкретные 12 и 22
    были подобраны под старый набор кадров и на новых уже ничего не значат (у
    оригинала P1 средняя C* = 11.13 при пороге 12 — старые ворота отбраковали
    бы полноцветный кадр и пропустили его сепию с 14.85). Инвариант же держится
    на всех кадрах: измеренное отношение сепия/оригинал — 0.82-1.80 по средней
    и 0.86-1.49 по p90.
    """
    m = chroma_mod
    img = m.load_bgr(path)
    _e_o, _c_o, mean_o, p90_o = m.hue_entropy(m._prepared(img))
    _e_s, _c_s, mean_s, p90_s = m.hue_entropy(m._prepared(m._sepia(img)))
    assert mean_s >= 0.75 * mean_o, \
        f"{cell}: средняя C* сепии {mean_s:.2f} против {mean_o:.2f} у оригинала"
    assert p90_s >= 0.75 * p90_o, \
        f"{cell}: p90 C* сепии {p90_s:.2f} против {p90_o:.2f} у оригинала"
