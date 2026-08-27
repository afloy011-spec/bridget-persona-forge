"""Управление кадром: контроль обязан ДОХОДИТЬ до того, что рисует кадр.

  py -3 -m pytest -q tests/test_control.py

ЧЕМ ЭТА ЧАСТЬ ОПАСНА. Собрать пять узлов контроля и не переставить последнюю
ссылку — сэмплер остаётся висеть на хвосте лор — можно так, что глазами по JSON
разницы не увидеть: узлы на месте, имена правильные, ссылки красивые. Прогон
после этого честно рисует лотерею и отчитывается как управляемый, а понять это
можно только по кадрам, то есть через GPU-час. Поэтому половина файла проверяет
не «построилось ли», а «дошло ли до сэмплера».

Второй нетривиальный кусок — сам замер. Метрика, которая режет ближнюю маску по
ПЕРЦЕНТИЛЮ, вырезает одинаковую площадь по построению, и масштаб фигуры после
неё всегда равен единице: число есть, промах показать нечем. Здесь это ловится
синтетическими картами, где правильный ответ известен заранее.

Сети тут нет: заливка опоры подменяется, живой замер живёт в CLI.
"""
import copy
import json
import os

import pytest

from conftest import MANIFEST, ROOT  # noqa: F401

import comfy_client as cc
import control as C
import generate as G

SPEC = {"image": "ref.jpg", "strength": 1.0, "kind": "depth"}


def _keep(path):
    """Заглушка заливки: путь остаётся путём, на сервер никто не ходит."""
    return path


def _base():
    return cc.load_template("krea2_t2i_api")


def _with_control(spec=None, graph=None):
    return C.attach_control(graph or _base(), spec or SPEC, uploader=_keep)


# ------------------------------------------------------- контроль доходит до кадра

def test_control_reaches_the_sampler():
    """Apply обязан лежать НА ПУТИ model к сэмплеру, а не просто в графе."""
    g = _with_control()
    path = C.model_path(g)
    assert path[-1] == C.control_state(g)["nodes"]["apply"], (
        f"хвост цепочки model — {path[-1]}, а не узел Apply; "
        f"сэмплер контроля не увидит")
    assert C.control_state(g)["state"] == C.ON


def test_stray_control_block_reads_absent():
    """ГЛАВНЫЙ ЛОЖНЫЙ ЗЕЛЁНЫЙ: блок собран, ссылка сэмплера не переставлена.

    Такой граф отличается от управляемого одной строкой JSON и рисует лотерею.
    control_state обязан назвать это ABSENT и показать пальцем на брошенные
    узлы, а не сказать «контроль есть».
    """
    g = _with_control()
    st = C.control_state(g)
    lora = st["nodes"]["lora"]
    # Ровно та ошибка: сэмплер возвращается на хвост лор, узлы остаются.
    g[st["sampler"]]["inputs"]["model"] = g[lora]["inputs"]["model"]
    after = C.control_state(g)
    assert after["state"] == C.ABSENT, f"брошенный блок прочитан как {after}"
    assert st["nodes"]["apply"] in after["why"], (
        f"в объяснении не названы брошенные узлы: {after['why']}")
    with pytest.raises(SystemExit):
        C.require_control(g)


def test_apply_without_the_control_lora_reads_off():
    """Apply без control-лоры перед ним — Apply в пустоту.

    Веса, которые умеют читать латент опоры, в модель не подмешаны, и узел
    получает латент, обрабатывать который нечем. Со стороны граф выглядит
    полным: пять узлов, ссылки на месте, сэмплер висит на Apply — то есть это
    ровно тот случай, который отличим только кодом.
    """
    g = _with_control()
    st = C.control_state(g)
    # Лора обходится: Apply берёт модель прямо оттуда, откуда её брала лора.
    g[st["nodes"]["apply"]]["inputs"]["model"] = \
        g[st["nodes"]["lora"]]["inputs"]["model"]
    after = C.control_state(g)
    assert after["state"] == C.OFF, after
    assert C.LORA_LOADER in after["why"]
    with pytest.raises(SystemExit):
        C.require_control(g)


def test_attaching_control_twice_is_refused():
    """Два Apply на одном пути — не «сильнее», а неопределённость.

    Легко получается из невнимательности: attach_control зовут в цикле по
    ячейкам и передают один и тот же граф. Молча собрать такой граф значит
    отдать GPU-час кадру, про который нельзя сказать, чему он следовал.
    """
    g = _with_control()
    with pytest.raises(SystemExit) as e:
        _with_control(graph=g)
    assert C.APPLY in str(e.value)


