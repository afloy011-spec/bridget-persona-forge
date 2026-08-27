#!/usr/bin/env python3
"""Батч кадров по раскадровке: ячейка × сид → PNG + запись в реестр.

  py -3 generate.py <project_dir> [cell_id ...] [--seeds 101,202] [--dry]
  py -3 generate.py <project_dir> --ref <файл|portrait=…,full=фигура|лицо>
                                                    ЭДИТ РЕФЕРЕНСА вместо t2i
  py -3 generate.py <project_dir> --casting 16      пул для калибровки

ДВА ИСТОЧНИКА ПИКСЕЛЕЙ, ОДИН КОНВЕЙЕР. Без `--ref` кадр выдумывается по
описанию; с `--ref` он ПЕРЕСНИМАЕТСЯ с референса персонажа эдит-графом. Всё
ниже по течению — реестр, ворота, отбор, сдача, тату, родинка, последняя миля
— разницы не знает и знать не должно. Замерено, зачем это нужно: косинус
ArcFace к лицу референса у сдачи, снятой текстом, 0.131-0.229 при потолке
самого материала 0.527 — в кадре другая женщина; те же сцены через эдит дают
медианы 0.47-0.53. Текст задаёт типаж, лицо есть только на референсе.

Кадры складываются в <work_root>/<project>/frames/<cell>/<cell>_s<seed>.png,
на сервере не остаётся ничего (см. политику эфемерности в comfy_client).
Рядом пишется frames.json — реестр того, что сгенерировано, с промптом и
сидом каждого кадра. Ворота и борд читают именно его, а не список файлов:
кадр без записи в реестре считается мусором и в вердикт не попадает.

--dry печатает план и промпты, ничего не отправляя. Пользоваться перед каждым
большим батчем: опечатка в раскадровке дешевле ловится здесь, чем через сорок
минут GPU.
"""
import os, sys, json, random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (setup_console, manifest, work_dir, work_root, write_json,
                   project_name, character_lora)
from prompts import load_project, build_cell, build_casting, CASTING_AXES
import comfy_client as cc

TEMPLATE = "krea2_t2i_api.json"

# Ручки шаблона. Держатся здесь, а не размазаны по коду: поменяется шаблон —
# правится одна таблица.
KNOB = {
    "prompt": "4.text",
    "seed": "7.seed",
    "steps": "7.steps",
    "cfg": "7.cfg",
    "sampler": "7.sampler_name",
    "scheduler": "7.scheduler",
    "width": "6.width",
    "height": "6.height",
    "prefix": "9.filename_prefix",
    "unet": "1.unet_name",
    # ЭНКОДЕР И VAE ТОЖЕ ИЗ МАНИФЕСТА, И ЭТОГО ЗДЕСЬ НЕ БЫЛО. Ключи
    # models.base.clip / .clip_type / .vae объявлены, задокументированы в
    # docs/environment.md и не читались НИ ОДНОЙ строкой: имена были зашиты в
    # шаблоне. Правка манифеста молча ничего не меняла — обнаружено при
    # попытке подменить энкодер на расцензуренный: три варианта дали три
    # побайтово одинаковых кадра.
    "clip": "2.clip_name",
    "clip_type": "2.type",
    "vae": "3.vae_name",
}
LORA_NODES = ["20", "21", "22", "23", "24"]

