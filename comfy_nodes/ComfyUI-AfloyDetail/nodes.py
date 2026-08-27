#!/usr/bin/env python3
"""Узлы ComfyUI — тонкие обёртки над detail.py.

ДВА УЗЛА, А НЕ ОДИН, И ЭТО ГЛАВНОЕ РЕШЕНИЕ ПАКЕТА. Между «вырезать» и
«вклеить» пользователь ставит СВОЮ цепочку: сэмплер, референс, апскейлер,
что угодно. Один узел «отредактируй мне область» пришлось бы кормить моделью,
промптом и сидом, то есть встроить в себя половину графа и запретить всё
остальное — ровно то, из-за чего готовые детейлеры неудобно переиспользовать.
Здесь узлы отвечают только за геометрию, и это единственное, чего в ComfyUI
нет из коробки.

РАМКА ЕДЕТ В ctx, А НЕ ЗАДАЁТСЯ ВТОРОЙ РАЗ. Если бы «вклеить» просил
координаты снова, они разошлись бы с «вырезать» на первой же правке ползунка, и
вклейка встала бы мимо — молча, потому что картинка всё равно получится.
Поэтому рамка, исходный кадр и размеры едут одним объектом: рассинхронизировать
их нечем.
"""
import torch

# Тот же приём, что в __init__.py: относительный импорт для ComfyUI,
# абсолютный — для всего остального, что читает этот файл напрямую.
try:
    from .detail import (CANVAS, FEATHER, SHARP_MIN, box_from_mask,
                         box_from_point, cut, paste, report, sharpness)
except ImportError:
    from detail import (CANVAS, FEATHER, SHARP_MIN, box_from_mask,
                        box_from_point, cut, paste, report, sharpness)


