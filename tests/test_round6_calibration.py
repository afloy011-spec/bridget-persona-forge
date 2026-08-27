"""Раунд 6, находка PF-04: калибровка идентичности пишет файл и мерит сцену.

  py -3 -m pytest -q tests/test_round6_calibration.py

БЫЛО СЛОМАНО ДВА РАЗА В ОДНОМ ФАЙЛЕ.

Первое: README, SKILL.md и assets.json → gates._identity_is_informational
посылают за актуальными числами калибровки в docs/<проект>/
identity_calibration.json и прямо пишут, что прозой числа не хранятся, потому
что трижды устаревали. Файл по этой ссылке конвейером НЕ СОЗДАВАЛСЯ:
identity_calibration.py печатал в stdout и всё. Лежащий там файл написали
руками — то есть единственное разрешённое место для чисел устаревало ровно так
же, как проза, из которой их оттуда убирали.

Второе, методическое: калибровка сравнивала худшую пару сданного набора (пять
РАЗНЫХ сцен) с худшей парой случайного набора кастинга (одна сцена, портреты).
Разброс кадрирования и ракурса у сданного набора заведомо больше, поэтому
вывод «метрика не отделяет одного человека от разных» мог быть свойством
сравнения, а не метрики — а на этом выводе стоит статус ворот идентичности.
Замер при контроле сцены (ячейка против кастинга того же размера) обязан
считаться и обязан быть виден в отчёте.

ПОЧЕМУ ЛИЦА ЗДЕСЬ ПОДДЕЛЬНЫЕ. `_emb` подменяется единичными векторами на
плоскости: угол между кадрами и есть косинус. Настоящий ArcFace тянет ~340 МБ
моделей и в CI не ставится (см. шапку .github/workflows/ci.yml), а проверяется
здесь не он, а арифметика сравнения и то, что результат доезжает до файла.
Материал подобран так, что сданный набор (кадры из разных «сцен») лежит в
середине случайного распределения, а внутри «ячейки» кадры почти совпадают —
то есть контроль сцены обязан дать другой ответ, чем основное сравнение.
"""
import datetime
import json
import math
import os
import re

import pytest

from conftest import MANIFEST

import identity_calibration as IC

PROJECT = "t"
DRAWS = 400

# Кандидаты кастинга — веером с равным шагом; «ячейки» — далеко друг от друга,
# а кадры внутри ячейки почти совпадают. Числа тут не замер, а конструкция
# материала: их выбирали так, чтобы два сравнения дали РАЗНЫЙ ответ и разница
# была не на грани.
CAST_N, CAST_STEP = 12, 12.0
CELL_ANGLE = {"P1": 0.0, "P2": 30.0, "P3": 60.0, "P4": 90.0, "P5": 120.0}
# У P5 кадров больше нарочно: розыгрыш сравнения обязан считаться под ЕЁ число
# пар, а не под чужое.
CELL_FRAMES = {"P1": 4, "P2": 4, "P3": 4, "P4": 4, "P5": 6}
JITTER = 0.5


class Lab:
    """Поддельный проект целиком: карточка, сдача, пул кастинга, кадры ячеек."""

    def __init__(self, tmp_path, monkeypatch, rows_extra=()):
        np = pytest.importorskip("numpy")
        self.repo = tmp_path / "repo"
        self.work = tmp_path / "work"
        self.pdir = tmp_path / "project"
        self.angles = {}

        self.pdir.mkdir(parents=True)
        (self.pdir / "character.json").write_text(
            json.dumps({"id": PROJECT}), encoding="utf-8")
        (self.pdir / "shotlist.json").write_text(
            json.dumps({"project": PROJECT, "cells": []}), encoding="utf-8")

        casting = self.work / PROJECT / "casting"
        casting.mkdir(parents=True)
        for i in range(CAST_N):
            self._png(casting / f"cast_{i:02d}.png", i * CAST_STEP)

        rows = []
        for cell, base in CELL_ANGLE.items():
            folder = self.work / PROJECT / "frames" / cell
            folder.mkdir(parents=True)
            for j in range(CELL_FRAMES[cell]):
                p = self._png(folder / f"{cell}_{j:02d}.png", base + j * JITTER)
                if j == 0:
                    rows.append({"cell": cell, "source": p})
        rows += list(rows_extra)

        sel = self.repo / "deliverables" / PROJECT / "part1_profile"
        sel.mkdir(parents=True)
        (sel / "selection.json").write_text(
            json.dumps({"project": PROJECT, "part": 1, "frames": rows}),
            encoding="utf-8")

        def fake_emb(path):
            a = math.radians(self.angles[str(path).replace("\\", "/")])
            return np.array([math.cos(a), math.sin(a)], dtype=np.float32)

        monkeypatch.setattr(IC, "_emb", fake_emb)
        monkeypatch.setattr(IC, "ROOT", str(self.repo))
        monkeypatch.setenv("PERSONA_WORK_ROOT", str(self.work))

    def _png(self, path, angle):
        path.write_bytes(b"")            # содержимое не читается: `_emb` подменён
        key = str(path).replace("\\", "/")
        self.angles[key] = angle
        return key

    def run(self, monkeypatch, *extra):
        monkeypatch.setattr("sys.argv", ["identity_calibration.py",
                                         str(self.pdir), "--draws", str(DRAWS),
                                         *extra])
        IC.main()

    @property
    def default_out(self):
        return self.repo / "docs" / PROJECT / "identity_calibration.json"


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_calibration_writes_the_file_the_docs_send_readers_to(tmp_path,
                                                              monkeypatch):
    """Скрипт печатал в stdout и НЕ писал docs/<проект>/…json, на который
    ссылаются README, SKILL.md и манифест. Числа по ссылке были рукописные."""
    lab = Lab(tmp_path, monkeypatch)
    lab.run(monkeypatch)
    assert lab.default_out.is_file(), (
        f"калибровка не написала {lab.default_out} — за числами по-прежнему "
        f"некуда идти")
    data = _read(lab.default_out)
    assert data["project"] == PROJECT and data["part"] == 1
    assert data["delivered_worst_pair"] == pytest.approx(
        math.cos(math.radians(max(CELL_ANGLE.values()))), abs=1e-3)


