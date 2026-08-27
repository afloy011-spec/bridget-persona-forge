"""Линтер раскадровки: ловит то, что стоило прогонов на GPU.

Каждое правило здесь — не стиль, а замер. Тесты держат линтер честным в обе
стороны: он обязан ловить нарушение И обязан НЕ ловить исправную клетку.
Линтер, ругающийся на рабочее, перестают читать — и тогда он не ловит ничего.
"""
import pytest

import lint_shotlist as L


def cell(**kw):
    base = {"id": "T1", "label": "клетка", "trait": "independent",
            "body_in_frame": False, "scene_class": "indoor",
            "delivery_name": "some_frame"}
    base.update(kw)
    return base


def lint_one(c):
    return L.lint_cell(c, set(), set())


def test_a_clean_cell_passes():
    assert lint_one(cell(set="a kitchen in morning light")) == []


@pytest.mark.parametrize("text", [
    "soft light, no hard shadows",
    "caught mid-thought, not posing",
    "a plain wall without decoration",
    "she is never looking at the lens",
    "a half-smile rather than a full one",
])
def test_negations_are_caught(text):
    """При cfg 1.0 отрицание — это ЗАПРОС.

    «no hard shadows» просит жёсткие тени. Правило записано в карточке
    (forbidden_as_positive) и нарушается чаще всего, потому что по-русски
    отрицание звучит естественно.
    """
    bad = lint_one(cell(light=text))
    assert any("отрицание" in b for b in bad), text


@pytest.mark.parametrize("text", [
    "a notebook open on the table",
    "the bridge of her nose catching the light",
    "a north-facing window",
    "an annotated map on the wall",
])
def test_innocent_words_are_not_negations(text):
    """`no` и `not` берутся по границе слова.

    Без этого «notebook» и «nose» — нарушения, и линтер начинает мешать. Оба
    слова встречаются в описании сцены постоянно.
    """
    assert not any("отрицание" in b for b in lint_one(cell(set=text)))


def test_full_figure_without_its_own_frame_shape_is_caught():
    """Полный рост словами не выпрашивается.

    Замерено: на 4:5 модель тянет к портрету, что ни пиши. Единственный
    рычаг — форма кадра.
    """
    bad = lint_one(cell(full_figure=True, framing="full figure"))
    assert any("рост целиком" in b for b in bad)


def test_a_frame_shape_too_close_to_square_is_caught():
    """Порог поднят по замеру, и это не придирка.

    Стояло 1.4, то есть 2:3 (1024x1536) считалось достаточным для фигуры.
    Прогон 19.08 показал обратное: двадцать клеток, снятых на 1.50, вышли
    поясными все до одной. Лестница на одной клетке и одних сидах дала
    фигуру целиком от 2.33. Порог 2.2 пропускает работающее и отсекает то,
    что раньше проходило и молча не работало.
    """
    for bad_size in ([1152, 1440], [1024, 1536], [896, 1600]):
        assert any("тянет к портрету" in b
                   for b in lint_one(cell(full_figure=True, size=bad_size))),             bad_size
    assert not any("портрет" in b
                   for b in lint_one(cell(full_figure=True,
                                          size=[704, 1856])))


@pytest.mark.parametrize("text", [
    "a 51-year-old woman by the door",
    "her green-hazel eyes catching the light",
    "visible pores across her cheeks",
    "warm balayage through the lengths",
])
def test_repeating_the_card_is_caught(text):
    """Карточка подставляется в каждую клетку сама.

    Написанное второй раз не усиливает, а вытесняет из промпта сцену.
    """
    assert any("карточка подставляет" in b for b in lint_one(cell(set=text)))


def test_none_is_a_legal_refusal_of_a_trait():
    """Есть клетка, где состояние задаёт сам взгляд.

    Приписывать ей ещё и черту значит сказать одно дважды; это закреплено
    отдельным тестом сборщика промпта.
    """
    assert not any("черта" in b for b in lint_one(cell(trait="none")))


def test_an_invented_trait_is_caught():
    assert any("черта" in b for b in lint_one(cell(trait="mysterious")))


def test_an_unknown_scene_class_is_caught():
    """От класса сцены зависит сила лоры плёночной мыльницы.

    Опечатка в нём не ломает прогон — она молча выключает лору, и кадр
    выходит не тем, что заказывали.
    """
    assert any("класс сцены" in b for b in lint_one(cell(scene_class="dusk")))


def test_tattoo_flag_is_not_a_violation():
    """Флаг законный: он отправляет кадр на отдельный шаг вклейки.

    Диффузия тату не рисует — это замерено, — поэтому флаг и существует.
    Ругаться на работающий механизм значит приучить читателя пролистывать.
    """
    assert lint_one(cell(tattoo_visible=True)) == []


def test_repeated_delivery_name_is_caught():
    """Имя файла в сдаче: повтор — это молча перезаписанный кадр."""
    names = set()
    L.lint_cell(cell(id="T1"), set(), names)
    bad = L.lint_cell(cell(id="T2"), set(), names)
    assert any("повторяется" in b for b in bad)


def test_delivery_name_must_survive_a_filesystem():
    assert any("snake_case" in b
               for b in lint_one(cell(delivery_name="Кадр Один")))


def test_missing_trait_is_a_note_and_not_a_violation():
    """Охват черт — правило ПРОЕКТА, а не отдельной раскадровки.

    История части 2 это пять кадров одного вечера; вместить в них все четыре
    черты нельзя. Правило в этом масштабе валило исправную раскадровку и
    подталкивало приписать черту ради тишины. Проектный охват стережёт
    tests/test_shotlist.py по объединению всех раскадровок.
    """
    shots = {"cells": [cell(id="T%d" % i, trait="independent",
                            delivery_name="f%d" % i) for i in range(4)]}
    assert L.lint(shots) == []
    assert len(L.notes(shots)) == 3


def test_greedy_selection_terminates_on_a_twenty_cell_set():
    """Отбор обязан ЗАКАНЧИВАТЬСЯ на двадцати ячейках.

    ЭТО НЕ ГИПОТЕТИКА. select_set после урезания пулов всё равно делал полный
    itertools.product и копил результаты в список. На пяти ячейках это 6^5 =
    7776 и работало, поэтому дефект прожил до первой большой раскадровки. На
    двадцати это 6^20 ≈ 3.7e15: процесс не кончается никогда и молча съедает
    память. Докстринг при этом обещал «жадный старт с лучшей пары и
    достройка» — обещание не было выполнено ни строчкой.
    """
    import numpy as np

    import select_set as S

    rng = np.random.RandomState(7)
    by_cell, emb = {}, {}
    for c in range(20):
        cid = "T%02d" % c
        by_cell[cid] = []
        for k in range(6):
            f = "%s_%d.png" % (cid, k)
            by_cell[cid].append(f)
            v = rng.randn(64).astype(np.float32)
            v[0] += 8.0                      # общий «человек» + шум
            emb[f] = v / np.linalg.norm(v)

    cells, sets = S.best_sets(by_cell, emb, top=3)
    assert len(cells) == 20
    assert sets, "отбор не вернул ни одного набора"
    worst, mean, combo = sets[0]
    assert len(combo) == 20, "в наборе должен быть кадр из каждой ячейки"
    assert len(set(combo)) == 20
    assert 0.0 < worst <= mean <= 1.0
    # наборы отсортированы по худшей паре, а не по средней
    assert all(sets[i][0] >= sets[i + 1][0] for i in range(len(sets) - 1))
