"""Холст и батч снимают ОДНИМ И ТЕМ ЖЕ. Иначе холст не превью, а обманка.

ШОВ, КОТОРЫЙ УЖЕ РАЗОШЁЛСЯ. Ручной холст читал `models.realism_loras` из
манифеста сам, а батч строил стек в `generate.edit_lora_stack`. Два читателя
одного файла разъехались молча: на холсте стоял полный риг без персонажной
лоры, в батче — персонажная лора и одна реализм-лора. То есть человек
подбирал кадр на одном наборе весов, а конвейер снимал на другом, и подбор
ничего не предсказывал.

Хуже того, промпт обоим строит `prompts.build_cell`, а он подставляет
триггер персонажной лоры. На холсте, где этой лоры не было, первое слово
промпта не имело за собой весов вовсе.

Здесь закреплено, что стек у них один и берётся из одного места.
"""
import json
import os

import pytest

import build_ui_edit as B
import generate as G
from _util import ROOT

# Заглушка объявлений сервера. Высоты нод здесь неважны — проверяется состав
# графа, а не раскладка; важно лишь, чтобы сборка прошла без сети.
STUB = {
    "UNETLoader": {}, "CLIPLoader": {}, "VAELoader": {},
    "LoadImage": {}, "ImageScaleToMaxDimension": {"required": {"image": ["IMAGE"]}},
    "LoraLoaderModelOnly": {"required": {"model": ["MODEL"]}},
    "Krea2EditGroundedEncode": {"required": {"clip": ["CLIP"]},
                                "optional": {"image": ["IMAGE"],
                                             "image_b": ["IMAGE"]}},
    "CLIPTextEncode": {"required": {"clip": ["CLIP"]}},
    "VAEEncode": {"required": {"pixels": ["IMAGE"], "vae": ["VAE"]}},
    "Krea2EditModelPatch": {"required": {"model": ["MODEL"]},
                            "optional": {"source_latent": ["LATENT"],
                                         "vae": ["VAE"]}},
    "EmptyLatentImage": {}, "KSampler": {"required": {"model": ["MODEL"]}},
    "VAEDecode": {"required": {"samples": ["LATENT"], "vae": ["VAE"]}},
    "PreviewImage": {"required": {"images": ["IMAGE"]}}, "Note": {},
}


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(B, "OBJ", dict(STUB))
    monkeypatch.setattr(B, "_object_info", lambda: dict(STUB))


def canvas_loras(wf):
    """(имя, сила) каждой лоры холста, в порядке применения."""
    out = []
    for n in wf["nodes"]:
        if n["type"] == "LoraLoaderModelOnly":
            out.append((n["widgets_values"][0], float(n["widgets_values"][1])))
    return out


def test_canvas_and_batch_carry_the_same_loras(offline):
    """Один стек, а не два похожих.

    Механизм `krea2_identity_edit` в батче стоит в самом шаблоне (нода 4), а
    на холсте — отдельной нодой, поэтому он сверяется отдельно; всё остальное
    обязано совпадать поимённо и по силе.
    """
    wf = B.build("P1", "body", os.path.join(ROOT, "projects", "bridget"))
    got = canvas_loras(wf)
    assert got[0][0].startswith("krea2_identity_edit"), (
        "первой на холсте обязана стоять эдит-лора: она механизм переноса "
        "личности, без неё группа IDENTITY — пустая ручка")

    want = [(l["name"], float(l["strength"]))
            for l in G.lora_stack(char_id="bridget")]
    assert got[1:] == want, (
        "холст и батч разошлись по весам:\n  холст: {}\n  батч:  {}"
        .format(got[1:], want))


