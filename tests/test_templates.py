#!/usr/bin/env python3
"""Сторож папки шаблонов: что в ней лежит, тем и снимаем.

  py -3 -m pytest tests/test_templates.py -q

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ. Ревизия 20.08.2026 нашла в `templates/comfy/` три вида
гнили, и все три завелись молча, потому что смотреть за папкой было некому.

  1. МЁРТВЫЙ ГРАФ. Шаблон, который не грузит ни один скрипт и не поминает ни
     один документ, отличим от рабочего только чтением всего репозитория. К
     ревизии таких набралось три из четырнадцати.
  2. ССЫЛКА, ПЕРЕЖИВШАЯ ФАЙЛ. Шапка эдит-шаблона отправляла читателя к
     соседнему графу «он лежит рядом» — а графа рядом не было бы уже через
     одну правку, и узнать об этом было неоткуда.
  3. ИМЯ ВЕСОВ, РАЗОШЕДШЕЕСЯ С МАНИФЕСТОМ. Самое дорогое: конвейер остаётся
     зелёным, тесты тоже, а кадры снимаются другой моделью или другой силой
     лоры. Никакого сигнала, кроме пикселей, здесь нет.

Каждое правило ниже привязано к одному из этих трёх случаев, и ни одно не
написано «на всякий случай». Сеть не нужна: всё проверяется по файлам.

СПИСКОВ-ПОБЛАЖЕК ЗДЕСЬ НЕТ НАМЕРЕННО. Единственный способ разрешить
расхождение — написать его в `docs/templates.md`: тест считает документ частью
проверки, а не украшением. Тихо добавить исключение в тест можно всегда, а
тихо добавить абзац в сдаваемую страницу — нельзя.
"""
import os, re, json, glob

import pytest

import conftest  # noqa: F401  — кладёт scripts/ в путь раньше импортов ниже

from _util import ROOT, manifest

DOC = os.path.join(ROOT, "docs", "templates.md")
DIR = os.path.join(ROOT, "templates", "comfy")

# Расширения весов. Ищутся по СЫРОМУ ТЕКСТУ файла, а не по разобранным входам:
# на холсте имена лежат внутри строки-виджета Lora Box, и разбор по узлам их
# не видит — а подменить вес там так же легко, как в любом другом месте.
_WEIGHT = re.compile(r"[\w./\\-]+\.(?:safetensors|pth|onnx|torchscript|ckpt|pt|sft)\b")

# Ссылка прозой на файл репозитория. Только три расширения: у путей вида
# «REPLACED_BY_SCRIPT.png» и имён весов проверять существование бессмысленно —
# первое подставляет скрипт, второе живёт на воркере, а не в дереве.
_REF = re.compile(r"\b(?:[\w.-]+/)*[\w.-]+\.(?:py|json|md)\b")

LORA_CLASSES = ("LoraLoaderModelOnly", "LoraLoader")
BASE_LOADERS = {"UNETLoader": "unet", "CLIPLoader": "clip", "VAELoader": "vae"}

# «Одноразовая камера» — ЕДИНСТВЕННАЯ лора, чья сила в шаблоне законно не равна
# манифесту. Её силу выбирает generate.DISPOSABLE_BY_SCENE по классу сцены
# (день и интерьер 0.0, ночь 0.55, вспышка 0.8) и подставляет ПО ИМЕНИ ЛОРЫ, а
# не по номеру слота. В файле стоит дневное значение, чтобы шаблон, запущенный
# руками как есть, не зеленил кадр. Причина записана и в шаблоне, и в
# docs/templates.md — здесь она повторена, потому что тест читают отдельно.
SCENE_DRIVEN = "disposable"


def templates():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(DIR, "*.json")))


