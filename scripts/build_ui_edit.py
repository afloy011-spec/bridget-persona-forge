#!/usr/bin/env python3
"""Воркфлоу для КАНВАСА: персонаж подгружается картинкой, а не лорой.

  py -3 build_ui_edit.py [--out <файл.json>] [--cell P1]
                         [--second body|detail|face]

ЗАЧЕМ ОТДЕЛЬНО ОТ build_ui.py. Тот собирает t2i-стек, где личность держит
персонажная лора. Здесь второй маршрут проекта: личность приезжает С
РЕФЕРЕНСА, лоры отвечают только за вид. Он нужен, когда персонаж новый и лоры
под него ещё нет, — а по брифу тестового задания эталонной фотографии нет
вовсе, есть только описание, поэтому маршрут «референс + отбор» штатный.

ДВА ВХОДА ИЗОБРАЖЕНИЯ, И ЭТО НЕ ДУБЛЬ. `Krea2EditGroundedEncode` и
`Krea2EditModelPatch` берут по две картинки: первая — лицо (портретная панель
турнэраунда), вторая — фигура (ростовая панель). У портрета и ростового кадра
разная крупность лица, и подпирать поясной портрет ростовой панелью значит
отдать половину внимания одежде. Правило: где `body_in_frame` — вторым входом
рост, иначе оба входа портрет.

ЧТО КРУТИТЬ РУКАМИ, РАДИ ЧЕГО ВОРКФЛОУ И СОБИРАЕТСЯ:
  ref_boost (Identity)  — сила референса. Замерено: 8 перебор, 4 рабочее.
  strength у лор (Look) — вид кадра. Полный риг сходства НЕ роняет.
  grounding_px          — на сколько пикселей смотрит энкодер референса.
  seed                  — кадров надо много: личность добирается ОТБОРОМ.

Раскладка по домашним правилам: колонками, зазор GAP, центрирование внутри
колонки, заголовки групп по-английски.
"""
import json
import os
import uuid
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import setup_console, manifest, ROOT, cli_opt   # noqa: E402
from build_ui import _n, _in, _out                        # noqa: E402
from ui_layout import columns, check, node_height, GROUP_GAP  # noqa: E402

SIZE = {
    "LoadImage": [400, 380],
    "ImageScaleToMaxDimension": [400, 106],
    "VAEEncode": [400, 60],
    "Krea2EditGroundedEncode": [480, 420],
    "Krea2EditModelPatch": [400, 180],
    "CLIPTextEncode": [480, 260],
    "UNETLoader": [400, 106],
    "CLIPLoader": [400, 130],
    "VAELoader": [400, 82],
    "LoraLoaderModelOnly": [400, 130],
    "EmptyLatentImage": [400, 130],
    "KSampler": [400, 290],
    "VAEDecode": [400, 60],
    "PreviewImage": [400, 340],
    "SaveImage": [400, 340],
}

SYSTEM = ("Attend to the person's facial identity: the shape of the eyes, brows "
          "and nose, the proportions of the lips, the line of the jaw and "
          "cheekbones, the exact hair colour and its distribution. Preserve "
          "these; the scene, pose, framing and light are free to change.")

NEGATIVE = ("text, letters, words, watermark, logo, caption, signature, frame, "
            "border, collage, multiple panels, contact sheet, turnaround, "
            "grid of images")

