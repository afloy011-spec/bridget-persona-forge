"""Договор раскадровки с карточкой персонажа.

  py -3 -m pytest tests/test_shotlist.py -q

Раскадровка НАЗНАЧАЕТ то, что раньше угадывалось по тексту: черту характера и
наличие тела в кадре. Угадывание ставило в P4 черту guarded («её внимание в
другом месте») поверх задачи кадра — настоящей открытой улыбки, — и дописывало
«upright posture, strong legs» человеку, скрючившемуся на полу. Явное поле
лечит это, но только пока оно действительно есть в КАЖДОЙ ячейке; забыть его в
новой ячейке легко, и молчаливого отката к эвристике быть не должно.
"""
import pytest

from conftest import cell_params, shotlist_params
from prompts import build_cell


@pytest.mark.parametrize("char,cell", cell_params())
def test_cell_declares_trait_explicitly(char, cell):
    """Поле trait обязано быть в ячейке — «none» это тоже осознанный ответ."""
    assert "trait" in cell, "черта не назначена; допустимо и \"none\""


@pytest.mark.parametrize("char,cell", cell_params())
def test_cell_declares_body_in_frame_explicitly(char, cell):
    """body_in_frame решает ячейка, а не подстрока «seated» в кадрировке."""
    assert "body_in_frame" in cell
    assert isinstance(cell["body_in_frame"], bool)


@pytest.mark.parametrize("char,cell", cell_params())
def test_cell_trait_is_described_in_character(char, cell):
    """Черта ячейки должна существовать в карточке, иначе промпт её потеряет."""
    known = {k for k in char.get("personality_in_frame", {})
             if not k.startswith("_")}
    assert cell["trait"] == "none" or cell["trait"] in known


@pytest.mark.parametrize("char,cell", cell_params())
def test_build_body_block_follows_the_flag(char, cell):
    """Блок сложения попадает в промпт ровно тогда, когда объявлено тело."""
    prompt = build_cell(char, cell)
    assert (char["build"] in prompt) is bool(cell["body_in_frame"])


def test_unknown_trait_raises():
    """Опечатка в trait обязана падать, а не молча давать промпт без черты.

    Промпт без черты выглядит нормальным: кадр просто теряет поведение, и
    заметно это становится через сорок минут генерации.
    """
    char = {"personality_in_frame": {"independent": "…"}}
    with pytest.raises(KeyError):
        build_cell(char, {"id": "X1", "trait": "independant"})


def test_missing_trait_raises():
    """Отсутствие поля — ошибка данных, а не повод угадать черту по gaze."""
    char = {"personality_in_frame": {"independent": "…"}}
    with pytest.raises(KeyError):
        build_cell(char, {"id": "X1"})


def test_trait_none_is_accepted():
    """«none» — легальный отказ от черты (в P4 её задаёт сам gaze).

    ТРИГГЕР ПЕРСОНАЖНОЙ ЛОРЫ ИЗ ПРОМПТА ВЫЧИТАЕТСЯ, А НЕ ИГНОРИРУЕТСЯ. Пока
    лоры не было, build_cell отдавал голое «a photo», и тест сверялся с этой
    строкой. В день, когда лору обучили и вписали в assets.json, промпт стал
    начинаться с триггера — и тест покраснел на исправном коде. Проверяется
    здесь ЧЕРТА, а не наличие триггера, поэтому он снимается явно.
    """
    from prompts import _character_trigger
    char = {"personality_in_frame": {"independent": "…"}, "medium": "a photo"}
    got = build_cell(char, {"id": "X1", "trait": "none"})
    trig = _character_trigger()
    if trig and got.startswith(trig):
        got = got[len(trig):].lstrip(", ")
    assert got == "a photo"


@pytest.mark.parametrize("char,path,shots", shotlist_params())
def test_cell_ids_are_unique(char, path, shots):
    ids = [c["id"] for c in shots["cells"]]
    assert len(set(ids)) == len(ids), ids


@pytest.mark.parametrize("char,path,shots", shotlist_params())
def test_tattoo_visible_in_matches_shotlist(char, path, shots):
    """character.json → tattoo.visible_in обязан совпадать с флагами ячеек.

    Два списка одного и того же: карточка обещает, в каких кадрах открыто
    запястье, ячейки этим флагом включают площадку под композит. Разъедутся —
    и тату либо вклеится в кадр, где запястья нет, либо не вклеится там, где
    оценщик его ищет отдельной строкой критериев.
    """
    promised = set(char.get("tattoo", {}).get("visible_in", []))
    ids = {c["id"] for c in shots["cells"]}
    flagged = {c["id"] for c in shots["cells"] if c.get("tattoo_visible")}
    assert flagged <= promised, f"кадры с тату вне visible_in: {flagged - promised}"
    # Обещания карточки про ЧУЖИЕ раскадровки эта проверка не трогает: части
    # проекта живут в разных файлах, и P3 из Part 1 не обязан быть в story.
    assert (promised & ids) == flagged, \
        f"visible_in обещает {promised & ids}, ячейки помечают {flagged}"


@pytest.mark.parametrize("char,path,shots", shotlist_params())
def test_tattoo_prompt_clause_reaches_flagged_cells(char, path, shots):
    """Флаг обязан открывать запястье словами: композиту нужно КУДА лечь."""
    clause = char.get("tattoo", {}).get("prompt_clause", "")
    for cell in shots["cells"]:
        prompt = build_cell(char, cell)
        assert (clause in prompt) is bool(cell.get("tattoo_visible")), cell["id"]


def test_every_personality_trait_is_used_at_least_once():
    """Все четыре черты ТЗ должны быть отработаны набором, а не тремя из них.

    Проверяется по объединению всех раскадровок проекта: черта, не попавшая ни
    в один кадр, в сдаче не существует.
    """
    from conftest import PROJECTS
    used = {}
    known = {}
    for pdir, char, _spath, shots in PROJECTS:
        known[pdir] = {k for k in char.get("personality_in_frame", {})
                       if not k.startswith("_")}
        used.setdefault(pdir, set()).update(
            c["trait"] for c in shots["cells"] if c.get("trait") != "none")
    for pdir, traits in known.items():
        assert traits <= used[pdir], f"{pdir}: не использованы {traits - used[pdir]}"
