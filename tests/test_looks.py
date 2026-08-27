"""Названные образы: цена объявлена, и объявление сверяется с замером.

  py -3 -m pytest -q tests/test_looks.py

ЧТО ЗДЕСЬ СТЕРЕЖЁТСЯ. Образ — это обещание («так снято и вот чего это
стоит»), и у обещания ровно два способа испортиться молча. Первый: метрику не
померили, а образ выглядит проверенным — тот самый ложный зелёный, ради
которого в проекте три состояния, а не два. Второй: замер разошёлся с тем, что
образ про себя объявляет, — и разошёлся в любую из двух сторон, потому что
устаревшее предупреждение приучает пролистывать красное так же надёжно, как
его отсутствие.

Ни один тест здесь не ходит в сеть и не читает кадры: замер подставляется
словарём той же формы, что кладёт в grid.json scripts/lab_grid.py.
"""
import copy
import os
import re
import subprocess
import sys

import pytest

from conftest import MANIFEST, ROOT  # noqa: F401

from _util import age_band
import generate as G
import lab_grid as LG
import looks as L


def _run(argv, env=None):
    """Запуск скрипта отдельным процессом — как его зовёт человек из README.

    Адрес воркера вычищается из окружения: команда, обещанная как «без GPU»,
    обязана работать у того, кто ComfyUI ещё не настраивал.
    """
    e = dict(os.environ, PYTHONIOENCODING="utf-8")
    e.pop("COMFY_HOST", None)
    e.update(env or {})
    return subprocess.run([sys.executable, *argv], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          env=e, cwd=ROOT, timeout=180)


def _gates(**over):
    """Копия ворот манифеста с точечной правкой. Копия, чтобы тест, который
    двигает порог, не влиял на соседний через общий словарь."""
    g = copy.deepcopy(MANIFEST["gates"])
    g.update(over)
    return g


# Карточка персонажа для замеров. Возраст здесь есть не для красоты: полоса
# возраста считается ОТ НЕГО (_util.age_band), а не лежит числами в манифесте,
# и вердикт, снятый без карточки, про возраст ничего не знает.
CARD = {"id": "стендовая", "age": 50}


def _ok(gates=None, char=CARD):
    """Замер, который проходит ВСЕ ворота. Числа считаются ИЗ ПОРОГОВ.

    Константы здесь были бы четвёртой точкой правды про пороги (после
    манифеста, метрик и ворот) и устарели бы на первой же перекалибровке —
    ровно так, как это уже случалось с прозой в манифесте.
    """
    out = {}
    for metric, (lo, hi) in L._bounds(gates or _gates(), char).items():
        out[metric] = ((lo + hi) / 2 if lo is not None and hi is not None
                       else lo * 1.05 if lo is not None else hi * 0.5)
    return out


def _rows(base, **per_look):
    """Строки сетки той же формы, что кладёт в grid.json lab_grid.

    Аргументы — {сид: {метрика: СДВИГ от годного замера}} на каждый вариант.
    Сдвигами, а не абсолютными числами: годный замер считается из порогов
    манифеста и переезжает вместе с ними, а «на 40 резкости выше базы» — это
    утверждение о цене, и оно от порогов не зависит.
    """
    g = _gates()
    rows = []
    for variant, per_seed in [(L.BASE, base)] + list(per_look.items()):
        for seed, over in per_seed.items():
            row = _ok(g)
            for metric, delta in over.items():
                row[metric] += delta
            row["вариант"], row["сид"] = variant, seed
            rows.append(row)
    return rows


def _write(tmp_path, rows, name="grid.json"):
    import json
    p = tmp_path / name
    p.write_text(json.dumps({"cell": "P1", "axis": L.AXIS,
                             "seeds": sorted({r["сид"] for r in rows}),
                             "rows": rows}, ensure_ascii=False),
                 encoding="utf-8")
    return str(p)


def _grid(tmp_path, **per_look):
    """Сетка на двух сидах: база и перечисленные образы с одним и тем же
    сдвигом на обоих сидах — то есть с устойчивой ценой."""
    return _write(tmp_path, _rows({11: {}, 22: {}},
                                  **{k: {11: v, 22: v}
                                     for k, v in per_look.items()}))


def _check(name, measured, gates=None, per_seed=None, char=CARD):
    """check() с карточкой персонажа — как его зовёт скрипт из main().

    Карточка подставляется по умолчанию, чтобы возраст в этих тестах СУДИЛСЯ, а
    не тихо уходил в незамер: ворота возраста справочные, и вердикт от их
    исчезновения не меняется — то есть потеря полосы прошла бы через весь файл
    незамеченной. Путь без карточки проверяется отдельным тестом, и там она не
    подставляется намеренно.
    """
    return L.check(name, measured, gates, per_seed, char)


