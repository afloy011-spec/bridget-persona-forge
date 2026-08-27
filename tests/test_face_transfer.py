#!/usr/bin/env python3
"""Перенос лица меняет ЛИЦО и ничего больше.

ЗАЧЕМ ЭТОТ ТЕСТ СУЩЕСТВУЕТ. Заказчик посмотрел на прогон и сказал «качество
уплыло». Замер детализации (дисперсия лапласиана) по стадиям подтвердил и
уточнил: терял не только участок лица, а ВЕСЬ КАДР — 304→259, 176→113,
291→206, то есть 15-35% на волосах, ткани и фоне, которых перенос вообще не
касается по замыслу. Свап прогоняет через себя всю картинку и возвращает её
мягче.

Лечится это не настройкой, а устройством: лицо берётся с переноса, всё
остальное — из исходника байт в байт. Тест держит именно эту границу, потому
что нарушить её легко и незаметно: достаточно вернуть из transfer() файл
воркера напрямую, и кадр снова начнёт мылиться целиком.

Воркер здесь не нужен: проверяется склейка, а не свап.
"""
import os
import sys

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from _util import imread, imwrite  # noqa: E402
import face_transfer as ft  # noqa: E402
from metrics import faces  # noqa: E402

FACE = os.path.join("D:/Cursor/persona-forge-work/bridget/ref", "ref_face.png")


@pytest.fixture(scope="module")
def real_face():
    if not os.path.exists(FACE):
        pytest.skip("нет референса лица: проверка склейки требует живого лица")
    if faces.detect(FACE) is None:
        pytest.skip("детектор лиц недоступен")
    return FACE


def _blurred(path, dst):
    """«Результат свапа»: тот же кадр, но размытый ЦЕЛИКОМ.

    Именно так вёл себя воркер — мягче становилось всё, а не только лицо.
    """
    img = imread(path)
    imwrite(dst, cv2.GaussianBlur(img, (0, 0), 3.0))
    return dst


def test_everything_outside_the_face_is_bit_identical(real_face, tmp_path):
    """Вне маски лица кадр не меняется НИ НА ОДИН уровень.

    Не «почти не меняется»: сравнение идёт по максимуму модуля разницы, и он
    обязан быть нулём. Замер на живом кадре: так остаётся нетронутым 82%
    площади.
    """
    swapped = _blurred(real_face, str(tmp_path / "swap.png"))
    out = ft.keep_outside(real_face, swapped, str(tmp_path / "out.png"))
    m = ft.face_mask(real_face)
    assert m is not None, "маска лица не построилась"

    a, b = imread(real_face), imread(out)
    assert a.shape == b.shape
    outside = m < 1e-6
    assert outside.mean() > 0.5, (
        f"маска лица закрыла {1 - outside.mean():.0%} кадра — это уже не лицо")
    d = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(2)
    assert int(d[outside].max()) == 0, (
        f"вне маски кадр изменился на {int(d[outside].max())} уровней — значит "
        f"перенос снова переписывает весь кадр, а не лицо")


def test_the_face_itself_does_change(real_face, tmp_path):
    """И при этом лицо ВЗЯТО С ПЕРЕНОСА, а не оставлено своим.

    Без этой половины предыдущий тест зелен у функции, которая просто
    возвращает исходник.
    """
    swapped = _blurred(real_face, str(tmp_path / "swap.png"))
    out = ft.keep_outside(real_face, swapped, str(tmp_path / "out.png"))
    m = ft.face_mask(real_face)
    inside = m > 0.99
    a, b = imread(real_face), imread(out)
    d = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(2)
    assert inside.any() and int(d[inside].max()) > 0, (
        "внутри маски кадр не изменился — склейка вернула исходник целиком")


def test_detail_outside_the_face_survives(real_face, tmp_path):
    """Детализация вне лица остаётся исходной.

    Тот же инвариант, но на языке, которым была найдена беда: дисперсия
    лапласиана вне маски у склейки обязана совпадать с исходной, а у сырого
    результата свапа — падать.
    """
    swapped = _blurred(real_face, str(tmp_path / "swap.png"))
    out = ft.keep_outside(real_face, swapped, str(tmp_path / "out.png"))
    m = ft.face_mask(real_face)
    outside = m < 1e-6

    def det(p):
        g = cv2.cvtColor(imread(p), cv2.COLOR_BGR2GRAY).astype(np.float32)
        return float(cv2.Laplacian(g, cv2.CV_32F)[outside].var())

    raw, bad, good = det(real_face), det(swapped), det(out)
    assert bad < 0.5 * raw, (
        f"фикстура не воспроизводит беду: размытие уронило детализацию вне "
        f"лица только с {raw:.0f} до {bad:.0f}")
    # РОВНО НУЛЯ ЗДЕСЬ НЕ БУДЕТ, И ЭТО НЕ ПОБЛАЖКА. Лапласиан у каждой точки
    # считается по соседям, а у точек НА КРАЮ маски часть соседей лежит внутри
    # неё — то есть взята с переноса. Сами пиксели вне маски совпадают байт в
    # байт (это проверяет отдельный тест выше); разъезжается только производная
    # на границе, и на живом кадре это 0.005 из 57, то есть 0.01%.
    assert abs(good - raw) < 0.01 * raw, (
        f"склейка потеряла детализацию вне лица: {good:.1f} против {raw:.1f}")


def test_transfer_returns_the_glued_frame_not_the_worker_one(real_face,
                                                            tmp_path,
                                                            monkeypatch):
    """transfer() отдаёт СКЛЕЙКУ, а не то, что вернул воркер.

    Тесты выше проверяют склейку саму по себе — и остаются зелёными, если
    перенос перестанет ею пользоваться. Мутационный прогон показал на них
    ровно эту слепоту. Воркер здесь подменён: проверяется решение функции, а
    не свап.
    """
    swapped = _blurred(real_face, str(tmp_path / "worker.png"))
    monkeypatch.setattr(ft.cc, "upload", lambda p, **kw: "up.png")
    monkeypatch.setattr(ft.cc, "load_template", lambda name: {})
    monkeypatch.setattr(ft.cc, "apply_sets", lambda g, s: g)
    monkeypatch.setattr(ft.cc, "run_graph", lambda g, d, **kw: [swapped])

    out = ft.transfer(real_face, real_face, str(tmp_path))
    assert out != swapped, (
        "перенос вернул кадр воркера как есть — весь кадр снова мылится")
    m = ft.face_mask(real_face)
    a, b = imread(real_face), imread(out)
    d = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(2)
    assert int(d[m < 1e-6].max()) == 0, "вне лица кадр изменился"

    # А с явным ключом — как есть: он нужен, чтобы посмотреть на сырой свап.
    raw = ft.transfer(real_face, real_face, str(tmp_path), whole_frame=True)
    assert raw == swapped


def test_a_frame_without_a_face_comes_back_unharmed(tmp_path):
    """Кадр без лица возвращается как есть, а не портится маской.

    На ростовом плане и на макро-кропе детектор лицо находит не всегда;
    молчаливая порча такого кадра была бы худшим исходом, чем отказ.
    """
    flat = str(tmp_path / "flat.png")
    imwrite(flat, np.full((240, 320, 3), 180, np.uint8))
    swapped = _blurred(flat, str(tmp_path / "swap.png"))
    out = ft.keep_outside(flat, swapped, str(tmp_path / "out.png"))
    assert out == swapped, (
        "без лица склейка обязана вернуть результат свапа как есть — маску "
        "строить не по чему")