# ВТОРОЙ ИСТОЧНИК ТОГО ЖЕ КОНВЕЙЕРА: кадр не выдумывается по описанию, а
# ПЕРЕСНИМАЕТСЯ с референса персонажа. Всё, что ниже по течению — ворота,
# отбор, сдача, тату, родинка, последняя миля — не знает разницы и знать не
# должно: меняется только источник пикселей.
#
# ЗАЧЕМ. Замерено на этом проекте: косинус ArcFace к лицу референса у сдачи,
# снятой текстом, — 0.131-0.229 при потолке материала 0.527, то есть в кадре
# другая женщина. Тот же набор сцен через эдит даёт медианы 0.47-0.53.
# Текст задаёт типаж, лицо есть только на референсе.
EDIT_TEMPLATE = "krea2_identity_edit_api.json"
EDIT_KNOB = {
    "ref": "5.image", "ref_b": "15.image", "prompt": "9.prompt",
    "negative": "10.text", "seed": "12.seed", "steps": "12.steps",
    "cfg": "12.cfg", "width": "11.width", "height": "11.height",
    "prefix": "14.filename_prefix", "unet": "1.unet_name",
}
# Стек лор в эдит-графе встаёт ПОСЛЕ krea2_identity_edit (узел 4) и втекает в
# патч внимания (узел 8), а не в сэмплер: между ними лежит сам механизм эдита.
EDIT_LORA_START = "4"
EDIT_LORA_SINK = ("8", "model")

# Свет сцены → сила лоры «одноразовая камера». Лора заведена ровно под ночь со
# вспышкой; при дневном свете она красит кадр в зелень, поэтому по умолчанию
# ноль. Ячейка объявляет свой scene_class, а не гадает по тексту света.
DISPOSABLE_BY_SCENE = {"day": 0.0, "indoor": 0.0, "night": 0.55, "flash": 0.8}


def lora_stack(man=None, char_id=None):
    """Полный стек лор графа, В ПОРЯДКЕ ПРИМЕНЕНИЯ. Список словарей.

    ПЕРСОНАЖНАЯ ЛОРА ИДЁТ ПЕРВОЙ, сразу за базовой моделью, а реализм и грейд
    ложатся поверх. Она отвечает на вопрос «кто в кадре», остальные — «как это
    снято»; закреплять личность поверх стилизации значит бороться с ней же.

    Её может не быть — тогда стек прежний, и это НЕ деградация: идентичность
    в таком режиме берётся отбором набора (select_set.py), как и было. Но
    молчать о её отсутствии нельзя: «в кадре она» и «в кадре кто-то похожий»
    — разные обещания.
    """
    man = man or manifest()
    stack = []
    ch = character_lora(char_id, man)
    if ch:
        stack.append({"name": ch["name"], "strength": float(ch.get("strength", 1.0)),
                      "role": "персонаж"})
    stack += list(man["models"]["realism_loras"])
    return stack


def _apply_loras(graph, loras, start="1", slots=None, sink=("7", "model")):
    """Разложить стек лор по узлам, ДОСТРАИВАЯ цепочку под его длину.

    ТРИ ТОЧКИ ПРИВЯЗКИ ВЫНЕСЕНЫ В АРГУМЕНТЫ, потому что графов теперь два.
    `start` — узел, с которого цепочка начинается (в t2i это UNETLoader, в
    эдит-графе — уже стоящая на нём лора krea2_identity_edit: она не «вид», а
    МЕХАНИЗМ, без неё патч внимания к референсу не работает, и вставать она
    обязана первой). `slots` — готовые узлы шаблона, `sink` — куда цепляется
    хвост: в t2i это сэмплер, в эдит-графе — патч внимания. Пока всё это было
    зашито числами, второй граф означал бы вторую копию функции — и вторую
    копию дефекта, который она чинит.

    ЗДЕСЬ БЫЛА ДЫРА, И ОНА ЗАКРЫВАЛА ДОРОГУ ПЕРСОНАЖНОЙ ЛОРЕ. Узлов в шаблоне
    ровно пять, реализм-лор в манифесте тоже пять — свободных слотов не было
    ни одного, а лишние молча отбрасывались с предупреждением в stderr,
    которое при батче на сорок кадров никто не читает. То есть добавить
    персонажную лору в манифест было можно, а в кадр она не попадала.

    Узлы соединены model→model, поэтому цепочка наращивается дешевле, чем
    выбирается, что выкинуть: недостающие звенья создаются, лишние (когда
    стек короче шаблона) обнуляются по силе, а не вырезаются — вырезание
    требует перешивки связей.
    """
    slots = LORA_NODES if slots is None else slots
    last = start
    nxt = max(int(k) for k in graph if k.isdigit()) + 1
    for i, lora in enumerate(loras):
        if i < len(slots):
            nid = slots[i]
            graph[nid]["inputs"]["model"] = [last, 0]
        else:
            nid = str(nxt); nxt += 1
            graph[nid] = {"class_type": "LoraLoaderModelOnly",
                          "inputs": {"model": [last, 0]}}
        graph[nid]["inputs"]["lora_name"] = lora["name"]
        graph[nid]["inputs"]["strength_model"] = float(lora["strength"])
        last = nid
    for node_id in slots[len(loras):]:
        graph[node_id]["inputs"]["model"] = [last, 0]
        graph[node_id]["inputs"]["strength_model"] = 0.0
        last = node_id
    # Приёмник цепляется за ХВОСТ, каким бы длинным тот ни оказался.
    graph[sink[0]]["inputs"][sink[1]] = [last, 0]
    return graph