class AfloyDetailCut:
    """Выделение → окно → холст. Отдаёт кроп, рамку в ctx и отчёт строкой."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "canvas": ("INT", {"default": CANVAS, "min": 128,
                                   "max": 4096, "step": 64}),
                "pad": ("FLOAT", {"default": 1.6, "min": 1.0, "max": 8.0,
                                  "step": 0.05}),
                "square": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                # Маска — основной путь: рисуется прямо в ComfyUI, правой
                # кнопкой по LoadImage → Open in MaskEditor. Необязательная,
                # потому что у скриптов маски нет, у них есть точка.
                "mask": ("MASK",),
                "at_x": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0,
                                   "step": 0.005}),
                "at_y": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0,
                                   "step": 0.005}),
                "size": ("FLOAT", {"default": 0.42, "min": 0.02, "max": 1.0,
                                   "step": 0.01}),
                "min_sharpness": ("FLOAT", {"default": SHARP_MIN, "min": 0.0,
                                            "max": 1000.0, "step": 1.0}),
            },
        }

    RETURN_TYPES = ("IMAGE", "DETAIL_CTX", "STRING")
    RETURN_NAMES = ("crop", "ctx", "report")
    FUNCTION = "run"
    CATEGORY = "Afloy/detail"
    DESCRIPTION = ("Вырезает окно вокруг выделения и отдаёт ему собственный "
                   "холст. Размер окна (pad) — это ручка МАСШТАБА: модель "
                   "рисует деталь в масштабе того, что видит.")

    def run(self, image, canvas, pad, square, mask=None, at_x=0.5, at_y=0.5,
            size=0.42, min_sharpness=SHARP_MIN):
        img = image if image.dim() == 4 else image.unsqueeze(0)
        h, w = int(img.shape[1]), int(img.shape[2])
        box = box_from_mask(mask, w, h, pad=pad, square=square)
        source = "маска"
        if box is None:
            # Молчаливого отката быть не должно: пустая маска и НЕподключённая
            # маска — разные случаи, и первый почти всегда ошибка человека.
            source = "точка (маски нет)" if mask is None else (
                "точка (МАСКА ПУСТА — в ней нет ни одного пикселя)")
            box = box_from_point(at_x, at_y, size, w, h, square=square)
        crop = cut(img, box, canvas=canvas)
        sh = sharpness(img[0, box[1]:box[3], box[0]:box[2], :])
        text = "область задана: %s\n%s" % (
            source, report(box, w, h, canvas, sh, min_sharpness))
        print("[AfloyDetailCut] " + text.replace("\n", "\n[AfloyDetailCut] "))
        ctx = {"image": img, "box": box, "canvas": int(canvas),
               "sharpness": sh, "source": source}
        return (crop, ctx, text)


class AfloyDetailPaste:
    """Правленое окно назад в кадр. На выходе — ПОЛНЫЙ кадр, не кроп."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "ctx": ("DETAIL_CTX",),
                "edited": ("IMAGE",),
                "feather": ("FLOAT", {"default": FEATHER, "min": 0.0,
                                      "max": 0.49, "step": 0.01}),
                "blend": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0,
                                    "step": 0.01}),
            },
            "optional": {
                # Вклеить можно и в ДРУГОЙ кадр того же размера — например в
                # тот же кадр после апскейла в другой ветке. Рамка при этом
                # берётся из ctx и остаётся верной, потому что она в долях
                # пикселей исходника; при несовпадении размера узел откажет.
                "into": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "run"
    CATEGORY = "Afloy/detail"
    DESCRIPTION = ("Возвращает правленое окно в кадр с пером по краю. "
                   "blend гасит силу правки, не трогая её рисунок.")

    def run(self, ctx, edited, feather, blend, into=None):
        if not isinstance(ctx, dict) or "box" not in ctx:
            raise ValueError("ctx не от AfloyDetailCut")
        base = ctx["image"] if into is None else (
            into if into.dim() == 4 else into.unsqueeze(0))
        if into is not None and tuple(base.shape[1:3]) != tuple(
                ctx["image"].shape[1:3]):
            raise ValueError(
                "«into» другого размера (%dx%d против %dx%d): рамка из ctx "
                "встала бы мимо. Приведи кадр к размеру исходника или вклеивай "
                "в него." % (base.shape[2], base.shape[1],
                             ctx["image"].shape[2], ctx["image"].shape[1]))
        return (paste(base, edited, ctx["box"], feather=feather,
                      blend=blend),)


class AfloyDetailPreviewBox:
    """Кадр с нарисованной рамкой окна — посмотреть ДО того, как тратить проход.

    Отдельный узел, а не ключ у «вырезать»: превью нужно на другом этапе, до
    сэмплера, и смешивать это с рабочим выходом значило бы возвращать из одного
    узла две разные по смыслу картинки.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"ctx": ("DETAIL_CTX",),
                             "width": ("INT", {"default": 4, "min": 1,
                                               "max": 64})}}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("preview",)
    FUNCTION = "run"
    CATEGORY = "Afloy/detail"
    DESCRIPTION = "Кадр целиком с жёлтой рамкой на месте окна."

    def run(self, ctx, width):
        img = ctx["image"].clone()
        x0, y0, x1, y1 = ctx["box"]
        c = torch.tensor([1.0, 0.78, 0.0], dtype=img.dtype, device=img.device)
        w = max(1, int(width))
        for a, b in ((y0, y0 + w), (y1 - w, y1)):
            img[:, max(0, a):max(0, b), x0:x1, :3] = c
        for a, b in ((x0, x0 + w), (x1 - w, x1)):
            img[:, y0:y1, max(0, a):max(0, b), :3] = c
        return (img,)


NODE_CLASS_MAPPINGS = {
    "AfloyDetailCut": AfloyDetailCut,
    "AfloyDetailPaste": AfloyDetailPaste,
    "AfloyDetailPreviewBox": AfloyDetailPreviewBox,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AfloyDetailCut": "Afloy Detail · вырезать окно",
    "AfloyDetailPaste": "Afloy Detail · вклеить обратно",
    "AfloyDetailPreviewBox": "Afloy Detail · показать рамку",
}
