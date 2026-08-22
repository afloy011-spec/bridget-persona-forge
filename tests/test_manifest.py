"""Манифест: пороги ворот, последняя миля, единственное место правды про сервер.

  py -3 -m pytest tests/test_manifest.py -q

assets.json — данные, но данные исполняемые: числа отсюда решают, поедет кадр
в сдачу или нет. Три вещи, которые уже стоили ревью отдельного абзаца:
повторное JPEG-сжатие с ПОВЫШЕНИЕМ качества (физически невозможная история
файла), пороги, перепутанные местами, и адрес сервера, вписанный в код.
"""
import glob
import os
import re

import pytest

from conftest import MANIFEST, ROOT, scripts_sources


def test_lastmile_encodes_jpeg_once():
    """Второго прохода JPEG быть не должно.

    q92 → q96 не добавляет информации: повторное кодирование с БОЛЬШИМ
    качеством только раздувает файл и оставляет таблицы квантования, которых у
    настоящего снимка не бывает — «снял → отправил» так не выглядит ни в одном
    реальном файле. Один проход, один набор таблиц.
    """
    lastmile = MANIFEST["lastmile"]
    extra = {k: v for k, v in lastmile.items()
             if not k.startswith("_") and "jpeg" in k and k != "jpeg_quality"}
    assert not any(bool(v) for v in extra.values()), \
        f"второй проход JPEG всё ещё объявлен: {extra}"
    assert 70 <= lastmile["jpeg_quality"] <= 96


def test_no_script_performs_a_second_jpeg_pass():
    """И в коде тоже: ключ можно убрать из манифеста, а вызов оставить."""
    for path in scripts_sources():
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        assert "jpeg_second_pass" not in src, path


def test_gate_thresholds_are_ordered():
    """Минимум ниже максимума у КАЖДОЙ пары порогов, какой бы она ни была.

    Перебор по именам, а не список ключей: метрики заменяются (хрома → разброс
    тона, резкость кадра → резкость лица), и проверка, прибитая к конкретным
    именам, умирает вместе со старой метрикой ровно тогда, когда новая ещё не
    проверена никем. Перепутанные местами границы дают ворота, которые не
    отбраковывают ничего и при этом выглядят настроенными.
    """
    g = {k: v for k, v in MANIFEST["gates"].items()
         if not k.startswith("_") and isinstance(v, (int, float))}
    pairs = [(k, k[:-4] + "_max") for k in g if k.endswith("_min")
             and k[:-4] + "_max" in g]
    assert pairs, f"в манифесте нет ни одной пары порогов: {sorted(g)}"
    for lo, hi in pairs:
        assert g[lo] < g[hi], f"{lo} = {g[lo]} не ниже {hi} = {g[hi]}"


def test_share_thresholds_stay_within_zero_and_one():
    """Пороги-доли (косинус, вероятность, доля кожи) обязаны лежать в [0, 1].

    Число вне шкалы — это не строгие ворота, а отключённые: 45 при пороге
    «доля» не отбракует ничего и никогда.
    """
    g = MANIFEST["gates"]
    for key in ("identity_cosine_min", "identity_cosine_warn",
                "skin_smooth_max", "detector_max_ai_prob"):
        if key in g:
            assert 0.0 < g[key] < 1.0, f"{key} = {g[key]}"
    if {"identity_cosine_warn", "identity_cosine_min"} <= set(g):
        assert g["identity_cosine_warn"] < g["identity_cosine_min"]


def test_declared_age_band_contains_the_character_age():
    """Полоса возраста обязана накрывать возраст персонажа из карточки.

    Спрашивается у _util.age_band, а не у ключей манифеста. Жёсткие age_min и
    age_max были верны ровно для ОДНОГО человека, и второй персонаж 34 лет
    проваливал ворота возраста самим фактом своего существования: ворота,
    зашитые под одну карточку, — это не ворота системы. Тест поймал это на
    первом же чужом проекте.
    """
    from conftest import PROJECTS
    import _util
    for pdir, char, _spath, _shots in PROJECTS:
        age = char.get("age")
        if age is None:
            continue
        lo, hi = _util.age_band(char)
        assert lo <= age <= hi, f"{os.path.basename(pdir)}: {age} вне {lo}-{hi}"
        # ПРО АСИММЕТРИЮ ДОПУСКА ЗДЕСЬ НИЧЕГО НЕ УТВЕРЖДАЕТСЯ. Первая
        # редакция этого теста требовала, чтобы запас снизу был не уже, чем
        # сверху («модели тянут женщину к двадцати семи»), — и покраснела на
        # собственных числах: у Бриджит 6 вниз и 7 вверх. Обоснование звучало
        # разумно и противоречило данным; проверять надо то, что известно, а
        # не то, что складно.
        assert lo < hi, "полоса вырождена"


def test_output_sizes_are_vertical():
    """Профиль 4:5, история 9:16 — «снято её телефоном», а не кино."""
    w, h = MANIFEST["output"]["profile_size"]
    assert h > w and abs(w / h - 0.8) < 0.01
    w, h = MANIFEST["output"]["story_size"]
    assert h > w and abs(w / h - 9 / 16) < 0.01