NOTE = """ВОРКФЛОУ: персонаж с референса

КУДА КЛАСТЬ КАРТИНКИ
  Face reference  — портретная панель турнэраунда (крупное лицо).
  Body reference  — ростовая панель. Для поясных кадров поставьте сюда ту же
                    портретную: рост отбирает внимание у лица.

ЧТО КРУТИТЬ, В ПОРЯДКЕ ВЛИЯНИЯ
  1. seed. Личность здесь берётся ОТБОРОМ: снимите 6-8 кадров на сцену и
     выберите. Один сид ничего не доказывает — замерено, худшая пара набора
     из одиночных сидов вышла 0.319, это разные женщины.
  2. ref_boost в Identity. 4 — рабочее. 8 — перебор: кадр начинает
     повторять позу и фон референса.
  3. Силы лор в Look. Весь риг сходства не роняет — проверено.
     disposable camera: 0 днём, 0.55 ночью, 0.8 со вспышкой. Днём она
     красит кадр в зелень.
  4. grounding_px. 768 по умолчанию.

ЧЕГО НЕ ДЕЛАТЬ
  Не писать в промпт запреты. cfg = 1.0, негативный обусловливатель мёртв,
  и «no watch» приносит watch. Всё нежелательное формулируйте
  положительно: не «без часов», а «запястье голое, кожа открыта».
"""


# Сколько текстовых полей у ноды: они занимают блок, а не строку.
MULTILINE = {"Krea2EditGroundedEncode": 2, "CLIPTextEncode": 1}
# Ширины остаются таблицей: они про читаемость, а не про содержимое.
WIDTH = {"Krea2EditGroundedEncode": 480, "CLIPTextEncode": 480,
         "LoadImage": 400, "PreviewImage": 400}
# Что нода рисует сверх портов: LoadImage — превью картинки, PreviewImage —
# саму картинку. Их высота от объявления не считается, задаётся отдельно.
EXTRA = {"LoadImage": 250, "PreviewImage": 280, "SaveImage": 280}


def _object_info():
    """Объявления нод с сервера: только по ним видно, сколько портов
    ComfyUI НАРИСУЕТ. Без сервера собирать нельзя — высоты будут гаданием,
    а гадание уже дало ноду, вылезшую из рамки."""
    import urllib.request
    host = manifest().get("host_default") or os.environ.get("COMFY_HOST")
    if not host:
        local = os.path.join(ROOT, "assets.local.json")
        if os.path.exists(local):
            host = json.load(open(local, encoding="utf-8")).get("host")
    if not host:
        raise SystemExit("адрес ComfyUI не задан: COMFY_HOST или assets.local.json")
    with urllib.request.urlopen(host + "/object_info", timeout=180) as r:
        raw = json.load(r)
    return {k: v.get("input", {}) for k, v in raw.items()}


OBJ = {}


def _node(nid, ntype, title, widgets=None, inputs=None, outputs=None):
    n = _n(nid, ntype, title, [0, 0], widgets, inputs, outputs)
    spec = dict(OBJ.get(ntype, {}))
    spec["_outputs"] = len(outputs or [])
    h = node_height(spec, len(widgets or []), MULTILINE.get(ntype, 0))
    n["size"] = [WIDTH.get(ntype, 400), h + EXTRA.get(ntype, 0)]
    return n


def cell_prompt(project_dir, cell_id):
    """Промпт клетки — ТОТ ЖЕ, что уйдёт в батче.

    Холст ценен ровно тем, что показывает, во что превратится батч, до того
    как за батч заплачено. Заглушка «опишите кадр» этого не показывает: снятое
    на холсте и снятое конвейером расходились уже на промпте, и сравнивать их
    было нельзя. Поэтому строка берётся у prompts.build_cell, а не пишется
    здесь второй раз.
    """
    from prompts import build_cell, load_project
    char, shots = load_project(project_dir)
    for c in shots["cells"]:
        if c["id"] == cell_id:
            return build_cell(char, c)
    have = ", ".join(c["id"] for c in shots["cells"])
    raise SystemExit(f"клетки {cell_id} нет в {project_dir}; есть: {have}")