def _check_grid(path, gates=None, char=CARD):
    """check_grid() с карточкой — по той же причине, что и _check."""
    return L.check_grid(path, gates, char)


def _chain(graph):
    """Цепочка лор от сэмплера назад к базовой модели: [(имя, сила), ...].

    Та же конструкция, что в test_lora_chain: граф соединён model→model, и
    единственный способ проверить, что добавка ДОЕХАЛА до сэмплера, — пройти
    цепочку от него.
    """
    out, node = [], graph["7"]["inputs"]["model"][0]
    while node != "1":
        n = graph[node]
        out.append((n["inputs"].get("lora_name"),
                    n["inputs"].get("strength_model")))
        node = n["inputs"]["model"][0]
    return list(reversed(out))


# ------------------------------------------------------------------ данные

def test_every_look_says_what_it_is_for():
    """Образ без назначения — это набор лор, а не выбор. Ровно то, чем была
    работа до этого файла: «фотореализм» и никакого заявленного взгляда."""
    assert L.names(), "образов нет вовсе"
    for name in L.names():
        look = L.LOOKS[name]
        for field in ("title", "why", "light", "limits", "tail"):
            assert look.get(field, "").strip(), f"{name}: пустое поле {field}"
        assert look["loras"], f"{name}: пустой стек — это база, а не образ"
        assert look["fits"], f"{name}: не сказано, на каких сценах он уместен"
        for lora, strength in look["loras"]:
            assert lora.endswith(".safetensors"), f"{name}: {lora}"
            assert 0 < float(strength) <= 1.5, f"{name}: сила {strength}"


def test_prose_of_a_look_carries_no_measured_numbers():
    """ПОДПИСНАЯ ОШИБКА ПРОЕКТА, найденная семь раз: измеренное число в прозе
    рядом с кодом, который это число меняет. Цена образа живёт в
    docs/looks.md, который пишет скрипт из замера стенда, — а в полях why /
    light / limits ей делать нечего, потому что здесь её никто не пересчитает.

    Ловятся именно те формы, в которых замер и приходит: дробь (0.140) и
    трёхзначное целое (410). Силы лор под это правило не попадают — они лежат
    в поле loras, а не в прозе."""
    bad = re.compile(r"\d+[.,]\d|\b\d{3,}\b")
    for name in L.names():
        for field in ("why", "light", "limits"):
            hit = bad.search(L.LOOKS[name][field])
            assert not hit, (f"{name}.{field}: число «{hit.group()}» в прозе — "
                             f"его место в docs/looks.md, который пишет "
                             f"looks.py --md из замера lab_grid.py")


def test_unknown_look_is_loud_not_empty():
    """Опечатка в имени обязана падать. Пустой стек нарисовал бы кадр БЕЗ
    образа, положил бы его в реестр и в сдачу, и отличить его от кадра с
    образом было бы нечем."""
    with pytest.raises(SystemExit) as e:
        L.stack("windwo_noon")
    assert "window_noon" in str(e.value), "в отказе нет списка известных имён"


def test_no_look_is_the_pipeline_as_it_was():
    """None — штатный режим «образ не назначен», а не ошибка: конвейер без
    образа обязан работать ровно как работал, без ветвления у вызывающего."""
    assert L.stack(None) == [] and L.tail(None) == ""


def test_look_does_not_re_add_a_lora_from_the_base_stack():
    """Второй экземпляр той же лоры в цепочке ComfyUI не ошибка — он
    складывается по силе. То есть образ, повторивший строку манифеста, молча
    меняет чужую настройку, и найти это можно только по номеру узла."""
    for name in L.names():
        assert L.conflicts_with_base(name) == [], (
            f"{name} повторяет лору базового стека — силы сложатся молча")


def test_suits_answers_before_the_gpu():
    """Грейд не на своей сцене виден только на готовом кадре, а стоит столько
    же, сколько правильный."""
    name = "window_noon"
    for scene in L.LOOKS[name]["fits"]:
        assert L.suits(name, scene)
    assert not L.suits(name, "flash")
    assert L.suits(None, "flash"), "без образа ограничивать нечего"


# ------------------------------------------------------------------ ворота

def test_unmeasured_metric_is_not_measured_and_never_pass():
    """ГЛАВНЫЙ ТЕСТ ФАЙЛА. Образ, у которого не померили обязательные ворота,
    неотличим от образа, у которого они в допуске, — если молчание считать
    согласием. Здесь оно им не считается."""
    g = _gates()
    measured = _ok(g)
    measured.pop("sharp")
    res = _check("window_noon", measured, g)
    assert res["verdict"] == "NOT_MEASURED", res
    assert "sharp" in res["missing"]
    assert not res["accepted"], "незамер не может быть принят"
    assert res["gates"]["sharp"]["state"] == "NOT_MEASURED"
    assert res["gates"]["sharp"]["note"], "незамер без причины неотличим от бага"