def test_plain_graph_reads_absent_with_a_reason():
    """Граф без контроля — ABSENT, и причина не пустая: пустое «почему»
    неотличимо от «проверка не отработала»."""
    st = C.control_state(_base())
    assert st["state"] == C.ABSENT
    assert st["why"].strip()
    assert st["kind"] is None and st["strength"] is None


def test_control_sits_on_top_of_however_many_loras(monkeypatch):
    """Контроль встаёт в ХВОСТ цепочки, какой бы длины она ни была.

    Прибитый номер узла (в базовом шаблоне хвост лор — 24) работает ровно до
    первой персонажной лоры в манифесте: она достраивает цепочку, номер съезжает,
    и контроль либо теряет часть лор, либо повисает в стороне.
    """
    def chain(graph):
        return C.model_path(graph)

    # ОПОРА «ДО» ЗАДАЁТСЯ ЯВНО — манифестом БЕЗ персонажной лоры. Раньше она
    # бралась из настоящего манифеста молча и совпадала с пустым ключом
    # случайно; в день, когда лору обучили и вписали, «до» стало уже содержать
    # её, подстановка тестовой лишь заменяла запись, и тест краснел на
    # исправном коде. Это третий тест в сьюте с той же болезнью — состояние
    # проекта не должно быть скрытым входом проверки.
    plain_man = copy.deepcopy(MANIFEST)
    plain_man["models"].pop("character_lora", None)
    monkeypatch.setattr(G, "manifest", lambda: plain_man)
    # Вызов сохранён, ПРИВЯЗКА УБРАНА: длина «до» больше не сравнивается
    # (см. комментарий ниже), но сама сборка графа без персонажной лоры
    # обязана оставаться в тесте — она и есть опора «до».
    chain(G.build_graph("t", 1, (64, 64), "p"))
    man = copy.deepcopy(MANIFEST)
    man["models"]["character_lora"] = {"name": "char_test.safetensors",
                                       "strength": 0.9, "trigger": "chartest_w"}
    monkeypatch.setattr(G, "manifest", lambda: man)
    longer = G.build_graph("t", 1, (64, 64), "p")
    # РОСТ МЕРИТСЯ ПО СТЕКУ ЛОР, А НЕ ПО ДЛИНЕ ПУТИ МОДЕЛИ. С Afloy Lora Box
    # путь всегда из двух узлов (загрузчик и коробка), сколько бы лор в ней ни
    # лежало, — прежняя проверка длины стала бы вечно красной на исправном
    # коде. Смысл теста прежний: добавленная лора обязана оказаться в графе, а
    # контроль — встать в хвост пути, каким бы тот ни был.
    import json as _json
    box = [n for n in longer.values() if isinstance(n, dict)
           and n.get("class_type") == "LoraBox"]
    assert box, "в графе нет ноды LoraBox — тест ни о чём"
    names = [r["name"] for r in _json.loads(box[0]["inputs"]["data"])["rows"]]
    assert "char_test.safetensors" in names, (
        f"персонажная лора не попала в стек: {names}")
    before = [n for n in chain(longer)
              if longer[n]["class_type"] == "LoraBox"]

    g = _with_control(graph=longer)
    st = C.control_state(g)
    path = C.model_path(g)
    assert path[-1] == st["nodes"]["apply"]
    # Стек лор остался ПОД контролем и не отвалился от пути модели.
    boxes = [n for n in path if g[n]["class_type"] == "LoraBox"]
    assert boxes == before, "нода лор потерялась под контролем"
    kept = [r["name"] for r in _json.loads(
        g[boxes[0]]["inputs"]["data"])["rows"]]
    assert "char_test.safetensors" in kept, (
        f"персонажная лора выпала из стека: {sorted(kept)}")


# ------------------------------------------------------- схема, разведанная у ноды

