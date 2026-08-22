"""Провенанс кадра: сид и промпт лежат в самом PNG, и сдача обязана их нести.

  py -3 -m pytest tests/test_provenance.py -q

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ И ПОЧЕМУ ИМЕННО ЭТО. Три записи в реестрах проекта
стояли с seed=null, prompt=null и припиской «Сид и промпт УТРАЧЕНЫ… Кадр
невоспроизводим». Приписка была неверна: ComfyUI зашивает граф прогона в
текстовый чанк PNG, и всё, что объявили утраченным, лежало внутри самих
файлов. Значит, ломались две вещи сразу — разбор чанка (его не было) и
сторож, который обязан был закричать (его тоже не было).

Поэтому файл делится надвое. Сверху — разбор метаданных на синтетических PNG:
он должен доставать верное, молчать там, где данных нет, и НЕ путать негатив
с позитивом. Снизу — сторож по НАСТОЯЩИМ файлам сдачи: ни один кадр,
уехавший заказчику, не смеет быть без сида и промпта.

Синтетика, а не живые кадры: тест обязан быть зелёным на машине, где рабочей
папки нет вовсе. Сторож снизу — единственный, кто смотрит на реальные файлы,
и он пропускается, если сдачи ещё нет.
"""
import glob
import json
import os

import pytest

import conftest  # noqa: F401  — кладёт scripts/ в путь раньше импортов ниже

from _util import ROOT, read_json, write_json  # noqa: E402
import recover_provenance as rp  # noqa: E402


# ----------------------------------------------------------- синтетика

# ПОЗИТИВ ЗДЕСЬ КОРОЧЕ НЕГАТИВА, И ЭТО ГЛАВНОЕ В ЭТОМ ГРАФЕ. Разбор,
# берущий «самую длинную строку в графе», на нашем боевом шаблоне отвечает
# правильно случайно: негатив там ConditioningZeroOut без своего текста.
# Здесь негатив свой и намеренно длиннее — такой шаблон встречается у любого
# чужого воркфлоу, и на нём ленивый разбор молча вернул бы список запретов
# вместо промпта, а реестр после этого выглядел бы починенным.
POSITIVE = "brdgt_w, a candid photograph of a real woman, kitchen window light"
NEGATIVE = ("blurry, lowres, cgi, 3d render, plastic skin, watermark, text, "
            "extra fingers, deformed hands, oversaturated, painting, drawing, "
            "anime, doll, mannequin, airbrushed, beauty filter, smooth skin")
SEED = 2127312947
SIZE = [1152, 1440]

GRAPH = {
    "1": {"class_type": "UNETLoader",
          "inputs": {"unet_name": "base.safetensors"}},
    "4": {"class_type": "CLIPTextEncode",
          "inputs": {"text": POSITIVE, "clip": ["1", 1]}},
    "5": {"class_type": "CLIPTextEncode",
          "inputs": {"text": NEGATIVE, "clip": ["1", 1]}},
    "6": {"class_type": "EmptyLatentImage",
          "inputs": {"width": SIZE[0], "height": SIZE[1], "batch_size": 1}},
    "7": {"class_type": "KSampler",
          "inputs": {"seed": SEED, "steps": 8, "cfg": 1.0,
                     "sampler_name": "euler", "scheduler": "simple",
                     "denoise": 1.0, "model": ["1", 0], "positive": ["4", 0],
                     "negative": ["5", 0], "latent_image": ["6", 0]}},
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0]}},
    "9": {"class_type": "PreviewImage", "inputs": {"images": ["8", 0]}},
}


def make_png(path, graph=GRAPH, raw=None):
    """PNG с зашитым графом. `raw` — положить в чанк произвольный текст.

    Картинка нарочно крошечная и НЕ того размера, что объявлен в графе:
    разбор обязан читать размер генерации из графа, а не подглядывать в
    пиксели. Кадр, увеличенный последней милей, именно так и выглядит.
    """
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    meta = None
    if raw is not None or graph is not None:
        meta = PngInfo()
        meta.add_text(rp.META_KEY,
                      raw if raw is not None
                      else json.dumps(graph, ensure_ascii=False))
    Image.new("RGB", (16, 20), (120, 100, 90)).save(str(path), pnginfo=meta)
    return str(path)


def test_seed_prompt_and_size_come_out_of_the_png(tmp_path):
    """Всё, что объявили утраченным, читается из файла — и читается точно."""
    prov = rp.provenance(make_png(tmp_path / "frame.png"))
    assert prov["seed"] == SEED
    assert prov["prompt"] == POSITIVE
    assert prov["size"] == SIZE
    # Откуда взято — часть ответа, а не украшение: именно эти номера уезжают
    # в поле `_recovered`, и по ним читатель реестра может перепроверить.
    assert prov["nodes"] == {"seed": "7", "prompt": "4", "size": "6"}
    assert rp.is_complete(prov)


