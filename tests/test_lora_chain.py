"""Цепочка лор графа: место под персонажную лору и всё, что с этим связано.

БЫЛО СЛОМАНО ТАК. В шаблоне ровно пять узлов лоры, в манифесте ровно пять
реализм-лор — свободных слотов не было НИ ОДНОГО, а generate._fit_loras
лишние молча отбрасывал с предупреждением в stderr, которого при батче на
сорок кадров никто не читает. То есть добавить персонажную лору в манифест
было можно, а в кадр она бы не попала: конвейер обещал бы закреплённое лицо и
рисовал бы прежнее.

Второй дефект того же места: сила «одноразовой камеры» (она делает ночной кадр
ночным) правилась по НОМЕРУ последнего слота. Перестановка строк в манифесте
молча переносила регулировку света на другую лору, а появление персонажной
лоры сдвинуло бы её гарантированно.
"""
import copy
import json
import os

import pytest

from conftest import MANIFEST, ROOT  # noqa: F401

import generate as G
import prompts as P


def _rows(graph):
    """Строки панели Afloy Lora Box: [(имя, сила), …] в порядке применения.

    Боевой t2i-граф с 17.08.2026 собирается ОДНОЙ нодой Lora Box вместо
    цепочки загрузчиков (замер: фактура 232→274, волосы 0.599→0.542, лучше в
    7 и 8 кадрах из 8 соответственно). Проверять надо ровно то же, что
    проверялось у цепочки: ни одна лора не потерялась, персонажная первая,
    сила «одноразовой камеры» правится по имени. Изменился носитель, не
    требования.
    """
    box = [n for n in graph.values()
           if isinstance(n, dict) and n.get("class_type") == "LoraBox"]
    assert len(box) == 1, f"ожидалась одна нода LoraBox, найдено {len(box)}"
    data = json.loads(box[0]["inputs"]["data"])
    return [(r["name"], r["sm"]) for r in data["rows"] if r.get("on", True)]


def _chain(graph):
    """Цепочка от сэмплера назад к базовой модели: [(узел, лора, сила), ...]."""
    out, node, seen = [], graph["7"]["inputs"]["model"][0], set()
    while node != "1":
        assert node not in seen, f"цикл в цепочке на узле {node}"
        seen.add(node)
        n = graph[node]
        assert n["class_type"] == "LoraLoaderModelOnly", (
            f"узел {node} в цепочке модели — не лора, а {n['class_type']}")
        out.append((node, n["inputs"].get("lora_name"),
                    n["inputs"].get("strength_model")))
        node = n["inputs"]["model"][0]
    return list(reversed(out))


def _with_character(monkeypatch, name="char_test.safetensors", strength=0.9,
                    trigger="chartest_w"):
    man = copy.deepcopy(MANIFEST)
    man["models"]["character_lora"] = {"name": name, "strength": strength,
                                       "trigger": trigger}
    monkeypatch.setattr(G, "manifest", lambda: man)
    return man


def _without_character(monkeypatch):
    """Манифест БЕЗ персонажной лоры — явная опора для замера «до».

    Раньше опора бралась из настоящего манифеста молча, и это работало ровно
    до того дня, когда лору обучили и вписали в manifest: «до» стало уже
    содержать её, подстановка тестовой лишь ЗАМЕНЯЛА запись, длина цепочки не
    менялась, и тест краснел на исправном коде. Опора обязана быть заявленной,
    а не унаследованной от состояния проекта.
    """
    man = copy.deepcopy(MANIFEST)
    man["models"].pop("character_lora", None)
    monkeypatch.setattr(G, "manifest", lambda: man)
    return man


def test_stack_grows_with_the_character_lora(monkeypatch):
    """Персонажная лора обязана ПОПАСТЬ В ГРАФ, а не потеряться по дороге.

    У цепочки загрузчиков этот тест ловил обрезку по числу слотов шаблона
    (их было пять, реализм-лор тоже пять — свободных не оставалось). У Lora
    Box слотов нет вовсе, но требование то же: сколько строк в манифесте,
    столько и в панели.
    """
    _without_character(monkeypatch)
    before = len(_rows(G.build_graph("t", 1, (64, 64), "p")))
    _with_character(monkeypatch)
    after = _rows(G.build_graph("t", 1, (64, 64), "p"))
    assert len(after) == before + 1, (
        f"стек не вырос: было {before}, стало {len(after)} — персонажная "
        f"лора отброшена и в кадр не попадёт")
    assert "char_test.safetensors" in [n for n, _ in after]


