#!/usr/bin/env python3
"""Узлы точечной правки: проверяется ГЕОМЕТРИЯ, потому что ломается она.

Картинка получится всегда — и вклеенная мимо, и вклеенная не того масштаба.
Поэтому здесь проверяется не «отработало без исключения», а три свойства, на
которых этот приём стоит: вне рамки кадр не тронут, рамка у края СДВИГАЕТСЯ, а
не сжимается, и увеличение считается от короткой стороны окна.
"""
import os
import sys

import pytest

torch = pytest.importorskip("torch")

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "comfy_nodes", "ComfyUI-AfloyDetail"))

import detail as D  # noqa: E402


def img(h=200, w=300, value=0.5):
    return torch.full((1, h, w, 3), float(value))


def mask_rect(h, w, x0, y0, x1, y1):
    m = torch.zeros((1, h, w))
    m[0, y0:y1, x0:x1] = 1.0
    return m


# ---------------------------------------------------------------- рамка

def test_mask_box_is_the_selection_grown_by_pad():
    m = mask_rect(200, 300, 100, 80, 140, 120)      # 40x40
    x0, y0, x1, y1 = D.box_from_mask(m, 300, 200, pad=2.0, square=True)
    assert (x1 - x0, y1 - y0) == (80, 80)
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == (120, 100)  # центр не уехал


def test_square_box_takes_the_longer_side():
    """Иначе вытянутое выделение дало бы вытянутое окно, а холст квадратный —
    и деталь растянулась бы по одной оси."""
    m = mask_rect(200, 300, 100, 90, 200, 110)      # 100x20
    x0, y0, x1, y1 = D.box_from_mask(m, 300, 200, pad=1.0, square=True)
    assert (x1 - x0) == (y1 - y0) == 100


def test_box_at_the_edge_is_shifted_not_shrunk():
    """САМОЕ ВАЖНОЕ СВОЙСТВО РАМКИ. Обрезка у края молча уменьшила бы окно, то
    есть изменила бы масштаб рисования — ту самую величину, ради управления
    которой узел и написан. Деталь у края кадра вышла бы крупнее, чем в
    середине, и человек искал бы причину в промпте."""
    m = mask_rect(200, 300, 0, 0, 20, 20)           # прижато в угол
    x0, y0, x1, y1 = D.box_from_mask(m, 300, 200, pad=4.0, square=True)
    assert (x1 - x0, y1 - y0) == (80, 80), "окно у края изменило размер"
    assert (x0, y0) == (0, 0)


def test_box_larger_than_frame_is_capped_to_the_frame():
    m = mask_rect(200, 300, 140, 90, 160, 110)
    x0, y0, x1, y1 = D.box_from_mask(m, 300, 200, pad=40.0, square=True)
    assert (x1 - x0, y1 - y0) == (200, 200)         # по короткой стороне
    assert 0 <= x0 and x1 <= 300 and 0 <= y0 and y1 <= 200


def test_empty_mask_gives_none_so_the_node_can_say_so():
    """None, а не молчаливый откат на середину кадра: пустая маска — почти
    всегда ошибка человека, и узел обязан назвать её."""
    assert D.box_from_mask(torch.zeros((1, 200, 300)), 300, 200) is None
    assert D.box_from_mask(None, 300, 200) is None


def test_point_box_measures_size_from_the_short_side():
    """От короткой стороны, а не от ширины: иначе одно и то же число даёт
    разные окна на портрете и на альбоме."""
    a = D.box_from_point(0.5, 0.5, 0.5, 300, 200)   # короткая 200
    b = D.box_from_point(0.5, 0.5, 0.5, 200, 300)   # короткая тоже 200
    assert (a[2] - a[0]) == (b[2] - b[0]) == 100


# ---------------------------------------------------------------- кроп

def test_cut_gives_the_window_its_own_canvas():
    box = D.box_from_point(0.5, 0.5, 0.2, 300, 200)
    crop = D.cut(img(200, 300), box, canvas=512)
    assert tuple(crop.shape) == (1, 512, 512, 3)


