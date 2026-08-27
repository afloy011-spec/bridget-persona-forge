"""Мост «холст → реестр»: что снято руками, доходит до ворот.

ЗАЧЕМ ЭТОТ ФАЙЛ. Холст и конвейер были двумя отдельными инструментами: холст
заканчивается превью, кадры оседают во временной папке сервера, а ворота,
отбор и выдача читают реестр. По правилу generate.py кадр без записи в реестре
считается мусором — то есть на холсте можно было снять хорошее и не суметь
это сдать. Здесь закреплено то, что мост обязан делать, чтобы шов снова не
разошёлся.
"""
import json
import os

import pytest

import adopt_canvas as A


def _node(cls, **inputs):
    return {"class_type": cls, "inputs": inputs}


def _canvas_run(pid="abc123", seed=7, prompt="a woman", w=1152, h=1440):
    """Запись истории, как её отдаёт сервер после прогона холста."""
    graph = {
        "8": _node("Krea2EditModelPatch", ref_boost=4.0),
        "9": _node("Krea2EditGroundedEncode", prompt=prompt,
                   grounding_px=1024, clip=["3", 1]),
        "11": _node("EmptyLatentImage", width=w, height=h),
        "12": _node("KSampler", seed=seed, steps=8, model=["8", 0]),
        "14": _node("PreviewImage", images=["13", 0]),
    }
    item = {"prompt": [0, pid, graph, {}, []],
            "outputs": {"14": {"images": [
                {"filename": f"pf_{pid}.png", "subfolder": "", "type": "temp"}]}},
            "status": {"completed": True}}
    return pid, item, graph


def test_canvas_runs_recognises_the_canvas():
    pid, item, _ = _canvas_run()
    got = A.canvas_runs({pid: item})
    assert [g[0] for g in got] == [pid]


def test_foreign_jobs_on_the_shared_server_are_not_adopted():
    """Сервер общий: чужой прогон не должен попасть в наш реестр.

    Признак холста — связка грунтованного энкодера с патчем модели. Обычный
    t2i соседа проходит мимо, даже если он тоже KSampler и тоже отдал кадр.
    """
    alien = {"1": _node("KSampler", seed=1),
             "2": _node("CLIPTextEncode", text="cat")}
    item = {"prompt": [0, "zzz", alien, {}, []],
            "outputs": {"9": {"images": [
                {"filename": "x.png", "subfolder": "", "type": "temp"}]}}}
    assert A.canvas_runs({"zzz": item}) == []


def test_run_without_output_is_skipped():
    """Упавший или ещё не досчитанный прогон кадра не даёт."""
    pid, item, _ = _canvas_run()
    item["outputs"] = {}
    assert A.canvas_runs({pid: item}) == []


def test_pick_reads_widgets_but_never_links():
    """Связь — это [нода, слот], а не значение.

    Путать дорого: в реестр вместо сида уехал бы список, и повторить кадр
    стало бы нечем.
    """
    _pid, _item, g = _canvas_run(seed=42, prompt="hello")
    assert A._pick(g, "KSampler", "seed") == 42
    assert A._pick(g, "Krea2EditGroundedEncode", "prompt") == "hello"
    assert A._pick(g, "Krea2EditGroundedEncode", "clip") is None
    assert A._pick(g, "NoSuchNode", "seed") is None


def test_free_cell_defaults_are_the_strict_ones():
    """Кадр вне шотлиста не должен случайно проехать чужие ворота.

    Умолчания берутся самые строгие: одет, тату не ждём. Иначе ручной кадр
    получил бы поблажки, рассчитанные на другое задание.
    """
    c = A._cell_meta(".", "shotlist.json", "free")
    assert c["nudity_level"] == "clothed"
    assert c["tattoo_visible"] is False


