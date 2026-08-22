"""Раунд 6: шапка метрики кожи и итог её самотеста.

  py -3 -m pytest -q tests/test_round6_skin.py

Обе находки — про одно и то же: про замер, положенный прозой рядом с кодом,
который этот замер меняет.

F3. В шапке `scripts/metrics/skin.py` стояла таблица «оригиналы / Gauss /
билатеральный фильтр» по двум поколениям кадров и полоса ворот резкости. Кадры
на диске говорили другое (доля стёртой кожи у оригиналов оказалась нулевой на
всех замеренных кадрах), а полоса резкости осталась от калибровки, которую
манифест давно отменил. Проза при этом читалась как обоснование порогов.

F4. Итогом самотеста печаталась зашитая строка «билатеральный фильтр проходит
ворота резкости и падает на коже». Таблица прямо над ней показывала обратное —
резкость валила аэрограф на большинстве копий, — а самотест всё равно выходил
нулём. Вывод, который не может оказаться ложным, не проверяет ничего.

Поэтому здесь проверяется поведение, а не намерение: что в шапке нет чисел,
что пороги берутся из манифеста без запасных значений в коде и что итог
самотеста МЕНЯЕТСЯ вместе с таблицей и ведёт код возврата.
"""
import ast
import re
import sys
import types

import pytest

from conftest import MANIFEST

import metrics
from metrics import skin as skin_mod
from metrics.verdict import FAIL, PASS


def _header():
    """Докстринг модуля — из исходника, а не из __doc__: под -OO его нет."""
    with open(skin_mod.__file__, encoding="utf-8") as fh:
        return ast.get_docstring(ast.parse(fh.read())) or ""


# ------------------------------------------------------------------ F3, шапка

def test_header_carries_no_numbers_at_all():
    """В шапке не должно остаться ни одного числа.

    Не «правильные вместо неправильных»: правильные протухают ровно так же —
    именно это и произошло трижды подряд. Единственная цифра, которой в шапке
    место, — имя команды в блоке запуска.
    """
    rest = [ln for ln in _header().splitlines() if "py -3" not in ln]
    numbered = [ln.strip() for ln in rest if re.search(r"\d", ln)]
    assert not numbered, ("числа вернулись в шапку skin.py — их печатает "
                          f"самотест, а не проза: {numbered}")


def test_header_sends_the_reader_to_the_selftest():
    """Раз чисел нет, шапка обязана сказать, чем их получить."""
    doc = _header()
    assert "py -3 scripts/metrics/skin.py" in doc
    assert "gates.skin_relief_floor" in doc, "шапка не называет ключ манифеста"


# --------------------------------------------------- пороги только из манифеста

@pytest.mark.parametrize("key", ["skin_smooth_max", "skin_relief_floor",
                                 "min_face_ipd_px"])
def test_thresholds_have_no_hidden_default_in_the_code(key):
    """Запасное значение у порога — это второй, невидимый порог.

    `g.get("skin_relief_floor", 0.004)` продолжает считать по числу из кода
    после того, как манифест поправили, и разойтись они могут только молча.
    Отсутствие ключа обязано быть слышно: раннер ворот ловит исключение
    метрики и пишет в вердикт NOT_MEASURED с причиной.
    """
    gates = {k: v for k, v in MANIFEST["gates"].items() if k != key}
    with pytest.raises(KeyError):
        # Файла нет намеренно: пороги читаются раньше кадра, до диска дело не
        # дойдёт — а если дойдёт, значит порог взят не из манифеста.
        skin_mod.skin("кадра-нет.png", face=None, gates=gates)


# ------------------------------------------------- F4, итог считается по таблице

ORIG = "кадр"
GAUSS = "кадр|gauss"
BILAT1 = "кадр|bilat"
BILAT2 = "кадр|bilat|bilat"