def load(name):
    with open(os.path.join(DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def raw(name):
    with open(os.path.join(DIR, name), encoding="utf-8") as fh:
        return fh.read()


def doc_text():
    with open(DOC, encoding="utf-8") as fh:
        return fh.read()


def manifest_text():
    with open(os.path.join(ROOT, "assets.json"), encoding="utf-8") as fh:
        return fh.read()


def is_canvas(graph):
    """Холст или API-prompt. Отличаются формой корня, а не именем файла."""
    return isinstance(graph.get("nodes"), list)


def api_nodes(graph):
    return {nid: node for nid, node in graph.items()
            if not nid.startswith("_") and isinstance(node, dict)}


def loras(name):
    """(имя лоры, сила) из шаблона любой формы, включая нутро Lora Box."""
    graph = load(name)
    out = []
    if is_canvas(graph):
        for node in graph["nodes"]:
            wv = node.get("widgets_values") or []
            if node.get("type") in LORA_CLASSES and len(wv) >= 2:
                out.append((wv[0], float(wv[1])))
            elif node.get("type") == "LoraBox" and wv:
                try:
                    rows = json.loads(wv[0]).get("rows", [])
                except (ValueError, TypeError):
                    rows = []
                for row in rows:
                    out.append((row.get("name"), float(row.get("sm", 0.0))))
        return out
    for node in api_nodes(graph).values():
        if node.get("class_type") in LORA_CLASSES:
            inp = node.get("inputs", {})
            out.append((inp.get("lora_name"), float(inp.get("strength_model", 0.0))))
    return out


def base_models(name):
    """(что грузится, имя файла) для трёх базовых загрузчиков."""
    graph = load(name)
    out = []
    if is_canvas(graph):
        for node in graph["nodes"]:
            kind = BASE_LOADERS.get(node.get("type"))
            wv = node.get("widgets_values") or []
            if kind and wv:
                out.append((kind, wv[0]))
        return out
    for node in api_nodes(graph).values():
        kind = BASE_LOADERS.get(node.get("class_type"))
        if kind:
            out.append((kind, node.get("inputs", {}).get(kind + "_name")))
    return out


NAMES = templates()


@pytest.mark.parametrize("name", NAMES)
def test_template_parses(name):
    """Разбирается как JSON и имеет узлы.

    Правка шаблона — это правка текста руками (комментарии в нём живут
    ключами `_`, и переписывать файл через json.dump нельзя, иначе слетает вся
    вёрстка). Значит запятая теряется здесь так же легко, как в коде, а
    падает такой файл уже на воркере, посреди батча.
    """
    graph = load(name)
    assert isinstance(graph, dict) and graph, name
    count = len(graph["nodes"]) if is_canvas(graph) else len(api_nodes(graph))
    assert count > 0, "в {} нет ни одного узла".format(name)


@pytest.mark.parametrize("name", NAMES)
def test_links_point_at_existing_nodes(name):
    """Ссылка ведёт в узел, который есть.

    Разорванную связь ComfyUI ловит только на исполнении, то есть после
    загрузки моделей: минута ожидания ради ошибки, которую видно в файле.
    Чаще всего она появляется при удалении узла — как при выкидывании второго
    референса, где `drop_second_ref` обязан снять и узлы, и ссылки на них.
    """
    graph = load(name)
    if is_canvas(graph):
        ids = {n["id"] for n in graph["nodes"]}
        for link in graph.get("links", []):
            lid, src, _sslot, dst, _dslot = link[0], link[1], link[2], link[3], link[4]
            assert src in ids and dst in ids, (
                "связь {} холста {} висит в пустоте: {} → {}"
                .format(lid, name, src, dst))
        return
    nodes = api_nodes(graph)
    for nid, node in nodes.items():
        assert "class_type" in node, "у узла {} шаблона {} нет class_type".format(nid, name)
        for key, value in node.get("inputs", {}).items():
            if (isinstance(value, list) and len(value) == 2
                    and isinstance(value[0], str) and isinstance(value[1], int)):
                assert value[0] in nodes, (
                    "{}: вход {} узла {} ссылается на узел {}, которого в "
                    "шаблоне нет".format(name, key, nid, value[0]))


@pytest.mark.parametrize("name", NAMES)
def test_every_weight_is_declared_somewhere(name):
    """Каждое имя весов объявлено: либо в манифесте, либо в docs/templates.md.

    ЭТО ПРО ТИХУЮ ПОДМЕНУ. Имя модели в шаблоне — такой же параметр, как сила
    лоры, но ошибка в нём не падает: воркер берёт то, что назвали, и кадр
    выходит нормальный, просто снятый не тем. Манифест объявляет веса
    конвейера; всё остальное (стенд без дистилляции, выключенная ветка свопа,
    препроцессоры метрик) обязано быть названо в сдаваемой странице с
    объяснением, почему его нет в манифесте.
    """
    declared = manifest_text() + doc_text()
    unknown = sorted({w for w in _WEIGHT.findall(raw(name)) if w not in declared})
    assert not unknown, (
        "{} грузит веса, о которых не сказано ни в assets.json, ни в "
        "docs/templates.md: {}.\n"
        "  Либо это подмена, либо про неё надо написать — молча вписанное имя "
        "меняет кадры при зелёных тестах.".format(name, ", ".join(unknown)))


@pytest.mark.parametrize("name", NAMES)
def test_base_models_match_the_manifest(name):
    """unet / clip / vae равны `models.base`.

    ПОЧЕМУ ЭТО СТРОЖЕ ПРЕДЫДУЩЕГО ПРАВИЛА. В эдит-ветке имена базовых моделей
    из манифеста не берутся вовсе: `generate.EDIT_KNOB` их не применяет, и
    работает то, что зашито в узлах шаблона. То есть манифест можно поправить,
    а сниматься всё будет прежним — ровно тот дефект, который уже находили на
    энкодере (три варианта дали три побайтово одинаковых кадра).

    Отступление разрешено только записанное: имя, названное в
    docs/templates.md, считается объяснённым (там стенд базы без дистилляции).
    """
    base = manifest()["models"]["base"]
    doc = doc_text()
    for kind, got in base_models(name):
        if got is None:
            continue
        assert got == base[kind] or got in doc, (
            "{}: {} = {!r}, а манифест говорит {!r}. Либо привести к "
            "манифесту, либо объяснить расхождение в docs/templates.md."
            .format(name, kind, got, base[kind]))


@pytest.mark.parametrize("name", NAMES)
def test_lora_strengths_match_the_manifest(name):
    """Сила лоры в шаблоне равна силе в манифесте.

    Силы подобраны замерами и лежат в `assets.json`. Число, разошедшееся с
    ними в шаблоне, — это другой вид кадра при полном отсутствии сигнала:
    ручной прогон снимет одним, конвейер другим, и разницу видно только
    глазами на кропе.

    Исключение ровно одно и названо выше константой: сила «одноразовой
    камеры» выбирается по классу сцены.
    """
    man = manifest()["models"]
    known = {lora["name"]: float(lora["strength"]) for lora in man["realism_loras"]}
    char = man.get("character_lora") or {}
    if char.get("name"):
        known[char["name"]] = float(char.get("strength", 1.0))
    for got_name, strength in loras(name):
        if not got_name or got_name not in known:
            continue
        if SCENE_DRIVEN in got_name.lower():
            continue
        assert strength == known[got_name], (
            "{}: у лоры {} сила {}, в манифесте {}."
            .format(name, got_name, strength, known[got_name]))


@pytest.mark.parametrize("name", NAMES)
def test_prose_references_exist(name):
    """Файл, названный в комментарии шаблона, лежит в репозитории.

    ИМЕННО ТАК И БЫЛО. Шапка эдит-шаблона отправляла читателя к соседнему
    графу под qwen — «шаблон под него лежит рядом», — и этот граф удалён при
    ревизии как ненужный никому. Ссылка пережила бы файл молча: комментарии
    никто не исполняет.
    """
    missing = []
    for token in set(_REF.findall(raw(name))):
        if os.path.exists(os.path.join(ROOT, token)):
            continue
        if glob.glob(os.path.join(ROOT, "**", token), recursive=True):
            continue
        missing.append(token)
    assert not missing, (
        "{} ссылается на файлы, которых нет: {}."
        .format(name, ", ".join(sorted(missing))))


@pytest.mark.parametrize("name", NAMES)
def test_every_template_is_documented(name):
    """Каждый шаблон назван в docs/templates.md.

    ЭТО ПРАВИЛО ПРОТИВ НАКОПЛЕНИЯ. Мёртвый граф заводится не злым умыслом, а
    обычным ходом работы: сняли вопрос стендом, вопрос закрылся, файл остался.
    Через месяц никто не помнит, живой он или нет, и проверяющему приходится
    читать весь репозиторий, чтобы это выяснить. Пока каждый файл обязан иметь
    строку в таблице, ответ занимает одну минуту.
    """
    assert name in doc_text(), (
        "{} не описан в docs/templates.md. Либо строка в таблице (кто грузит, "
        "что делает, какие ноды нужны), либо файл удалить.".format(name))


def test_the_doc_names_only_templates_that_exist():
    """Обратная сторона: ТАБЛИЦА не обещает того, чего нет.

    Удалённый шаблон обязан исчезать из таблицы. Иначе читатель ищет файл,
    которого нет, и справедливо решает, что документация врёт целиком.

    ПРОВЕРЯЕТСЯ ИМЕННО ТАБЛИЦА, А НЕ ВСЯ СТРАНИЦА, и это не поблажка. Запись
    об удалении обязана называть удалённое по имени — иначе она бесполезна:
    «удалён один шаблон» не даёт ни найти его в истории git, ни понять, не он
    ли нужен. Обещание живого файла даёт таблица, у неё и спрашиваем.
    """
    # ТАБЛИЦ В ДОКУМЕНТЕ ДВЕ, и первая ячейка второй — не шаблон, а МОДЕЛЬ,
    # которой нет в манифесте (строка объясняет, почему её там нет). Первая
    # редакция брала первый обратный апостроф в любой строке и потому
    # требовала найти `inswapper_128.onnx` среди шаблонов. Отбор по
    # расширению `.json` разводит две таблицы, не зная, где какая начинается.
    named = set()
    for line in doc_text().splitlines():
        if line.startswith("| `"):
            first = line.split("`")[1]
            if first.endswith(".json"):
                named.add(first)
    missing = sorted(n for n in named if not os.path.exists(os.path.join(DIR, n)))
    assert not missing, (
        "docs/templates.md называет шаблоны, которых нет в templates/comfy: "
        "{}.".format(", ".join(missing)))