def test_whole_grid_without_a_row_keeps_the_look_in_the_report(tmp_path):
    """Образ, которого нет в замере, обязан остаться в отчёте с NOT_MEASURED.
    Выпасть из таблицы — это и есть молчание: именно так из вердикта исчезали
    непромеренные кадры (см. _util.verdict_coverage)."""
    grid = tmp_path / "grid.json"
    grid.write_text('{"cell": "P1", "seeds": [1], "rows": []}',
                    encoding="utf-8")
    res = _check_grid(str(grid))
    assert set(res["looks"]) == set(L.names())
    for name, r in res["looks"].items():
        assert r["verdict"] == "NOT_MEASURED" and not r["accepted"], name
        assert r["why_not_measured"], name


def test_metric_out_of_the_gate_is_a_fail():
    """Перешарп — это не «зато красиво»: верхняя граница резкости стоит
    против звенящих краёв, подписи апскейлера."""
    g = _gates()
    measured = _ok(g)
    measured["sharp"] = g["face_sharp_max"] + 1
    res = _check("warm_flat", measured, g)
    assert res["verdict"] == "FAIL" and "sharp" in res["failed"]
    assert res["undeclared"] == ["sharp"], "провал не объявлен, а тест молчит"
    assert not res["accepted"]


def test_thresholds_come_from_the_manifest_not_from_a_copy():
    """Образ, судимый своей копией порогов, разошёлся бы с воротами на первой
    же перекалибровке — и разошёлся бы молча. Порог резкости в этом проекте
    уже переезжал, и при старом числе ворота пропускали мыло."""
    g = _gates()
    measured = _ok(g)
    assert _check("soft_matte", measured, g)["verdict"] == "PASS"
    tight = _gates(face_sharp_max=measured["sharp"] - 1)
    assert _check("soft_matte", measured, tight)["verdict"] == "FAIL", (
        "порог из манифеста не подействовал — значит он зашит в looks.py")


def test_the_age_band_is_this_character_s_band_not_a_number_from_the_manifest():
    """Полоса возраста считается от возраста КАРТОЧКИ, а не лежит числами в
    манифесте: жёсткие age_min/age_max верны ровно для одной женщины, и вторая
    проваливала бы ворота возраста самим фактом своего существования.

    Проверяется тем, что один и тот же замер меняет состояние ворот при смене
    карточки — то есть полоса действительно ЕЁ, а не общая. Числа обеих полос
    берутся у _util.age_band: своя формула здесь была бы четвёртой точкой
    правды про возраст.
    """
    g = _gates()
    young, old = {"id": "м", "age": 30}, {"id": "с", "age": 60}
    measured = _ok(g, old)
    measured["age"] = sum(age_band(old, g)) / 2      # середина полосы старшей

    assert _check("window_noon", measured, g, char=old)["gates"]["age"][
        "state"] == "PASS", "возраст не судится полосой своей карточки"
    res = _check("window_noon", measured, g, char=young)
    assert res["gates"]["age"]["state"] == "FAIL", (
        "полоса не поехала за карточкой — значит она зашита числами, и второй "
        "персонаж будет судим полосой первого")
    # Ворота возраста справочные: подменённая полоса не меняет вердикт образа
    # и потому проходит через весь файл незаметно. Смотреть надо на сами
    # границы, а не на PASS/FAIL всего образа.
    assert res["gates"]["age"]["min"] == age_band(young, g)[0]


def test_without_a_card_the_age_band_is_unknown_and_that_is_not_a_pass():
    """ТРЕТЬЕ СОСТОЯНИЕ ДЛЯ ПОЛОСЫ. Замер, прочитанный без карточки (`--grid`
    без `--project`), про возраст не знает ничего. Молча выкинуть метрику
    значило бы выдать образ проверенным по батарее, из которой вынули ворота, а
    судить чужой полосой — мерить не того человека.

    Ворота возраста здесь справочные, поэтому вердикт образа не пострадает ни
    при каком исходе — и тем вернее незамер прошёл бы незамеченным.
    """
    g = _gates()
    measured = _ok(g)
    res = _check("window_noon", measured, g, char=None)
    assert "age" in res["gates"], (
        "возраст пропал из отчёта целиком — а пустая клетка читается как «к "
        "образу неприменимо», то есть как согласие")
    gate = res["gates"]["age"]
    assert gate["state"] == "NOT_MEASURED", (
        "возраст судится без карточки — значит полоса взята из воздуха")
    assert gate["min"] is None and gate["max"] is None
    assert "карточк" in gate["note"], "незамер без причины неотличим от бага"


