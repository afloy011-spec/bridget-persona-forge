"""Договор второй части: пять кадров истории с явными уровнями откровенности.

  py -3 -m pytest tests/test_story_contract.py -q

Part 2 оценивается по составу набора, а не по каждому кадру отдельно: пять
кадров, из них три эротических и два обнажённых, хотя бы одно зеркальное селфи
с телефоном в кадре, у каждого кадра подпись. Состав легко «почти» сойтись —
четыре эротических и один обнажённый выглядят как выполненная работа и валят
формальный критерий. Поэтому счёт здесь точный, а не «не меньше».

Файл раскадровки может ещё не существовать — тогда тест пропускается, а не
падает: части проекта пишутся параллельно.
"""
import os

import pytest

from conftest import PROJECTS, ROOT

STORY = os.path.join(ROOT, "projects", "bridget", "shotlist_story.json")

pytestmark = pytest.mark.skipif(not os.path.exists(STORY),
                                reason="projects/bridget/shotlist_story.json "
                                       "ещё не написан")


def _story():
    for _pdir, _char, spath, shots in PROJECTS:
        if os.path.abspath(spath) == os.path.abspath(STORY):
            return shots
    raise AssertionError("shotlist_story.json есть на диске, но не собран "
                         "conftest — проверь маску shotlist*.json")


def test_exactly_five_cells():
    assert len(_story()["cells"]) == 5


def test_three_erotic_and_two_nude():
    """Ровно 3 + 2 по nudity_level — состав набора, а не пожелание."""
    levels = [c.get("nudity_level") for c in _story()["cells"]]
    assert levels.count("erotic") == 3, levels
    assert levels.count("nude") == 2, levels


def test_at_least_one_mirror_selfie_with_phone():
    """Зеркальное селфи без телефона в кадре — не зеркальное селфи.

    Флаг mirror_selfie обещает узнаваемую бытовую съёмку; без phone_visible
    промпт получает зеркало и теряет ровно ту деталь, по которой кадр читается
    как снятый ею самой.
    """
    cells = [c for c in _story()["cells"] if c.get("mirror_selfie")]
    assert cells, "ни одного кадра с mirror_selfie"
    assert any(c.get("phone_visible") for c in cells), \
        "есть зеркальное селфи, но телефон ни в одном не объявлен"


def test_every_cell_has_caption():
    """Подпись едет в реестр кадров и в презентацию — пустой не бывает."""
    for cell in _story()["cells"]:
        assert str(cell.get("caption", "")).strip(), cell["id"]


def test_story_size_is_vertical():
    """История — 9:16: кинематографичное 16:9 «селфи» читается как фейк."""
    from conftest import MANIFEST
    size = _story().get("size") or MANIFEST["output"]["story_size"]
    assert size[1] > size[0], size