LORABOX_NODE = "20"

_HAS_LORABOX = None


def _lorabox_available():
    """Есть ли нода Lora Box на ТОМ сервере, куда мы сейчас отправляем.

    ЗАЧЕМ ПРОБА. `generate.py` — центральная команда README, и она собирала
    граф с кастомной нодой БЕЗУСЛОВНО. На стоковом ComfyUI такой граф не
    проходит валидацию вовсе, то есть главный путь проекта у стороннего
    человека не работал, а `docs/environment.md` при этом писал, что базовому
    шаблону не нужен ни один кастомный пак.

    «СЕРВЕР ОТВЕТИЛ, ЧТО НОДЫ НЕТ» И «СПРОСИТЬ НЕ УДАЛОСЬ» — РАЗНЫЕ ОТВЕТЫ, и
    путать их дорого в обе стороны. Пустой ответ на существующий эндпойнт —
    ноды действительно нет, идём в фолбэк. Сеть недоступна (сборка графа без
    сервера — это весь набор тестов и `--dry`) — сохраняем прежнее поведение,
    Lora Box, потому что оно замерено лучшим; иначе одна оборванная связь
    молча меняла бы граф, который поедет на живую машину.

    Проба одна на процесс: батч зовёт сборку сорок раз, ответ не меняется.
    """
    global _HAS_LORABOX
    if _HAS_LORABOX is None:
        try:
            _HAS_LORABOX = bool(cc.object_info("LoraBox"))
        except (Exception, SystemExit) as e:
            # SystemExit ЛОВИТСЯ ОТДЕЛЬНО, и это не педантизм: он наследует
            # BaseException, а не Exception, поэтому `except Exception` его
            # пропускает. Ровно так проба и роняла двадцать тестов на чистой
            # копии без COMFY_HOST — `comfy_client._default_host()` отвечает на
            # отсутствие адреса именно SystemExit, а сборка графа обязана
            # работать без сервера: на этом стоит весь набор и `--dry`.
            code = getattr(e, "code", None)
            # 404/400 — сервер жив и говорит «такой ноды не знаю».
            _HAS_LORABOX = code not in (400, 404)
    return _HAS_LORABOX


def _apply_lora_stack(graph, loras):
    """Lora Box, если она на сервере есть; иначе — цепочка загрузчиков.

    ЦЕНА ФОЛБЭКА НАЗЫВАЕТСЯ ВСЛУХ, а не замалчивается. `_apply_lorabox`
    дополнительно перепроводит CLIP через коробку, и реализм-лоры действуют на
    текстовый энкодер; `_apply_loras` кладёт лоры только на модель. Замер этой
    разницы — в докстроке `_apply_lorabox`: фактура лица 232 → 274, волосы
    0.599 → 0.542. То есть на стоковом сервере кадр выйдет ЧУТЬ ХУЖЕ, но
    выйдет — вместо отказа валидатора на пустом месте.

    ПЕРСОНАЖНОЙ ЛОРЫ РАЗНИЦА НЕ КАСАЕТСЯ: она обучена с
    train_text_encoder: false и CLIP-ключей не содержит вовсе.
    """
    if _lorabox_available():
        return _apply_lorabox(graph, loras)
    sys.stderr.write(
        "ВНИМАНИЕ: ноды LoraBox на сервере нет — стек лор собран цепочкой "
        "загрузчиков. Кадр получится, но реализм-лоры не подействуют на "
        "текстовый энкодер (фактура лица ~232 против ~274). Поставить пак: "
        "custom_nodes/ComfyUI-LoraBox, см. docs/environment.md.\n")
    return _apply_loras(graph, loras)