def test_control_latent_is_the_frame_latent():
    """Латент опоры берётся у ТОГО ЖЕ узла, из которого рисуется кадр.

    Иначе кодировщик подгоняет опору под чужой размер, и Apply складывает
    тензоры разной формы — либо падает, либо (что хуже) режет опору по центру
    другого кадра. Ячейка P2 просит 1024x1536 вместо 1152x1440, так что размеры
    в этом конвейере расходятся штатно.
    """
    g = _with_control()
    st = C.control_state(g)
    enc = g[st["nodes"]["encode"]]["inputs"]
    assert enc["latent"] == g[st["sampler"]]["inputs"]["latent_image"]
    assert enc["resize"] == "match_latent_size"


def test_control_uses_the_vae_that_decodes_the_frame():
    """VAE берётся у VAEDecode, а не «первый найденный VAELoader».

    Опора, закодированная другим VAE, лежит в другом пространстве, и контроль
    тянет кадр в шум. Проверяется на графе с ДВУМЯ загрузчиками — на одном
    ошибка неотличима от правильного поведения.
    """
    g = _base()
    g["90"] = {"class_type": "VAELoader",
               "inputs": {"vae_name": "чужой_vae.safetensors"}}
    g["8"]["inputs"]["vae"] = ["90", 0]
    st = C.control_state(_with_control(graph=g))
    assert g[st["nodes"]["encode"]]["inputs"]["vae"] == ["90", 0], (
        "опора кодируется не тем VAE, которым декодируется кадр")


def test_reference_goes_through_the_depth_preprocessor_in_the_graph():
    """Опорой должен работать ЛЮБОЙ снимок, а не готовая карта глубины.

    Значит цепочка обязана быть LoadImage → препроцессор → кодировщик. Если
    картинка идёт в кодировщик напрямую, человеку придётся готовить карты
    заранее — второй артефакт, который надо хранить и рассинхронизировать.
    """
    g = _with_control()
    n = C.control_state(g)["nodes"]
    assert g[n["depth"]]["class_type"] == C.DEPTH_PREPROCESSOR
    assert g[n["depth"]]["inputs"]["image"] == [n["image"], 0]
    assert g[n["image"]]["class_type"] == "LoadImage"
    assert g[n["encode"]]["inputs"]["control_image"] == [n["depth"], 0]


def test_two_samplers_are_refused_not_guessed():
    """Взять «первый попавшийся» сэмплер значит подключить контроль к одной
    ветке графа и отрапортовать об успехе, пока кадр рисует другая."""
    g = _base()
    g["70"] = copy.deepcopy(g["7"])
    with pytest.raises(SystemExit):
        C.attach_control(g, SPEC, uploader=_keep)


# ------------------------------------------------------- отказы вместо тихих no-op

def test_zero_strength_is_refused_before_the_upload():
    """Сила 0 — граф, который ВЫГЛЯДИТ управляемым и не управляется.

    Отказ обязан случиться ДО заливки опоры: она стоит круговой обход до общей
    машины и оставляет там файл, а бессмысленность запроса видна из самого
    запроса. Проверяется заливкой, которая падает, если её всё-таки позвали.
    """
    def never(_path):
        raise AssertionError("опора залита ради заведомо мёртвого графа")

    with pytest.raises(SystemExit) as e:
        C.attach_control(_base(), dict(SPEC, strength=0), uploader=never)
    assert "0" in str(e.value)


def test_unknown_kind_is_refused_by_name():
    """canny/openpose к Krea 2 не существует. Молча свалиться на depth значит
    выдать другую композицию за заказанную."""
    with pytest.raises(SystemExit) as e:
        C.attach_control(_base(), dict(SPEC, kind="canny"), uploader=_keep)
    assert "depth" in str(e.value)


def test_missing_reference_file_is_refused_before_the_queue():
    """Опора, которой нет на диске, обязана падать здесь, а не превращаться в
    имя файла на сервере, которого там тоже нет."""
    with pytest.raises(SystemExit):
        C.attach_control(_base(), dict(SPEC, image="нет-такого-файла.jpg"))


def test_reference_is_uploaded_once_per_batch(monkeypatch, tmp_path):
    """Батч на сорок кадров зовёт attach_control сорок раз. Сорок заливок
    одного файла — это сорок круговых обходов до общей машины."""
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"x")
    calls = []
    monkeypatch.setattr(cc, "upload", lambda p, *a, **k: calls.append(p) or "s/ref.png")
    monkeypatch.setattr(C, "_UPLOADED", {})
    for _ in range(3):
        C.attach_control(_base(), dict(SPEC, image=str(ref)))
    assert len(calls) == 1, f"опора залита {len(calls)} раз(а)"