def test_the_longer_negative_is_not_taken_for_the_prompt(tmp_path):
    """Промпт берётся по связи `positive`, а не по длине строки.

    Проверяется на графе, где негатив ДЛИННЕЕ позитива: «самый длинный текст»
    здесь вернул бы список запретов, и запись выглядела бы восстановленной.
    """
    prov = rp.provenance(make_png(tmp_path / "frame.png"))
    assert len(NEGATIVE) > len(POSITIVE), "тест потерял смысл: негатив короче"
    assert prov["prompt"] == POSITIVE
    assert NEGATIVE not in prov["prompt"]


def test_prompt_is_followed_through_an_intermediate_node(tmp_path):
    """Между сэмплером и текстом бывает узел — обход идёт дальше, а не сдаётся.

    ConditioningCombine, FluxGuidance, ControlNetApply: у чужих шаблонов
    `positive` указывает не на энкодер, а на надстройку над ним. Разбор,
    смотрящий ровно на один шаг, объявил бы такой кадр невосстановимым.
    """
    graph = json.loads(json.dumps(GRAPH))
    graph["30"] = {"class_type": "ConditioningSetTimestepRange",
                   "inputs": {"conditioning": ["4", 0], "start": 0.0}}
    graph["7"]["inputs"]["positive"] = ["30", 0]
    prov = rp.provenance(make_png(tmp_path / "frame.png", graph))
    assert prov["prompt"] == POSITIVE
    assert prov["nodes"]["prompt"] == "4"


def test_a_png_without_metadata_says_nothing_instead_of_guessing(tmp_path):
    """Нет чанка — пустой ответ. Ни исключения, ни выдуманного сида.

    Это ровно та развилка, на которой скрипт обязан промолчать: догадка,
    записанная в реестр, через день неотличима от факта. Пустой ответ
    заставляет напечатать «восстанавливать не из чего» и оставить null.
    """
    path = make_png(tmp_path / "bare.png", graph=None)
    assert rp.png_graph(path) == {}
    assert rp.provenance(path) == {}
    assert not rp.is_complete(rp.provenance(path))


@pytest.mark.parametrize("raw", ["не json вовсе", "[]", "null", ""])
def test_unreadable_metadata_is_not_a_crash(tmp_path, raw):
    """Битый чанк — такой же «нечего читать», а не падение обхода.

    Обход реестра из двухсот записей, споткнувшийся на одном файле, не чинит
    и остальные сто девяносто девять.
    """
    assert rp.provenance(make_png(tmp_path / "broken.png", raw=raw)) == {}


def test_a_graph_without_a_sampler_yields_nothing(tmp_path):
    """Граф без сэмплера сида не содержит — и придумать его неоткуда."""
    graph = {k: v for k, v in GRAPH.items() if k != "7"}
    assert rp.provenance(make_png(tmp_path / "nosampler.png", graph)) == {}


def test_the_registry_folder_rule_is_borrowed_not_reinvented():
    """Папка реестра выбирается ЧУЖОЙ функцией, а не четвёртой копией правила.

    «frames для shotlist.json, frames_<имя> для остальных» уже записано в
    generate.py, adopt_canvas.py и deliver.py. Четвёртая копия разошлась бы с
    ними на первой правке и отправила бы починку в папку, которой конвейер не
    пользуется, — отчитавшись при этом об успехе.
    """
    import adopt_canvas
    assert rp.frames_sub is adopt_canvas.frames_sub


# ------------------------------------------------- расхождение с PNG


def test_a_recorded_seed_that_disagrees_with_the_png_is_caught():
    """Записанный сид против зашитого: расхождение обязано быть названо.

    Это ловит подмену файла — кадр, положенный в папку руками, или
    переименованный сосед по ячейке. Снаружи такая запись выглядит нормальной:
    сид есть, промпт есть, ворота посчитаны.
    """
    prov = {"seed": SEED, "prompt": POSITIVE, "size": SIZE}
    same = {"seed": SEED, "prompt": POSITIVE, "size": SIZE}
    assert rp.disagreements(same, prov) == []

    other = dict(same, seed=SEED + 1)
    said = rp.disagreements(other, prov)
    assert said and "сид" in said[0], said
    assert str(SEED) in said[0] and str(SEED + 1) in said[0]