def test_server_address_lives_only_in_the_manifest():
    """В коде адресов нет: вписанный в скрипт хост молча ходил в чужую сеть.

    Локальная заглушка 127.0.0.1 разрешена — это последний запасной вариант
    клиента, а не чей-то настоящий сервер.
    """
    ip = re.compile(r"\b(?!127\.0\.0\.1)(?:\d{1,3}\.){3}\d{1,3}\b")
    for path in scripts_sources():
        with open(path, encoding="utf-8") as fh:
            found = ip.findall(fh.read())
        assert not found, f"{path}: адрес в коде {found}"


def test_host_override_is_read_from_environment(monkeypatch, tmp_path):
    """Контракт адреса: COMFY_HOST → assets.local.json → внятная ошибка.

    Отслеживаемый манифест адреса не содержит вообще: раньше в нём лежал
    адрес рабочей машины, а соседний комментарий уверял, что «адресов
    в коде нет». Проверяется вся цепочка, включая последнее звено — падение с
    инструкцией вместо молчаливого похода на 127.0.0.1, откуда приходит
    невнятный ConnectionRefused посреди батча.
    """
    import comfy_client
    monkeypatch.setenv("COMFY_HOST", "http://example.invalid:9999/")
    assert comfy_client._default_host() == "http://example.invalid:9999"

    monkeypatch.delenv("COMFY_HOST")
    assert MANIFEST["host_default"] is None, "адрес вернулся в манифест"

    # ROOT подменяется целиком, поэтому рядом кладётся и сам манифест: без
    # него падает manifest(), а не проверяемая ветка.
    import shutil
    shutil.copy(os.path.join(ROOT, "assets.json"), tmp_path / "assets.json")
    local = tmp_path / "assets.local.json"
    local.write_text('{"host": "http://local.invalid:8188/"}', encoding="utf-8")
    monkeypatch.setattr(comfy_client, "ROOT", str(tmp_path))
    monkeypatch.setattr(comfy_client, "_MANIFEST", None)
    assert comfy_client._default_host() == "http://local.invalid:8188"

    local.unlink()
    with pytest.raises(SystemExit) as e:
        comfy_client._default_host()
    assert "COMFY_HOST" in str(e.value)


def test_metrics_modules_know_the_not_measured_state():
    """Ворота обязаны различать PASS / FAIL / НЕ ИЗМЕРЕНО.

    Метрика, которая при отсутствии зависимости (insightface, ключ детектора)
    просто выключается, даёт ложный PASS: кадр уезжает в сдачу непроверенным и
    выглядит проверенным. Отсутствие измерения среди обязательных ворот — это
    не «остальные посчитаем», а «кадр не едет».
    """
    mods = [p for p in glob.glob(os.path.join(ROOT, "scripts", "metrics", "*.py"))
            if os.path.basename(p) != "__init__.py"]
    if not mods:
        pytest.skip("ворота качества ещё не написаны")
    texts = []
    for path in mods:
        with open(path, encoding="utf-8") as fh:
            texts.append(fh.read())
    assert any("NOT_MEASURED" in t for t in texts), \
        "ни один модуль ворот не знает состояния NOT_MEASURED"


def test_base_encoder_and_vae_reach_the_graph():
    """Имена энкодера и VAE из манифеста ДОХОДЯТ до собранного графа.

    ОНИ НЕ ДОХОДИЛИ. `build_graph` подставлял unet, шаги, cfg, сэмплер и
    планировщик, а `models.base.clip`, `.clip_type` и `.vae` не подставлял:
    имена были зашиты в шаблоне. Ключи при этом объявлены в assets.json и
    описаны в docs/environment.md — то есть выглядели рабочими.

    Обнаружено попыткой заменить энкодер на расцензуренный: три разных имени
    дали три ПОБАЙТОВО ОДИНАКОВЫХ кадра. Замер, поставленный на такой подмене,
    ответил бы уверенно и неверно.
    """
    import generate as G
    g = G.build_graph("проверка", 1, (1152, 1440), "X")
    clip = [v for v in g.values()
            if isinstance(v, dict) and v.get("class_type") == "CLIPLoader"]
    vae = [v for v in g.values()
           if isinstance(v, dict) and v.get("class_type") == "VAELoader"]
    assert clip, "в графе нет CLIPLoader"
    assert vae, "в графе нет VAELoader"
    base = MANIFEST["models"]["base"]
    assert clip[0]["inputs"]["clip_name"] == base["clip"], (
        "энкодер в графе не из манифеста: {} против {}"
        .format(clip[0]["inputs"]["clip_name"], base["clip"]))
    assert clip[0]["inputs"]["type"] == base.get("clip_type", "krea2")
    assert vae[0]["inputs"]["vae_name"] == base["vae"], (
        "VAE в графе не из манифеста: {} против {}"
        .format(vae[0]["inputs"]["vae_name"], base["vae"]))
