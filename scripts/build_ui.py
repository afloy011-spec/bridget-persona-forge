#!/usr/bin/env python3
"""Собрать UI-воркфлоу ComfyUI для ручной проверки конвейера.

  py -3 build_ui.py [--cell P1] [--out <файл>] [--verify] [--chain]

На выходе — файл, который открывается в ComfyUI (Load или перетаскиванием) и
показывает конвейер ручками: модели, всю цепочку лор со своими силами, промпт,
сэмплер, просмотр и увеличение. Нужен, чтобы проверить руками то, что батч
делает вслепую: подхватились ли модели, что реально дают лоры, как выглядит
кадр до всякой автоматики.

ПЕРВОЙ В ЦЕПОЧКЕ ЛОР СТОИТ ПЕРСОНАЖНАЯ — она отвечает на вопрос «кто в кадре»,
остальные на вопрос «как снято». С её появлением референс для съёмки перестал
быть нужен: этот граф — обычный t2i, и он же теперь боевой путь.

ДОВОДКА ПОКАЗАНА ЧАСТИЧНО, И ЭТО НАЗВАНО В ЗАМЕТКЕ НА ХОЛСТЕ. Увеличение
(ESRGAN x4 плюс уменьшение вдвое) выражается нодами и стоит в графе. Проход
фактуры в масштабе лица — нет: он режет кроп по детектору лиц, а детектора
среди нод ComfyUI нет, и делает его scripts/detail_face.py.

--verify сверяет порядок виджетов с сервером. Это не педантизм: у KSampler в
UI между seed и steps стоит служебный виджет control_after_generate, которого
нет в API-формате. Собрать значения по API-порядку — значит положить steps в
поле control_after_generate и получить молча сломанный воркфлоу.

ПОЛИТИКА СЕЙВОВ. PreviewImage — основной выход, SaveImage лежит рядом
выключенным (mode=2). Машина общая, и воркфлоу, который пишет в output/ по
умолчанию, за неделю набивает туда сотни тестовых PNG.
"""
import os, sys, json, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import setup_console, manifest, ROOT, cli_opt
from prompts import load_project, build_cell

# Цветовой код групп — принятый стандарт оформления.
C_MODELS, C_CONTROL, C_STAGE1 = "#b58b2a", "#2a8b4f", "#3f789e"
C_STAGE2, C_OUTPUT, C_NOTE = "#b06634", "#8AA", "#8A8"

# Числа раскладки — из общего модуля: копия в каждом сборщике разъезжается
# при первой же правке. См. scripts/ui_layout.py.
from ui_layout import (GROUP_GAP, check as layout_check,
                       columns as layout_columns)  # noqa: E402
COL_GAP = GROUP_GAP

# Высоты с запасом. Заниженная высота — главная причина визуального налипания:
# реальная нода выше расчётной на бейдж пака и подписи виджетов.
SIZE = {
    "UNETLoader": [400, 106],
    "CLIPLoader": [400, 130],
    "VAELoader": [400, 82],
    "LoraLoaderModelOnly": [400, 130],
    "CLIPTextEncode": [480, 320],
    "ConditioningZeroOut": [480, 60],
    "EmptyLatentImage": [400, 130],
    "KSampler": [400, 290],
    "VAEDecode": [400, 60],
    "PreviewImage": [400, 300],
    "SaveImage": [400, 320],
    "UpscaleModelLoader": [400, 82],
    "ImageUpscaleWithModel": [400, 60],
    "ImageScaleBy": [400, 106],
    # Высота LoraBox зависит от числа строк в её панели: шапка, ряд кнопок и
    # по строке на лору. С запасом, иначе следующая нода налипнет.
    "LoraBox": [460, 300],
}