def test_default_path_is_exactly_the_one_the_manifest_names(tmp_path,
                                                            monkeypatch):
    """Файл должен появляться ТАМ, куда манифест посылает читателя. Написать
    его рядом — тот же дефект: ссылка снова ведёт в пустоту."""
    live = str(MANIFEST["gates"].get("_identity_is_informational", ""))
    named = re.search(r"docs/<[^>]+>/identity_calibration\.json", live)
    if not named:
        pytest.skip("манифест больше не называет файл — сверять не с чем")
    lab = Lab(tmp_path, monkeypatch)
    lab.run(monkeypatch)
    want = os.path.normpath(os.path.join(
        str(lab.repo), re.sub(r"<[^>]+>", PROJECT, named.group(0))))
    assert os.path.normpath(str(lab.default_out)) == want
    assert os.path.isfile(want)


def test_out_key_overrides_the_default(tmp_path, monkeypatch):
    """--out обязан писать туда, куда просили: молча положить файл по
    умолчанию значило бы «записал не туда и не сказал»."""
    lab = Lab(tmp_path, monkeypatch)
    mine = tmp_path / "куда просили" / "cal.json"
    lab.run(monkeypatch, "--out", str(mine))
    assert mine.is_file(), "--out проигнорирован"
    assert not lab.default_out.exists(), "написано ещё и по умолчанию"


def test_file_holds_every_line_that_was_printed(tmp_path, monkeypatch, capsys):
    """«Числа живут в файле, а не в прозе» держится только если в файле лежит
    ВСЁ, что показано на экране. Иначе рецензент видит одно, а по ссылке
    находит другое — с этого расхождения и началась вся история."""
    lab = Lab(tmp_path, monkeypatch)
    lab.run(monkeypatch)
    printed = capsys.readouterr().out.rstrip("\n").split("\n")
    stored = _read(lab.default_out)["report"]
    assert printed[-1].startswith("числа:"), "скрипт не сказал, куда написал"
    assert printed[:-1] == stored, (
        "напечатанное и записанное разошлись; только на экране: "
        f"{[ln for ln in printed[:-1] if ln not in stored]}")


def test_file_holds_the_date_and_the_draw_parameters(tmp_path, monkeypatch):
    """Без даты и параметров розыгрыша файл неотличим от прошлогоднего — а
    незамеченная несвежесть и есть та ошибка, которую тут чинят четвёртый
    раз. Путь к сдаче — оттуда же: числа описывают КОНКРЕТНЫЙ набор."""
    lab = Lab(tmp_path, monkeypatch)
    lab.run(monkeypatch, "--seed", "7")
    data = _read(lab.default_out)
    stamped = datetime.datetime.fromisoformat(data["generated_at"])
    assert abs((datetime.datetime.now(stamped.tzinfo) - stamped).days) < 1
    assert data["draws"] == DRAWS and data["seed"] == 7
    assert os.path.basename(data["selection"]) == "selection.json"


def test_scene_control_separates_where_the_delivered_set_does_not(tmp_path,
                                                                  monkeypatch,
                                                                  capsys):
    """ГЛАВНОЕ. Сданный набор — разные сцены, кастинг — одна; при контроле
    сцены (ячейка против кастинга того же размера) ответ обязан считаться
    отдельно и обязан быть напечатан. Пока замера не было, вывод «метрика не
    разделяет» нельзя было отличить от артефакта сравнения несравнимого."""
    lab = Lab(tmp_path, monkeypatch)
    lab.run(monkeypatch)
    data = _read(lab.default_out)
    sc = data["scene_control"]

    assert data["separates"] is False, "материал теста собран не так"
    assert 0.05 < data["share_of_random_sets_worse_than_ours"] < 0.95, (
        "сданный набор обязан лежать ВНУТРИ случайного распределения, иначе "
        "тест не про то")
    assert [c["cell"] for c in sc["cells"]] == list(CELL_ANGLE)
    assert sc["cells_separating"] == len(CELL_ANGLE), (
        "внутри одной сцены кадры почти совпадают — метрика обязана "
        "разделять, а замер этого не увидел")
    assert sc["separates_under_scene_control"] is True

    out = capsys.readouterr().out
    assert "КОНТРОЛЬ СЦЕНЫ" in out, "замер сделан, но в отчёте его не видно"
    for cell in CELL_ANGLE:
        assert re.search(rf"^\s+{cell}\s", out, re.M), f"{cell} не напечатана"