def test_informational_gates_report_but_do_not_block():
    """Идентичность на этом конвейере провалена у ВСЕХ кадров, включая базу
    (assets.json → gates._identity_is_informational). Судить ею образы значило
    бы забраковать все разом — и при этом ничего не измерить."""
    g = _gates()
    measured = _ok(g)
    measured["identity"] = g["identity_cosine_min"] - 0.2
    measured["age"] = age_band(CARD, g)[0] - 10
    res = _check("window_noon", measured, g)
    assert res["verdict"] == "PASS", "справочные ворота забраковали образ"
    assert res["gates"]["identity"]["state"] == "FAIL", (
        "число справочных ворот пропало из отчёта — отказ блокировать не есть "
        "отказ измерять")
    assert "identity" in res["informational"]


def test_no_required_gates_is_a_refusal_not_a_green_light():
    """Список обязательных ворот, целиком уехавший в справочные, означает, что
    судить образ нечем, и каждый вышел бы с PASS. Тот же отказ, что в
    gates.run_gates, и по той же причине."""
    g = _gates(required=["chroma"], informational=["chroma", "identity"])
    with pytest.raises(SystemExit):
        _check("soft_matte", _ok(), g)


def test_required_gate_the_bench_cannot_measure_is_not_measured():
    """Ворота, которые стенд не считает (тату, внешний детектор), обязаны
    остаться незамером, а не выпасть из вердикта: образ иначе выходит
    проверенным, ни разу не встретившись с половиной блокирующей батареи."""
    g = _gates(required=["chroma", "sharp", "skin", "tattoo"])
    res = _check("window_noon", _ok(g), g)
    assert res["verdict"] == "NOT_MEASURED" and "tattoo" in res["missing"]
    assert res["gates"]["tattoo"]["note"], "незамер без причины"


def test_declaration_is_checked_in_both_directions():
    """Объявленный провал — честная пометка. Необъявленный — образ, который
    врёт про себя. Объявленный, но не подтверждённый замером, — устаревшее
    предупреждение, а оно приучает проходить мимо красного."""
    g = _gates()
    over = _ok(g)
    over["sharp"] = g["face_sharp_max"] + 1

    honest = copy.deepcopy(L.LOOKS["warm_flat"])
    honest["out"] = ["sharp"]
    stale = copy.deepcopy(honest)

    saved = L.LOOKS["warm_flat"]
    try:
        L.LOOKS["warm_flat"] = honest
        res = _check("warm_flat", over, g)
        assert res["verdict"] == "FAIL" and res["accepted"], (
            "объявленный заранее провал обязан считаться честной пометкой")
        assert res["undeclared"] == []

        L.LOOKS["warm_flat"] = stale
        res = _check("warm_flat", _ok(g), g)
        assert res["stale_declarations"] == ["sharp"], (
            "объявление, которого замер не подтверждает, прошло молча")
        assert not res["accepted"]
    finally:
        L.LOOKS["warm_flat"] = saved


def test_cost_is_counted_against_the_base_row_of_the_same_grid(tmp_path):
    """Цена образа — это разница с базой ТОЙ ЖЕ сетки, а не с прошлым
    прогоном: сид фиксирован по строке, и сравнивать можно только внутри."""
    res = _check_grid(_grid(tmp_path, soft_matte={"sharp": +40}))
    assert res["looks"]["soft_matte"]["cost"]["sharp"] == pytest.approx(40)
    assert res["looks"]["window_noon"]["cost"]["sharp"] is None, (
        "цена посчиталась образу, которого в замере не было")


def test_cost_is_paired_seed_to_seed_not_a_difference_of_two_means(tmp_path):
    """Сид закреплён по строке сетки ради парности. Разница средних её теряет:
    у базы и образа наборы сидов могут не совпасть (кадр не отрисовался, лицо
    не нашлось), и тогда «цена» — это разница между разными наборами кадров.
    Считать надо по общим сидам, пара к паре."""
    res = _check_grid(_write(tmp_path, _rows({11: {}, 22: {"sharp": +100}},
                                              soft_matte={11: {"sharp": +40}})))
    # Общий сид один — 11, и цена по нему +40. Разница средних дала бы
    # +40 - 50 = -10, то есть цену противоположного знака.
    assert res["looks"]["soft_matte"]["cost"]["sharp"] == pytest.approx(40), (
        "цена посчитана по средним, а у базы и образа разные наборы сидов")