NOTES = [
    ("Что проверяем", """1. Подхватились ли модели — если нода красная или
пустой выпадающий список, модели на сервере нет.

2. ЧТО ДАЁТ ПЕРСОНАЖНАЯ ЛОРА. Она стоит ПЕРВОЙ в цепочке и отвечает на
вопрос «кто в кадре»; реализм-лоры после неё — на вопрос «как снято».
Обнули её силу и прогони тот же сид: лицо уплывёт к типажу. Замер на чистом
t2i без референса — косинус 0.642 к эталону.

3. Кожа и возраст. Смотреть на шею, кисти и зону у глаз — именно там
модель сползает к 27 годам, лицо крупным планом обманывает.

4. Кадр целиком до всякой автоматики: композиция, свет, руки."""),

    ("Референс больше не нужен", """Личность лежит В ВЕСАХ лоры, а не в
картинке. Раньше кадр переснимался с референса эдит-графом, потом лицо
вклеивалось свапом — и своп уничтожал 78% фактуры лица (замер на 14 парах:
дисперсия лапласиана 180 → 40, на КАЖДОМ кадре от -53% до -87%).

Свап убран, эдит для съёмки не нужен: этот граф — обычный t2i, и он же
теперь боевой путь. Триггер лоры стоит в начале промпта."""),

    ("Почему нет негативного промпта", """Модель работает на cfg = 1.0, а при
cfg = 1.0 негативный обусловливатель не влияет на результат ВООБЩЕ.
ConditioningZeroOut стоит только потому, что граф требует вход negative.

Писать «no plastic skin» бессмысленно. Всё нежелательное выражается
положительным требованием прямо в промпте: не «без пластиковой кожи», а
«visible skin pores». Это уже сделано в character.json → realism_clause."""),

    ("Сейвы выключены намеренно", """Основной выход — PreviewImage: кадр падает
в temp/ и чистится при рестарте ComfyUI.

SaveImage рядом выключен (mode = Never). Машина общая: воркфлоу, который
пишет в output/ по умолчанию, за неделю набивает туда сотни тестовых PNG,
а удалить их по API нечем.

Нужен файл — включи SaveImage руками и выключи обратно."""),

    ("Afloy Lora Box", """Весь стек лор — одна нода: список в её панели, у
каждой лоры своя сила и выключатель, триггер-слова подмешиваются в промпт
сама. Персонажная первой строкой.

ЭТО БОЕВОЙ ПУТЬ, А НЕ УДОБСТВО ДЛЯ ГЛАЗ, и решение по замеру. Цепочка
LoraLoaderModelOnly кладёт лоры только на модель, Lora Box — ещё и на CLIP.
Сравнение на восьми ячейках при одних сидах:
    фактура лица   232 -> 274  (лучше в 7 кадрах из 8)
    волосы         0.599 -> 0.542 (лучше в 8 из 8)
    сходство       0.611 -> 0.591 (знак неустойчив: лучше в 3 из 8)
Выигрыш ровно по двум оставшимся долгам проекта, и он систематичен.

Плата названа вслух: нода кастомная (ComfyUI-LoraBox), на чистом ComfyUI её
нет, и генерация перестала быть переносимой. Ключ --chain собирает прежний
вариант с цепочкой — для сверки и для машины без этой ноды."""),

    ("Доводка после съёмки", """Справа стоит ВТОРАЯ половина конвейера, и она
включена не всегда — это ручная проверка, а не батч.

УВЕЛИЧЕНИЕ: ESRGAN x4, затем ImageScaleBy 0.5 — итого ровно x2. Апскейлер
даёт разрешение и структуру, но придумать не умеет ничего.

ФАКТУРА: её кладёт отдельный проход В МАСШТАБЕ ЛИЦА (scripts/detail_face.py),
и в этом графе его НЕТ намеренно — он режет кроп вокруг лица по детектору,
гонит его на холсте 1024 и вклеивает обратно с растушёвкой, а детектора лиц
в нодах ComfyUI нет. Почему в масштабе лица: диффузия рисует детали в
масштабе ХОЛСТА, а лицу при съёмке достаётся 72-161 px межзрачкового, и поры
ему рисовать негде. Замер на кропе: 52.7 -> 71.3 против 5.3 -> 11.5 у прохода
по всему кадру."""),
]