def test_uploaded_reference_is_scrubbed_from_the_shared_machine(monkeypatch,
                                                                tmp_path):
    """Опора — СДАННЫЙ КАДР ЗАКАЗЧИКА на чужой машине. Удалить её по API нечем,
    но перезалить под тем же именем пустышкой можно, и это надо делать.

    Проверяется по содержимому: заглушка обязана быть картинкой (иначе
    LoadImage начнёт падать) и обязана быть заметно меньше опоры, иначе
    «затёрли» — это слово, а не действие.
    """
    from _util import imwrite
    import numpy as np
    ref = imwrite(str(tmp_path / "hero.png"),
                  np.random.randint(0, 255, (600, 480, 3), dtype="uint8"))
    sent = []
    monkeypatch.setattr(C, "_UPLOADED", {})
    monkeypatch.setattr(cc, "upload",
                        lambda p, *a, **k: sent.append(p) or
                        f"persona-forge/{os.path.basename(p)}")
    C.attach_control(_base(), dict(SPEC, image=ref))
    assert C.scrub_uploads() == ["persona-forge/hero.png"]
    assert len(sent) == 2 and os.path.basename(sent[1]) == "hero.png", sent
    assert not C._UPLOADED, "реестр залитого не очищен — второй scrub промолчит"


def test_measure_scrubs_the_reference_even_when_it_falls_over(monkeypatch,
                                                              tmp_path):
    """Падение на третьем сиде из трёх — это ровно тот случай, когда убрать за
    собой забывают наверняка, а кадр заказчика остаётся лежать в input/ чужой
    машины. Уборка обязана быть в finally, а не в конце удачного пути."""
    import numpy as np
    from _util import imwrite
    ref = imwrite(str(tmp_path / "hero.png"),
                  np.random.randint(0, 255, (600, 480, 3), dtype="uint8"))
    sent = []
    monkeypatch.setattr(C, "_UPLOADED", {})
    monkeypatch.setattr(cc, "preflight", lambda *a, **k: True)
    monkeypatch.setattr(cc, "upload",
                        lambda p, *a, **k: sent.append(os.path.getsize(p)) or
                        f"persona-forge/{os.path.basename(p)}")

    def boom(*a, **k):
        raise RuntimeError("воркер упал посреди замера")

    monkeypatch.setattr(cc, "run_graph", boom)
    with pytest.raises(RuntimeError):
        C.measure(os.path.join(ROOT, "projects", "bridget"), ref,
                  seeds=[1], out_md=str(tmp_path / "r.md"))
    assert len(sent) == 2, f"опора залита {len(sent)} раз, затёрта — нет: {sent}"
    assert sent[1] < sent[0] / 10, f"затёрли не заглушкой: {sent}"


def test_scrub_stub_is_a_real_image_and_tiny(tmp_path, monkeypatch):
    """Заглушка проверяется отдельно: она уезжает на чужую машину, и «пустышка»,
    которую не открыть, ломает там чужой LoadImage."""
    import cv2
    from _util import imread
    seen = {}

    def grab(path, *a, **k):
        seen["path"] = path
        seen["bytes"] = os.path.getsize(path)
        seen["img"] = imread(path, cv2.IMREAD_COLOR)
        return "persona-forge/x.png"

    monkeypatch.setattr(C, "_UPLOADED", {("k", 1, 1): "persona-forge/x.png"})
    C.scrub_uploads(uploader=grab)
    assert seen["img"] is not None and seen["img"].shape[:2] == (1, 1)
    assert seen["bytes"] < 1024, f"заглушка на {seen['bytes']} байт"
    assert not os.path.exists(seen["path"]), "временный файл заглушки не убран"


# ------------------------------------------------------- шаблон и код не расходятся

