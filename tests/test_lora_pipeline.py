"""Персонажная LoRA: сборка датасета из плотного ядра и задание в AI Toolkit.

  py -3 -m pytest tests/test_lora_pipeline.py -q

Каждый тест здесь красный, если убрать соответствующую починку, — это в этом
репозитории единственное, что отличает проверку от описания намерений.

Сеть тут не нужна: ответы AI Toolkit подставляются заглушкой, а эмбеддинги
кадров — синтетические векторы на окружности, у которых косинус равен косинусу
угла между ними и потому известен наперёд. Настоящий insightface в сьюте
означал бы, что набор зелёный ровно на машине автора.
"""
import copy
import json
import math
import io
import os
import urllib.error

import pytest

import conftest  # noqa: F401  — кладёт scripts/ в путь раньше импортов ниже

import lora_dataset as LD
import lora_train as LT


# --------------------------------------------------------------- материал


def vec(deg):
    """Единичный вектор под углом deg: косинус пары = косинусу разности углов."""
    r = math.radians(deg)
    return [math.cos(r), math.sin(r)]


# Два сгустка: пять кадров в пределах 20° и три далеко в стороне. Косинус
# внутри первого не ниже cos 20° = 0.9397, между сгустками — около cos 70°.
ANGLES = {"A0": 0, "A5": 5, "A10": 10, "A15": 15, "A20": 20,
          "B90": 90, "B95": 95, "B100": 100}