def test_a_cost_whose_sign_flips_between_seeds_is_marked_not_averaged(tmp_path):
    """ГЛАВНАЯ ЛОВУШКА ЦЕНЫ. Три пары могут смотреть в разные стороны, и
    среднее по ним выглядит как маленькая аккуратная цена. Разброс между
    сидами на этом конвейере больше цены образа, поэтому «плавает знак» —
    частый ответ, и он обязан быть виден: такую цену нельзя ни предъявлять,
    ни закладывать в выбор образа."""
    res = _check_grid(_write(tmp_path, _rows(
        {11: {}, 22: {}},
        soft_matte={11: {"sharp": +60}, 22: {"sharp": -60}}), "flip.json"))
    r = res["looks"]["soft_matte"]
    assert r["cost"]["sharp"] == pytest.approx(0), "проверяется не тот случай"
    assert r["cost_firm"]["sharp"] is False, "знак пляшет, а цена подана как факт"
    assert "знак плавает" in L.doc(res), "в документе цена выглядит измеренной"

    firm = _check_grid(_write(tmp_path, _rows(
        {11: {}, 22: {}},
        soft_matte={11: {"sharp": +60}, 22: {"sharp": +40}}), "firm.json"))
    assert firm["looks"]["soft_matte"]["cost_firm"]["sharp"] is True


def test_a_cost_that_is_zero_on_every_seed_is_a_result_not_a_wobble(tmp_path):
    """«+0.000, +0.000, +0.000» — это измеренный ответ «образ эту метрику не
    трогает», а не пляшущий знак и не погрешность округления. Свалить его в
    общее «не устойчиво» значит выбросить единственную новость, которую эта
    строка несёт."""
    res = _check_grid(_grid(tmp_path, soft_matte={}))
    assert res["looks"]["soft_matte"]["cost_firm"]["sharp"] is True
    # Смотреть надо в РАЗДЕЛ образа, а не во весь документ: «знак плавает»
    # стоит ещё и в объяснении того, как читать цену, и проверка по всему
    # тексту прошла бы одинаково при любой починке.
    body = (L.doc(res).split(f"## {L.LOOKS['soft_matte']['title']}")[1]
            .split("\n## ")[0])
    # Проверяется РОВНО та строка, которую печатает код. Первая редакция
    # искала «не трогает» — и оставалась зелёной на сломанном коде, потому что
    # ровно эти слова стоят в описании самого образа («Цвет образ не
    # трогает»). Мутационный прогон это и показал.
    assert "0 на всех сидах" in body, body
    assert "знак плавает" not in body, body


def test_a_gate_busted_on_one_seed_is_not_hidden_by_the_average(tmp_path):
    """Вердикт образа считается по СРЕДНЕМУ трёх кадров, и среднее прячет
    одиночный провал: образ, у которого один сид из трёх вышел за ворота,
    отправляет треть кадров в брак — а в таблице средних выглядит чистым. Тот
    же дефект, из-за которого в проекте частичный вердикт перестал выдавать
    себя за полный, только спрятанный усреднением, а не выборкой."""
    g = _gates()
    ok = _ok(g)
    high = g["face_sharp_max"] - ok["sharp"] + 50      # сид 11 — за верх ворот
    low = -(ok["sharp"] - g["face_sharp_min"]) / 2     # сид 33 — с запасом внутри
    res = _check_grid(_write(tmp_path, _rows(
        {11: {}, 22: {}, 33: {}},
        soft_matte={11: {"sharp": high}, 22: {}, 33: {"sharp": low}})))
    r = res["looks"]["soft_matte"]

    assert r["values"]["sharp"] < g["face_sharp_max"], (
        "проверяется не тот случай: среднее и само за воротами")
    assert r["gates"]["sharp"]["state"] == "PASS", "то же самое"
    assert r["seed_fails"]["sharp"] == [11], r["seed_fails"]
    assert not r["accepted"], "провал на сиде принят как чистый образ"
    assert "sharp" in r["undeclared"]
    text = L.doc(res)
    assert "не на каждом сиде" in text and "11" in text


def test_a_single_seed_proves_no_stability_and_says_so(tmp_path):
    """Третье состояние и здесь: на одном сиде устойчивость не проверяется
    вовсе, и True тут значило бы «проверено» ровно там, где не проверялось."""
    res = _check_grid(_write(tmp_path, _rows({11: {}},
                                              soft_matte={11: {"sharp": +60}})))
    assert res["looks"]["soft_matte"]["cost_firm"]["sharp"] is None
    assert "устойчивость не проверена" in L.doc(res)


# ------------------------------------------------------------------ стенд

@pytest.mark.parametrize("name", L.names())
def test_the_stack_of_a_look_reaches_the_sampler(name):
    """Добавка обязана ДОЕХАТЬ до сэмплера. В шаблоне пять слотов лоры и в
    манифесте пять реализм-лор: свободных слотов нет вообще, и добавка,
    положенная в слот, была бы молча отброшена вместе со всем образом."""
    graph = G.build_graph("t", 1, (64, 64), "p")
    before = _chain(graph)
    after = _chain(LG.stack_loras(graph, L.stack(name)))
    assert len(after) == len(before) + len(L.stack(name))
    got = dict(after[len(before):])
    for lora, strength in L.stack(name):
        assert got[lora] == pytest.approx(strength), f"{name}: {lora}"