def _n(nid, ntype, title, pos, widgets=None, inputs=None, outputs=None, mode=0):
    return {
        "id": nid, "type": ntype, "title": title,
        "pos": list(pos), "size": list(SIZE.get(ntype, [400, 110])),
        "flags": {}, "order": 0, "mode": mode,
        "inputs": inputs or [], "outputs": outputs or [],
        "properties": {"Node name for S&R": ntype},
        "widgets_values": widgets if widgets is not None else [],
    }


def _in(name, type_, link):
    return {"name": name, "type": type_, "link": link}


def _out(name, type_, links):
    return {"name": name, "type": type_, "links": links, "slot_index": 0}








def build(cell_id="P1", show_character=True, lorabox=True):
    man = manifest()
    base = man["models"]["base"]
    # СТЕК БЕРЁТСЯ ИЗ ТОЙ ЖЕ ФУНКЦИИ, ЧТО И В БОЕВОМ ГРАФЕ. Прежняя редакция
    # резала манифест до трёх лор — в шаблоне их было пять, — и видимый
    # воркфлоу показывал НЕ ТО, что уходит на сервер. UI-двойник, который
    # врёт, хуже отсутствующего: его открывают именно чтобы посмотреть, что
    # происходит на самом деле.
    from generate import lora_stack
    loras = lora_stack(man)
    # ПУСТОЙ СЛОТ ПЕРСОНАЖА ПОКАЗЫВАЕТСЯ, А НЕ ПРЯЧЕТСЯ. Пока лора не обучена,
    # ключ манифеста пуст и в цепочке её нет — но человек, открывший граф
    # именно чтобы понять устройство, должен видеть, КУДА она встанет.
    # Режим 4 — обход: узел на месте, подписан, модель проходит сквозь него
    # нетронутой, и граф остаётся запускаемым. Тот же приём, что у выключенного
    # SaveImage рядом.
    if show_character and not (man["models"].get("character_lora") or {}).get("name"):
        ch = man["models"].get("character_lora") or {}
        loras = [{"name": ch.get("name") or "<обучить и вписать в assets.json>",
                  "strength": float(ch.get("strength", 1.0)),
                  "role": "персонаж", "bypass": True}] + loras
    size = man["output"]["profile_size"]

    project = os.path.join(ROOT, "projects", "bridget")
    prompt = "ВСТАВЬ СЮДА ПРОМПТ ИЗ prompts.py"
    try:
        char, shots = load_project(project)
        # Не подставлять первую ячейку молча: опечатка в --cell означала, что
        # человек руками проверяет совсем не тот кадр, который собирался.
        cell = next((c for c in shots["cells"] if c["id"] == cell_id), None)
        if cell is None:
            raise SystemExit(f"нет ячейки {cell_id}; есть: "
                             f"{[c['id'] for c in shots['cells']]}")
        prompt = build_cell(char, cell)
    except SystemExit:
        raise
    except Exception as e:
        print(f"! карточка проекта не прочитана ({e}) — промпт оставлен пустым",
              file=sys.stderr)

    # ---- ноды. Номера повторяют API-шаблон, чтобы граф читался рядом с ним.
    L = {}                                   # link_id → кортеж связи
    nxt = [1]

    def link(src, sslot, dst, dslot, type_):
        i = nxt[0]; nxt[0] += 1
        L[i] = [i, src, sslot, dst, dslot, type_]
        return i

    # Цепочка model→model строится ПОД ДЛИНУ СТЕКА: номера узлов идут с 20,
    # как в API-шаблоне, а последний цепляется за сэмплер, сколько бы их ни
    # оказалось. Захардкоженные четыре связи ломались на любой правке
    # манифеста и были причиной того, что двойник отстал от шаблона.
    if lorabox:
        # AFLOY LORA BOX: одна нода вместо цепочки. Она берёт и model, и clip,
        # отдаёт их же плюс промпт с подмешанными триггер-словами.
        BOX = 20
        l_model1 = link(1, 0, BOX, 0, "MODEL")
        l_clip_in = link(2, 0, BOX, 1, "CLIP")
        l_model_out = link(BOX, 0, 7, 0, "MODEL")
        l_clip = link(BOX, 1, 4, 0, "CLIP")
        lora_ids, chain = [], []
    else:
        lora_ids = [20 + i for i in range(len(loras))]
        chain = [link(1, 0, lora_ids[0], 0, "MODEL")] if lora_ids else []
        for a, b in zip(lora_ids, lora_ids[1:]):
            chain.append(link(a, 0, b, 0, "MODEL"))
        l_model_out = link(lora_ids[-1] if lora_ids else 1, 0, 7, 0, "MODEL")
        chain.append(l_model_out)
        l_model1 = chain[0] if lora_ids else l_model_out
        l_clip = link(2, 0, 4, 0, "CLIP")
    l_cond = link(4, 0, 7, 1, "CONDITIONING")
    l_zero_in = link(4, 0, 5, 0, "CONDITIONING")
    l_zero = link(5, 0, 7, 2, "CONDITIONING")
    l_lat = link(6, 0, 7, 3, "LATENT")
    l_out = link(7, 0, 8, 0, "LATENT")
    l_vae = link(3, 0, 8, 1, "VAE")
    l_img_p = link(8, 0, 9, 0, "IMAGE")
    l_img_s = link(8, 0, 10, 0, "IMAGE")

    models = [
        _n(1, "UNETLoader", "Base model", (0, 0),
           [base["unet"], "default"], [], [_out("MODEL", "MODEL", [l_model1])]),
        _n(2, "CLIPLoader", "Text encoder", (0, 0),
           [base["clip"], base["clip_type"], "default"], [],
           [_out("CLIP", "CLIP", [l_clip])]),
        _n(3, "VAELoader", "VAE", (0, 0),
           [base["vae"]], [], [_out("VAE", "VAE", [l_vae])]),
    ]
    if lorabox:
        # Список лор лежит в JSON-панели ноды. Схема — её собственная:
        # {"v":1,"mute":bool,"pos":"beginning","delim":", ","rows":[…]},
        # строка — {"on":bool,"name":str,"sm":float,"sc":float}. Порядок строк
        # тот же, что в цепочке: персонажная первой.
        rows = [{"on": not l.get("bypass"), "name": l["name"],
                 "sm": float(l["strength"]), "sc": float(l["strength"])}
                for l in loras]
        data = json.dumps({"v": 1, "mute": False, "pos": "beginning",
                           "delim": ", ", "rows": rows}, ensure_ascii=False)
        lora_nodes = [_n(20, "LoraBox", "Afloy Lora Box — character first",
                         # ОДИН виджет, а не два: `prompt` у ноды объявлен
                         # forceInput, то есть это сокет, и места в
                         # widgets_values он не занимает. Лишний пустой
                         # элемент сдвигал бы data в несуществующий слот.
                         (0, 0), [data],
                         [_in("model", "MODEL", l_model1),
                          _in("clip", "CLIP", l_clip_in)],
                         [_out("MODEL", "MODEL", [l_model_out]),
                          _out("CLIP", "CLIP", [l_clip]),
                          _out("prompt", "STRING", [])])]
    else:
        lora_nodes = []
        for i, l in enumerate(loras):
            role = l.get("role", "")
            # Персонажная лора подписана иначе и стоит первой: она про «кто
            # в кадре», остальные про «как это снято». В заголовке это видно
            # сразу, чтобы человек за графом не искал её глазами по имени.
            title = (("CHARACTER — BYPASS, not trained yet" if l.get("bypass")
                      else "CHARACTER — the face itself") if role == "персонаж"
                     else f"Realism {i} — {role}" if i else f"Lora 1 — {role}")
            lora_nodes.append(_n(
                lora_ids[i], "LoraLoaderModelOnly", title, (0, 0),
                [l["name"], l["strength"]],
                [_in("model", "MODEL", chain[i])],
                [_out("MODEL", "MODEL", [chain[i + 1]])],
                mode=4 if l.get("bypass") else 0))

    prompt_nodes = [
        _n(4, "CLIPTextEncode", "PROMPT — from prompts.py", (0, 0),
           [prompt], [_in("clip", "CLIP", l_clip)],
           [_out("CONDITIONING", "CONDITIONING", [l_cond, l_zero_in])]),
        _n(5, "ConditioningZeroOut", "Negative is dead at cfg 1.0", (0, 0),
           [], [_in("conditioning", "CONDITIONING", l_zero_in)],
           [_out("CONDITIONING", "CONDITIONING", [l_zero])]),
    ]
    sample_nodes = [
        _n(6, "EmptyLatentImage", f"Frame {size[0]}x{size[1]}", (0, 0),
           [size[0], size[1], 1], [], [_out("LATENT", "LATENT", [l_lat])]),
        _n(7, "KSampler", "Sampler", (0, 0),
           [101, "fixed", base["steps"], base["cfg"],
            base["sampler"], base["scheduler"], 1.0],
           [_in("model", "MODEL", l_model_out),
            _in("positive", "CONDITIONING", l_cond),
            _in("negative", "CONDITIONING", l_zero),
            _in("latent_image", "LATENT", l_lat)],
           [_out("LATENT", "LATENT", [l_out])]),
    ]
    # ДОВОДКА В ГРАФЕ, А НЕ ТОЛЬКО В СКРИПТАХ. Апскейл теперь всегда-включённый
    # шаг конвейера, и UI-двойник, показывающий только съёмку, снова стал бы
    # рассказывать про вчерашний конвейер. Вклейка кропа лица сюда НЕ вынесена
    # намеренно: она режет кроп по детектору лиц, а детектора среди нод нет —
    # см. заметку «Доводка после съёмки».
    up_model = man["models"]["upscale"]["general"]
    # Связи объявляются ТЕМИ ЖЕ концами, какими потом подключаются. Первая
    # редакция объявила их со сдвигом на узел (11→12, 12→13, 13→14), а
    # подключила иначе — граф собрался, номера сошлись, а кадр из сэмплера в
    # апскейлер не приходил вовсе.
    l_dec_up = link(8, 0, 12, 1, "IMAGE")       # готовый кадр → апскейлер
    l_upm = link(11, 0, 12, 0, "UPSCALE_MODEL")  # модель → апскейлер
    l_up_sc = link(12, 0, 13, 0, "IMAGE")        # апскейлер → уменьшение вдвое
    l_sc_prev = link(13, 0, 14, 0, "IMAGE")      # → просмотр
    out_nodes = [
        _n(8, "VAEDecode", "", (0, 0), [],
           [_in("samples", "LATENT", l_out), _in("vae", "VAE", l_vae)],
           [_out("IMAGE", "IMAGE", [l_img_p, l_img_s, l_dec_up])]),
        _n(9, "PreviewImage", "Preview — as shot", (0, 0), [],
           [_in("images", "IMAGE", l_img_p)]),
        _n(10, "SaveImage", "Save — OFF on purpose", (0, 0),
           ["persona-forge/manual"], [_in("images", "IMAGE", l_img_s)],
           [], mode=2),
    ]
    finish_nodes = [
        _n(11, "UpscaleModelLoader", "", (0, 0), [up_model], [],
           [_out("UPSCALE_MODEL", "UPSCALE_MODEL", [l_upm])]),
        _n(12, "ImageUpscaleWithModel", "ESRGAN x4", (0, 0), [],
           [_in("upscale_model", "UPSCALE_MODEL", l_upm),
            _in("image", "IMAGE", l_dec_up)],
           [_out("IMAGE", "IMAGE", [l_up_sc])]),
        _n(13, "ImageScaleBy", "0.5 — net x2", (0, 0),
           ["lanczos", 0.5], [_in("image", "IMAGE", l_up_sc)],
           [_out("IMAGE", "IMAGE", [l_sc_prev])]),
        _n(14, "PreviewImage", "Preview — after upscale", (0, 0), [],
           [_in("images", "IMAGE", l_sc_prev)]),
    ]

    # ---- раскладка: заметки одним рядом сверху, группы ниже
    note_nodes, x = [], 80
    for i, (title, text) in enumerate(NOTES):
        n = {"id": 90 + i, "type": "Note", "title": title,
             "pos": [x, 40], "size": [460, 330], "flags": {}, "order": 0,
             "mode": 0, "properties": {"text": ""}, "widgets_values": [text],
             "color": "#432", "bgcolor": "#653"}
        note_nodes.append(n); x += 460 + COL_GAP

    y0 = 40 + 330 + 120          # группы начинаются ниже полосы заметок
    cols = [("MODELS", models, C_MODELS),
               ("LORAS — CHARACTER FIRST", lora_nodes, C_CONTROL),
               ("PROMPT", prompt_nodes, C_STAGE1),
               ("SAMPLE", sample_nodes, C_STAGE2),
               ("OUTPUT", out_nodes, C_OUTPUT),
               ("FINISHING", finish_nodes, C_STAGE2)]
    # РАСКЛАДКА ОБЩИМ ДВИЖКОМ, а не своей арифметикой. Ручной вариант ставил
    # колонки на фиксированный шаг COL_W_MAX и считал рамку по габаритам
    # содержимого — при просвете 60 группы разной ширины начали налезать друг
    # на друга, а узкие ноды оказывались ближе к кромке заявленного. Один
    # движок на оба сборщика: сначала коробка группы, потом расстановка
    # коробок с постоянным зазором, и только потом ноды внутрь.
    groups = layout_columns([[c] for c in cols], origin=(80, y0))
    for i, g in enumerate(groups, 1):
        g["id"] = i

    # ГРУППА БЕЗ СВОИХ УЗЛОВ — ЭТО ПУСТАЯ РАМКА, И ЗАМЕТИТЬ ЕЁ ТРУДНО.
    # Список колонок и этот список — два места, где перечислены одни и те же
    # ноды. Забыв дописать сюда, я получила граф с группой «ДОВОДКА», внутри
    # которой не было ничего: сборка отработала без единой жалобы, проверка
    # раскладки тоже — рамка-то валидная. Поймалось только пересчётом типов
    # нод в готовом файле.
    all_nodes = note_nodes + models + lora_nodes + prompt_nodes \
        + sample_nodes + out_nodes + finish_nodes
    for i, n in enumerate(all_nodes):
        n["order"] = i

    return {
        # Детерминированный id: со случайным uuid каждый прогон --verify делал
        # отслеживаемый файл «изменённым», и сверку «пересобранное ==
        # закоммиченное» нельзя было ни глазом сделать, ни поставить в CI.
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL,
                             f"persona-forge/ui/{cell_id}")), "revision": 0,
        "last_node_id": max(n["id"] for n in all_nodes),
        "last_link_id": nxt[0] - 1,
        "nodes": all_nodes,
        "links": [L[k] for k in sorted(L)],
        "groups": groups,
        "config": {}, "extra": {"ds": {"scale": 0.55, "offset": [0, 0]}},
        "version": 0.4,
    }