def test_unknown_cell_names_the_ones_that_exist(tmp_path):
    shots = {"cells": [{"id": "P1", "label": "портрет"}]}
    (tmp_path / "shotlist.json").write_text(json.dumps(shots), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        A._cell_meta(str(tmp_path), "shotlist.json", "P9")
    assert "P1" in str(e.value)


def _fixture_project(tmp_path):
    shots = {"cells": [{"id": "P1", "label": "портрет", "scene_class": "indoor",
                        "nudity_level": "clothed", "caption": "у окна"}]}
    (tmp_path / "shotlist.json").write_text(json.dumps(shots), encoding="utf-8")
    return str(tmp_path)


def test_adopted_frame_carries_seed_prompt_and_the_cell_task(tmp_path,
                                                             monkeypatch):
    """Сид и промпт — из графа, задание — из клетки.

    Выдумывать задание за снявшего нельзя: ворота судят кадр по тому, что от
    него требовалось, а не по тому, что получилось.
    """
    proj = _fixture_project(tmp_path)
    work = tmp_path / "work"
    monkeypatch.setattr(A, "work_dir",
                        lambda *p: str(work.joinpath(*p)))
    pid, item, _ = _canvas_run(seed=99, prompt="кадр у окна")
    monkeypatch.setattr(A.cc, "_req", lambda _p: {pid: item})
    monkeypatch.setattr(A.cc, "fetch",
                        lambda _i, d: [os.path.join(d, "pf.png")])

    led = A.adopt(proj, "t", "shotlist.json", "P1", 20)
    assert len(led) == 1
    e = led[0]
    assert e["seed"] == 99 and e["prompt"] == "кадр у окна"
    assert e["cell"] == "P1" and e["caption"] == "у окна"
    assert e["origin"] == "canvas" and e["prompt_id"] == pid
    assert e["size"] == [1152, 1440]


def test_running_adopt_twice_does_not_duplicate(tmp_path, monkeypatch):
    """Повторный запуск — обычное дело: сняли ещё, позвали снова.

    Без сверки по prompt_id каждый вызов плодил бы копии одного кадра, и
    отбор считал бы один удачный кадр за несколько.
    """
    proj = _fixture_project(tmp_path)
    work = tmp_path / "work"
    monkeypatch.setattr(A, "work_dir", lambda *p: str(work.joinpath(*p)))
    pid, item, _ = _canvas_run()
    monkeypatch.setattr(A.cc, "_req", lambda _p: {pid: item})
    monkeypatch.setattr(A.cc, "fetch",
                        lambda _i, d: [os.path.join(d, "pf.png")])

    A.adopt(proj, "t", "shotlist.json", "P1", 20)
    led = A.adopt(proj, "t", "shotlist.json", "P1", 20)
    assert len(led) == 1


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    proj = _fixture_project(tmp_path)
    work = tmp_path / "work"
    monkeypatch.setattr(A, "work_dir", lambda *p: str(work.joinpath(*p)))
    pid, item, _ = _canvas_run()
    monkeypatch.setattr(A.cc, "_req", lambda _p: {pid: item})

    def _boom(*_a, **_k):
        raise AssertionError("всухую сервер за кадрами не зовут")
    monkeypatch.setattr(A.cc, "fetch", _boom)

    A.adopt(proj, "t", "shotlist.json", "P1", 20, dry=True)
    assert not os.path.exists(os.path.join(str(work), "t", "frames",
                                           "frames.json"))


def test_a_run_that_saves_is_not_ours():
    """Прогон, пишущий в output/, — чужой.

    На общей машине мы туда не пишем: comfy_client.ephemeral приводит наши
    прогоны к превью. Проверка отсекает соседа, но батч от холста НЕ отличает
    — оба идут превью. За дубли отвечает сверка по сиду и промпту ниже.
    """
    pid, item, g = _canvas_run()
    g.pop("14")
    g["14"] = _node("SaveImage", filename_prefix="persona-forge/x",
                    images=["13", 0])
    assert A.canvas_runs({pid: item}) == []


def test_preview_alone_is_not_enough():
    """Чужое превью на общем сервере — не наш кадр."""
    g = {"1": _node("PreviewImage", images=["0", 0]),
         "2": _node("KSampler", seed=3)}
    item = {"prompt": [0, "q", g, {}, []],
            "outputs": {"1": {"images": [
                {"filename": "a.png", "subfolder": "", "type": "temp"}]}}}
    assert A.canvas_runs({"q": item}) == []


def test_a_frame_the_batch_already_shot_is_not_adopted_again(tmp_path,
                                                             monkeypatch):
    """Сид плюс промпт — это и есть кадр.

    ЭТО ВЫЯСНИЛОСЬ ЖИВЫМ ПРОГОНОМ, А НЕ НА СИНТЕТИКЕ. Сначала холст отличался
    от батча тем, что показывает, а не сохраняет. На сервере оказалось, что
    ephemeral() приводит к превью и батч тоже, и мост потянул в реестр все 16
    кадров соседнего замера — уже записанных generate.py. Один кадр получил бы
    несколько голосов при отборе набора.
    """
    proj = _fixture_project(tmp_path)
    work = tmp_path / "work"
    monkeypatch.setattr(A, "work_dir", lambda *p: str(work.joinpath(*p)))
    frames = work / "t" / "frames"
    frames.mkdir(parents=True)
    (frames / "frames.json").write_text(json.dumps(
        [{"file": "batch.png", "seed": 7, "prompt": "a woman",
          "cell": "P1"}]), encoding="utf-8")

    pid, item, _ = _canvas_run(seed=7, prompt="a woman")
    monkeypatch.setattr(A.cc, "_req", lambda _p: {pid: item})

    def _boom(*_a, **_k):
        raise AssertionError("за уже снятым кадром ходить на сервер незачем")
    monkeypatch.setattr(A.cc, "fetch", _boom)

    led = A.adopt(proj, "t", "shotlist.json", "P1", 20)
    assert len(led) == 1, "кадр батча принят второй раз"


def test_a_frame_shot_for_the_other_part_is_also_a_duplicate(tmp_path,
                                                             monkeypatch):
    """Реестра два — профиль и история. Дубль в любом из них остаётся дублем."""
    proj = _fixture_project(tmp_path)
    work = tmp_path / "work"
    monkeypatch.setattr(A, "work_dir", lambda *p: str(work.joinpath(*p)))
    (tmp_path / "shotlist_story.json").write_text(
        json.dumps({"cells": []}), encoding="utf-8")
    story = work / "t" / "frames_story"
    story.mkdir(parents=True)
    (story / "frames.json").write_text(json.dumps(
        [{"file": "s.png", "seed": 7, "prompt": "a woman"}]), encoding="utf-8")

    pid, item, _ = _canvas_run(seed=7, prompt="a woman")
    monkeypatch.setattr(A.cc, "_req", lambda _p: {pid: item})
    monkeypatch.setattr(A.cc, "fetch", lambda *_a: (_ for _ in ()).throw(
        AssertionError("кадр части 2 принят в часть 1")))
    assert A.adopt(proj, "t", "shotlist.json", "P1", 20) == []


def test_a_genuinely_new_frame_still_gets_through(tmp_path, monkeypatch):
    """Сторож от дублей не должен закрывать дорогу новому кадру."""
    proj = _fixture_project(tmp_path)
    work = tmp_path / "work"
    monkeypatch.setattr(A, "work_dir", lambda *p: str(work.joinpath(*p)))
    frames = work / "t" / "frames"
    frames.mkdir(parents=True)
    (frames / "frames.json").write_text(json.dumps(
        [{"file": "batch.png", "seed": 7, "prompt": "a woman"}]),
        encoding="utf-8")

    pid, item, _ = _canvas_run(seed=8, prompt="a woman by the window")
    monkeypatch.setattr(A.cc, "_req", lambda _p: {pid: item})
    monkeypatch.setattr(A.cc, "fetch",
                        lambda _i, d: [os.path.join(d, "new.png")])
    led = A.adopt(proj, "t", "shotlist.json", "P1", 20)
    assert len(led) == 2 and led[-1]["seed"] == 8
