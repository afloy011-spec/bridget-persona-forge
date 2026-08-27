#!/usr/bin/env python3
"""Сторожа того, что репозиторий обещает СНАРУЖИ, а не внутри себя.

  py -3 -m pytest tests/test_publication_guards.py -q

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ. Предпубликационная ревизия нашла шесть блокеров, и пять
из шести — не дефекты кода, а расхождение между тем, что репозиторий говорит, и
тем, что он делает. Общая форма у всех одна: правило объявлено прозой, а
проверять его нечем, поэтому оно тихо протухает при первой же правке соседнего
файла.

Здесь лежат проверки ровно этого класса. Каждая привязана к конкретному
случаю, который УЖЕ произошёл, — ни одна не написана «на всякий случай».
"""
import json
import glob
import os
import re
import subprocess

import pytest

import conftest  # noqa: F401  — кладёт scripts/ в путь раньше импортов ниже

from _util import ROOT, manifest, character_lora
import prompts as P


# ------------------------------------------------------ адреса чужих машин


def _text_files():
    """Всё, что человек читает как документацию, плюс конфиги CI.

    НЕ scripts_sources(): её делят house-style тесты, и расширять её значит
    менять смысл сразу нескольких проверок. Адрес переехал из assets.json в
    docs/environment.md ровно потому, что сторож смотрел только в scripts/.
    """
    out = []
    for sub in ("docs", ".github"):
        for dirpath, _, names in os.walk(os.path.join(ROOT, sub)):
            for n in names:
                if n.lower().endswith((".md", ".yml", ".yaml")):
                    out.append(os.path.join(dirpath, n))
    for n in ("README.md", "SKILL.md", ".env.example"):
        p = os.path.join(ROOT, n)
        if os.path.exists(p):
            out.append(p)
    return out


# 127.0.0.1 и 0.0.0.0 разрешены намеренно: это заведомо мёртвые адреса, и
# именно ими CI пиннит COMFY_HOST, чтобы тест, полезший в сеть, упал у себя,
# а не постучался в чью-то живую машину.
_LOCAL = ("127.0.0.1", "0.0.0.0", "255.255.255.255")
_ADDR = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})(?::\d+)?")