def check_layout(wf):
    """Группы не должны пересекаться, ноды — лежать внутри своей группы."""
    problems = []
    gs = wf["groups"]
    for i in range(len(gs)):
        for j in range(i + 1, len(gs)):
            a, b = gs[i]["bounding"], gs[j]["bounding"]
            if (a[0] < b[0] + b[2] and b[0] < a[0] + a[2]
                    and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]):
                problems.append(f"группы «{gs[i]['title']}» и «{gs[j]['title']}»"
                                " пересекаются")
    gaps = []
    for g in gs:
        inside = [n for n in wf["nodes"]
                  if g["bounding"][0] <= n["pos"][0]
                  and n["pos"][0] + n["size"][0] <= g["bounding"][0] + g["bounding"][2]
                  and g["bounding"][1] <= n["pos"][1]]
        ys = sorted((n["pos"][1], n["size"][1]) for n in inside)
        for k in range(len(ys) - 1):
            gaps.append(ys[k + 1][0] - (ys[k][0] + ys[k][1]))
    return problems, (min(gaps) if gaps else None)


def verify_widgets(wf):
    """Сверить виджеты с сервером — иначе значения лягут не в те поля.

    Проверяется и ЧИСЛО слотов, и содержимое каждого: раньше сверялась только
    длина списка, поэтому перестановка sampler_name и scheduler — ровно та
    ошибка, ради которой функция написана, — проходила с вердиктом «чисто».
    """
    import urllib.parse
    import urllib.request
    from comfy_client import _default_host
    host = _default_host()      # COMFY_HOST должен работать и здесь
    bad, skipped = [], []
    seen, specs = {}, {}
    for n in wf["nodes"]:
        t = n["type"]
        if t == "Note" or t in seen:
            continue
        try:
            # ИМЯ ТИПА КОДИРУЕТСЯ ДЛЯ URL. Без этого любой узел с пробелом или
            # скобками в имени («Switch conditioning [Crystools]») ронял сверку
            # не проверкой, а исключением urllib — и выглядело это как
            # претензия к узлу, хотя ломался сам проверяльщик.
            d = json.load(urllib.request.urlopen(
                f"{host}/object_info/{urllib.parse.quote(t, safe='')}",
                timeout=60))[t]
        except Exception as e:
            bad.append(f"{t}: не прочитан с сервера ({e})"); continue
        # ОПЦИОНАЛЬНЫЕ ВИДЖЕТЫ ТОЖЕ СЧИТАЮТСЯ. Первая версия читала только
        # required и ругалась на CLIPLoader: device лежит в optional с флагом
        # advanced, в интерфейсе по умолчанию скрыт — но слот в widgets_values
        # занимает. Сверено с рабочим воркфлоу, который открывался в ComfyUI:
        # там у CLIPLoader ровно три значения.
        req = dict(d["input"].get("required", {}))
        req.update(d["input"].get("optional", {}))
        names = []
        for k, v in req.items():
            ty = v[0]
            cfg = v[1] if len(v) > 1 and isinstance(v[1], dict) else {}
            if (isinstance(ty, list) or ty in ("INT", "FLOAT", "STRING",
                                               "BOOLEAN", "COMBO")) \
                    and not cfg.get("forceInput"):
                names.append(k)
                if k == "seed":
                    names.append("control_after_generate")
        seen[t] = names
        specs[t] = req
    for n in wf["nodes"]:
        exp = seen.get(n["type"])
        if exp is None:
            continue
        # УЗЕЛ В ОБХОДЕ (mode 4) НЕ ИСПОЛНЯЕТСЯ, и значения его виджетов —
        # заведомо заглушка. Такой узел стоит в графе, чтобы человек ВИДЕЛ,
        # куда встанет персонажная лора, когда её обучат; требовать от
        # заглушки существующего имени файла значит либо подсунуть чужую лору
        # (и запутать), либо убрать слот совсем (и не показать устройство).
        # Проверка не выключена, а разделена: обойдённые узлы перечисляются
        # отдельной строкой, чтобы «пропущено» нельзя было прочитать как
        # «проверено».
        if n.get("mode") == 4:
            skipped.append(f"{n['type']} (нода {n['id']}, "
                           f"{n.get('title', '')}) — в обходе, не исполняется")
            continue
        vals = n["widgets_values"]
        if len(vals) != len(exp):
            bad.append(f"{n['type']} (нода {n['id']}): виджетов "
                       f"{len(vals)}, сервер ждёт {len(exp)} → {exp}")
            continue
        sp = specs.get(n["type"], {})
        for i, nm in enumerate(exp):
            if nm == "control_after_generate":
                continue
            ty = sp.get(nm, [None])[0]
            v = vals[i]
            if isinstance(ty, list):        # COMBO: значение обязано быть в списке
                if v not in ty:
                    bad.append(f"{n['type']} (нода {n['id']}): слот {i} ({nm}) "
                               f"= {v!r}, сервер ждёт одно из {ty[:6]}")
            elif ty in ("INT", "FLOAT") and isinstance(v, (bool, str)):
                bad.append(f"{n['type']} (нода {n['id']}): слот {i} ({nm}) "
                           f"= {v!r}, ожидалось число ({ty})")
            elif ty == "STRING" and not isinstance(v, str):
                bad.append(f"{n['type']} (нода {n['id']}): слот {i} ({nm}) "
                           f"= {v!r}, ожидалась строка")
    return bad, seen, skipped