def _tpl(name):
    with open(os.path.join(ROOT, "templates", "comfy", name + ".json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def test_template_is_exactly_what_the_code_builds():
    """Шаблон существует для глаз, схему строит код. Разойтись им нельзя.

    Файл открывают в ComfyUI, правят там ручку и забывают перенести в код —
    после чего конвейер месяцами гоняет схему, которой в репозитории не видно.
    """
    built = C.attach_control(_base(), {"image": C.PLACEHOLDER_IMAGE,
                                       "strength": 1.0, "kind": "depth"},
                             uploader=_keep)
    assert built == cc.load_template("krea2_t2i_control_api"), (
        "templates/comfy/krea2_t2i_control_api.json разошёлся с "
        "control.attach_control")


def test_control_template_is_the_base_template_plus_control():
    """Всё, кроме блока контроля, обязано совпасть с базовым шаблоном.

    Иначе правка базового графа (новая лора, другой энкодер) молча остаётся в
    одном файле из двух, и «тот же граф плюс контроль» перестаёт быть правдой.
    """
    base = cc.load_template("krea2_t2i_api")
    ctl = cc.load_template("krea2_t2i_control_api")
    extra = set(ctl) - set(base)
    assert len(extra) == 5, f"блок контроля не из пяти узлов: {sorted(extra)}"
    for nid, node in base.items():
        got = copy.deepcopy(ctl[nid])
        if nid == C.control_state(ctl)["sampler"]:
            got["inputs"]["model"] = node["inputs"]["model"]
        assert got == node, f"узел {nid} в шаблонах разный"


def test_template_placeholder_cannot_run_as_is():
    """Заглушка опоры обязана быть заведомо нерабочей: шаблон с чьим-нибудь
    настоящим снимком внутри однажды уедет в прогон как есть."""
    ctl = cc.load_template("krea2_t2i_control_api")
    st = C.control_state(ctl)
    assert st["image"] == C.PLACEHOLDER_IMAGE
    assert not os.path.exists(st["image"])


# ------------------------------------------------------- пробы для замера

def test_probes_survive_the_ephemeral_swap():
    """Пробы забираются из temp/ по ИМЕНИ, и имя даёт filename_prefix.

    comfy_client.ephemeral подменяет SaveImage на PreviewImage и запоминает
    basename префикса; замер потом ищет файлы по этим именам. Префикс без
    имени превращает отчёт в «сервер не вернул файл».
    """
    g = C.add_depth_probe(C.add_control_probe(_with_control(), "ref77"), "out77")
    names = C.save_names(g)
    assert {"out77", "ref77"} <= names, names
    # ephemeral() правит граф на месте, поэтому имена снимаются до него.
    assert names == set(cc.ephemeral(g).values()), (
        "save_names расходится с тем, как называет файлы comfy_client")


def test_depth_probe_measures_the_frame_that_was_drawn():
    """Проба висит на выходе VAEDecode — на кадре, а не на латенте или опоре."""
    g = C.add_depth_probe(_base())
    dec = [n for n, v in g.items() if v["class_type"] == "VAEDecode"][0]
    probe = [n for n, v in g.items()
             if v["class_type"] == C.DEPTH_PREPROCESSOR][0]
    assert g[probe]["inputs"]["image"] == [dec, 0]
    assert g[probe]["inputs"]["ckpt_name"] == C.DEPTH_CKPT, (
        "проба и опора считаются разными весами — сравнивались бы две разные "
        "функции, а не две композиции")


def test_control_probe_takes_what_the_model_saw():
    """Второй выход кодировщика — опора ПОСЛЕ препроцессора, ресайза и кропа.

    Сравнивать кадр с исходным снимком нечестно: до модели он в таком виде не
    доходит."""
    g = _with_control()
    C.add_control_probe(g)
    enc = C.control_state(g)["nodes"]["encode"]
    saves = [v for v in g.values() if v["class_type"] == "SaveImage"
             and v["inputs"]["images"][0] == enc]
    assert saves and saves[0]["inputs"]["images"][1] == 1, (
        "проба снимает не encoded_control_image")


def test_control_probe_refuses_a_graph_without_control():
    with pytest.raises(SystemExit):
        C.add_control_probe(_base())


# ------------------------------------------------------- две ветки замера

def _pair(seed=7):
    return C.build_pair("t", seed, (64, 64), "ref.jpg", 1.0, uploader=_keep)


def test_seeds_write_to_different_files_too():
    """Замер идёт по НЕСКОЛЬКИМ сидам в одну папку. Имена, не различающие сид,
    дают ту же тихую подмену, что и совпавшие имена веток: файл второго сида
    ложится поверх первого, а строки отчёта остаются разными числами из
    одного и того же файла."""
    a_on, a_off = _pair(11)
    b_on, b_off = _pair(22)
    first = C.save_names(a_on) | C.save_names(a_off)
    second = C.save_names(b_on) | C.save_names(b_off)
    assert not (first & second), f"сиды пишут в одни файлы: {sorted(first & second)}"


def test_the_two_arms_write_to_different_files():
    """ЭТО СЛОМАЛОСЬ НА ПЕРВОМ ЖЕ ЖИВОМ ЗАМЕРЕ, И СЛОМАЛОСЬ БЕСШУМНО.

    Обе ветки давали пробе имя «depthout», оба прогона забирались в одну папку,
    второй файл ложился поверх первого — и обе строки отчёта считались по ОДНОЙ
    карте. Числа получились одинаковые до третьего знака, что читается как
    «контроль ничего не меняет»: замер отвечал наоборот и при этом не падал.
    """
    on, off = _pair()
    assert not (C.save_names(on) & C.save_names(off)), (
        f"ветки пишут в одни файлы: {sorted(C.save_names(on) & C.save_names(off))}")


def test_build_pair_refuses_colliding_probe_names(monkeypatch):
    """И сборщик обязан ловить это сам, а не надеяться на тест.

    Воспроизводится исходная ошибка: проба обеих веток называется одинаково.
    """
    real = C.add_depth_probe
    monkeypatch.setattr(C, "add_depth_probe",
                        lambda g, prefix="depth_out": real(g, "depthout"))
    with pytest.raises(SystemExit) as e:
        C.build_pair("t", 7, (64, 64), "ref.jpg", 1.0, uploader=_keep)
    assert "depthout" in str(e.value)


def test_the_arms_differ_only_by_control():
    """Разница строк отчёта обязана быть разницей КОНТРОЛЯ, а не сида и промпта.

    Один сид, один промпт, один размер: иначе сравниваются две случайные
    картинки, и любое число в отчёте объясняется чем угодно.
    """
    on, off = _pair()
    assert C.control_state(on)["state"] == C.ON
    assert C.control_state(off)["state"] == C.ABSENT
    for nid, node in off.items():
        if node["class_type"] in ("KSampler", "EmptyLatentImage",
                                  "CLIPTextEncode"):
            same = {k: v for k, v in node["inputs"].items() if k != "model"}
            got = {k: v for k, v in on[nid]["inputs"].items() if k != "model"}
            assert same == got, f"ветки разошлись в узле {nid} ({node['class_type']})"


# ------------------------------------------------------- метрика замера

def _map(tmp_path, name, box, size=(120, 150)):
    """Синтетическая карта глубины: белый прямоугольник (ближний план) на сером.

    box = (x0, y0, x1, y1) в долях кадра. Правильный ответ известен заранее —
    именно поэтому метрику можно проверять без GPU.
    """
    import numpy as np
    from _util import imwrite
    w, h = size
    img = np.full((h, w), 60, dtype="uint8")
    x0, y0, x1, y1 = box
    img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)] = 240
    return imwrite(str(tmp_path / (name + ".png")), img)