def _apply_lorabox(graph, loras):
    """Весь стек лор одной нодой Afloy Lora Box вместо цепочки загрузчиков.

    ПОЧЕМУ ПЕРЕШЛИ, И ЭТО ЗАМЕР, А НЕ УДОБСТВО. Цепочка LoraLoaderModelOnly
    кладёт лоры ТОЛЬКО на модель; Lora Box берёт и model, и clip, то есть
    реализм-лоры действуют ещё и на текстовый энкодер. Сравнение на восьми
    ячейках при одних сидах и одном промпте:
        фактура лица   232 → 274  (+42, лучше в 7 кадрах из 8)
        волосы         0.599 → 0.542 (-0.057, лучше в 8 из 8)
        сходство       0.611 → 0.591 (-0.020 при разбросе 0.040)
        фон            0.446 → 0.443 (без изменений)
    Выигрыш ровно по двум осям, которые оставались долгами проекта — фактура и
    глянцевые волосы, — и обе систематичны, а не шумны. Просадка сходства
    тонет в разбросе: лучше у Lora Box в 3 кадрах из 8, то есть знак не
    устойчив. Композиция сохраняется: тот же сид даёт ту же сцену.

    ЧЕМ ПЛАТИМ, НАЗВАНО ВСЛУХ. Lora Box — кастомная нода (ComfyUI-LoraBox).
    На чистом ComfyUI её нет, и генерация перестала быть переносимой: на
    другой машине сначала ставится нода, потом воспроизводится кадр. Это
    осознанный размен, а не недосмотр.

    ПЕРСОНАЖНОЙ ЛОРЫ РАЗНИЦА НЕ КАСАЕТСЯ: она обучена с
    train_text_encoder: false и CLIP-ключей не содержит вовсе. Меняется
    поведение реализм-лор.
    """
    import json as _json
    rows = [{"on": True, "name": l["name"], "sm": float(l["strength"]),
             "sc": float(l["strength"])} for l in loras]
    data = _json.dumps({"v": 1, "mute": False, "pos": "beginning",
                        "delim": ", ", "rows": rows}, ensure_ascii=False)
    # Слоты шаблона схлопываются в один узел: 20 становится Lora Box, 21-24
    # удаляются. Оставить их выключенными нельзя — они ждут вход model, а
    # цепочки больше нет, и валидатор графа отказал бы.
    for nid in LORA_NODES[1:]:
        graph.pop(nid, None)
    graph[LORABOX_NODE] = {
        "class_type": "LoraBox",
        "inputs": {"model": ["1", 0], "clip": ["2", 0], "data": data},
    }
    graph["7"]["inputs"]["model"] = [LORABOX_NODE, 0]
    # CLIP К ЭНКОДЕРУ ИДЁТ ЧЕРЕЗ КОРОБКУ, А НЕ НАПРЯМУЮ ОТ ЗАГРУЗЧИКА. Забыть
    # эту связь — значит получить рабочий граф, в котором лоры молча НЕ
    # действуют на текст: ровно тот выигрыш, ради которого переходили, и
    # пропал бы, а кадр остался бы правдоподобным.
    graph["4"]["inputs"]["clip"] = [LORABOX_NODE, 1]
    return graph


