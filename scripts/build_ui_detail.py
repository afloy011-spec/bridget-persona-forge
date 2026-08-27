#!/usr/bin/env python3
"""Холст точечной правки: выделил область → поправил → получил полный кадр.

  py -3 build_ui_detail.py [--out <файл>] [--verify] [--deploy]
                           [--image <имя на воркере>]

НА ВЫХОДЕ — ФАЙЛ ДЛЯ ComfyUI: templates/comfy/PERSONA_DETAIL_EDIT.json.
Открывается перетаскиванием в окно ComfyUI, а с ключом `--deploy` кладётся
сразу на сервер и появляется в его списке Workflows под именем проекта.

ЧТО ЭТОТ ХОЛСТ ДЕЛАЕТ, ЧЕГО НЕ ДЕЛАЕТ БАТЧ. Батч снимает кадр целиком по
описанию. Здесь кадр уже есть, и правится его КУСОК: надпись на запястье,
родинка, украшение, шов на ткани. Всё остальное в кадре обязано остаться
побитово тем же — этим правка отличается от пересъёмки.

ПУТЬ ПО ХОЛСТУ, слева направо:

  1 · Кадр и область   загрузить кадр, ВЫДЕЛИТЬ ОБЛАСТЬ (правой кнопкой по
                       LoadImage → Open in MaskEditor), посмотреть рамку и
                       отчёт: какое увеличение вышло и не мягкий ли участок
  2 · Модели           та же база и тот же стек лор, что у батча
  3 · Что нарисовать    промпт; отрицательного поля нет намеренно (cfg = 1.0)
  4 · Референс         НЕОБЯЗАТЕЛЕН, по умолчанию выключен
  5 · Проход по окну   сэмплер + ПРЕВЬЮ ПРОМЕЖУТОЧНОГО результата
  6 · Готовый кадр     вклейка обратно и полный кадр

РЕФЕРЕНС ВЫКЛЮЧАЕТСЯ ОДНИМ ПЕРЕКЛЮЧАТЕЛЕМ, И ЭТО НЕ САМО СОБОЙ. У
«Switch conditioning [Crystools]» обе ветки объявлены ЛЕНИВЫМИ (lazy) —
проверено по схеме сервера. Значит при boolean = false ветка референса не
считается ВООБЩЕ: ни зрячий энкодер не запускается, ни картинка не читается.
Обычный переключатель считал бы обе и требовал референс всегда.
Патч внимания (Krea2EditModelPatch) переключателем не накрыть — у него на
входе и выходе MODEL, — поэтому он стоит в ОБХОДЕ (mode 4): модель проходит
сквозь него нетронутой, а включается он вторым движением, Ctrl+B.

ПОВТОРНОЕ РЕДАКТИРОВАНИЕ. Выход шестой группы — обычная картинка, и её можно
подать во второй круг двумя способами. Внутри одного прогона: протянуть её в
новый «вырезать окно» и править другую область. Между прогонами: включить
SaveImage (он стоит выключенным, машина общая) — кадр ляжет в output, и
LoadImage возьмёт его следующим запуском.

ЧЕГО ЭТОТ ХОЛСТ НЕ ЗАМЕНЯЕТ. Для инпейнта по маске в полном смысле — с
подготовкой маски под inpaint-модель, батчем масок и outpainting — на воркере
стоят Impact Pack и Inpaint Crop and Stitch, и они умеют больше. Здесь другое:
проход по окну на низком denoise, где маска задаёт МЕСТО, а не дыру.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _util import ROOT, cli_opt, manifest, setup_console  # noqa: E402
from build_ui import _in, _n, _out, verify_widgets  # noqa: E402
from ui_layout import check as layout_check  # noqa: E402
from ui_layout import columns  # noqa: E402
import build_ui as BU  # noqa: E402

# Размеры узлов, которых нет в таблице батчевого сборщика.
BU.SIZE.update({
    "LoadImage": [400, 380],
    "AfloyDetailCut": [400, 260],
    "AfloyDetailPaste": [400, 130],
    "AfloyDetailPreviewBox": [400, 82],
    "PreviewAny": [400, 190],
    "Krea2EditGroundedEncode": [480, 300],
    "Krea2EditModelPatch": [400, 130],
    "Switch conditioning [Crystools]": [400, 106],
    "VAEEncode": [400, 60],
})

# Заголовок группы «референс» говорит, что он выключен: человек, открывший
# холст, не обязан выяснять это, тыкая в узлы.
G_IN = "#3f5159"
G_MODEL = "#443b57"
G_PROMPT = "#39544a"
G_REF = "#5a4a35"
G_RUN = "#4a3f5c"
G_OUT = "#37503f"

DENOISE = 0.42          # замерено в detail_tattoo: читается, рука не тронута
PAD = 1.6               # окно шире выделения; это ручка МАСШТАБА
CANVAS = 1024


def _placeholder_image():
    """Имя картинки-заглушки для LoadImage, взятое У СЕРВЕРА.

    Своё придумывать нельзя: значение комбо-виджета обязано быть из списка
    сервера, иначе ComfyUI откроет узел с пустым полем, а сверка виджетов
    справедливо покраснеет. Загруженное нами через /upload лежит в подпапке,
    которую LoadImage не перечисляет вовсе — проверено, в списке 42 имени и
    ни одного нашего. Поэтому берётся первое доступное: холст всё равно
    открывают, чтобы подставить СВОЙ кадр, а заглушка нужна лишь затем, чтобы
    файл был валиден с первого открытия.
    """
    try:
        import json
        import urllib.request
        from comfy_client import _default_host
        d = json.load(urllib.request.urlopen(
            _default_host() + "/object_info/LoadImage", timeout=30))
        opts = d["LoadImage"]["input"]["required"]["image"][0]
        if opts:
            return opts[0]
    except Exception:
        pass
    return "example.png"


def build(image_name=None):
    image_name = image_name or _placeholder_image()
    man = manifest()
    b = man["models"]["base"]
    from generate import lora_stack
    loras = lora_stack(man)

    nxt = [1]
    L = {}

    def link(src, sslot, dst, dslot, ty):
        i = nxt[0]
        nxt[0] += 1
        L[i] = [i, src, sslot, dst, dslot, ty]
        return i

    # ---------------------------------------------------- 1 · кадр и область
    n_img = _n(1, "LoadImage", "1 · кадр — правой кнопкой → Open in MaskEditor",
               [0, 0], [image_name],
               outputs=[_out("IMAGE", "IMAGE", []), _out("MASK", "MASK", [])])
    n_cut = _n(2, "AfloyDetailCut", "выделение → окно → холст", [0, 0],
               [CANVAS, PAD, True, 0.5, 0.5, 0.42, 40.0],
               inputs=[_in("image", "IMAGE", None), _in("mask", "MASK", None)],
               outputs=[_out("crop", "IMAGE", []), _out("ctx", "DETAIL_CTX", []),
                        _out("report", "STRING", [])])
    n_box = _n(3, "AfloyDetailPreviewBox", "где встало окно", [0, 0], [4],
               inputs=[_in("ctx", "DETAIL_CTX", None)],
               outputs=[_out("preview", "IMAGE", [])])
    n_boxp = _n(4, "PreviewImage", "рамка на кадре", [0, 0], [],
                inputs=[_in("images", "IMAGE", None)])
    n_rep = _n(5, "PreviewAny", "отчёт: увеличение и резкость участка", [0, 0],
               [], inputs=[_in("source", "*", None)])

    # ---------------------------------------------------------- 2 · модели
    n_unet = _n(10, "UNETLoader", "база", [0, 0], [b["unet"], "default"],
                outputs=[_out("MODEL", "MODEL", [])])
    n_clip = _n(11, "CLIPLoader", "энкодер", [0, 0],
                [b["clip"], b["clip_type"], "default"],
                outputs=[_out("CLIP", "CLIP", [])])
    n_vae = _n(12, "VAELoader", "VAE", [0, 0], [b["vae"]],
               outputs=[_out("VAE", "VAE", [])])
    # КЛИП ИДЁТ СКВОЗЬ КОРОБКУ ЛОР, А НЕ МИМО НЕЁ. Узел требует и model, и
    # clip — первая редакция подала только модель, и живой прогон отбраковал
    # весь граф с «Required input is missing: clip». Заодно это правильно по
    # существу: лора правит и текстовый энкодер тоже, и промпт, закодированный
    # мимо коробки, отвечал бы не той модели, что рисует.
    n_lora = _n(13, "LoraBox", "лоры — тот же стек, что у батча", [0, 0],
                [_lorabox(loras)],
                inputs=[_in("model", "MODEL", None), _in("clip", "CLIP", None)],
                outputs=[_out("MODEL", "MODEL", []), _out("CLIP", "CLIP", []),
                         _out("prompt", "STRING", [])])

    # ------------------------------------------------------ 3 · что рисовать
    n_pos = _n(20, "CLIPTextEncode", "что нарисовать в окне", [0, 0],
               ["опиши ТОЛЬКО то, что должно быть в окне — не весь кадр"],
               inputs=[_in("clip", "CLIP", None)],
               outputs=[_out("CONDITIONING", "CONDITIONING", [])])

    # ------------------------------------------------- 4 · референс (выкл.)
    n_ref = _n(30, "LoadImage", "референс — нужен только если включён", [0, 0],
               [image_name],
               outputs=[_out("IMAGE", "IMAGE", []), _out("MASK", "MASK", [])])
    n_ge = _n(31, "Krea2EditGroundedEncode", "зрячий энкодер: видит референс",
              [0, 0], ["опиши, что взять с референса", 768, ""],
              inputs=[_in("clip", "CLIP", None), _in("image", "IMAGE", None)],
              outputs=[_out("CONDITIONING", "CONDITIONING", [])])
    n_sw = _n(32, "Switch conditioning [Crystools]",
              "РЕФЕРЕНС: true — с ним, false — без", [0, 0], [False],
              inputs=[_in("on_true", "CONDITIONING", None),
                      _in("on_false", "CONDITIONING", None)],
              outputs=[_out("CONDITIONING", "CONDITIONING", [])])
    # ОБХОД, а не удаление: узел на месте, подписан, модель идёт сквозь него
    # нетронутой. Включается Ctrl+B вместе с переключателем выше.
    n_patch = _n(33, "Krea2EditModelPatch",
                 "патч внимания к референсу — В ОБХОДЕ (Ctrl+B чтобы включить)",
                 [0, 0], [4.0, 1.0, "fit"],
                 inputs=[_in("model", "MODEL", None),
                         _in("source_latent", "LATENT", None),
                         _in("vae", "VAE", None),
                         _in("source_image", "IMAGE", None)],
                 outputs=[_out("MODEL", "MODEL", [])], mode=4)

    # ------------------------------------------------------ 5 · проход
    n_neg = _n(40, "ConditioningZeroOut",
               "отрицательного поля нет: при cfg = 1.0 оно мертво", [0, 0], [],
               inputs=[_in("conditioning", "CONDITIONING", None)],
               outputs=[_out("CONDITIONING", "CONDITIONING", [])])
    n_enc = _n(41, "VAEEncode", "окно → латент", [0, 0], [],
               inputs=[_in("pixels", "IMAGE", None), _in("vae", "VAE", None)],
               outputs=[_out("LATENT", "LATENT", [])])
    n_ks = _n(42, "KSampler", "проход ПО ОКНУ, не по кадру", [0, 0],
              [606, "fixed", b["steps"], b["cfg"], b["sampler"],
               b["scheduler"], DENOISE],
              inputs=[_in("model", "MODEL", None),
                      _in("positive", "CONDITIONING", None),
                      _in("negative", "CONDITIONING", None),
                      _in("latent_image", "LATENT", None)],
              outputs=[_out("LATENT", "LATENT", [])])
    n_dec = _n(43, "VAEDecode", "латент → пиксели окна", [0, 0], [],
               inputs=[_in("samples", "LATENT", None), _in("vae", "VAE", None)],
               outputs=[_out("IMAGE", "IMAGE", [])])
    n_mid = _n(44, "PreviewImage", "ПРОМЕЖУТОЧНЫЙ результат: окно после прохода",
               [0, 0], [], inputs=[_in("images", "IMAGE", None)])

    # ------------------------------------------------------ 6 · готовый кадр
    n_paste = _n(50, "AfloyDetailPaste", "вклейка: blend гасит силу правки",
                 [0, 0], [0.14, 1.0],
                 inputs=[_in("ctx", "DETAIL_CTX", None),
                         _in("edited", "IMAGE", None)],
                 outputs=[_out("image", "IMAGE", [])])
    n_fin = _n(51, "PreviewImage", "ПОЛНЫЙ кадр с правленой областью", [0, 0],
               [], inputs=[_in("images", "IMAGE", None)])
    # Выключен: машина общая, и холст, пишущий в output по умолчанию, за
    # неделю набивает туда сотни PNG. Включается для второго круга правки.
    n_save = _n(52, "SaveImage",
                "ВЫКЛЮЧЕН. Включить для второго круга: кадр ляжет в output и "
                "его возьмёт LoadImage", [0, 0], ["detail/edit"],
                inputs=[_in("images", "IMAGE", None)], mode=2)

    # ------------------------------------------------------------- связи
    def wire(a, aslot, bnode, bslot, ty):
        i = link(a["id"], aslot, bnode["id"], bslot, ty)
        a["outputs"][aslot]["links"].append(i)
        bnode["inputs"][bslot]["link"] = i

    wire(n_img, 0, n_cut, 0, "IMAGE")
    wire(n_img, 1, n_cut, 1, "MASK")
    wire(n_cut, 1, n_box, 0, "DETAIL_CTX")
    wire(n_box, 0, n_boxp, 0, "IMAGE")
    wire(n_cut, 2, n_rep, 0, "STRING")

    wire(n_unet, 0, n_lora, 0, "MODEL")
    wire(n_clip, 0, n_lora, 1, "CLIP")
    wire(n_lora, 1, n_pos, 0, "CLIP")
    wire(n_lora, 1, n_ge, 0, "CLIP")
    wire(n_ref, 0, n_ge, 1, "IMAGE")

    wire(n_ge, 0, n_sw, 0, "CONDITIONING")
    wire(n_pos, 0, n_sw, 1, "CONDITIONING")
    wire(n_sw, 0, n_neg, 0, "CONDITIONING")

    wire(n_lora, 0, n_patch, 0, "MODEL")
    wire(n_cut, 0, n_enc, 0, "IMAGE")
    wire(n_vae, 0, n_enc, 1, "VAE")
    wire(n_enc, 0, n_patch, 1, "LATENT")
    wire(n_vae, 0, n_patch, 2, "VAE")
    wire(n_ref, 0, n_patch, 3, "IMAGE")

    wire(n_patch, 0, n_ks, 0, "MODEL")
    wire(n_sw, 0, n_ks, 1, "CONDITIONING")
    wire(n_neg, 0, n_ks, 2, "CONDITIONING")
    wire(n_enc, 0, n_ks, 3, "LATENT")
    wire(n_ks, 0, n_dec, 0, "LATENT")
    wire(n_vae, 0, n_dec, 1, "VAE")
    wire(n_dec, 0, n_mid, 0, "IMAGE")

    wire(n_cut, 1, n_paste, 0, "DETAIL_CTX")
    wire(n_dec, 0, n_paste, 1, "IMAGE")
    wire(n_paste, 0, n_fin, 0, "IMAGE")
    wire(n_paste, 0, n_save, 0, "IMAGE")

    # ---------------------------------------------------------- раскладка
    spec = [
        [("1 · кадр и область", [n_img, n_cut, n_box, n_boxp, n_rep], G_IN)],
        [("2 · модели", [n_unet, n_clip, n_vae, n_lora], G_MODEL),
         ("3 · что нарисовать в окне", [n_pos], G_PROMPT)],
        [("4 · референс — ВЫКЛЮЧЕН, включается переключателем",
          [n_ref, n_ge, n_sw, n_patch], G_REF)],
        [("5 · проход по окну", [n_neg, n_enc, n_ks, n_dec, n_mid], G_RUN)],
        [("6 · готовый кадр", [n_paste, n_fin, n_save], G_OUT)],
    ]
    groups = columns(spec)
    nodes = [n for col in spec for _t, ns, _c in col for n in ns]
    for i, n in enumerate(nodes):
        n["order"] = i

    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "persona-forge/ui/detail")),
        "revision": 0,
        "last_node_id": max(n["id"] for n in nodes),
        "last_link_id": nxt[0] - 1,
        "nodes": nodes,
        "links": [L[k] for k in sorted(L)],
        "groups": groups,
        "config": {}, "extra": {"ds": {"scale": 0.5, "offset": [0, 0]}},
        "version": 0.4,
    }


def _lorabox(loras):
    """Значение виджета LoraBox — тем же форматом, что у батчевого холста."""
    import json
    return json.dumps({"loras": [
        {"name": x["name"], "strength": float(x.get("strength", 1.0)),
         "enabled": not x.get("bypass"), "trigger": ""} for x in loras]},
        ensure_ascii=False)


def main():
    setup_console()
    args = sys.argv[1:]
    out = cli_opt(args, "--out", os.path.join(
        ROOT, "templates", "comfy", "PERSONA_DETAIL_EDIT.json"))
    wf = build(cli_opt(args, "--image"))
    print("нод %d, связей %d, групп %d"
          % (len(wf["nodes"]), len(wf["links"]), len(wf["groups"])))
    bad = layout_check(wf)
    print("раскладка:", "налипаний нет" if not bad else "ПРЕТЕНЗИИ:")
    for b in bad:
        print("   ✗", b)
    if "--verify" in args:
        problems, seen, skipped = verify_widgets(wf)
        for t, names in sorted(seen.items()):
            print("  %-34s %s" % (t, names))
        for s in skipped:
            print("  пропущено:", s)
        print("сверка виджетов:", "чисто" if not problems else "ПРЕТЕНЗИИ:")
        for p in problems:
            print("   ✗", p)
        if problems:
            raise SystemExit(1)
    import json as _json
    with open(out, "w", encoding="utf-8", newline="") as fh:
        _json.dump(wf, fh, ensure_ascii=False, indent=1)
    print("записан:", out)
    # ФАЙЛ НА ДИСКЕ РЕПОЗИТОРИЯ — ЕЩЁ НЕ ХОЛСТ, КОТОРЫЙ МОЖНО ОТКРЫТЬ. Пока
    # шага не было, собранный воркфлоу лежал в templates/comfy и не появлялся
    # в списке Workflows на сервере; «открой холст» упиралось в пустоту.
    if "--deploy" in args:
        from comfy_client import save_workflow
        print("на сервере:", save_workflow(out))


if __name__ == "__main__":
    main()
