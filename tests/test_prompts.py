"""Сборщик промптов: дедуп и центральное обещание проекта.

  py -3 -m pytest tests/test_prompts.py -q

Здесь два разных предмета. Первый — дедупликация в _clean: она однажды съела
осмысленный кусок промпта, потому что сравнивала подстроки без границ слов.
Второй — то, ради чего скилл вообще написан: описание лица и маркеры возраста
обязаны попадать в КАЖДЫЙ промпт дословно. Второе не проверяла ни одна строка
кода, при том что вся идентичность персонажа держится именно на этом.
"""
import pytest

from conftest import PROJECTS, cell_params, chunks
from prompts import _clean, build_casting, build_cell


def test_clean_keeps_short_word_swallowed_by_longer_phrase():
    """«low» не должно исчезать из-за букв l-o-w внутри «fuller lower lip».

    Ровно это и случилось: блок идентичности стоит в каждом промпте, поэтому
    высота камеры в P4 пропадала всегда и незаметно — кадр снимался не с пола.
    """
    out = _clean(["thin upper lip and fuller lower lip", "low"])
    assert "low" in chunks(out), out


def test_clean_drops_only_exact_repeat_of_one_word():
    """Однословный кусок выбрасывается лишь при точном совпадении."""
    assert chunks(_clean(["low", "low"])) == ["low"]
    assert chunks(_clean(["low", "lower"])) == ["low", "lower"]


def test_clean_collapses_contained_requirement():
    """«a half-smile» и «a half-smile rather than a full one» — одно требование.

    Дубль при cfg=1.0 это удвоенный вес: кадр уезжает в подчёркнутую фактуру.
    Побеждает ранний кусок — порядок блоков в промпте осмыслен.
    """
    assert chunks(_clean(["a half-smile",
                          "a half-smile rather than a full one"])) \
        == ["a half-smile"]
    assert chunks(_clean(["a half-smile rather than a full one",
                          "a half-smile"])) \
        == ["a half-smile rather than a full one"]


def test_clean_drops_empty_and_blank_parts():
    """Пустой блок не должен превращаться в задвоенную запятую."""
    assert _clean(["", None, "  ", "silk blouse", ",,"]) == "silk blouse"


@pytest.mark.parametrize("char,cell", cell_params())
def test_prompt_carries_identity_core_verbatim(char, cell):
    """Описание лица — ДОСЛОВНО, посимвольно, в каждом кадре.

    Не «похоже по смыслу»: синоним в шестом промпте и есть тот способ, которым
    лицо уезжает. Если дедуп или новый блок съест кусок identity_core, тест
    покажет это раньше, чем сорок минут GPU.
    """
    assert char["identity_core"] in build_cell(char, cell)


@pytest.mark.parametrize("char,cell", cell_params())
def test_prompt_carries_age_markers_verbatim(char, cell):
    """Маркеры возраста — там же и на тех же правах.

    Числу «51» модель не верит, мелким морщинам и коже шеи верит. Потеря этого
    блока = самый частый автопровал задачи, и внешне промпт выглядит целым.
    """
    assert char["age_markers"] in build_cell(char, cell)


@pytest.mark.parametrize("char,cell", cell_params())
def test_prompt_has_no_duplicated_requirement(char, cell):
    """Ни один кусок промпта не повторяется — инвариант _clean."""
    lowered = [c.lower() for c in chunks(build_cell(char, cell))]
    assert len(set(lowered)) == len(lowered), "точный повтор требования"


@pytest.mark.parametrize("char,cell", cell_params())
def test_camera_single_word_survives(char, cell):
    """Однословные куски поля camera доезжают до промпта.

    Именно так выглядел дефект «low»: поле ячейки заполнено, а в промпте его
    нет. Проверять весь промпт целиком нельзя — дедуп имеет право убирать
    повторы; куски поля camera уникальны по построению.
    """
    prompt = chunks(build_cell(char, cell))
    for c in chunks(cell.get("camera", "")):
        if len(c.split()) == 1:
            assert c in prompt, f"{c!r} пропало из промпта"


def test_casting_prompts_carry_identity_blocks():
    """Кастинг меняет только свет и ракурс — человек описан теми же словами."""
    chars = {pdir: char for pdir, char, _spath, _shots in PROJECTS}
    assert chars, "в projects/ нет ни одной карточки персонажа"
    for pdir, char in chars.items():
        for prompt in build_casting(char, 4):
            assert char["identity_core"] in prompt, pdir
            assert char["age_markers"] in prompt, pdir