def _cell_refs(refs, cell):
    """(сцена, субъект|None) для ячейки: план берётся из body_in_frame.

    Отдельного поля «план» у ячейки сдачи нет и заводить его не надо: она уже
    объявляет, попадает ли в кадр фигура целиком, а именно от этого и зависит,
    чем референсить. Замерено: кроп фигуры на плане «по пояс» даёт медиану
    косинуса 0.234, кроп лица — 0.489, и полосы восьми кадров не пересекаются.
    """
    if not refs:
        return (None, None)
    key = "full" if cell.get("body_in_frame") else "portrait"
    v = refs.get(key, refs.get("*"))
    if v is None:
        raise SystemExit(
            f"ячейка {cell.get('id')} просит референс плана «{key}», а в --ref "
            f"его нет.\n  Либо допишите «{key}=путь», либо задайте общий "
            f"одним путём без «=».")
    return v if isinstance(v, tuple) else (v, None)


def build_graph(prompt, seed, size, prefix, scene_class="indoor", edit_ref=None,
                char_id=None):
    """Граф одного кадра. `edit_ref` — (сцена, субъект|None) на воркере.

    С референсом собирается эдит-граф, без него — обычный t2i. Ветка одна и
    та же ниже по течению: реестр, ворота и сдача читают кадр, а не источник.
    """
    man = manifest()
    base = man["models"]["base"]
    # СИЛА «ОДНОРАЗОВОЙ КАМЕРЫ» ПРИВЯЗАНА К ИМЕНИ ЛОРЫ, А НЕ К НОМЕРУ СЛОТА.
    # Прежняя редакция правила ПОСЛЕДНИЙ слот шаблона: перестановка строк в
    # манифесте молча переносила регулировку света на другую лору, а с
    # появлением персонажной лоры «последний слот» съехал бы гарантированно.
    loras = []
    # ОДИН СТЕК НА ОБЕ ВЕТКИ. Здесь стоял отдельный короткий список для
    # эдита: считалось, что реализм-лоры переписывают приехавшее с референса
    # лицо, и полный риг ронял косинус с 0.538 до 0.301. ПЕРЕПРОВЕРЕНО
    # 19.08.2026 — не воспроизводится. Тот же референс, те же сиды, две
    # ячейки по четыре сида на стек, 16 кадров: полный риг 0.654 по медиане
    # против 0.644 у короткого, худший кадр 0.461 против 0.426. Разница
    # +0.010 в пользу РИГА, то есть внутри разброса и уж точно не -0.237.
    # Старый замер шёл на трёх сидах одной ячейки против другого эталона и
    # больше не подтверждается; держать из-за него две расходящиеся ветки
    # дороже, чем снимать одинаково. Замер: docs/edit_rig_ab.md.
    for lora in lora_stack(man, char_id):
        lora = dict(lora)
        if "disposable" in lora["name"].lower():
            lora["strength"] = DISPOSABLE_BY_SCENE.get(scene_class, 0.0)
        loras.append(lora)
    if edit_ref:
        scene, subject = edit_ref
        graph = cc.load_template(EDIT_TEMPLATE)
        if not subject:
            from edit_dataset import drop_second_ref
            drop_second_ref(graph)
        else:
            cc.apply_sets(graph, {EDIT_KNOB["ref_b"]: subject})
        # Персонажная лора и реализм ложатся ПОВЕРХ механизма эдита; сила
        # «одноразовой камеры» по-прежнему считается по сцене выше.
        graph = _apply_loras(graph, loras, start=EDIT_LORA_START, slots=[],
                             sink=EDIT_LORA_SINK)
        cc.apply_sets(graph, {
            EDIT_KNOB["ref"]: scene,
            EDIT_KNOB["prompt"]: prompt,
            EDIT_KNOB["seed"]: int(seed),
            EDIT_KNOB["width"]: int(size[0]),
            EDIT_KNOB["height"]: int(size[1]),
            EDIT_KNOB["prefix"]: prefix,
        })
        return graph

    graph = _apply_lora_stack(cc.load_template(TEMPLATE), loras)
    cc.apply_sets(graph, {
        KNOB["unet"]: base["unet"],
        KNOB["clip"]: base["clip"],
        KNOB["clip_type"]: base.get("clip_type", "krea2"),
        KNOB["vae"]: base["vae"],
        KNOB["prompt"]: prompt,
        KNOB["seed"]: int(seed),
        KNOB["steps"]: base["steps"],
        KNOB["cfg"]: base["cfg"],
        KNOB["sampler"]: base["sampler"],
        KNOB["scheduler"]: base["scheduler"],
        KNOB["width"]: int(size[0]),
        KNOB["height"]: int(size[1]),
        KNOB["prefix"]: prefix,
    })
    return graph