def build(cell_id="P1", second="body", project_dir=None):
    global OBJ
    if not OBJ:
        OBJ = _object_info()
    man = manifest()
    base = man["models"]["base"]
    # СТЕК БЕРЁТСЯ У generate, А НЕ ЧИТАЕТСЯ ИЗ МАНИФЕСТА ЗАНОВО. Здесь стояло
    # `man["models"]["realism_loras"]`, и это был второй читатель того же
    # файла: холст собирал полный риг без персонажной лоры, а батч —
    # персонажную плюс короткий список. Человек подбирал кадр на одних весах,
    # конвейер снимал на других, и подбор ничего не предсказывал. Теперь
    # источник один, и разойтись они могут только вместе.
    from generate import lora_stack
    char_id = None
    if project_dir:
        from _util import read_json
        char_id = read_json(os.path.join(project_dir,
                                         "character.json")).get("id")
    rig = lora_stack(man, char_id)

    L = {}                      # счётчик связей
    def link(n):                # noqa: E306
        L[n] = L.get(n, 0) + 1
        return n

    nodes, links = [], []
    lid = [0]

    def wire(src_node, src_slot, dst_node, dst_slot, type_):
        """Связь пишется В ТРИ МЕСТА, и забыть можно ровно два из них.

        В UI-формате общий массив `links` — это только реестр. Рисует холст по
        полям самих нод: `inputs[i].link` у приёмника и `outputs[j].links` у
        источника. Граф, где заполнен только массив, открывается с нодами и
        БЕЗ ЕДИНОЙ СВЯЗИ — что и произошло с первой редакцией этого сборщика.
        Ошибка молчаливая: JSON валиден, ноды на местах, проверка раскладки
        зелёная, и увидеть её можно только открыв холст.
        """
        lid[0] += 1
        links.append([lid[0], src_node["id"], src_slot,
                      dst_node["id"], dst_slot, type_])
        dst_node["inputs"][dst_slot]["link"] = lid[0]
        out = src_node["outputs"][src_slot]
        out.setdefault("links", [])
        if out["links"] is None:
            out["links"] = []
        out["links"].append(lid[0])
        out["slot_index"] = src_slot
        return lid[0]

    # ---------------------------------------------------- CHARACTER
    load_face = _node(1, "LoadImage", "Face reference — портрет",
                      ["ПОЛОЖИТЕ СЮДА ПОРТРЕТ.png", "image"],
                      outputs=[_out("IMAGE", "IMAGE", []), _out("MASK", "MASK", [])])
    fit_face = _node(2, "ImageScaleToMaxDimension", "Fit face",
                     ["lanczos", 1024],
                     inputs=[_in("image", "IMAGE", None)],
                     outputs=[_out("IMAGE", "IMAGE", [])])
    load_body = _node(3, "LoadImage", "Body reference — рост",
                      ["ПОЛОЖИТЕ СЮДА РОСТ.png", "image"],
                      outputs=[_out("IMAGE", "IMAGE", []), _out("MASK", "MASK", [])])
    fit_body = _node(4, "ImageScaleToMaxDimension", "Fit body",
                     ["lanczos", 1024],
                     inputs=[_in("image", "IMAGE", None)],
                     outputs=[_out("IMAGE", "IMAGE", [])])

    # ТРЕТИЙ ВХОД — ДЕТАЛЬ, И ОН ЗАНИМАЕТ МЕСТО ВТОРОГО, А НЕ ДОБАВЛЯЕТСЯ.
    # `Krea2EditGroundedEncode` и `Krea2EditModelPatch` берут РОВНО ДВЕ
    # картинки (image / image_b, source_image / source_image_b) — третьего
    # слота у них нет вовсе, проверено по /object_info. Поэтому деталь не
    # прибавляется к лицу и фигуре, а встаёт вместо фигуры: ключ --second
    # решает, кто поедет во второй слот.
    #
    # ДЛЯ ТАТУ ЭТО НЕ ТОТ ПУТЬ, и это замер, а не мнение. Тату у персонажа —
    # НАДПИСЬ, а диффузия выдаёт в каждом кадре другую кашу из букв: имя либо
    # совпадает буква в букву, либо это чужая тату. Поэтому чернило вынуто из
    # фотографии и ВКЛЕИВАЕТСЯ (scripts/composite_tattoo.py), а не рисуется.
    # Второй слот под деталь полезен для другого: узор ткани, конкретное
    # украшение, оправа очков, рисунок ковра — всё, что читается формой и
    # цветом, а не буквами.
    load_detail = _node(8, "LoadImage",
                        "Detail reference — во 2-й слот вместо роста",
                        ["ПОЛОЖИТЕ СЮДА ДЕТАЛЬ.png", "image"],
                        outputs=[_out("IMAGE", "IMAGE", []),
                                 _out("MASK", "MASK", [])])
    fit_detail = _node(15, "ImageScaleToMaxDimension", "Fit detail",
                       ["lanczos", 1024],
                       inputs=[_in("image", "IMAGE", None)],
                       outputs=[_out("IMAGE", "IMAGE", [])])
    character = [load_face, fit_face, load_body, fit_body,
                 load_detail, fit_detail]
    # Кто поедет во второй слот обоих узлов эдита.
    fit_second = {"body": fit_body, "detail": fit_detail,
                  "face": fit_face}[second]

    # ---------------------------------------------------- MODELS
    unet = _node(5, "UNETLoader", "Base model", [base["unet"], "default"],
                 outputs=[_out("MODEL", "MODEL", [])])
    clip = _node(6, "CLIPLoader", "Text encoder",
                 [base["clip"], base.get("clip_type", "krea2"), "default"],
                 outputs=[_out("CLIP", "CLIP", [])])
    vae = _node(7, "VAELoader", "VAE", [base["vae"]],
                outputs=[_out("VAE", "VAE", [])])
    models = [unet, clip, vae]

    # ---------------------------------------------------- ЭДИТ-ЛОРА (механизм)
    # ОНА НЕ ПРО ВИД И СТОИТ ПЕРВОЙ. `krea2_identity_edit` — сам механизм
    # переноса личности с референса: без неё патч внимания к картинке не
    # работает вовсе, и группа IDENTITY становится пустой ручкой. Поэтому она
    # вынесена из группы LOOK в отдельную и подписана как механизм — чтобы её
    # не выключили заодно с реализмом, подбирая вид.
    edit_lora = _node(9, "LoraLoaderModelOnly",
                      "Edit mechanism — НЕ ВЫКЛЮЧАТЬ",
                      ["krea2_identity_edit_v1_2.safetensors", 1.0],
                      inputs=[_in("model", "MODEL", None)],
                      outputs=[_out("MODEL", "MODEL", [])])

    # ---------------------------------------------------- LOOK (риг)
    # НУМЕРАЦИЯ С 100, А НЕ С 10, И ЭТО НЕ ВКУСОВЩИНА. Цепочка растёт вместе
    # со стеком: как только в стек добавилась персонажная лора, шестая нода
    # получила номер 15 — уже занятый узлом подгонки детали. Ссылка на деталь
    # молча переехала на лору, и граф остался «собранным» на вид. Сотня выше
    # любого зашитого номера, а сторож парности проверяет это отдельно.
    look, nid = [], 100
    for l in rig:
        n = _node(nid, "LoraLoaderModelOnly", l.get("role") or l["name"],
                  [l["name"], float(l["strength"])],
                  inputs=[_in("model", "MODEL", None)],
                  outputs=[_out("MODEL", "MODEL", [])])
        look.append(n)
        nid += 1
    # ---------------------------------------------------- PROMPT
    # ПОРЯДОК ВИДЖЕТОВ БЕРЁТСЯ ИЗ /object_info, А НЕ ИЗ ЗДРАВОГО СМЫСЛА.
    # Сервер объявляет prompt в required, а grounding_px и system_prompt — в
    # optional, поэтому в UI-формате они идут именно так: prompt, grounding_px,
    # system_prompt. Список, собранный «как удобнее», кладёт число в поле
    # текста, и граф выглядит рабочим до самого запуска.
    text = (cell_prompt(project_dir, cell_id) if project_dir
            else "ОПИШИТЕ КАДР ОДНИМ ДЛИННЫМ ПРЕДЛОЖЕНИЕМ")
    enc = _node(20, "Krea2EditGroundedEncode", "Prompt — что в кадре",
                [text, 768, SYSTEM],
                inputs=[_in("clip", "CLIP", None), _in("image", "IMAGE", None),
                        _in("image_b", "IMAGE", None)],
                outputs=[_out("CONDITIONING", "CONDITIONING", [])])
    neg = _node(21, "CLIPTextEncode", "Negative — мёртв при cfg 1.0",
                [NEGATIVE],
                inputs=[_in("clip", "CLIP", None)],
                outputs=[_out("CONDITIONING", "CONDITIONING", [])])
    prompt_g = [enc, neg]

    # ---------------------------------------------------- IDENTITY
    venc = _node(30, "VAEEncode", "Reference to latent", [],
                 inputs=[_in("pixels", "IMAGE", None), _in("vae", "VAE", None)],
                 outputs=[_out("LATENT", "LATENT", [])])
    patch = _node(31, "Krea2EditModelPatch", "Identity — ref_boost",
                  [4.0, 1.0, "fit"],
                  inputs=[_in("model", "MODEL", None),
                          _in("source_latent", "LATENT", None),
                          _in("vae", "VAE", None),
                          _in("source_image", "IMAGE", None),
                          _in("source_image_b", "IMAGE", None)],
                  outputs=[_out("MODEL", "MODEL", [])])
    identity = [venc, patch]

    # ---------------------------------------------------- RENDER
    latent = _node(40, "EmptyLatentImage", "Frame size", [1152, 1440, 1],
                   outputs=[_out("LATENT", "LATENT", [])])
    ks = _node(41, "KSampler", "Render",
               [0, "randomize", int(base["steps"]), float(base["cfg"]),
                base["sampler"], base["scheduler"], 1.0],
               inputs=[_in("model", "MODEL", None), _in("positive", "CONDITIONING", None),
                       _in("negative", "CONDITIONING", None),
                       _in("latent_image", "LATENT", None)],
               outputs=[_out("LATENT", "LATENT", [])])
    dec = _node(42, "VAEDecode", "Decode", [],
                inputs=[_in("samples", "LATENT", None), _in("vae", "VAE", None)],
                outputs=[_out("IMAGE", "IMAGE", [])])
    prev_n = _node(43, "PreviewImage", "Preview", [],
                   inputs=[_in("images", "IMAGE", None)])
    render = [latent, ks, dec, prev_n]

    # ---------------------------------------------------- раскладка
    # Колонки задаются группами, а не координатами: зазор между рамками
    # держит ui_layout.columns, и он одинаков по обеим осям.
    groups = columns([
        [("1. CHARACTER — reference images", character, "#3f789e")],
        [("2. MODELS", models, "#8a6d3b"),
         ("3. EDIT MECHANISM", [edit_lora], "#7a3a3a"),
         ("4. LOOK — realism rig", look, "#3f6f4f")],
        [("5. PROMPT", prompt_g, "#6b4f7a"),
         ("6. IDENTITY — ref_boost", identity, "#a1553a")],
        [("7. RENDER", render, "#444444")],
    ])

    nodes = character + models + [edit_lora] + look + prompt_g + identity + render

    note = _n(99, "Note", "ЧИТАТЬ ПЕРЕД ЗАПУСКОМ", [40, 40], [NOTE])
    note["size"] = [520, 660]
    note["pos"] = [40, max(g["bounding"][1] + g["bounding"][3]
                           for g in groups) + GROUP_GAP]
    nodes.append(note)

    # ---------------------------------------------------- связи
    wire(unet, 0, edit_lora, 0, "MODEL")
    wire(load_face, 0, fit_face, 0, "IMAGE")
    wire(load_body, 0, fit_body, 0, "IMAGE")
    wire(load_detail, 0, fit_detail, 0, "IMAGE")
    wire(clip, 0, enc, 0, "CLIP")
    wire(fit_face, 0, enc, 1, "IMAGE")
    wire(fit_second, 0, enc, 2, "IMAGE")
    wire(clip, 0, neg, 0, "CLIP")
    wire(fit_face, 0, venc, 0, "IMAGE")
    wire(vae, 0, venc, 1, "VAE")
    chain = edit_lora
    for n in look:
        wire(chain, 0, n, 0, "MODEL")
        chain = n
    wire(chain, 0, patch, 0, "MODEL")
    wire(venc, 0, patch, 1, "LATENT")
    wire(vae, 0, patch, 2, "VAE")
    wire(fit_face, 0, patch, 3, "IMAGE")
    wire(fit_second, 0, patch, 4, "IMAGE")
    wire(patch, 0, ks, 0, "MODEL")
    wire(enc, 0, ks, 1, "CONDITIONING")
    wire(neg, 0, ks, 2, "CONDITIONING")
    wire(latent, 0, ks, 3, "LATENT")
    wire(ks, 0, dec, 0, "LATENT")
    wire(vae, 0, dec, 1, "VAE")
    wire(dec, 0, prev_n, 0, "IMAGE")

    # ORDER У КАЖДОЙ НОДЫ СВОЙ, И ЭТО НЕ КОСМЕТИКА. Litegraph восстанавливает
    # граф, обходя ноды в порядке `order`; одинаковый порядок у всех ломает
    # восстановление МОЛЧА — холст открывается с нодами и без единой связи,
    # притом что реестр `links` полон, поля нод заполнены и JSON валиден.
    # Строка уже терялась дважды: первый раз её просто не перенесли из
    # build_ui.py, второй — вырезали вместе с блоком групп при перестройке
    # раскладки. Она стоит ПОСЛЕДНЕЙ и перед самым возвратом именно поэтому.
    for i, n in enumerate(nodes):
        n["order"] = i

    return {
        # Детерминированный id, как у соседнего сборщика: со случайным uuid
        # каждая пересборка делала бы отслеживаемый файл «изменённым».
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL,
                             "persona-forge/ui-edit/%s" % cell_id)),
        "revision": 0,
        "last_node_id": max(n["id"] for n in nodes),
        "last_link_id": lid[0],
        "nodes": nodes, "links": links, "groups": groups,
        "config": {}, "extra": {"ds": {"scale": 0.55, "offset": [0, 0]}},
        "version": 0.4,
    }


def main():
    setup_console()
    args = sys.argv[1:]
    out = cli_opt(args, "--out", os.path.join(
        ROOT, "templates", "comfy", "PERSONA_CHARACTER_FROM_REFERENCE.json"))
    wf = build(cli_opt(args, "--cell", "P1"),
               cli_opt(args, "--second", "body"),
               cli_opt(args, "--project", None))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(wf, fh, ensure_ascii=False, indent=1)
    problems = check(wf)
    print("нод %d, связей %d, групп %d" %
          (len(wf["nodes"]), len(wf["links"]), len(wf["groups"])))
    # ХОЛСТ НЕ ЗАПИСЫВАЕТСЯ, ПОКА НА НЁМ ЕСТЬ НАЛИПАНИЯ. Раньше сборка
    # печатала «пересечений нет» по своей же мерке и клала файл на диск при
    # любом исходе; вычитывалось это глазами в браузере и по два раза.
    if problems:
        print("НАЛИПАНИЯ, файл не записан:")
        for p_ in problems:
            print("  ✗", p_)
        raise SystemExit(1)
    print("раскладка: налипаний нет")
    print("записан:", out)


if __name__ == "__main__":
    main()