def test_cut_takes_the_pixels_of_that_window_and_no_others():
    src = img(200, 300, 0.0)
    src[0, 90:110, 140:160, :] = 1.0                # белый квадрат в центре
    box = (140, 90, 160, 110)
    crop = D.cut(src, box, canvas=64)
    assert float(crop.min()) > 0.99, "в кроп попало что-то вне рамки"


# ---------------------------------------------------------------- вклейка

def test_paste_leaves_everything_outside_the_box_untouched():
    src = img(200, 300, 0.25)
    box = (100, 80, 140, 120)
    out = D.paste(src, torch.ones((1, 64, 64, 3)), box)
    m = torch.ones((200, 300), dtype=torch.bool)
    m[80:120, 100:140] = False
    assert torch.allclose(out[0][m], src[0][m]), "правка вылезла за рамку"


def test_paste_does_not_mutate_its_input():
    """Шаг не идемпотентен: второй проход лёг бы поверх первого. Запись на
    месте сделала бы это незаметным."""
    src = img(200, 300, 0.25)
    before = src.clone()
    D.paste(src, torch.ones((1, 64, 64, 3)), (100, 80, 140, 120))
    assert torch.equal(src, before)


def test_blend_zero_is_exactly_the_original():
    src = img(200, 300, 0.25)
    out = D.paste(src, torch.ones((1, 64, 64, 3)), (100, 80, 140, 120),
                  blend=0.0)
    assert torch.allclose(out, src, atol=1e-6)


def test_blend_is_monotone_between_original_and_edit():
    src = img(200, 300, 0.0)
    box, ed = (100, 80, 140, 120), torch.ones((1, 64, 64, 3))
    mid = [float(D.paste(src, ed, box, blend=b)[0, 100, 120, 0])
           for b in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert mid == sorted(mid) and mid[0] == 0.0 and mid[-1] > 0.9


def test_feather_is_one_inside_and_zero_at_the_border():
    """Без пера шов виден полосой: проход слегка меняет яркость всего окна."""
    m = D.feather_mask(100, 100, feather=0.2)
    assert float(m[50, 50]) == pytest.approx(1.0, abs=1e-6)
    assert float(m[0, 50]) < 0.02 and float(m[50, 0]) < 0.02
    assert torch.allclose(m, m.flip(0), atol=1e-6)
    assert torch.allclose(m, m.flip(1), atol=1e-6)


def test_round_trip_without_editing_returns_almost_the_original():
    """Кроп → назад без правки обязан вернуть почти то же самое; разница —
    только ошибка двух ресайзов, и она обязана быть мелкой."""
    torch.manual_seed(0)
    src = torch.rand((1, 200, 300, 3)) * 0.4 + 0.3
    box = D.box_from_point(0.5, 0.5, 0.3, 300, 200)
    out = D.paste(src, D.cut(src, box, canvas=256), box)
    assert float((out - src).abs().max()) < 0.12


# ---------------------------------------------------------------- отчёт

def test_sharpness_separates_a_sharp_patch_from_a_blurred_one():
    """Порог носителя стоит между 19 и 99, замеренными на двух кадрах одного
    запястья. Здесь проверяется, что мерка вообще смотрит в ту сторону."""
    torch.manual_seed(1)
    sharp = torch.rand((1, 64, 64, 3))
    blur = torch.nn.functional.avg_pool2d(
        sharp.permute(0, 3, 1, 2), 9, 1, 4).permute(0, 2, 3, 1)
    assert D.sharpness(sharp[0]) > 4 * D.sharpness(blur[0])


def test_report_names_the_zoom_and_warns_on_a_soft_host():
    text = D.report((0, 0, 400, 400), 1280, 960, 1024, sharp=19.0)
    assert "2.56" in text, "увеличение не названо"
    assert "мягкий" in text
    assert "мягкий" not in D.report((0, 0, 400, 400), 1280, 960, 1024, 99.0)


def test_report_warns_when_the_window_is_bigger_than_the_canvas():
    """Увеличение меньше единицы означает, что деталь будет нарисована МЕЛЬЧЕ,
    чем видна в кадре, — и это почти всегда не то, чего хотели."""
    assert "МЕЛЬЧЕ" in D.report((0, 0, 900, 900), 1280, 960, 512, sharp=99.0)
