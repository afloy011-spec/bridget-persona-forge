"""Раунд 6, PF-05: композит тату писал поверх своего же входа.

Шаг 9 конвейера стоит ПОСЛЕ сдачи, то есть его вход — файл из deliverables/,
который уходит клиенту. В разметке у обеих записей приёмник совпадал с входом,
а вклейка не идемпотентна: чернило умножается на кожу, и повтор команды
умножал его на уже вклеенное. Соседняя последняя миля от ровно этого класса
дефекта защищена сравнением по иноду; композит тату не имел защиты вовсе.

Тесты ниже поведенческие — они гоняют настоящий скрипт и смотрят на БАЙТЫ на
диске, а не спрашивают вспомогательную функцию. Прошлые раунды показали, что
тест на помощника остаётся зелёным, когда проверку в рабочем коде выключают.
"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

from conftest import ROOT, case_insensitive_fs, link_dir

SCRIPTS = os.path.join(ROOT, "scripts")
SCRIPT = os.path.join(SCRIPTS, "composite_tattoo.py")


def _run(args, cwd=None):
    e = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          env=e, cwd=cwd or ROOT, timeout=180)


def _frame(path, size=(320, 400), colour=(150, 128, 112)):
    """Кадр под вклейку. Кожа ровная и светлая — тату обязана лечь заметно."""
    Image = pytest.importorskip("PIL.Image")
    pytest.importorskip("cv2")
    Image.new("RGB", size, colour).save(str(path))
    return str(path)


def _aliases(path):
    """Псевдонимы ОДНОГО файла, на которых сравнение строк молчит.

    Регистр ловится normcase, а junction (mklink /J) и короткое имя 8.3 — нет;
    именно в 8.3 раскрывается %TEMP% на рабочей машине. Список ровно тот же,
    что у теста последней мили: там эти два псевдонима и показали хешами, что
    исходник переписывается на месте при «включённой» защите.
    """
    d, name = os.path.split(path)
    # ВЕРХНИЙ РЕГИСТР — ПСЕВДОНИМ НЕ ВЕЗДЕ. На томе, различающем регистр
    # (linux в CI), это ДРУГОЙ путь, и отказа быть не должно. Спрашиваем у
    # файловой системы, а не у os.name: регистр — свойство тома.
    out = [path, os.path.join(d, ".", name)]
    if case_insensitive_fs(pathlib.Path(d)):
        out.append(path.upper())
    # Каталог-ссылка — псевдоним на обеих системах: junction на windows,
    # симлинк на posix. Без неё на linux оставались бы два варианта, которые
    # проходят и через строковое сравнение.
    link = os.path.join(os.path.dirname(d), "j_" + os.path.basename(d))
    if link_dir(d, link):
        out.append(os.path.join(link, name))
    if os.name == "nt":
        import ctypes
        buf = ctypes.create_unicode_buffer(600)
        if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 600):
            if os.path.normcase(buf.value) != os.path.normcase(path):
                out.append(buf.value)
    return out


def test_composite_refuses_to_write_over_its_input(tmp_path):
    """Приёмник = вход отвергается, и отвергается ПО ИНОДУ.

    Дефект был буквальным: --out мог указывать на сам кадр, и вклейка ложилась
    поверх предыдущей, меняя сданный файл при каждом прогоне. Регистр,
    junction и короткое имя 8.3 — это тот же файл для файловой системы и
    разные строки для сравнения строк.
    """
    src = tmp_path / "src"
    src.mkdir()
    f = _frame(src / "a.jpg")
    before = open(f, "rb").read()
    for alias in _aliases(f):
        r = _run([f, "--at", "0.5,0.5", "--size", "0.4", "--out", alias])
        assert r.returncode != 0, f"--out {alias} не отвергнут"
        assert "совпадает с входным кадром" in (r.stdout + r.stderr), r.stdout
        assert open(f, "rb").read() == before, f"кадр изменён отказом на {alias}"


def test_default_out_does_not_land_on_a_jpg_input(tmp_path):
    """Приёмник по умолчанию строился заменой ".png" в имени входа. Сдача
    лежит в .jpg, замена не срабатывала — и команда БЕЗ --out записывала
    результат прямо в сданный кадр. Ветка превью это уже чинила через
    splitext, то есть ловушка была закрыта ровно там, где не портила кадр.
    """
    f = _frame(tmp_path / "05_restaurant_evening.jpg")
    before = open(f, "rb").read()
    r = _run([f, "--at", "0.5,0.5", "--size", "0.4"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert open(f, "rb").read() == before, "кадр переписан прогоном по умолчанию"
    made = [p for p in os.listdir(tmp_path) if p != os.path.basename(f)]
    assert made, "прогон не создал ни одного нового файла"


def _placements(tmp_path, frames_dir, out_dir):
    """Разметка на два кадра: вход в одной папке, приёмники в другой."""
    os.makedirs(frames_dir, exist_ok=True)
    places = []
    for name in ("03_paddle_court.jpg", "05_restaurant_evening.jpg"):
        _frame(os.path.join(frames_dir, name))
        places.append({"frame": os.path.join(frames_dir, name),
                       "at": [0.5, 0.5], "size": 0.4, "rot": 12,
                       "out": os.path.join(out_dir, name)})
    p = tmp_path / "placements.json"
    p.write_text(json.dumps(places, ensure_ascii=False), encoding="utf-8")
    return str(p), places


def test_placements_run_twice_gives_the_same_bytes(tmp_path):
    """ПОВТОРЯЕМОСТЬ шага, ради которой всё и затевалось: два прогона одной
    разметки дают одинаковый файл, а вход не меняется вовсе. Замеренный дефект
    был обратным — размер приёмника рос от прогона к прогону, потому что
    приёмником был сам вход.
    """
    path, places = _placements(tmp_path, str(tmp_path / "deliver"),
                               str(tmp_path / "tattoo"))
    src_before = [open(p["frame"], "rb").read() for p in places]

    r = _run(["--placements", path])
    assert r.returncode == 0, r.stdout + r.stderr
    first = [open(p["out"], "rb").read() for p in places]

    r = _run(["--placements", path])
    assert r.returncode == 0, r.stdout + r.stderr
    second = [open(p["out"], "rb").read() for p in places]

    for p, a, b, s in zip(places, first, second, src_before):
        assert a == b, f"{p['out']}: второй прогон дал другой файл"
        assert open(p["frame"], "rb").read() == s, f"{p['frame']}: вход изменён"
        assert a != s, f"{p['out']}: тату не вклеилась вовсе"


def test_placements_refuse_an_out_that_is_another_entry_input(tmp_path):
    """Приёмник одной записи = вход другой: разметка обходится по порядку, и
    вторая запись легла бы на уже вклеенный кадр. Отказ обязан случиться ДО
    первой записи — иначе «отказ» означает наполовину сделанную работу.
    """
    frames = tmp_path / "deliver"
    out_dir = tmp_path / "tattoo"
    path, places = _placements(tmp_path, str(frames), str(out_dir))
    # Псевдоним берётся такой, который им является на ЭТОМ томе: на linux
    # верхний регистр — другой путь, и тогда пара проверяется прямым
    # совпадением, а сам разбор регистра — отдельным случаем выше.
    places[0]["out"] = (places[1]["frame"].upper()
                        if case_insensitive_fs(tmp_path)
                        else places[1]["frame"])
    (tmp_path / "placements.json").write_text(
        json.dumps(places, ensure_ascii=False), encoding="utf-8")

    r = _run(["--placements", path])
    assert r.returncode != 0, "разметка с приёмником поверх чужого входа принята"
    assert "входной кадр разметки" in (r.stdout + r.stderr), r.stdout
    assert not os.path.isdir(out_dir), "отказ случился после первой записи"


def test_preview_lands_next_to_the_destination_not_the_delivery(tmp_path):
    """Рамка не имеет права появляться в папке сдачи. Раньше --placements
    --preview клал её рядом с кадром, то есть в deliverables/: контакт-лист
    собирает эту папку рекурсивно и брал рамку шестым кадром, а deliver.py
    ругался на неё как на файл прошлого прогона.
    """
    frames = tmp_path / "deliver"
    out_dir = tmp_path / "tattoo"
    path, places = _placements(tmp_path, str(frames), str(out_dir))
    was = sorted(os.listdir(frames))

    r = _run(["--placements", path, "--preview"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert sorted(os.listdir(frames)) == was, "превью насорило в папке сдачи"
    made = sorted(os.listdir(out_dir))
    assert made and all("_preview" in f for f in made), made
    for p in places:
        assert not os.path.exists(p["out"]), "превью вклеило тату по-настоящему"


def test_generated_placements_never_land_in_the_input_folder(tmp_path):
    """Разметка, которую СОБИРАЕТ замер запястья, не пишет в папку входа.

    Раньше здесь проверялась ручная разметка `projects/bridget/
    tattoo_placements.json` — у обеих её записей приёмник совпадал со сданным
    кадром, этим дефект и был. Файла больше нет: место тату теперь не
    подбирается руками, а считается (metrics/wrist.py), и стеречь надо не
    зафиксированные координаты, а сборку записей. Инвариант тот же и по той же
    причине: вклейка не идемпотентна, чернило умножается на кожу, и приёмник в
    папке входа превращает повтор команды в тату поверх тату.
    """
    sys.path.insert(0, SCRIPTS)
    from metrics import wrist
    src = tmp_path / "frames" / "a.png"
    src.parent.mkdir()
    _frame(src)
    m = {"at": [0.5, 0.6], "size": 0.2, "rot": 12.0}

    good = wrist.record(str(src), m, str(tmp_path / "tattooed"))
    assert os.path.dirname(good["out"]) != os.path.dirname(good["frame"])
    assert os.path.basename(good["out"]) == "a.png"

    with pytest.raises(SystemExit) as e:
        wrist.record(str(src), m, str(src.parent))
    assert "папке входа" in str(e.value), str(e.value)
    # И через «./» — то же место, другая строка.
    with pytest.raises(SystemExit):
        wrist.record(str(src), m, os.path.join(str(src.parent), "."))

    assert "out" not in wrist.record(str(src), m), (
        "без папки приёмника запись обязана остаться без ключа out — "
        "умолчание считает composite_tattoo, и оно у него проверено")


def test_placements_check_the_default_destination_too(tmp_path, monkeypatch):
    """Запись БЕЗ ключа out обходила предпроверку целиком: она стояла на
    `if dst and ...`, а умолчание считается позже, уже внутри composite.
    Значит пара «запись 1 пишет умолчанием в файл, который запись 2 читает»
    проходила молча — тот же дефект «вклейка поверх вклейки», только через
    имя, которого в разметке не написано.

    Проверяется ПОВЕДЕНИЕМ: приёмник по умолчанию у первой записи совпадает
    со входом второй, и прогон обязан отказаться ДО первой записи.
    """
    import composite_tattoo as ct
    frame = tmp_path / "a.png"
    _frame(frame)
    second = tmp_path / "a_tattoo.png"        # ровно умолчание первой записи
    _frame(second)
    places = tmp_path / "pl.json"
    places.write_text(json.dumps([
        {"frame": str(frame), "at": [0.5, 0.5], "size": 0.2},
        {"frame": str(second), "at": [0.5, 0.5], "size": 0.2,
         "out": str(tmp_path / "b.png")},
    ]), encoding="utf-8")
    before = second.read_bytes()
    with pytest.raises(SystemExit) as e:
        ct.run_placements(str(places))
    assert "входной кадр разметки" in str(e.value), str(e.value)
    assert second.read_bytes() == before, "отказ случился после записи"


def test_placements_refuse_two_entries_writing_to_one_file(tmp_path):
    """Две записи с ОДНИМ приёмником: вторая молча затирала первую, и пропажа
    обнаруживалась только тем, что кадров на выходе меньше, чем строк."""
    import composite_tattoo as ct
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    _frame(a)
    _frame(b)
    one = str(tmp_path / "one.png")
    places = tmp_path / "pl.json"
    places.write_text(json.dumps([
        {"frame": str(a), "at": [0.5, 0.5], "size": 0.2, "out": one},
        {"frame": str(b), "at": [0.5, 0.5], "size": 0.2, "out": one},
    ]), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        ct.run_placements(str(places))
    assert "уже занят записью" in str(e.value), str(e.value)
    assert not os.path.exists(one), "первая вклейка успела записаться"