def test_scene_control_draws_at_the_cell_own_pair_count(tmp_path, monkeypatch):
    """Правило, ради которого этот скрипт вообще написан: минимум — крайняя
    порядковая статистика, чем больше пар, тем он ниже, поэтому сравнивать
    можно только при РАВНОМ числе пар. Один розыгрыш на все ячейки сравнивал
    бы ячейку из шести кадров с распределением для четырёх."""
    lab = Lab(tmp_path, monkeypatch)
    lab.run(monkeypatch)
    cells = {c["cell"]: c for c in _read(lab.default_out)["scene_control"]["cells"]}
    for cell, c in cells.items():
        assert c["n"] == CELL_FRAMES[cell]
        assert c["pairs"] == c["n"] * (c["n"] - 1) // 2
    big, small = cells["P5"], cells["P1"]
    assert big["n"] > small["n"], "материал теста собран не так"
    assert big["random_worst_pair"]["median"] < small["random_worst_pair"]["median"], (
        "у большего набора худшая пара обязана быть ниже — значит и розыгрыш "
        "для него другой; здесь он взят от чужого числа пар")


def test_cell_without_frames_is_named_not_dropped(tmp_path, monkeypatch,
                                                  capsys):
    """Ячейка, чьих кадров на диске нет, обязана быть названа. Молча выпасть
    она не может: тогда таблица контроля сцены выглядит полной, а посчитана
    по части набора — ровно тот дефект, который раунд 6 чинил в вердикте
    ворот (частичный вердикт читался как полный)."""
    ghost = str(tmp_path / "нет такой папки" / "P9_00.png")
    lab = Lab(tmp_path, monkeypatch, rows_extra=[{"cell": "P9",
                                                  "source": ghost}])
    lab.run(monkeypatch)
    skipped = dict(tuple(s) for s in _read(lab.default_out)["scene_control"]["skipped"])
    assert "P9" in skipped, "ячейка без кадров исчезла из замера молча"
    assert "P9" in capsys.readouterr().out


def test_report_and_flag_agree_on_a_minority_of_cells():
    """Ветка отчёта стояла на `if k:` (хоть одна ячейка), а машинный флаг
    separates_under_scene_control — на большинстве. На одной разделяющей
    ячейке из трёх текст заявлял «сравнивалось несравнимое», а поле в JSON
    стояло false: частичный результат, прочитанный как полный.

    Материал bridget этой ветки не даёт — там разделяют 4 ячейки из 5, —
    поэтому она проверяется на подставленной сводке, а не на кадрах: иначе
    единственный случай, ради которого починка написана, остался бы
    непроверенным.
    """
    import importlib
    import identity_calibration as ic
    importlib.reload(ic)
    base = {"n": 5, "pairs": 10, "delivered_worst_pair": 0.5,
            "negative_pool": 15, "draws": 100,
            "random_worst_pair": {"median": 0.5, "p05": 0.4, "p95": 0.6},
            "share_of_random_sets_worse_than_ours": 0.5, "separates": False}

    def text(separating, measured):
        cells = [{"cell": f"P{i}", "n": 8, "pairs": 28, "worst_pair": 0.5,
                  "random_worst_pair": {"median": 0.4},
                  "share_of_random_sets_worse": 0.3,
                  "separates": i < separating} for i in range(measured)]
        sc = {"cells": cells, "cells_measured": measured,
              "cells_separating": separating,
              "separates_under_scene_control": separating > measured / 2,
              "same_person_across_cells_median": None,
              "different_people_same_scene_median": None,
              "skipped": []}
        return chr(10).join(ic.report(dict(base, scene_control=sc)))

    minority = text(1, 3)
    assert "НО СРАВНИВАЛОСЬ НЕСРАВНИМОЕ" not in minority, (
        "на меньшинстве ячеек отчёт заявляет то, что его же флаг отрицает")
    assert "в 1 ячейке из 3" in minority, minority   # и согласование с числом
    majority = text(4, 5)
    assert "НО СРАВНИВАЛОСЬ НЕСРАВНИМОЕ" in majority
    assert "в 4 ячейках из 5" in majority
    none = text(0, 3)
    assert "КОНТРОЛЬ СЦЕНЫ НИЧЕГО НЕ МЕНЯЕТ" in none