def test_canvas_carries_the_character_lora_its_prompt_triggers(offline):
    """Триггер в промпте — только если за ним есть веса.

    `build_cell` подставляет первым словом триггер персонажной лоры. Холст,
    собранный без этой лоры, отправлял в модель слово, которому ничего не
    соответствует, — и делал это молча.
    """
    proj = os.path.join(ROOT, "projects", "bridget")
    wf = B.build("P1", "body", proj)
    from _util import character_lora
    ch = character_lora("bridget")
    if not ch:
        pytest.skip("персонажной лоры для bridget в манифесте нет")
    names = [n for n, _s in canvas_loras(wf)]
    text = [n for n in wf["nodes"]
            if n["type"] == "Krea2EditGroundedEncode"][0]["widgets_values"][0]
    if ch.get("trigger") and text.startswith(ch["trigger"]):
        assert ch["name"] in names, (
            "промпт начинается с триггера {!r}, но лоры {!r} на холсте нет"
            .format(ch["trigger"], ch["name"]))


def test_canvas_prompt_is_the_one_the_batch_would_send(offline):
    """Иначе превью показывает не то, что снимет конвейер."""
    from prompts import build_cell, load_project
    proj = os.path.join(ROOT, "projects", "bridget")
    char, shots = load_project(proj)
    cell = [c for c in shots["cells"] if c["id"] == "P1"][0]
    wf = B.build("P1", "body", proj)
    text = [n for n in wf["nodes"]
            if n["type"] == "Krea2EditGroundedEncode"][0]["widgets_values"][0]
    assert text == build_cell(char, cell)


def test_without_a_project_the_prompt_stays_a_placeholder(offline):
    wf = B.build("P1", "body", None)
    text = [n for n in wf["nodes"]
            if n["type"] == "Krea2EditGroundedEncode"][0]["widgets_values"][0]
    assert "ОПИШИТЕ" in text


def test_unknown_cell_names_the_ones_that_exist(offline):
    with pytest.raises(SystemExit) as e:
        B.build("P99", "body", os.path.join(ROOT, "projects", "bridget"))
    assert "P1" in str(e.value)


def test_every_link_is_written_in_all_three_places(offline):
    """Связь живёт в трёх местах, и холст уже открывался без единой линии.

    litegraph рисует по `links`, но узлы читают свои `inputs[].link` и
    `outputs[].links`. Записанное только в массив связей давало граф, который
    на вид собран, а в браузере — россыпь несоединённых нод.
    """
    wf = B.build("P1", "body", None)
    by_id = {n["id"]: n for n in wf["nodes"]}
    declared = {l[0] for l in wf["links"]}
    for lid, src, sslot, dst, dslot, _t in wf["links"]:
        assert by_id[dst]["inputs"][dslot]["link"] == lid, (
            "вход {} ноды {} не знает про связь {}".format(dslot, dst, lid))
        assert lid in by_id[src]["outputs"][sslot]["links"], (
            "выход {} ноды {} не знает про связь {}".format(sslot, src, lid))
    for n in wf["nodes"]:
        for i, inp in enumerate(n.get("inputs") or []):
            if inp.get("link") is not None:
                assert inp["link"] in declared, (
                    "вход {} ноды {} ссылается на несуществующую связь"
                    .format(i, n["id"]))


def test_order_is_unique(offline):
    """Одинаковый `order` у всех нод — та самая причина «связей не видно».

    litegraph перестраивает граф по порядку исполнения; когда он у всех нулевой,
    восстановить связи браузер не может.
    """
    orders = [n["order"] for n in B.build("P1", "body", None)["nodes"]]
    assert len(set(orders)) == len(orders), "order обязан быть уникальным"


def test_shipped_canvas_matches_the_builder(offline):
    """Файл в репозитории собран текущим сборщиком, а не забыт после правки."""
    path = os.path.join(ROOT, "templates", "comfy",
                        "PERSONA_CHARACTER_FROM_REFERENCE.json")
    if not os.path.exists(path):
        pytest.skip("холст ещё не собран")
    with open(path, encoding="utf-8") as fh:
        shipped = json.load(fh)
    got = {(n, s) for n, s in canvas_loras(shipped)}
    want = {(l["name"], float(l["strength"]))
            for l in G.lora_stack(char_id="bridget")}
    want.add(("krea2_identity_edit_v1_2.safetensors", 1.0))
    assert got == want, (
        "холст в репозитории собран старым стеком — пересобрать "
        "build_ui_edit.py")