def test_an_empty_field_is_work_to_do_and_not_a_disagreement():
    """null в реестре — это починка, а не подмена.

    Мешать одно с другим значит получить сторожа, который красный всегда и
    потому не читается никем.
    """
    prov = {"seed": SEED, "prompt": POSITIVE, "size": SIZE}
    assert rp.disagreements({"seed": None, "prompt": None, "size": None},
                            prov) == []


# ------------------------------------------------- прогон целиком, на песке


def _sandbox(tmp_path, monkeypatch, seed=None, prompt=None):
    """Проект из воздуха: карточка, раскадровка, реестр и один настоящий PNG.

    Рабочий корень подменяется переменной окружения — тем же ключом, которым
    его подменяет generate.py --dry. Без этого тест правил бы реестр машины,
    на которой запущен.
    """
    work = tmp_path / "work"
    monkeypatch.setenv("PERSONA_WORK_ROOT", str(work))
    project_dir = tmp_path / "proj"
    os.makedirs(str(project_dir))
    write_json(str(project_dir / "character.json"), {"id": "sandbox"})
    write_json(str(project_dir / "shotlist_story.json"),
               {"project": "sandbox",
                "cells": [{"id": "S1", "label": "проба"}]})
    cell_dir = work / "sandbox" / "frames_story" / "S1"
    os.makedirs(str(cell_dir))
    png = make_png(cell_dir / "S1_pick.png")
    ledger = str(work / "sandbox" / "frames_story" / "frames.json")
    write_json(ledger, [{"file": png, "cell": "S1", "label": "проба",
                         "seed": seed, "prompt": prompt, "size": None,
                         "_origin": "Отобран руками. Сид и промпт УТРАЧЕНЫ: "
                                    "пул переписан. Кадр невоспроизводим."}])
    return str(project_dir), ledger


def test_dry_run_reports_but_writes_nothing(tmp_path, monkeypatch, capsys):
    """Сухой прогон по умолчанию — домашнее правило, и оно проверяется.

    Скрипт правит уже написанное; запуск, который чинит молча, стоит затёртой
    записи реестра.
    """
    project_dir, ledger = _sandbox(tmp_path, monkeypatch)
    before = read_json(ledger)
    fixed, broken = rp.recover(project_dir, "shotlist_story.json")
    assert (fixed, broken) == (1, 0)
    assert read_json(ledger) == before, "сухой прогон переписал реестр"
    assert "НИЧЕГО НЕ ЗАПИСАНО" in capsys.readouterr().out


def test_apply_fills_the_entry_and_says_where_it_came_from(tmp_path,
                                                           monkeypatch):
    """--apply кладёт сид, промпт, размер и честное объяснение.

    Проверяется и судьба опровергнутой приписки: утверждение «сид утрачен,
    кадр невоспроизводим» не может остаться рядом с восстановленным сидом —
    иначе в одной записи лежат два взаимоисключающих утверждения. Но и
    стереть его нельзя: тогда пропадает то, что запись БЫЛА неверна.
    """
    project_dir, ledger = _sandbox(tmp_path, monkeypatch)
    rp.recover(project_dir, "shotlist_story.json", apply=True)
    entry = read_json(ledger)[0]
    assert entry["seed"] == SEED
    assert entry["prompt"] == POSITIVE
    assert entry["size"] == SIZE
    assert rp.META_KEY in entry["_recovered"]
    assert "узел 7" in entry["_recovered"], entry["_recovered"]
    assert "УТРАЧЕНЫ" in entry["_origin_superseded"]
    assert "УТРАЧЕНЫ" not in entry["_origin"]
    assert "Отобран руками." in entry["_origin"], "правда потерялась вместе с ложью"


def test_apply_is_idempotent(tmp_path, monkeypatch):
    """Второй прогон не находит работы и не трогает файл.

    Скрипт, который каждый раз что-то переписывает, невозможно поставить в
    ранбук: непонятно, чинил он или просто шумел.
    """
    project_dir, ledger = _sandbox(tmp_path, monkeypatch)
    rp.recover(project_dir, "shotlist_story.json", apply=True)
    after = read_json(ledger)
    assert rp.recover(project_dir, "shotlist_story.json", apply=True) == (0, 0)
    assert read_json(ledger) == after


def test_a_disagreeing_record_stops_the_run_and_is_not_repaired(tmp_path,
                                                                monkeypatch):
    """--all падает на расхождении и НЕ чинит его молча.

    Реестр и пиксели разошлись; какой из них прав — решает человек. Молчаливая
    правка здесь стёрла бы единственный след подмены файла.
    """
    project_dir, ledger = _sandbox(tmp_path, monkeypatch, seed=SEED + 7,
                                   prompt=POSITIVE)
    before = read_json(ledger)
    with pytest.raises(SystemExit) as err:
        rp.recover(project_dir, "shotlist_story.json", apply=True,
                   check_all=True)
    assert "расходятся" in str(err.value)
    assert read_json(ledger) == before