# Раздел труда держится: аэрограф ворота резкости проходит и падает только на
# коже, мыло — наоборот. Ровно то, чем обоснованы отдельные ворота кожи.
SPLIT_HOLDS = {ORIG: (PASS, PASS), GAUSS: (PASS, FAIL),
               BILAT1: (FAIL, PASS), BILAT2: (FAIL, PASS)}

# Та же таблица, но резкость валит и аэрограф — состояние кадров на диске
# после того, как face_sharp_min подняли. Ожидания по ВАРИАНТАМ здесь не
# нарушены ни разу (оригинал проходит, мыло падает хоть где-то, аэрограф
# падает на коже), поэтому красным самотест может стать только из-за итога.
SPLIT_BROKEN = {ORIG: (PASS, PASS), GAUSS: (PASS, FAIL),
                BILAT1: (FAIL, FAIL), BILAT2: (FAIL, FAIL)}


def _selftest(monkeypatch, capsys, states):
    """Прогнать main() на подставном кадре. Возвращает (код возврата, вывод).

    Подменяется всё, что стоит между таблицей и диском: замер кожи, ворота
    резкости, детектор лиц и фильтры cv2. Смысл в этом и есть — итог обязан
    выводиться ИЗ СОСТОЯНИЙ, попавших в таблицу, поэтому состояния задаются
    здесь напрямую, а кадр не нужен вовсе. Заодно тест не читает кадры с
    диска и не поднимает buffalo_l: сьют обязан быть зелёным и там, где
    рабочей папки нет.
    """
    def result(name, state, value):
        return {"gate": name, "state": state, "value": value, "min": None,
                "max": None, "note": "", "relief_median": 0.02, "patches": 3,
                "ipd_px": 200.0}

    monkeypatch.setattr(skin_mod, "cv2", types.SimpleNamespace(
        GaussianBlur=lambda src, ksize, sigma: src + "|gauss",
        bilateralFilter=lambda src, d, sc, ss: src + "|bilat"))
    monkeypatch.setattr(skin_mod, "load_bgr", lambda path: ORIG)
    monkeypatch.setattr(skin_mod, "_frames", lambda argv: ["кадр.png"])
    monkeypatch.setattr(skin_mod, "skin", lambda src, face=None, gates=None:
                        result("skin", states[src][0], 0.5))

    faces = types.ModuleType("metrics.faces")
    faces.detect = lambda img: {"state": PASS, "ipd_px": 200.0, "note": ""}
    sharp = types.ModuleType("metrics.sharpness")
    sharp.sharpness = lambda src, face=None, gates=None: \
        result("sharp", states[src][1], 150.0)
    for name, mod in (("metrics.faces", faces), ("metrics.sharpness", sharp)):
        monkeypatch.setitem(sys.modules, name, mod)
        monkeypatch.setattr(metrics, name.split(".")[1], mod, raising=False)

    with pytest.raises(SystemExit) as exc:
        skin_mod.main()
    return exc.value.code, capsys.readouterr().out


def _conclusion(out):
    """Только итог: таблица меняется вместе с данными и сама по себе ничего
    не доказывает, а строка «РАСХОЖДЕНИЙ» — это уже код возврата."""
    assert "раздел труда" in out, f"итог из вывода исчез:\n{out}"
    return out.split("раздел труда")[-1].split("РАСХОЖДЕНИЙ")[0]


def test_selftest_is_green_when_the_split_holds(monkeypatch, capsys):
    code, out = _selftest(monkeypatch, capsys, SPLIT_HOLDS)
    assert code == 0, out
    assert "сходится" in _conclusion(out), out


def test_selftest_goes_red_when_sharpness_catches_the_airbrush(monkeypatch, capsys):
    """Ворота кожи стоят отдельно ровно потому, что резкость аэрограф
    пропускает. Если это перестало быть правдой, самотест обязан сказать это
    и вернуть ненулевой код, а не печатать обратное с кодом ноль."""
    code, out = _selftest(monkeypatch, capsys, SPLIT_BROKEN)
    assert "← ОЖИДАЛОСЬ" not in out, ("ожидания по вариантам не нарушены — "
                                      f"красным обязан сделать итог:\n{out}")
    assert code != 0, out
    assert "НЕ ДЕРЖИТСЯ" in _conclusion(out), out