def test_identical_maps_agree_completely(tmp_path):
    a = _map(tmp_path, "a", (0.3, 0.2, 0.7, 0.9))
    res = C.depth_agreement(a, a)
    assert res["corr"] == pytest.approx(1.0, abs=1e-6)
    assert res["iou"] == pytest.approx(1.0, abs=1e-6)
    assert res["shift"] == pytest.approx(0.0, abs=1e-6)
    assert res["scale"] == pytest.approx(1.0, abs=1e-6)


def test_shift_of_the_figure_is_measured_in_frame_fractions(tmp_path):
    """Сдвиг фигуры на 0.2 ширины обязан читаться как 0.2, а не «похоже»."""
    a = _map(tmp_path, "a", (0.2, 0.2, 0.5, 0.9))
    b = _map(tmp_path, "b", (0.4, 0.2, 0.7, 0.9))
    res = C.depth_agreement(a, b)
    assert res["dx"] == pytest.approx(0.2, abs=0.02)
    assert res["dy"] == pytest.approx(0.0, abs=0.02)
    assert res["iou"] < 0.7, "сдвинутая фигура прочиталась как совпавшая"


def test_scale_notices_a_bigger_figure(tmp_path):
    """МАСШТАБ ОБЯЗАН МЕНЯТЬСЯ. Если ближнюю маску резать по перцентилю, площадь
    у обеих карт равна по построению, и scale вечно равен единице — метрика,
    которая не может показать промах."""
    a = _map(tmp_path, "a", (0.35, 0.3, 0.65, 0.7))     # 0.30 x 0.40 = 0.12
    b = _map(tmp_path, "b", (0.30, 0.2, 0.70, 0.8))     # 0.40 x 0.60 = 0.24
    res = C.depth_agreement(a, b)
    assert res["scale"] == pytest.approx(1.41, abs=0.08), (
        f"масштаб не замечен: {res['scale']}")
    assert res["area_out"] > res["area_ref"]