def main():
    setup_console()
    args = sys.argv[1:]

    def opt(k, d=None):
        return cli_opt(args, k, d)

    cell = opt("--cell", "P1")
    # ИМЯ ФАЙЛА ПО УМОЛЧАНИЮ ЗАВИСИТ ОТ РЕЖИМА. Оно вычислялось независимо от
    # `--chain`, поэтому `build_ui.py --chain` без `--out` писал chain-граф
    # ПОВЕРХ файла с Lora Box — а assets.json советует читателю ровно
    # `--chain`, про `--out` не упоминая. Ущерб не случился только потому, что
    # закоммиченный CHAIN совпадал с тем, что даёт сборка сегодня.
    chain = "--chain" in args
    out = opt("--out", os.path.join(
        ROOT, "templates", "comfy",
        "PERSONA_MANUAL_CHECK_CHAIN.json" if chain else "PERSONA_MANUAL_CHECK.json"))
    wf = build(cell, lorabox=not chain)

    problems, min_gap = check_layout(wf)
    print(f"нод {len(wf['nodes'])}, связей {len(wf['links'])}, "
          f"групп {len(wf['groups'])}")
    print("пересечения групп:", "нет" if not problems else problems)
    print("минимальный вертикальный зазор:", min_gap, "px (норма ≥ 70)")

    # ЕДИНАЯ ПРОВЕРКА НАЛИПАНИЙ, ТА ЖЕ, ЧТО У ВТОРОГО СБОРЩИКА. Своя
    # check_layout сверяет только пересечения рамок и вертикальный зазор — она
    # не видит, что нода въехала в полосу заголовка или подошла к кромке
    # вплотную. Правило одно на оба воркфлоу, значит и проверка одна.
    sticks = layout_check(wf)
    print("налипания:", "нет" if not sticks else "")
    for st in sticks:
        print("  ✗", st)

    bad = []
    if "--verify" in args:
        bad, seen, skipped = verify_widgets(wf)
        for line in skipped:
            print(f"  пропущено (обход): {line}")
        for t, names in seen.items():
            print(f"  {t}: {names}")
        print("сверка виджетов:", "чисто" if not bad else f"ПРОБЛЕМ {len(bad)}")
        for b in bad:
            print("  ✗", b)

    # ПРОВАЛ СВЕРКИ НЕ ПИШЕТ ФАЙЛ И ВОЗВРАЩАЕТ НЕНОЛЬ. Раньше запись шла
    # безусловно, а main() возвращал None — то есть `--verify` печатал список
    # расхождений и тут же клал заведомо неверный граф на диск с кодом 0.
    # Проверка, которая ничего не останавливает и никому не сигналит, не
    # проверка; а битый файл на диске хуже отсутствующего.
    if bad or sticks:
        raise SystemExit(
            "граф не записан: {} расхождений с живым сервером.\n"
            "  Виджеты шаблона разошлись с тем, что нода объявляет в "
            "/object_info — собранный сейчас файл молча положил бы значения "
            "не в те поля.".format(len(bad)))

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(wf, fh, ensure_ascii=False, indent=1)
    print("записан:", out)


if __name__ == "__main__":
    main()