def test_nothing_here_imports_the_pipeline_or_the_bench_at_module_level():
    """Образы вписываются В КОНВЕЙЕР, то есть generate.py будет импортировать
    этот модуль сверху файла. Встречный импорт отсюда даёт кольцо, и кольцо
    это работает — ровно до тех пор, пока ни одна сторона не тронет другую на
    уровне модуля. Ломается оно поэтому не при вписывании, а позже и у того,
    кто про кольцо не знает.

    Разбирается ДЕРЕВО, а не текст: `grep import generate` одинаково находит
    и ленивый импорт внутри функции, ради которого всё и делалось.
    """
    import ast
    src = open(os.path.join(ROOT, "scripts", "looks.py"),
               encoding="utf-8").read()
    top = [n for n in ast.parse(src).body
           if isinstance(n, (ast.Import, ast.ImportFrom))]
    named = {a.name for n in top if isinstance(n, ast.Import) for a in n.names}
    named |= {n.module for n in top if isinstance(n, ast.ImportFrom)}
    assert not named & {"generate", "lab_grid"}, (
        f"импорт {named & {'generate', 'lab_grid'}} на уровне модуля — "
        f"конвейеру не встроиться без кольца")
    # Ленивые ссылки обязаны при этом работать: тест, который добился бы
    # отсутствия импорта ценой отсутствия функции, ничего не сторожит.
    assert L._pipeline().lora_stack and L._bench().stack_loras


@pytest.mark.parametrize("name", L.names())
def test_the_pipeline_hangs_the_look_with_the_same_hands_as_the_bench(name):
    """Конвейер и стенд обязаны собирать образ ОДНИМ кодом. Копия
    цепочки-накопителя в generate.py означала бы, что сдают не то, что меряли,
    — а вопрос «то же ли это самое» и есть весь смысл стенда.

    Сравнивается не «похоже», а граф с графом: расходятся они силой или
    порядком звеньев, и глазами это не видно.
    """
    mine = L.apply(G.build_graph("t", 1, (64, 64), "p"), name)
    bench = LG.stack_loras(G.build_graph("t", 1, (64, 64), "p"), L.stack(name))
    assert mine == bench, f"{name}: конвейер вешает образ иначе, чем стенд"
    assert _chain(mine)[-len(L.stack(name)):] == L.stack(name)


def test_without_a_look_the_graph_and_the_prompt_are_untouched():
    """«Образ не назначен» — штатный режим, а не деградация: конвейер без
    образа обязан отрисовать РОВНО тот же кадр, что и до появления этого
    файла. Лишняя запятая в хвосте промпта при cfg 1.0 — уже другой кадр на
    том же сиде, и заметить это по картинке нельзя."""
    graph = G.build_graph("t", 1, (64, 64), "p")
    assert L.apply(copy.deepcopy(graph), None) == graph
    assert L.dress("портрет", None) == "портрет"


@pytest.mark.parametrize("name", L.names())
def test_the_tail_of_a_look_joins_the_prompt_exactly_once(name):
    """Хвост обязан доехать до промпта и приехать туда один раз: стенд меряет
    образ ВМЕСТЕ с его хвостом, и кадр сдачи без хвоста — это другой образ с
    той же ценой в документе."""
    got = L.dress("портрет", name)
    assert got.endswith(L.LOOKS[name]["tail"])
    assert got.count(L.LOOKS[name]["tail"]) == 1
    assert ", ," not in got and not got.rstrip().endswith(",")


@pytest.mark.parametrize("name", L.names())
def test_the_pipeline_and_the_bench_glue_the_tail_the_same_way(name, monkeypatch):
    """Хвост к промпту приклеивают ДВОЕ: стенд — сам, у себя в run(), из своего
    словаря; конвейер — через dress(). Разъехавшись хоть пробелом, они дадут
    сдачу, снятую не тем промптом, который померили, — а цена в документе
    останется от померенного. Заметить это по кадру нельзя.

    Склейка стенда лежит ВНУТРИ его боевого цикла — в той же строке, что и
    отправка на воркер, — и позвать её без GPU нельзя. Поэтому вторая половина
    контракта закреплена сверкой с исходником: пин по тексту здесь не замена
    проверке поведения (она ниже, на настоящей dress), а единственный сторож
    для той стороны, которую не выполнить. Уехала строка стенда — тест падает
    вслух и называет, что сравнивать.
    """
    import inspect
    monkeypatch.setattr(LG, "AXES", copy.deepcopy(LG.AXES))
    monkeypatch.setattr(LG, "AGE_SUFFIX", copy.deepcopy(LG.AGE_SUFFIX))
    L.register_axis(LG)

    src = inspect.getsource(LG.run)
    assert 'text = prompt + ", " + AGE_SUFFIX[name]' in src, (
        "стенд склеивает хвост не так, как здесь записано, — сравнить не с чем")
    assert L.dress("портрет", name) == "портрет" + ", " + LG.AGE_SUFFIX[name]