def synth_vecs():
    return {name: vec(d) for name, d in ANGLES.items()}


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Синтетический проект: карточка, раскадровка, реестр и пустые кадры.

    Свой проект, а не projects/bridget: сьют обязан быть зелёным на машине, где
    рабочего корня с кадрами нет вовсе, и не зависеть от того, какой пул там
    лежит сегодня.
    """
    pdir = tmp_path / "proj"
    pdir.mkdir()
    (pdir / "character.json").write_text(
        json.dumps({"id": "testchar", "age": 51}), encoding="utf-8")
    (pdir / "shotlist.json").write_text(json.dumps({
        "project": "testchar",
        "cells": [
            {"id": "C1", "label": "Первая", "framing": "chest-up portrait",
             "gaze": "direct eye contact", "wardrobe": "an ivory blouse",
             "set": "at home by a window", "light": "soft window light",
             "camera": "85mm at f/2"},
            {"id": "C2", "label": "Вторая", "framing": "full length",
             "gaze": "looking away", "wardrobe": "a wine-red dress",
             "set": "a restaurant in the evening", "light": "candle warmth",
             "camera": "50mm at f/1.4"},
        ]}), encoding="utf-8")

    work = tmp_path / "work"
    monkeypatch.setenv("PERSONA_WORK_ROOT", str(work))
    frames = work / "testchar" / "frames"
    frames.mkdir(parents=True)
    ledger = []
    for name in ANGLES:
        f = frames / f"{name}.png"
        f.write_bytes(b"")
        ledger.append({"file": str(f), "cell": "C1" if name[0] == "A" else "C2",
                       "label": "Первая", "seed": 1, "caption": ""})
    (frames / "frames.json").write_text(json.dumps(ledger), encoding="utf-8")

    by_name = {str(frames / f"{n}.png"): v for n, v in synth_vecs().items()}
    monkeypatch.setattr(LD, "embeddings", lambda paths: (
        {p: by_name[p] for p in paths if p in by_name}, []))
    # ТРИГГЕР ПРОЕКТА ГЛУШИТСЯ НАМЕРЕННО. Тесты собирают свой датасет на слове
    # «tchar_w», а resolve_trigger читает настоящий assets.json. Пока ключ
    # models.character_lora.trigger был пуст, это совпадало случайно; в день,
    # когда лору обучили и вписали в манифест, сверка триггеров начала
    # отказывать в четырёх тестах — на исправном коде. Опора обязана быть
    # заявленной, а не унаследованной от состояния проекта.
    man = copy.deepcopy(conftest.MANIFEST)
    man["models"].pop("character_lora", None)
    monkeypatch.setattr(LD, "manifest", lambda: man)
    return {"dir": str(pdir), "work": work, "frames": frames,
            "md": str(tmp_path / "doc.md"), "out": str(tmp_path / "ds")}


def build(project, **kw):
    kw.setdefault("trigger", "tchar_w")
    kw.setdefault("md", project["md"])
    kw.setdefault("out", project["out"])
    return LD.build(project["dir"], **kw)


# ------------------------------------------------------- поиск ядра пула


def test_star_cluster_takes_the_biggest_group_not_the_first_one():
    """Берётся САМАЯ КРУПНАЯ звезда, а не первая попавшаяся.

    Ломалось бы так: обход идёт по отсортированным именам, и «первая
    подошедшая» звезда — это всегда звезда вокруг A0, у которой на этом пороге
    на один кадр меньше. Разница в один кадр из пяти незаметна глазом и
    полностью меняет, ЧЕМУ обучится лора.
    """
    v = synth_vecs()
    centre, members = LD.star_cluster(v, math.cos(math.radians(11)))
    assert centre == "A10", f"центр {centre}, а самая крупная звезда вокруг A10"
    assert sorted(members) == ["A0", "A10", "A15", "A20", "A5"]


def test_cluster_does_not_leak_the_far_group():
    """Порог обязан отрезать второй сгусток: 70° — это другой человек."""
    v = synth_vecs()
    _, members = LD.star_cluster(v, 0.9)
    assert not [m for m in members if m.startswith("B")], members


# Два сгустка по четыре кадра, у которых ВЫСОКИЙ порог даёт группу РЫХЛЕЕ.
# A: три кадра рядом и один в 22° — звезда собирается только на 0.95.
# B: четыре кадра по 8° — звезда собирается уже на 0.96, но внутри она шире
# (24° между крайними против 22° у A).
SKEW = {"A00": 0, "A02": 2, "A04": 4, "A22": 22,
        "B100": 100, "B108": 108, "B116": 116, "B124": 124}


def test_ladder_picks_the_tightest_group_not_the_highest_threshold():
    """Ступень выбирается по ПЛОТНОСТИ ГРУППЫ, а не по величине порога.

    Так и было сломано в первой редакции: лестница останавливалась на первом
    пороге, набравшем нужный размер, по рассуждению «размер монотонно растёт,
    значит первый подходящий порог — самый плотный». Порогом связан только
    ЦЕНТР звезды, а не пары внутри неё, поэтому соседние ступени дают группы
    одного размера с разной худшей парой, и более высокий порог может дать
    группу рыхлее. На живом пуле это стоило датасету 0.04 косинуса — ровно той
    величины, которой меряется вся эта задача.
    """
    v = {n: vec(d) for n, d in SKEW.items()}
    rows = LD.ladder(v, max_size=4, hi=0.97, lo=0.94, step=0.005)
    high = [r for r in rows if r["threshold"] == pytest.approx(0.96)][0]
    assert high["n"] == 4 and high["worst"] == pytest.approx(
        math.cos(math.radians(24)), abs=1e-6)

    row, why = LD.choose(rows, min_size=4, max_size=4)
    assert row["worst"] == pytest.approx(math.cos(math.radians(22)), abs=1e-6), (
        "взята рыхлая группа с высокого порога вместо плотной с низкого")
    assert row["threshold"] == pytest.approx(0.95)
    assert sorted(row["members"]) == ["A00", "A02", "A04", "A22"]


def test_ladder_says_when_the_size_band_is_unreachable():
    """Ни одна ступень не дала нужного размера — это сказано, а не подменено."""
    v = synth_vecs()
    rows = LD.ladder(v, max_size=20, hi=0.99, lo=0.98, step=0.01)
    row, why = LD.choose(rows, min_size=7, max_size=20)
    assert "ни одна ступень" in why
    assert row["n"] == max(r["n"] for r in rows)


def test_trim_keeps_the_frames_nearest_the_centre():
    """Обрезка до max_size идёт от центра, а не по алфавиту."""
    v = synth_vecs()
    kept = LD.trim(v, "A10", ["A0", "A5", "A10", "A15", "A20"], 3)
    assert sorted(kept) == ["A10", "A15", "A5"], kept


# --------------------------------------------------------- три состояния


def test_fitness_has_three_states_not_two():
    """Незамер отличается от провала: у группы из одного кадра пары нет.

    Двузначная проверка (worst >= floor) записывала бы такую группу в FAIL,
    то есть в «измерено и плохо», и человек крутил бы порог, который ни на что
    не влияет.
    """
    assert LD._fitness(0.60, 0.50) == "PASS"
    assert LD._fitness(0.40, 0.50) == "FAIL"
    assert LD._fitness(None, 0.50) == "NOT_MEASURED"
    assert LD._fitness(0.60, None) == "NOT_MEASURED"


def test_refuses_to_build_a_dataset_looser_than_the_floor(project):
    """Худшая пара ниже порога годности — это ОТКАЗ, а не предупреждение."""
    res = build(project, threshold=0.3, min_worst=0.9)
    assert res.get("refused"), res["fitness"]
    assert res["fitness"]["state"] == "FAIL"
    assert not os.path.exists(project["out"]), "отказ, а папка датасета создана"


def test_refuses_when_the_floor_cannot_be_measured(project):
    """Порога годности нет и сдачи нет — собирать вслепую нельзя.

    Это ровно та проверка, которая «при отсутствии зависимости молча
    выключается»: без неё датасет собрался бы, выглядел бы настоящим, и разница
    вылезла бы через два часа GPU.
    """
    res = build(project, threshold=0.9)
    assert res["fitness"]["state"] == "NOT_MEASURED"
    assert res.get("refused")
    assert not os.path.exists(project["out"])


# ------------------------------------------------------------- сдача как порог


def test_delivery_floor_survives_a_slash_flavoured_path(project, monkeypatch):
    """Порог годности берётся со сдачи, даже если пути записаны по-разному.

    Реестр пишет кадр через обратные слеши, сдача — через прямые; обе строки
    указывают на один файл. Сверка по сырой строке их не сводит, и порог
    годности МОЛЧА становится незамеренным — «в сдаче меньше двух кадров с
    лицом», хотя лица на месте, — а незамеренный порог отказывает собирать
    вообще всё.
    """
    # Корень уводится в tmp: тест, который положил бы правдоподобную сдачу в
    # deliverables/ репозитория, — это ровно тот дефект, который раунд 6 нашёл
    # в вердикте ворот, только на другом файле.
    monkeypatch.setattr(LD, "ROOT", str(project["work"].parent))
    d = os.path.join(str(project["work"].parent), "deliverables", "testchar",
                     "part1_profile")
    os.makedirs(d)
    src = [str(project["frames"] / "A0.png").replace("\\", "/"),
           str(project["frames"] / "B90.png").replace("\\", "/")]
    with open(os.path.join(d, "selection.json"), "w", encoding="utf-8") as fh:
        json.dump({"frames": [{"cell": "C1", "source": src[0]},
                              {"cell": "C2", "source": src[1]}]}, fh)

    res = build(project, threshold=0.9)
    f = res["fitness"]
    assert f["state"] != "NOT_MEASURED", f
    # Порог — косинус 90°, то есть примерно ноль; ядро его перекрывает.
    assert f["floor"] == pytest.approx(math.cos(math.radians(90)), abs=1e-6)
    assert f["state"] == "PASS", f


# ------------------------------------------------------------------ подписи


def test_caption_starts_with_the_trigger_and_describes_the_frame():
    cell = {"id": "C1", "framing": "chest-up portrait", "gaze": "direct gaze",
            "wardrobe": "an ivory blouse", "set": "at home",
            "light": "soft light", "camera": "85mm at f/2"}
    text = LD.caption_for(cell, "tchar_w")
    assert text.startswith("tchar_w, "), text
    for part in ("chest-up portrait", "an ivory blouse", "85mm at f/2"):
        assert part in text


def test_caption_leaves_the_identity_block_out():
    """Внешность в подпись не идёт: описанное словами садится на слова.

    Если блок идентичности попадёт в подпись, лора выучит «женщина 51 года со
    светлыми волосами», а триггер останется пустым словом — то есть ровно то,
    ради чего обучение и затевалось, не произойдёт.
    """
    cell = {"id": "C1", "framing": "chest-up portrait",
            "identity": "a 51-year-old woman with green-hazel eyes",
            "age": "a 51-year-old woman"}
    text = LD.caption_for(cell, "tchar_w")
    assert "51-year-old" not in text, text


def test_caption_refuses_cyrillic(project):
    """Русское поле в обучающей подписи — отказ, а не «как-нибудь стерпится»."""
    with pytest.raises(SystemExit) as e:
        LD.caption_for({"id": "C1", "framing": "поясной портрет"}, "tchar_w")
    assert "кириллиц" in str(e.value).lower()


def test_registry_caption_wins_over_the_assembled_one():
    cell = {"id": "C1", "framing": "chest-up portrait"}
    text = LD.caption_for(cell, "tchar_w", {"caption": "ready made caption"})
    assert text == "tchar_w, ready made caption"


def test_trigger_is_never_invented(monkeypatch):
    """Пустой триггер — отказ. Придуманное слово разошлось бы с промптом."""
    man = {"models": {"character_lora": {"name": None, "trigger": None}}}
    assert LD.resolve_trigger(None, man) == (None, None)
    assert LD.resolve_trigger("x", man)[0] == "x"
    assert LD.resolve_trigger(None, {"models": {"character_lora":
                                                {"trigger": "m_w"}}})[0] == "m_w"


def test_build_refuses_without_a_trigger(project, monkeypatch):
    monkeypatch.setattr(LD, "manifest",
                        lambda: {"models": {"character_lora": {}}})
    with pytest.raises(SystemExit) as e:
        LD.build(project["dir"], trigger=None, md=project["md"],
                 out=project["out"], min_worst=0.0)
    assert "триггер" in str(e.value).lower()


# ---------------------------------------------------------------- запись


def test_dry_run_writes_absolutely_nothing(project):
    """«--dry» включает «и папок не создаёт» — как у generate.py."""
    res = build(project, threshold=0.9, min_worst=0.0, dry=True)
    assert not res.get("refused")
    assert not os.path.exists(project["out"]), "--dry насорил"
    assert not os.path.exists(project["md"])


def test_dataset_is_aitoolkit_shaped(project):
    """Кадр и одноимённый .txt рядом — это и есть формат AI Toolkit."""
    res = build(project, threshold=0.9, min_worst=0.0)
    for src in res["frames"]:
        stem = os.path.splitext(os.path.basename(src))[0]
        img = os.path.join(project["out"], stem + ".png")
        txt = os.path.join(project["out"], stem + ".txt")
        assert os.path.exists(img) and os.path.exists(txt), (img, txt)
        with open(txt, encoding="utf-8") as fh:
            assert fh.read().startswith("tchar_w, ")
    assert os.path.exists(os.path.join(project["out"], "dataset.json"))
    assert os.path.exists(project["md"]), "отчёт с числами не записан"


def test_second_run_does_not_leave_the_previous_frames_behind(project):
    """Прогон с другим порогом обязан ЗАМЕНИТЬ набор, а не долить к старому.

    Иначе обучение молча идёт по объединению двух наборов — по тому самому
    рыхлому пулу, от которого весь скрипт и защищает, — и никакой отчёт этого
    не показывает: в отчёте состав нового прогона.
    """
    first = build(project, threshold=-0.5, min_worst=-1.0)
    assert len(first["frames"]) == len(ANGLES)
    second = build(project, threshold=0.9, min_worst=0.0)
    assert len(second["frames"]) < len(first["frames"])
    left = {f for f in os.listdir(project["out"]) if f.endswith(".png")}
    assert left == {os.path.basename(p) for p in second["frames"]}, left


def test_refuses_to_touch_a_folder_it_did_not_write(project):
    """Чужие файлы в папке датасета не стираются молча."""
    os.makedirs(project["out"])
    with open(os.path.join(project["out"], "чужое.png"), "w",
              encoding="utf-8") as fh:
        fh.write("x")
    with pytest.raises(SystemExit) as e:
        build(project, threshold=0.9, min_worst=0.0)
    assert "чужое" in str(e.value)


def test_report_and_the_written_doc_are_the_same_lines(project):
    """В файле лежит то же, что на экране, — конструкцией, а не обещанием."""
    res = build(project, threshold=0.9, min_worst=0.0)
    with open(project["md"], encoding="utf-8") as fh:
        doc = fh.read()
    for line in LD.report(res, quiet=True):
        assert line in doc, line


def test_single_cell_core_is_said_out_loud(project):
    """Ядро из одной ячейки — главный вывод замера, и он обязан быть в отчёте."""
    res = build(project, threshold=0.9, min_worst=0.0)
    assert res["single_cell"] is True
    assert any("ОДНОЙ ЯЧЕЙКИ" in ln for ln in LD.report(res, quiet=True))


# ================================================================ AI Toolkit


ARCH_BUNDLE = (
    '{name:"flux",label:"FLUX.1",group:"image",defaults:{'
    '"config.process[0].model.name_or_path":["black-forest-labs/FLUX.1-dev",""]}}'
    ',{name:"zimage:turbo",label:"Z-Image Turbo",group:"image",defaults:{'
    '"config.process[0].model.name_or_path":["Tongyi-MAI/Z-Image-Turbo",""],'
    '"config.process[0].model.assistant_lora_path":["ostris/adapter.safetensors"]}}'
)


def test_arch_list_is_read_from_the_toolkit_not_remembered(monkeypatch):
    monkeypatch.setattr(LT, "_ui_bundle", lambda: (ARCH_BUNDLE, None))
    archs, why = LT.supported_archs()
    assert why is None
    names = {a["name"] for a in archs}
    assert names == {"flux", "zimage:turbo"}
    turbo = [a for a in archs if a["name"] == "zimage:turbo"][0]
    assert turbo["name_or_path"] == "Tongyi-MAI/Z-Image-Turbo"
    assert turbo["assistant_lora_path"] == "ostris/adapter.safetensors"


def test_unknown_arch_list_is_not_measured_not_empty(monkeypatch):
    """Не выяснено — это None с причиной, а не пустой список.

    Пустой список читается потребителем как «тулкит не умеет ничего» и толкает
    к прямо противоположному выводу.
    """
    monkeypatch.setattr(LT, "_ui_bundle", lambda: ("", "морда не ответила"))
    archs, why = LT.supported_archs()
    assert archs is None and "не ответила" in why


def _toolkit(monkeypatch, archs=("zimage",), datasets=("bridget",),
             jobs=()):
    monkeypatch.setattr(LT, "supported_archs",
                        lambda: ([{"name": a, "label": a, "group": "image",
                                   "name_or_path": "repo/" + a} for a in archs],
                                 None))
    monkeypatch.setattr(LT, "settings",
                        lambda: {"TRAINING_FOLDER": "D:\\ai-toolkit\\output",
                                 "DATASETS_FOLDER": "D:\\ai-toolkit\\datasets"})
    monkeypatch.setattr(LT, "jobs", lambda: list(jobs))
    monkeypatch.setattr(LT, "api", lambda p, *a, **k: (200, list(datasets)))


def test_refuses_an_architecture_the_toolkit_does_not_have(project, monkeypatch):
    """krea2 в тулките нет, и узнать это надо ДО двух часов чужой карты."""
    _toolkit(monkeypatch)
    with pytest.raises(SystemExit) as e:
        LT.prepare(project["dir"], "D:\\ai-toolkit\\datasets\\bridget",
                   arch="krea2", trigger="tchar_w", local=project["out"])
    assert "krea2" in str(e.value) and "zimage" in str(e.value)


def test_refuses_to_guess_when_the_arch_list_is_unknown(project, monkeypatch):
    monkeypatch.setattr(LT, "supported_archs", lambda: (None, "морда молчит"))
    with pytest.raises(SystemExit) as e:
        LT.prepare(project["dir"], "D:\\ai-toolkit\\datasets\\bridget",
                   arch="zimage", trigger="tchar_w", local=project["out"])
    assert "молчит" in str(e.value)


def test_dataset_visibility_has_three_states(monkeypatch):
    """Путь ВНЕ DATASETS_FOLDER этим API не проверяется — и это NOT_MEASURED.

    Двузначная проверка объявила бы такой путь отсутствующим (FAIL) или,
    что хуже, годным (PASS): обучение стартует, занимает карту и падает на
    первом батче.
    """
    sets = {"DATASETS_FOLDER": "D:\\ai-toolkit\\datasets"}
    monkeypatch.setattr(LT, "api", lambda p, *a, **k: (200, ["bridget"]))
    assert LT._dataset_state("D:\\ai-toolkit\\datasets\\bridget", sets)[0] == "PASS"
    assert LT._dataset_state("D:\\ai-toolkit\\datasets\\nope", sets)[0] == "FAIL"
    assert LT._dataset_state("E:\\somewhere\\bridget", sets)[0] == "NOT_MEASURED"
    assert LT._dataset_state("D:\\x", {})[0] == "NOT_MEASURED"


def test_trigger_mismatch_between_dataset_and_manifest_is_refused(
        project, monkeypatch):
    """Подписи обучены одному слову, а задание объявляет другое — отказ.

    Обучение прошло бы до конца, лора легла бы на диск, и в кадре не появилось
    бы ничего: не включившаяся лора неотличима от отсутствующей.
    """
    _toolkit(monkeypatch)
    build(project, threshold=0.9, min_worst=0.0)     # подписи с tchar_w
    with pytest.raises(SystemExit) as e:
        LT.prepare(project["dir"], "D:\\ai-toolkit\\datasets\\bridget",
                   arch="zimage", trigger="другое_слово",
                   local=project["out"])
    assert "РАСХОДЯТСЯ" in str(e.value)


def test_job_config_carries_dataset_trigger_and_arch(project, monkeypatch):
    _toolkit(monkeypatch)
    build(project, threshold=0.9, min_worst=0.0)
    res = LT.prepare(project["dir"], "D:\\ai-toolkit\\datasets\\bridget",
                     arch="zimage", local=project["out"])
    proc = res["job_config"]["config"]["process"][0]
    assert proc["datasets"][0]["folder_path"] == "D:\\ai-toolkit\\datasets\\bridget"
    assert proc["datasets"][0]["caption_ext"] == "txt"
    assert proc["trigger_word"] == "tchar_w"
    assert proc["model"]["arch"] == "zimage"
    assert proc["model"]["name_or_path"] == "repo/zimage"
    assert proc["training_folder"] == "D:\\ai-toolkit\\output"
    assert res["dataset_state"][0] == "PASS"


def test_sample_prompts_speak_the_language_of_the_captions(project, monkeypatch):
    _toolkit(monkeypatch)
    build(project, threshold=0.9, min_worst=0.0)
    res = LT.prepare(project["dir"], "D:\\ai-toolkit\\datasets\\bridget",
                     arch="zimage", local=project["out"])
    samples = res["job_config"]["config"]["process"][0]["sample"]["samples"]
    assert samples and all(s["prompt"].startswith("tchar_w, ") for s in samples)


def test_job_name_cannot_leave_latin(project, monkeypatch):
    """Имя задания уходит в ПУТЬ выходной папки на чужой машине."""
    assert LT._slug("Бриджет Про") == ""
    assert LT._slug("Bridget v1") == "bridget_v1"


def test_nothing_is_sent_without_send(project, monkeypatch):
    """Создание задания без --send не трогает сервер ни одним запросом."""
    _toolkit(monkeypatch)
    build(project, threshold=0.9, min_worst=0.0)
    res = LT.prepare(project["dir"], "D:\\ai-toolkit\\datasets\\bridget",
                     arch="zimage", local=project["out"])
    calls = []
    monkeypatch.setattr(LT, "api", lambda *a, **k: calls.append(a) or (200, {}))
    assert LT.create(res, send=False) is None
    assert calls == [], calls


def test_create_refuses_when_the_server_cannot_see_the_dataset(
        project, monkeypatch):
    _toolkit(monkeypatch, datasets=("lenya",))
    build(project, threshold=0.9, min_worst=0.0)
    res = LT.prepare(project["dir"], "D:\\ai-toolkit\\datasets\\bridget",
                     arch="zimage", local=project["out"])
    assert res["dataset_state"][0] == "FAIL"
    with pytest.raises(SystemExit) as e:
        LT.create(res, send=True)
    assert "не виден" in str(e.value)


def test_http_error_comes_back_as_a_code_not_a_traceback(monkeypatch):
    """4xx — это ответ, а не авария: на нём стоит вся разведка этого API."""
    def boom(req, timeout=None):
        # fp=io.BytesIO(...), А НЕ None — иначе тест ложно краснеет на 3.9.
        # При fp=None HTTPError.__init__ не доходит до addinfourl.__init__, и
        # последующий .read() уезжает в tempfile._TemporaryFileWrapper.__getattr__
        # с KeyError('file'). Настоящий 4xx от тулкита всегда приходит с живым
        # телом, так что заглушка с телом ещё и честнее исходной.
        raise urllib.error.HTTPError(req.full_url, 409, "Conflict", {},
                                     io.BytesIO(b"{}"))
    monkeypatch.setenv("AITK_HOST", "http://127.0.0.1:9")
    monkeypatch.setattr(LT.urllib.request, "urlopen", boom)
    code, body = LT.api("/api/jobs")
    assert code == 409


def test_watch_stops_on_a_status_it_does_not_know(monkeypatch, capsys):
    """Незнакомый статус прекращает опрос и говорит об этом.

    Принять его за рабочий — вечный опрос; принять за конечный — молча
    сообщить, что обучение кончилось, пока оно идёт.
    """
    monkeypatch.setattr(LT, "job_of", lambda i: (
        {"id": "1", "name": "j", "status": "полёт_нормальный", "step": 5,
         "job_config": json.dumps({"config": {"process": [
             {"train": {"steps": 100}}]}})}, None))
    monkeypatch.setattr(LT.time, "sleep",
                        lambda s: pytest.fail("опрос не остановился"))
    LT.watch("j", every=0)
    assert "NOT_MEASURED" in capsys.readouterr().out


# ------------------------------------------------- два рубильника, не один

def _start_calls(monkeypatch, argv, job=None):
    """Прогнать `lora_train.py start …` и вернуть список задетых путей API.

    АДРЕС ТУЛКИТА ЗАДАЁТСЯ ЗДЕСЬ, И ЭТО ПОЧИНКА КРАСНОГО CI. `main()` зовёт
    `host()` раньше всякого запроса, а тот ищет AITK_HOST в окружении и
    `aitk_host` в assets.local.json — файле, который .gitignore намеренно не
    пускает в репозиторий. На машине автора он есть, поэтому оба теста были
    зелёными локально и падали на КАЖДОМ прогоне CI с «адрес AI Toolkit не
    задан»: состояние конкретной машины оказалось скрытым входом проверки.
    Адрес заведомо мёртвый — `api` всё равно подменён, в сеть никто не идёт;
    он нужен ровно для того, чтобы разбор аргументов дошёл до вызовов.
    """
    monkeypatch.setenv("AITK_HOST", "http://127.0.0.1:9")
    # И РОВНО ЗДЕСЬ ПРОГОН ХОДИЛ В ЖИВОЙ COMFYUI. `main()` после старта зовёт
    # `free_comfy()` (lora_train.py:733), а тот берёт адрес из assets.local.json
    # и шлёт `POST /free {"unload_models": true}`. То есть обычный `pytest -q`
    # на машине автора ВЫГРУЖАЛ МОДЕЛИ ИЗ РАБОТАЮЩЕГО ComfyUI — на общей машине,
    # посреди чужого прогона. Замер spy-сервером на полном наборе: два GET
    # /queue и два POST /free. conftest.py при этом обещает «ни один тест не
    # ходит в ComfyUI»; обещание держалось только потому, что CI пинит мёртвый
    # адрес, а не потому, что кода туда не было.
    monkeypatch.setattr(LT, "free_comfy", lambda: None)
    seen = []
    monkeypatch.setattr(LT, "job_of", lambda i: (
        job or {"id": "JID", "name": "j", "gpu_ids": "0"}, None))
    monkeypatch.setattr(LT, "api", lambda p, *a, **k: seen.append(p) or (200, {}))
    monkeypatch.setattr(LT.sys, "argv", ["lora_train.py"] + argv)
    LT.main()
    return seen


def test_start_turns_on_the_gpu_queue_after_the_job(monkeypatch, capsys):
    """Старт включает СНАЧАЛА задание, потом очередь карты. Именно так.

    У тулкита два рубильника, и второй молчит. Воркер
    (ui/dist/cron/actions/processQueue.js) обходит таблицу Queue, а не список
    заданий: для каждой очереди с is_running берёт первое задание в статусе
    queued с тем же gpu_ids. При выключенной очереди задание висит в queued
    вечно — без ошибки, без строки в логе, без единого признака.

    ПОРЯДОК ЗДЕСЬ БЫЛ ОБРАТНЫМ, И ЭТО НЕ РАБОТАЛО. Рассуждение «сначала
    включить очередь, потом положить в неё задание» выглядит верным и
    промахивается мимо одной детали: воркер ГАСИТ очередь, в которой нет ни
    одного queued-задания, и успевает сделать это между двумя вызовами.
    Замер: после `start --send` задание висело в queued, а /api/queue отдавал
    is_running: false у ОБЕИХ карт; тот же GET, повторённый вручную секундой
    позже — уже при стоящем в очереди задании, — поднял очередь, и обучение
    пошло немедленно.
    """
    seen = _start_calls(monkeypatch, ["start", "j", "--send"])
    assert seen[:2] == ["/api/jobs/JID/start", "/api/queue/0/start"], seen
    assert "queue/0/start" in capsys.readouterr().out


def test_the_queue_is_addressed_by_gpu_not_by_row_id(monkeypatch):
    """В маршруте очереди стоит НОМЕР КАРТЫ, а не id строки таблицы.

    Проверено дорого: `/api/queue/1/start` при единственной очереди с id = 1 и
    gpu_ids = "0" завёл ВТОРУЮ очередь — для несуществующей карты 1, — и
    воркер немедленно погасил её как пустую. Номер берётся из поля gpu_ids
    самого задания, а не из id, который вернул /api/queue.
    """
    seen = _start_calls(monkeypatch, ["start", "j", "--send"],
                        job={"id": "JID", "name": "j", "gpu_ids": "3"})
    assert "/api/queue/3/start" in seen, seen
    assert not any(x.startswith("/api/queue/1/") for x in seen), seen


def test_stop_does_not_touch_the_queue(monkeypatch):
    """Остановка задания очередь не трогает: это чужой рубильник.

    Выключить её здесь значило бы остановить и всё, что стоит в ней следом, —
    в том числе чужое: машина общая.
    """
    seen = _start_calls(monkeypatch, ["stop", "j", "--send"])
    assert seen == ["/api/jobs/JID/stop"], seen