def test_without_all_a_filled_record_is_not_even_opened(tmp_path, monkeypatch):
    """Без --all проверяются только пустые записи: это починка, а не ревизия.

    Иначе каждый запуск читал бы двести PNG ради трёх строк, и никто не звал
    бы его перед сдачей.
    """
    project_dir, ledger = _sandbox(tmp_path, monkeypatch, seed=SEED + 7,
                                   prompt=POSITIVE)
    assert rp.recover(project_dir, "shotlist_story.json") == (0, 0)
    assert read_json(ledger)[0]["seed"] == SEED + 7


# ------------------------------------------ сторож: что уехало заказчику


def _selections():
    return sorted(glob.glob(os.path.join(ROOT, "deliverables", "**",
                                         "selection.json"), recursive=True))


def test_no_delivered_frame_is_missing_its_seed_or_prompt():
    """НИ ОДИН кадр в сдаче не смеет быть без сида и промпта.

    ЭТО ПРАВИЛО ПРОЕКТА, И ДО СИХ ПОР ЕГО НЕ ПРОВЕРЯЛО НИЧТО. generate.py
    объявляет: «кадр без записи в реестре считается мусором и в вердикт не
    попадает», adopt_canvas.py повторяет это же про ручные кадры. Сторож при
    этом стоял только на реестре первой части (tests/test_registry.py смотрит
    в `*/frames/frames.json`), а сдача — то единственное, что реально уезжает
    заказчику, — не проверялась вовсе. Результат: в двух из трёх сдач лежали
    три кадра с seed=null и prompt=null, и узнали об этом не из красного
    теста, а глазами.

    Кадр без сида и промпта нельзя ни повторить, ни объяснить: в наборе он
    выглядит ровно как остальные и молча делает всю сдачу невоспроизводимой
    наполовину. Если сид действительно негде взять — это повод не сдавать
    кадр, а не повод записать null.
    """
    paths = _selections()
    if not paths:
        pytest.skip("сдачи на этой машине нет: deliverables/*/selection.json "
                    "не найдено — сначала scripts/deliver.py")
    blind = []
    for path in paths:
        for row in read_json(path).get("frames", []):
            missing = [k for k in ("seed", "prompt") if row.get(k) is None]
            if missing:
                blind.append("{}: ячейка {} ({}) без {}".format(
                    os.path.relpath(path, ROOT), row.get("cell"),
                    os.path.basename(str(row.get("source") or "?")),
                    ", ".join(missing)))
    assert not blind, (
        "в сдаче лежат кадры без провенанса:\n  " + "\n  ".join(blind)
        + "\n  Сид и промпт зашиты в сам PNG (чанк «{}»); достать их:\n"
          "    py -3 scripts/recover_provenance.py projects/<проект> "
          "--shotlist <раскадровка> --apply".format(rp.META_KEY))


def test_delivered_frames_agree_with_the_png_they_came_from():
    """Сданный сид совпадает с зашитым в кадр, из которого сделан JPEG.

    Сторож выше требует, чтобы поле было НЕ ПУСТЫМ; этот — чтобы оно было
    ВЕРНЫМ. Разница не теоретическая: восстановление провенанса заполняет
    пустое поле числом из PNG, и без этой проверки любая будущая ошибка
    разбора выглядела бы как успешная починка.
    """
    paths = _selections()
    if not paths:
        pytest.skip("сдачи на этой машине нет: deliverables/*/selection.json "
                    "не найдено — сначала scripts/deliver.py")
    from _util import work_resolve
    checked, bad = 0, []
    for path in paths:
        for row in read_json(path).get("frames", []):
            src = work_resolve(str(row.get("source") or "").replace("\\", "/"))
            if not src or not os.path.exists(src):
                continue        # кадры не переносятся вместе с реестром
            prov = rp.provenance(src)
            if not prov:
                continue        # «чанка нет» — случай сторожа выше, не этого
            checked += 1
            said = rp.disagreements(row, prov)
            if said:
                bad.append("{}: {} — {}".format(os.path.relpath(path, ROOT),
                                                row.get("cell"),
                                                "; ".join(said)))
    if not checked:
        pytest.skip("кадров сдачи нет на диске — сверять не с чем")
    assert not bad, "сдача расходится со своими PNG:\n  " + "\n  ".join(bad)