def test_axis_starts_with_the_base_row():
    """Стенд считает цену как разницу с вариантом «база». Переименование или
    потеря этой строки превращает всю колонку цены в прочерки — молча."""
    ax = L.axis()
    assert ax[0] == (L.BASE, []), ax[0]
    assert L.BASE in LG.AXES["look"][0][0], (
        "имя базовой строки разошлось с lab_grid")
    assert [n for n, _ in ax[1:]] == L.names()


def test_the_bench_learns_the_axis_and_the_tails_of_every_look(monkeypatch):
    """Стенд не знает про образы, пока ось ему не ОБЪЯВЯТ: в lab_grid.AXES её
    нет, и прямой вызов с `--axis looks` падает «нет оси». Ровно этим документ
    и врал — печатал команду пересчёта, которой не существует.

    Проверяются обе половины регистрации. Ось без хвостов означает, что каждый
    образ меряли БЕЗ его промпта, то есть меряли не его, — и заметить это по
    таблице нельзя: строк ровно столько, сколько ждёшь.
    """
    monkeypatch.setattr(LG, "AXES", copy.deepcopy(LG.AXES))
    monkeypatch.setattr(LG, "AGE_SUFFIX", copy.deepcopy(LG.AGE_SUFFIX))
    assert L.AXIS not in LG.AXES, "ось объявилась сама — тест ничего не ловит"

    L.register_axis(LG)
    assert [v for v, _ in LG.AXES[L.AXIS]] == [L.BASE] + L.names()
    for name in L.names():
        assert LG.AGE_SUFFIX.get(name) == L.LOOKS[name]["tail"], (
            f"{name}: стенд померил бы образ без его хвоста промпта")


def test_registering_over_a_foreign_tail_is_a_refusal(monkeypatch):
    """Словарь хвостов у стенда ОДИН на все оси. Образ, чьё имя совпало со
    строкой чужой оси, переписал бы ей промпт — и та начала бы мерить не то,
    что меряла, не оставив следа ни в таблице, ни в grid.json."""
    monkeypatch.setattr(LG, "AGE_SUFFIX",
                        dict(LG.AGE_SUFFIX, **{L.names()[0]: "чужой хвост"}))
    monkeypatch.setattr(LG, "AXES", copy.deepcopy(LG.AXES))
    with pytest.raises(SystemExit) as e:
        L.register_axis(LG)
    assert L.names()[0] in str(e.value)


def test_the_cli_judges_age_by_the_card_of_the_project_it_was_given(
        tmp_path, monkeypatch):
    """Полосу возраста скрипту приносит --project, и потерять её он может
    молча: ворота возраста справочные, вердикт образа от них не меняется, и
    отчёт без карточки выглядит ровно так же — только в колонке ворот стоит
    прочерк, а состояние NOT_MEASURED. Проверяется настоящим процессом, потому
    что теряется карточка именно в main(), а не в судящих функциях.

    Замер подставной, но лежит там, где скрипт его ищет САМ: путь и карточку
    даёт project_grid, то есть та же функция, которой пользуется main.
    """
    work = tmp_path / "work"
    monkeypatch.setenv("PERSONA_WORK_ROOT", str(work))
    dst, char = L.project_grid("bridget")

    import json
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    rows = _rows({11: {}, 22: {}}, **{n: {11: {}, 22: {}} for n in L.names()})
    for row in rows:
        row["age"] = float(char["age"])          # ровно возраст карточки
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump({"cell": "P1", "axis": L.AXIS, "seeds": [11, 22],
                   "rows": rows}, fh, ensure_ascii=False)

    r = _run(["scripts/looks.py", "--check", "--project", "bridget"],
             env={"PERSONA_WORK_ROOT": str(work)})
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    lo, hi = age_band(char, MANIFEST["gates"])
    band = L._range({"gate": "age", "min": lo, "max": hi})
    assert band in r.stdout, (
        f"скрипт не показал полосу возраста {band} — карточка до ворот не "
        f"доехала:\n{r.stdout}")
    ages = [ln for ln in r.stdout.splitlines() if "возраст" in ln]
    assert ages and all("NOT_MEASURED" not in ln for ln in ages), ages