def test_flat_map_is_not_measured_not_a_zero(tmp_path):
    """Ближний план не отделяется — фигура НЕ ЗАМЕРЕНА. Ноль читался бы как
    «промахнулись мимо опоры», а мерить было нечем."""
    import numpy as np
    from _util import imwrite
    a = _map(tmp_path, "a", (0.3, 0.2, 0.7, 0.9))
    flat = imwrite(str(tmp_path / "flat.png"), np.full((150, 120), 30, "uint8"))
    res = C.depth_agreement(a, flat)
    assert res["iou"] is None and res["scale"] is None and res["shift"] is None
    assert "не замерена" in res["why"]


def test_one_very_near_object_does_not_shrink_the_figure(tmp_path):
    """ЭТО ПОЙМАЛ ЖИВОЙ ЗАМЕР, И ОШИБКА БЫЛА В МЕТРИКЕ, А НЕ В КОНТРОЛЕ.

    DepthAnything растягивает каждую карту на весь диапазон отдельно. Кадр, где
    героиня тянет руку в объектив, отдаёт руке верх шкалы, и фигура съезжает в
    середину: при фиксированном пороге ближняя площадь вышла во много раз
    меньше опорной — метрика сказала «контроль промахнулся» про кадр, где
    фигура ровно того же размера, что на опоре.

    Здесь то же самое собрано синтетически: одна и та же фигура, но на второй
    карте перед ней маленькое очень близкое пятно. Масштаб обязан остаться
    единицей.
    """
    import cv2
    from _util import imread, imwrite
    ref = _map(tmp_path, "ref", (0.25, 0.15, 0.75, 0.95))
    img = imread(ref, cv2.IMREAD_GRAYSCALE)
    img[img == 240] = 150                      # фигура ушла в середину шкалы
    img[int(0.80 * img.shape[0]):, int(0.45 * img.shape[1]):
        int(0.60 * img.shape[1])] = 255        # рука в объектив
    hand = imwrite(str(tmp_path / "hand.png"), img)
    res = C.depth_agreement(ref, hand)
    assert res["scale"] == pytest.approx(1.0, abs=0.06), (
        f"фигура «уменьшилась» из-за одного близкого пятна: {res}")
    assert res["iou"] > 0.9


def test_maps_of_different_shape_are_refused(tmp_path):
    """Портрет 4:5 против кадра 2:3 через ресайз даёт число, и оно ни о чём."""
    a = _map(tmp_path, "a", (0.3, 0.2, 0.7, 0.9), size=(120, 150))
    b = _map(tmp_path, "b", (0.3, 0.2, 0.7, 0.9), size=(120, 180))
    with pytest.raises(SystemExit):
        C.depth_agreement(a, b)


# ------------------------------------------------------- дорогой путь и сухой прогон

def test_dry_run_sends_nothing(monkeypatch, capsys):
    """--dry обещан для каждого дорогого пути: замер — это два полных рендера."""
    def boom(*a, **k):
        raise AssertionError("сухой прогон пошёл на сервер")

    monkeypatch.setattr(cc, "preflight", boom)
    monkeypatch.setattr(cc, "run_graph", boom)
    monkeypatch.setattr(cc, "upload", boom)
    assert C.measure(os.path.join(ROOT, "projects", "bridget"), "ref.jpg",
                     dry=True) is None
    assert "сид" in capsys.readouterr().out


def test_report_path_uses_the_project_name_not_the_folder(monkeypatch, capsys):
    """`docs/<project>/control.md`, а не `docs/projects/bridget/control.md`.

    Перепутанный плейсхолдер здесь уже ловили: команда завершается успехом, а
    документ уезжает в каталог, которого в раскладке проекта нет.
    """
    monkeypatch.setattr(cc, "preflight", lambda *a, **k: False)
    C.measure(os.path.join(ROOT, "projects", "bridget"), "ref.jpg", dry=True)
    out = capsys.readouterr().out
    assert os.path.join("docs", "bridget", "control.md") in out, out
    assert os.path.join("docs", "projects") not in out