def generate(project_dir, cell_ids=None, seeds=None, dry=False,
             shotlist="shotlist.json", refs=None):
    char, shots = load_project(project_dir, shotlist)
    project = project_name(project_dir, shots, char)
    refs = refs or {}

    # ПЕРЕНОСА ЛИЦА ЗДЕСЬ НЕТ, И ЭТО РЕШЕНИЕ ПО ЗАМЕРУ. Ветка фейс-свопа
    # существовала, была измерена и удалена: она давала лучший косинус (0.855)
    # ценой кожи — inswapper синтезирует лицо в 128x128 и вклеивает в кадр
    # 1152x1440, а всё, что это чинит, либо заглаживает поры, либо тянет лицо
    # обратно к типажу. Идентичность берётся отбором набора (select_set.py).
    # Таблица замеров — assets.json → identity._measured; код ветки — в
    # истории git до коммита «мёртвый груз ветки свопа удалён».
    if refs:
        # План берётся из ячейки, а не из отдельного справочника: у портрета
        # и ростового кадра лицо разной крупности, и референс им нужен разный
        # — замерено, полосы косинуса не пересекаются (dataset_axes.json →
        # _measured_refs). body_in_frame в ячейке уже есть, второй источник
        # правды заводить не за чем.
        print("идентичность: ЭДИТ РЕФЕРЕНСА (источник пикселей — не текст)")
    else:
        # БАННЕР ВЕТВИЛСЯ ТОЛЬКО ПО --ref И ПОТОМУ ВРАЛ. С обученной
        # персонажной лорой он печатал «идентичность: отбором набора» над
        # сорока промптами, каждый из которых начинался её триггером, — то
        # есть сообщал о режиме, из которого проект уже вышел. Отбор при этом
        # никуда не делся, он просто перестал быть единственным механизмом.
        _ch = character_lora(char.get("id"))
        if _ch:
            print("идентичность: ЛОРА ПЕРСОНАЖА {} (сила {}, триггер «{}») "
                  "+ отбор набора".format(_ch["name"],
                                          _ch.get("strength", 1.0),
                                          _ch.get("trigger", "")))
        else:
            print("идентичность: отбором набора (select_set.py после батча)")
    default_size = shots.get("size") or manifest()["output"]["profile_size"]
    # Сиды случайные, а не 101..104: жёсткий дефолт означал, что «второй проход
    # отбора» из раскадровки воспроизводит ровно те же четыре картинки.
    # Фактические сиды пишутся в реестр, так что любой кадр воспроизводим.
    n_seeds = int(shots.get("seeds_per_cell", 4))
    seeds = seeds or [random.randint(1, 2**31 - 1) for _ in range(n_seeds)]

    # Каждая раскадровка живёт в своей папке со своим реестром: смешать Part 1
    # и Part 2 в одном frames.json значит потерять возможность собрать
    # контакт-шит и вердикт по одной части.
    sub = "frames" if shotlist == "shotlist.json" else \
        "frames_" + os.path.splitext(shotlist)[0].replace("shotlist_", "")
    # --dry обещан как «ничего не отправляя» — значит и каталогов не создаёт.
    out_root = (os.path.join(work_root(), project, sub)
                if dry else work_dir(project, sub))
    ledger_path = os.path.join(out_root, "frames.json")
    ledger = []
    if os.path.exists(ledger_path):
        with open(ledger_path, encoding="utf-8") as fh:
            ledger = json.load(fh)
        # Записи об исчезнувших файлах выбрасываются. Кадры удаляют руками
        # (переснять ячейку, вычистить брак), и реестр, который помнит их
        # вечно, врёт ровно в ту сторону, которая опаснее: ворота и отбор
        # рапортуют о наборе, половины которого на диске нет.
        alive = [e for e in ledger if os.path.exists(e["file"])]
        if len(alive) != len(ledger):
            print(f"из реестра выброшено записей об удалённых кадрах: "
                  f"{len(ledger) - len(alive)}")
            ledger = alive

    cells = [c for c in shots["cells"]
             if not cell_ids or c["id"] in cell_ids]
    if not cells:
        # Не return: опечатка в id ячейки не должна быть неотличима от
        # выполненного батча — оба давали exit 0.
        raise SystemExit(f"ни одна ячейка не подошла под фильтр {cell_ids}; "
                         f"есть: {[c['id'] for c in shots['cells']]}")

    print(f"проект {project} · ячеек {len(cells)} · сидов {len(seeds)} · "
          f"кадров к генерации {len(cells) * len(seeds)} · "
          f"{default_size[0]}x{default_size[1]}")

    if not dry and not cc.preflight():
        raise SystemExit("воркер не отвечает — батч не начат")

    # Референсы заливаются ОДИН раз на батч, сколько бы ячеек их ни просило.
    uploaded = {}
    if refs and not dry:
        for path in {p for c in cells for p in _cell_refs(refs, c) if p}:
            uploaded[path] = cc.upload(path)
            print(f"референс на воркере: {uploaded[path]}  "
                  f"({os.path.basename(path)})")

    for cell in cells:
        prompt = build_cell(char, cell)
        cell_dir = os.path.join(out_root, cell["id"])
        # Кадр в полный рост не выпрашивается словами: модель на 4:5 тянет к
        # портрету что ни пиши. Форма кадра — единственный надёжный рычаг,
        # поэтому ячейка может назначить свою.
        size = cell.get("size") or default_size
        for seed in seeds:
            name = f"{cell['id']}_s{seed}"
            print(f"\n[{name}] {cell['label']} — {cell.get('function','')}")
            if dry:
                print(f"  промпт ({len(prompt)} симв.): {prompt[:180]}…")
                continue
            scene, subject = _cell_refs(refs, cell)
            graph = build_graph(prompt, seed, size, f"persona-forge/{name}",
                                cell.get("scene_class", "indoor"),
                                edit_ref=((uploaded[scene],
                                           uploaded[subject] if subject else None)
                                          if scene else None),
                                char_id=char.get("id"))
            files = cc.run_graph(graph, cell_dir)
            if not files:
                raise RuntimeError(f"{name}: сервер не вернул ни одного кадра")
            for f in files:
                print("  →", f)
                ledger = [e for e in ledger if e.get("file") != f]
                ledger.append({
                    "file": f, "cell": cell["id"], "label": cell["label"],
                    "seed": seed, "prompt": prompt,
                    "tattoo_visible": bool(cell.get("tattoo_visible")),
                    "scene_class": cell.get("scene_class", "indoor"),
                    "caption": cell.get("caption", ""),
                    "nudity_level": cell.get("nudity_level", "clothed"),
                    "mirror_selfie": bool(cell.get("mirror_selfie")),
                    "size": size,
                    "source": "edit" if scene else "t2i",
                    "ref": scene, "ref_subject": subject,
                })
            # Реестр пишется после КАЖДОГО кадра, а не одним куском в конце:
            # падение на пятнадцатом кадре из двадцати теряло записи обо всех
            # уже скачанных, а кадр без записи в реестре по правилу этого файла
            # считается мусором — то есть терялся и сам GPU-час.
            write_json(ledger_path, ledger)

    if not dry:
        write_json(ledger_path, ledger)
        print(f"\nреестр: {ledger_path} ({len(ledger)} кадров)")
    return ledger