@pytest.mark.parametrize("path", _text_files(), ids=lambda p: os.path.relpath(p, ROOT))
def test_no_machine_addresses_in_prose(path):
    """В документации нет адреса ни одной живой машины.

    ЭТО БЫЛО, И ИМЕННО ТАК. assets.json → _host_default описывает вычистку
    частного адреса как осознанную политику со словами «репозиторий задуман
    публичным портфолио», tests/test_manifest.py эту политику стережёт — но
    только по scripts_sources(). Адрес при этом жил в docs/environment.md в
    трёх строках, включая строку таблицы «endpoint». Политика была объявлена,
    сторож написан, и смотрел он не туда, куда адрес переехал.
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    found = [m.group(1) for m in _ADDR.finditer(text) if m.group(1) not in _LOCAL]
    assert not found, (
        "в {} стоит адрес живой машины: {}. Публикация репозитория раздаёт "
        "его вместе с портом. Подставляйте $COMFY_HOST или "
        "http://<your-comfyui>:8188.".format(os.path.relpath(path, ROOT),
                                             ", ".join(sorted(set(found)))))


# --------------------------------------------- цитаты манифеста в прозе


_QUOTE = re.compile(r"assets\.json\s*(?:→|->)\s*([A-Za-z_][\w.]*)")


def test_manifest_paths_quoted_in_docs_resolve():
    """Каждый путь вида `assets.json → models.foo`, названный в прозе, есть.

    ЗАЧЕМ. docs/environment.md обосновывал всю архитектуру идентичности двумя
    ключами — `models.raw_for_training.installed` и `models.character_lora.path`
    — которых в манифесте НЕТ: первый удалён, второй не существовал никогда.
    Читатель шёл проверять довод и не находил, на что смотреть. Ошибка при
    этом молчаливая: проза не исполняется, и протухает она бесшумно.
    """
    man = manifest()
    bad = []
    for path in _text_files():
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for m in _QUOTE.finditer(text):
            node, ok = man, True
            for part in m.group(1).split("."):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    ok = False
                    break
            if not ok:
                bad.append("{}: assets.json -> {}".format(
                    os.path.relpath(path, ROOT), m.group(1)))
    assert not bad, (
        "проза ссылается на ключи манифеста, которых нет:\n  "
        + "\n  ".join(sorted(set(bad))))


# ------------------------------------------------ персонажная лора и её хозяин


def test_character_lora_declares_whose_face_it_carries():
    """У включённой персонажной лоры есть ключ `for`.

    Ключ глобальный, а лицо в нём — конкретного человека. Без `for` проверить
    принадлежность нечем, и лора уезжает в кадры любого персонажа.
    """
    ch = manifest()["models"].get("character_lora") or {}
    if not ch.get("name"):
        pytest.skip("персонажная лора не настроена — штатный режим")
    assert ch.get("for"), (
        "у персонажной лоры {} нет ключа `for`: некому проверить, тому ли "
        "персонажу она принадлежит".format(ch["name"]))


def test_character_lora_does_not_leak_into_other_projects():
    """Триггер чужой лоры не попадает в промпт другого персонажа.

    ЗАМЕР, ИЗ КОТОРОГО ЭТОТ ТЕСТ ВЫРОС: `py -3 scripts/prompts.py
    projects/marek` печатал `brdgt_w, a candid photograph of a real man, … a
    57-year-old man…`. Лицо 51-летней женщины на полной силе уезжало в кадры
    57-летнего мужчины, молча, а папки выхода разводились правильно — значит
    подмену было видно только в пикселях.
    """
    ch = manifest()["models"].get("character_lora") or {}
    owner = ch.get("for")
    if not ch.get("name") or not owner:
        pytest.skip("персонажная лора не настроена или не объявляет хозяина")
    trigger = ch.get("trigger") or ""
    checked = 0
    for name in sorted(os.listdir(os.path.join(ROOT, "projects"))):
        pdir = os.path.join(ROOT, "projects", name)
        card = os.path.join(pdir, "character.json")
        if not os.path.exists(card):
            continue
        with open(card, encoding="utf-8") as fh:
            char = json.load(fh)
        cid = char.get("id")
        mine = character_lora(cid)
        if cid == owner:
            assert mine.get("name") == ch["name"], (
                "своя лора не досталась «{}»".format(cid))
        else:
            assert mine == {}, (
                "персонажу «{}» досталась лора «{}», обученная на «{}»".format(
                    cid, ch["name"], owner))
            checked += 1
            if trigger:
                assert trigger not in P._character_trigger(char_id=cid), (
                    "триггер «{}» уезжает в промпт «{}»".format(trigger, cid))
    assert checked, "в репозитории нет второго персонажа — проверять нечего"


# ------------------------------------------------------- паритет ранбуков


_CMD = re.compile(r"scripts/([a-z_0-9]+\.py)")


def test_every_script_named_in_a_runbook_exists():
    """Ни один ранбук не зовёт скрипт, которого нет.

    README и SKILL — то, что копируют и вставляют. Команда, указывающая на
    отсутствующий файл, ничем не лучше отсутствующей: docs/environment.md
    перечислял `scripts/casting.py`, которого нет и никогда не было.
    """
    bad = []
    for path in _text_files():
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for m in _CMD.finditer(text):
            if not os.path.exists(os.path.join(ROOT, "scripts", m.group(1))):
                bad.append("{}: scripts/{}".format(
                    os.path.relpath(path, ROOT), m.group(1)))
    assert not bad, "ранбуки зовут несуществующие скрипты:\n  " + "\n  ".join(
        sorted(set(bad)))


def test_readme_and_skill_agree_on_which_scripts_the_runbook_uses():
    """Два ранбука называют один и тот же набор шагов.

    ОНИ РАСХОДИЛИСЬ, И ДОРОГО. Шаг 8b в README звал `skin_graft.py`, снятый с
    доводки по замеру («кладёт на смягчённую кожу регулярную сетку»), а SKILL
    на том же шаге звал `upscale.py`; строки `upscale.py` в README не было
    вовсе. Дальше шаг 9 README читал каталог, который создаёт только
    skin_graft, — то есть английский читатель, послушавшийся SKILL, упирался в
    отсутствующий вход. README при этом сам назначает SKILL источником правды.
    """
    def scripts_in(name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
            return set(_CMD.findall(fh.read()))

    readme, skill = scripts_in("README.md"), scripts_in("SKILL.md")
    # ПРОВЕРКА ОДНОСТОРОННЯЯ, И ЭТО НЕ ПОБЛАЖКА. README сам назначает SKILL.md
    # «нумерованным источником правды», поэтому SKILL законно описывает больше:
    # у него есть стенд lab_grid.py и генератор ассета тату, которых в коротком
    # ранбуке нет и быть не должно. А вот шаг, живущий ТОЛЬКО в README, — это
    # ровно тот случай, который здесь и ловится: README звал skin_graft.py,
    # снятый с доводки по замеру, и следом читал каталог, который создаёт лишь
    # он. Читатель, послушавшийся объявленного источника правды, упирался в
    # отсутствующий вход.
    only_readme = sorted(readme - skill)
    assert not only_readme, (
        "README зовёт шаги, которых нет в SKILL.md: {}.\n"
        "  README объявляет SKILL.md источником правды — значит шаг, живущий "
        "только в README, ведёт в тупик того, кто послушался README."
        .format(only_readme))


# ----------------------------------------------------------- счёт сдачи


def test_readme_promises_as_many_photographs_as_are_delivered():
    """Число кадров, обещанное README, совпадает с числом файлов в сдаче.

    ПЕРВАЯ СТРОКА README ОБЕЩАЛА ДЕСЯТЬ, В ПАПКАХ ЛЕЖАЛО ВОСЕМЬ. Проверяется
    кликом, а опровергает весь тезис репозитория о измерительной дисциплине.
    Механизм, из-за которого это прошло: deliver.py не сравнивал набор --pick
    с набором ячеек раскадровки, и частичная сдача не помечалась ничем.
    """
    # СЛОВАРЬ ДОВЕД�ён ДО ТРИДЦАТИ НЕ ДЛЯ КРАСОТЫ. Он кончался на двенадцати,
    # и в день, когда сдача выросла до тридцати кадров, тест перестал не
    # «падать», а ПРОВЕРЯТЬ: числа он не узнал и вышел через skip. Сторож,
    # который молча отключается ровно тогда, когда обещание меняется, хуже
    # отсутствующего — он создаёт видимость проверки.
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
             "twelve": 12, "fifteen": 15, "sixteen": 16, "eighteen": 18,
             "twenty": 20, "twenty-five": 25, "thirty": 30, "forty": 40,
             "fifty": 50}
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        head = fh.read(1200)
    m = re.search(r"\b(" + "|".join(words) + r")\b[^.\n]{0,40}photograph",
                  head, re.I)
    if not m:
        pytest.skip("README не называет число фотографий словом")
    promised = words[m.group(1).lower()]

    root = os.path.join(ROOT, "deliverables")
    if not os.path.isdir(root):
        pytest.skip("сдачи в репозитории нет")
    shipped = 0
    for dirpath, _, names in os.walk(root):
        shipped += len([n for n in names
                        if n.lower().endswith((".jpg", ".jpeg", ".png"))
                        and "contact_sheet" not in n.lower()])
    assert promised == shipped, (
        "README обещает {} фотографий, в deliverables/ лежит {}. Либо "
        "доотгрузить, либо поправить первую строку — но не оставлять как "
        "есть: это первое, что читает ревьюер.".format(promised, shipped))


def test_rules_digest_only_names_files_that_exist():
    """docs/RULES.md ссылается только на существующие файлы.

    ЭТО ЕДИНСТВЕННЫЙ ВИД ДРЕЙФА, КОТОРЫЙ ЗДЕСЬ ЛОВИТСЯ БУКВОЙ. Файл
    производный: он пересказывает правила, записанные в шести источниках, и
    устареть по существу может незаметно — на то в нём и стоит оговорка, что
    при расхождении прав источник. Но ссылка на переименованный или удалённый
    файл — уже не устаревание, а тупик: читатель идёт проверять правило и не
    находит, куда идти.
    """
    path = os.path.join(ROOT, "docs", "RULES.md")
    if not os.path.exists(path):
        pytest.skip("сводки правил в репозитории нет")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    # Пути внутри `обратных кавычек`: scripts/foo.py, docs/bar.md, assets.json
    named = set(re.findall(r"`([^`]+)`", text))
    missing = []
    for chunk in named:
        for token in re.split(r"[,;\s]+", chunk):
            token = token.strip().rstrip(".,;)")
            if not re.match(r"^[\w./-]+\.(py|md|json)$", token):
                continue
            if token.startswith("<") or "*" in token:
                continue
            if not os.path.exists(os.path.join(ROOT, token)):
                # имя без каталога ищется по дереву: сводка ссылается и так
                hits = glob.glob(os.path.join(ROOT, "**", token),
                                 recursive=True)
                if not hits:
                    missing.append(token)
    assert not missing, (
        "docs/RULES.md называет файлы, которых нет: {}.\n"
        "  Сводка — карта по репозиторию; ссылка в никуда делает её "
        "бесполезной ровно там, где читатель решил проверить."
        .format(sorted(set(missing))))


# ------------------------------------- вычистка перед передачей репозитория

# ЧТО ЗАПРЕЩЕНО НАЗЫВАТЬ, И ПОЧЕМУ ЭТО ШИРЕ, ЧЕМ АДРЕС. Сторож выше ловил
# только IP. Перед передачей репозитория выяснилось, что этого мало: город,
# в котором стоит воркер, имя пользователя машины, название VPN, нестандартные
# порты и личные пути в путях файлов сдачи опознают обстановку не хуже адреса,
# а некоторые — лучше. Каждый пункт здесь стоял в репозитории на самом деле.
_FORBIDDEN = [
    (r"[Cc]:[\\/]Users[\\/](?!<)[^\\/\s\"']+", "личный путь с именем пользователя"),
    (r"\b(?:SHA256|ssh-rsa|ssh-ed25519)[:\s]+[A-Za-z0-9+/]{20,}", "ключ или его отпечаток"),
    (r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "IP-адрес"),
    (r"[\w.+-]+@[\w-]+\.[\w.]{2,}", "почтовый адрес"),
]


def _local_patterns():
    """Строки, которые нельзя написать даже в сторо́же.

    ЗДЕСЬ БЫЛА СОБСТВЕННАЯ УТЕЧКА, И ЭТО ПОУЧИТЕЛЬНО. Первая редакция
    перечисляла запрещённое прямо в списке выше: логин удалённой машины,
    первое слово пароля, имя хоста, название города. Проверка текста их не
    видела ровно потому, что файл сторожа из неё исключён — сторож обязан
    содержать образцы. То есть механизм, написанный против утечки, ею и стал.

    Поэтому конкретные строки живут в `.scrub-patterns.local` — файле, который
    git не отслеживает. Владелец держит там свой список и проверяется строго;
    в переданном репозитории литералов нет вовсе, и остаются родовые признаки
    выше, которых достаточно, чтобы поймать возврат адреса или личного пути.
    """
    path = os.path.join(ROOT, ".scrub-patterns.local")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append((re.escape(line), "локальный запрет"))
    return out


_ALLOW_IP = {"0.0.0.0", "127.0.0.1", "255.255.255.255", "1.0.0.0"}


def _all_tracked():
    """ВСЕ отслеживаемые текстовые файлы, а не только документация.

    Прошлый сторож смотрел в docs/ и корень, и адрес переехал в другое место
    ровно потому, что смотрел он не туда. Здесь берётся то, что реально уедет
    с репозиторием: список git.
    """
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    for rel in out.stdout.splitlines():
        if rel.lower().endswith((".md", ".py", ".json", ".yml", ".yaml",
                                 ".txt", ".ini", ".cfg", ".example")):
            yield rel


@pytest.mark.parametrize("rel", sorted(_all_tracked()))
def test_nothing_identifies_the_machine_or_its_people(rel):
    """Ни один отслеживаемый файл не выдаёт машину, людей и обстановку.

    ПРОВЕРЯЕТСЯ ПЕРЕД ПЕРЕДАЧЕЙ И ПОСЛЕ НЕЁ. Репозиторий отдают третьей
    стороне; всё, что в нём написано, уезжает вместе с ним и обратно не
    возвращается. Каждый образец ниже стоял здесь на самом деле: город — в
    записи манифеста и трёх местах документации, имя пользователя — в путях
    `source` файлов сдачи, порты — в примерах команд.

    Заведомо безобидные адреса (localhost и подобные) разрешены явным
    списком: запрет ради запрета заставляет обходить сторожа, а не соблюдать.
    """
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        pytest.skip("файл удалён из дерева")
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    # сам сторож перечисляет запрещённое и потому себя не проверяет
    if os.path.basename(rel) == os.path.basename(__file__):
        pytest.skip("файл сторожа содержит образцы намеренно")

    hits = []
    for pattern, why in _FORBIDDEN + _local_patterns():
        for m in re.finditer(pattern, text):
            found = m.group(0)
            if why == "IP-адрес" and found in _ALLOW_IP:
                continue
            if why == "IP-адрес" and re.match(r"^\d+\.\d+\.\d+\.\d+$", found):
                # версии вида 1.43.19.2 — не адреса; у адреса все части < 256
                parts = [int(x) for x in found.split(".")]
                if any(p > 255 for p in parts) or parts[0] in (0, 1):
                    continue
            hits.append("%s (%s)" % (found, why))
    assert not hits, (
        "{} выдаёт обстановку работы: {}.\n"
        "  Репозиторий передаётся; написанное уезжает вместе с ним."
        .format(rel, "; ".join(sorted(set(hits))[:6])))