def test_clip_goes_through_the_box_not_around_it(monkeypatch):
    """Текстовый энкодер берёт CLIP У КОРОБКИ, а не напрямую у загрузчика.

    ЭТО СТОРОЖ ВСЕГО ПЕРЕХОДА НА LORA BOX. Ради чего меняли носитель: цепочка
    LoraLoaderModelOnly кладёт лоры только на модель, коробка — ещё и на CLIP,
    и именно это дало фактуру 232 → 274 и волосы 0.599 → 0.542. Уведи связь
    CLIP мимо коробки — и весь выигрыш исчезнет, а граф останется рабочим,
    кадры правдоподобными, а тесты зелёными. Мутационный прогон показал, что
    без этой проверки подмена не ловится ничем.
    """
    _with_character(monkeypatch)
    g = G.build_graph("t", 1, (64, 64), "p")
    box = [k for k, v in g.items()
           if isinstance(v, dict) and v.get("class_type") == "LoraBox"]
    assert len(box) == 1, f"ожидалась одна нода LoraBox, найдено {box}"
    src = g["4"]["inputs"]["clip"]
    assert src[0] == box[0] and src[1] == 1, (
        f"CLIPTextEncode берёт clip из {src}, а должен из выхода 1 ноды "
        f"LoraBox ({box[0]}) — иначе лоры не действуют на текстовый энкодер")
    assert g["7"]["inputs"]["model"][0] == box[0], (
        "сэмплер берёт модель мимо коробки")


def test_character_lora_goes_first(monkeypatch):
    """Она отвечает на вопрос «кто в кадре», реализм и грейд — «как снято».
    Закреплять личность ПОВЕРХ стилизации значит бороться с ней же."""
    _with_character(monkeypatch)
    rows = _rows(G.build_graph("t", 1, (64, 64), "p"))
    assert rows[0][0] == "char_test.safetensors", (
        f"персонажная лора не первая: {[n for n, _ in rows]}")
    assert rows[0][1] == pytest.approx(0.9)


def test_disposable_camera_follows_the_name_not_the_slot(monkeypatch):
    """Сила света привязана к ИМЕНИ лоры. Прежняя редакция правила последний
    слот шаблона, и с персонажной лорой регулировка уехала бы на соседа."""
    def strength(graph):
        for name, st in _rows(graph):
            if name and "disposable" in name.lower():
                return st
        pytest.fail("одноразовой камеры нет в стеке")

    for scene, want in G.DISPOSABLE_BY_SCENE.items():
        assert strength(G.build_graph("t", 1, (64, 64), "p", scene)) == \
            pytest.approx(want), f"сцена {scene}"
    # И с персонажной лорой, когда слот сдвинулся, — то же самое.
    _with_character(monkeypatch)
    assert strength(G.build_graph("t", 1, (64, 64), "p", "night")) == \
        pytest.approx(G.DISPOSABLE_BY_SCENE["night"])


def test_no_lora_is_silently_dropped(monkeypatch):
    """Каждая строка манифеста обязана оказаться в графе — с той же силой."""
    man = _with_character(monkeypatch)
    got = {n: s for n, s in _rows(G.build_graph("t", 1, (64, 64), "p", "day"))
           if s}
    for lora in G.lora_stack(man):
        if "disposable" in lora["name"].lower():
            continue          # её силу задаёт сцена, это проверяется отдельно
        assert lora["name"] in got, f"лора {lora['name']} потерялась"
        assert got[lora["name"]] == pytest.approx(lora["strength"])


def test_trigger_word_is_in_the_prompt_only_when_the_lora_is(monkeypatch):
    """Лора обучена на своём токене и БЕЗ НЕГО НЕ ВКЛЮЧАЕТСЯ. Молча не
    включившаяся лора неотличима от отсутствующей."""
    char, shots = P.load_project(os.path.join(ROOT, "projects", "bridget"))
    cell = shots["cells"][0]
    assert "chartest_w" not in P.build_cell(char, cell)

    man = copy.deepcopy(MANIFEST)
    man["models"]["character_lora"] = {"name": "char_test.safetensors",
                                       "strength": 0.9,
                                       "trigger": "chartest_w"}
    import _util
    monkeypatch.setattr(_util, "manifest", lambda: man)
    text = P.build_cell(char, cell)
    assert text.startswith("chartest_w"), (
        f"триггер не первым словом: {text[:60]}")


def test_manifest_declares_the_key_the_docs_point_at():
    """README и SKILL ссылаются на models.character_lora. Ключа в манифесте не
    было вовсе — ссылка вела в пустоту."""
    ch = MANIFEST["models"].get("character_lora")
    assert isinstance(ch, dict), "ключа character_lora нет в манифесте"
    assert set(ch) >= {"name", "strength", "trigger"}
    assert MANIFEST["models"].get("_character_lora"), (
        "ключ есть, а объяснения рядом нет")