def test_conclusion_changes_with_the_table(monkeypatch, capsys):
    """Итог обязан меняться вместе с данными.

    Зашитая строка печаталась одна и та же при любой таблице — в том числе при
    той, что говорила обратное.
    """
    _, holds = _selftest(monkeypatch, capsys, SPLIT_HOLDS)
    _, broken = _selftest(monkeypatch, capsys, SPLIT_BROKEN)
    assert _conclusion(holds) != _conclusion(broken), \
        f"итог не зависит от таблицы:\n{_conclusion(holds)}"


def test_selftest_prints_the_thresholds_from_the_manifest(monkeypatch, capsys):
    """Числа, по которым читается таблица, печатает скрипт из манифеста.

    Полоса резкости в том числе: ворота чужие, но колонка их состояния стоит в
    этой таблице, и именно эта полоса в шапке разошлась с манифестом.
    """
    _, out = _selftest(monkeypatch, capsys, SPLIT_HOLDS)
    head = out.splitlines()[0] + "\n" + out.splitlines()[1]
    for key in ("skin_relief_floor", "skin_smooth_max", "face_sharp_min",
                "face_sharp_max", "min_face_ipd_px"):
        assert str(MANIFEST["gates"][key]) in head, \
            f"{key} не напечатан из манифеста:\n{head}"


# ---------------------------------------------------------- счётчики раздела труда

def test_labour_split_counts_the_rows_it_was_given():
    """Счётчики итога — это пересчёт строк таблицы, и ничего кроме."""
    rows = [(skin_mod.AIRBRUSH, FAIL, PASS), (skin_mod.AIRBRUSH, FAIL, PASS),
            (skin_mod.AIRBRUSH, FAIL, FAIL), (skin_mod.BLUR, PASS, FAIL)]
    text, ok = skin_mod.labour_split(rows)
    assert ok, text
    assert "резкость пропускает 2, валит 1" in text, text
    assert "кожа пропускает 1, валит 0" in text, text


def test_labour_split_calls_a_hole_a_hole():
    """Испорченная копия, прошедшая обе метрики, — провал в любом случае.

    ТАБЛИЦА ПОДОБРАНА ТАК, ЧТО ПРОВАЛИТЬ ЕЁ МОЖЕТ ТОЛЬКО ПРОВЕРКА НА ДЫРУ.
    Прежняя редакция подавала [(AIRBRUSH, PASS, PASS)] — там заодно рушится
    и раздел труда (аэрографов мимо резкости ноль), поэтому тест оставался
    зелёным, даже если проверку на дыру выключить: проверяющий раунда 6
    показал это мутацией `if dead: ok = ok`. Здесь раздел труда заведомо
    держится (два аэрографа мимо резкости против нуля пойманных), мыло
    ловится кожей, и единственная причина сказать «не сходится» — мыло,
    прошедшее обе метрики.
    """
    rows = [(skin_mod.AIRBRUSH, FAIL, PASS), (skin_mod.AIRBRUSH, FAIL, PASS),
            (skin_mod.BLUR, FAIL, FAIL), (skin_mod.BLUR, PASS, PASS)]
    text, ok = skin_mod.labour_split(rows)
    assert not ok, text
    assert "ДЫРА" in text, text
    assert "РАЗДЕЛ ТРУДА НЕ ДЕРЖИТСЯ" not in text, (
        "таблица валится не только на дыре — тест снова проверяет не то")


def test_labour_split_refuses_an_empty_table():
    """Пустая таблица — это не «всё сошлось»: сходиться было нечему."""
    text, ok = skin_mod.labour_split([])
    assert not ok
    assert "не по чему" in text, text