def casting(project_dir, n=16, shotlist="shotlist.json"):
    """Пул кандидатов: одно и то же описание человека, разный свет и сид.

    ЗАЧЕМ ЭТО НУЖНО СЕЙЧАС, когда переноса лица больше нет. Пул — это
    ОТРИЦАТЕЛЬНЫЙ КЛАСС для калибровки идентичности: заведомо разные люди,
    сгенерированные по одному и тому же описанию, то есть самый тяжёлый
    возможный отрицательный класс. Без него identity_calibration.py не с чем
    сравнивать сданный набор, и весь вывод «косинус не различает» повисает
    без доказательства. Стадия была удалена вместе с веткой свопа по ошибке:
    у свопа она забирала якорь, но её настоящая ценность — вот эта.
    """
    char, shots = load_project(project_dir, shotlist)
    project = project_name(project_dir, shots, char)
    size = shots.get("size") or manifest()["output"]["profile_size"]
    out = work_dir(project, "casting")
    prompts = build_casting(char, len(CASTING_AXES))

    if not cc.preflight():
        raise SystemExit("воркер не отвечает — кастинг не начат")
    print(f"кастинг {project}: {n} кандидатов, {len(prompts)} осей света")
    made = []
    for i in range(n):
        seed = random.randint(1, 2**31 - 1)
        name = f"cast_{i:02d}_s{seed}"
        graph = build_graph(prompts[i % len(prompts)], seed, size,
                            f"persona-forge/{name}", "indoor",
                            char_id=char.get("id"))
        for f in cc.run_graph(graph, out):
            print(f"  [{i + 1:2d}/{n}] ось {i % len(prompts) + 1} → "
                  f"{os.path.basename(f)}")
            made.append(f)
    print(f"\n{len(made)} кандидатов в {out}\n"
          f"Это отрицательный класс для scripts/identity_calibration.py.")
    return made


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__); raise SystemExit(1)

    def opt(k, d=None):
        # Ключ последним аргументом или ключ, за которым стоит другой ключ, —
        # обычная опечатка. Голый IndexError показывает трейсбек вместо имени
        # ключа, а int('--dry') падает ещё непонятнее. gates.py и export_docs.py
        # это уже стерегут, generate.py — единственный, кто тратит GPU, — нет.
        if k not in args:
            return d
        i = args.index(k) + 1
        if i >= len(args) or args[i].startswith("--"):
            raise SystemExit(f"у ключа {k} нет значения")
        return args[i]

    seeds = opt("--seeds")
    seeds = [int(s) for s in seeds.split(",")] if seeds else None
    # Свободные аргументы = id ячеек. Значения ключей исключаются по позиции, а
    # не по совпадению со значением --seeds: старая проверка не знала про
    # --shotlist, и 'shotlist_story.json' уезжал в фильтр ячеек, отчего батч
    # падал с «ни одна ячейка не подошла».
    # БУЛЕВЫ КЛЮЧИ ЗНАЧЕНИЯ НЕ БЕРУТ, и это был тихий баг с ценой в GPU-час.
    # Прежняя строка помечала «занятым» аргумент ПОСЛЕ ЛЮБОГО ключа, включая
    # флаги без значения. `--dry S1 S3` поэтому терял S1: он числился
    # значением `--dry`. Батч молча снимал не то, что просили, а сухой прогон
    # показывал не тот план, который потом исполнится.
    FLAGS = {"--dry", "--force", "--partial", "--auto", "--list", "--verify"}
    taken = {i + 1 for i, a in enumerate(args)
             if a.startswith("--") and a not in FLAGS}
    cells = [a for i, a in enumerate(args)
             if i > 0 and i not in taken and not a.startswith("-")]
    if "--casting" in args:
        n = int(opt("--casting", 16))
        if "--dry" in args:
            # --dry обещан для КАЖДОГО дорогого пути, а кастинг — 16 рендеров.
            char, shots = load_project(args[0], opt("--shotlist", "shotlist.json"))
            print(f"кастинг {project_name(args[0], shots, char)}: {n} кандидатов, "
                  f"{len(CASTING_AXES)} осей света — сухой прогон, ничего не отправлено")
            return
        casting(args[0], n, opt("--shotlist", "shotlist.json"))
        return
    from edit_dataset import parse_refs
    generate(args[0], cells or None, seeds, dry="--dry" in args,
             shotlist=opt("--shotlist", "shotlist.json"),
             refs=parse_refs(opt("--ref")))


if __name__ == "__main__":
    main()