def test_the_recount_command_from_the_doc_actually_runs(tmp_path):
    """ГЛАВНЫЙ ТЕСТ ЭТОГО КУСКА. Документ обязан называть команду, которой его
    числа пересчитываются, и эта команда обязана работать. Здесь она НЕ
    работала: документ печатал прямой вызов стенда с осью, про которую стенд
    ничего не знает. Читатель узнаёт об этом, только попробовав, — а
    попробовать он собирается ровно тогда, когда числам перестал верить.

    Команда берётся ИЗ ТОЙ ЖЕ функции, что печатает документ, и запускается
    настоящим процессом в сухом режиме: без GPU, без сети, без записи кадров.
    """
    res = _check_grid(_grid(tmp_path))
    text = L.doc(res)
    assert L.measure_cmd() in text and L.doc_cmd() in text, (
        "документ печатает не ту команду, которую сам же собирает")

    work = tmp_path / "work"
    argv = L.measure_cmd("bridget", "P1", "11,22").split()[2:]
    assert argv[0].endswith("looks.py")
    r = _run(argv + ["--dry"], env={"PERSONA_WORK_ROOT": str(work)})
    assert r.returncode == 0, (
        f"команда пересчёта из документа не работает:\n{r.stdout}\n{r.stderr}")
    for name in L.names():
        assert name in r.stdout, f"{name} не попал в сетку стенда"
    # Сухой прогон обещан как «ничего не отправляя» — и каталогов он тоже не
    # заводит: скрипт, который на вопрос отвечает пустой папкой в чужом
    # рабочем корне, ровно так же «отвечает» и на всё остальное.
    assert not work.exists(), "сухой прогон завёл рабочий каталог"


def test_suffixes_feed_the_bench_by_variant_name():
    """Стенд дописывает хвост варианту, чьё имя нашлось в его словаре: имена
    строки сетки и ключа хвоста обязаны совпадать, иначе образ меряется без
    своего промпта — и меряется, стало быть, не он."""
    suf = L.suffixes()
    for name, _ in L.axis()[1:]:
        assert suf.get(name) == L.LOOKS[name]["tail"], name
    assert L.BASE not in suf, "у базы не бывает хвоста образа"


# ------------------------------------------------------------------ документ

def test_doc_names_its_source_and_the_way_to_recount_it(tmp_path):
    """Число без способа его пересчитать — это проза, а проза расходится с
    кодом. Документ обязан называть скрипт, который числа печатает, и
    команду."""
    res = _check_grid(_grid(tmp_path))
    text = L.doc(res)
    assert "lab_grid.py" in text, "документ не называет того, кто печатает числа"
    assert L.measure_cmd() in text and L.doc_cmd() in text


def test_doc_keeps_every_look_and_marks_the_unmeasured_one(tmp_path):
    """Документ, который печатает только померенное, читается как «остальных
    образов нет». Их не «нет» — их цена неизвестна."""
    res = _check_grid(_grid(tmp_path, soft_matte={}))
    text = L.doc(res)
    for name in L.names():
        assert L.LOOKS[name]["title"] in text, name
    assert "NOT_MEASURED" in text
    body = text.split("## Полдень у окна")[1]
    assert "NOT_MEASURED" in body or "стенд этого образа не гонял" in text


def test_doc_shows_the_failure_and_says_what_to_do(tmp_path):
    """Провал в документе обязан быть виден и исполним: либо переподбирать
    силы, либо объявлять честно. «FAIL» без продолжения читается как деталь
    оформления."""
    g = _gates()
    res = _check_grid(_grid(tmp_path,
                             warm_flat={"sharp": g["face_sharp_max"] + 50}))
    text = L.doc(res)
    assert "FAIL" in text
    assert "переподбирать" in text or "объявлять" in text


def test_written_doc_says_it_is_generated(tmp_path):
    """Файл, который выглядит написанным руками, руками и правят — а правка
    переживёт ровно до следующего перепрогона."""
    out = tmp_path / "docs" / "looks.md"
    L.write_doc(str(out), _check_grid(_grid(tmp_path)))
    text = out.read_text(encoding="utf-8")
    assert "СГЕНЕРИРОВАНО" in text and "looks.py" in text


def test_repo_doc_is_in_sync_with_the_measurement():
    """docs/looks.md в репозитории обязан быть тем, что печатает скрипт по
    лежащему рядом замеру. Разошлись — значит документ правили руками либо
    забыли перегенерировать после перепрогона стенда.

    Пропускается, когда замера нет на этой машине: рабочий корень локален, и
    у рецензента кадров может не быть вовсе.
    """
    doc_path = os.path.join(ROOT, "docs", "looks.md")
    if not os.path.exists(doc_path):
        pytest.skip("docs/looks.md ещё не собран")
    with open(doc_path, encoding="utf-8") as fh:
        have = fh.read()
    # Замер И карточка берутся той же функцией, что зовёт main(): собранные
    # здесь по отдельности, они дали бы «расхождение» ровно тогда, когда
    # документ верен, — и научили бы чинить не то.
    grid, char = L.project_grid("bridget")
    if not os.path.exists(grid):
        pytest.skip(f"замера нет на этой машине: {grid}")
    assert have == L.doc(L.check_grid(grid, char=char)), (
        f"docs/looks.md разошёлся с замером — перегенерируй: "
        f"{L.doc_cmd('bridget')}")
