"""UI-воркфлоу: сверка виджетов и детерминизм пересборки.

  py -3 -m pytest tests/test_build_ui.py -q

Сверка виджетов — единственная защита от молча сломанного воркфлоу. У KSampler
в UI-формате между seed и steps стоит служебный виджет control_after_generate,
которого нет в API-формате: собранный по API-порядку граф кладёт steps в чужое
поле и работает без единой ошибки, просто не тем, чем задумано. Первая версия
verify_widgets сверяла только ДЛИНУ списка, поэтому перестановка sampler_name и
scheduler — ровно та ошибка, ради которой функция написана, — проходила с
вердиктом «чисто».

Ответ сервера здесь подставляется заглушкой. В CI ComfyUI нет, а тест, который
зелен только рядом с включённым сервером, не проверяет ничего.
"""
import io
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

import build_ui
from conftest import MANIFEST, ROOT

_BASE = MANIFEST["models"]["base"]
# Список лор заглушки — ВСЕ, что объявляет манифест, включая персонажную.
# Раньше здесь были только realism_loras, и это совпадало с правдой ровно до
# дня, когда лору обучили и вписали в assets.json: сверщик честно сказал, что
# сервер такой лоры не знает, — но знал её выдуманный сервер теста, а не
# настоящий. Заглушка обязана отражать манифест целиком, иначе она проверяет
# вчерашний проект.
_LORAS = [lora["name"] for lora in MANIFEST["models"]["realism_loras"]]
_CHAR = (MANIFEST["models"].get("character_lora") or {}).get("name")
if _CHAR:
    _LORAS = [_CHAR] + _LORAS

# Ответ /object_info в формате ComfyUI: {тип: {"input": {"required": {имя:
# [тип, конфиг]}}}}. Списки-варианты COMBO намеренно НЕ пересекаются между
# sampler_name и scheduler — иначе перестановка этих двух значений осталась бы
# законной и тест на неё был бы фикцией.
SAMPLERS = [_BASE["sampler"], "dpmpp_2m", "heun"]
SCHEDULERS = [_BASE["scheduler"], "normal", "karras"]

OBJECT_INFO = {
    "UNETLoader": {"input": {"required": {
        "unet_name": [[_BASE["unet"], "other.safetensors"]],
        "weight_dtype": [["default", "fp8_e4m3fn"]]}}},
    "CLIPLoader": {"input": {
        "required": {"clip_name": [[_BASE["clip"]]],
                     "type": [[_BASE["clip_type"], "stable_diffusion"]]},
        # device лежит в optional с флагом advanced: в интерфейсе скрыт, а слот
        # в widgets_values занимает — сверка обязана его учитывать.
        "optional": {"device": [["default", "cpu"], {"advanced": True}]}}},
    "VAELoader": {"input": {"required": {"vae_name": [[_BASE["vae"]]]}}},
    # Ноды доводки. Появились в графе вместе с апскейлом, и заглушка обязана
    # знать их так же, как знает загрузчики: иначе сверка виджетов ругается на
    # исправный граф — она честно сообщает, что сервер такого узла не знает, а
    # не знает его выдуманный сервер теста.
    # Afloy Lora Box — кастомная нода, и с 17.08.2026 она в боевом графе.
    # Заглушка обязана её знать, иначе сверка виджетов ругается на исправный
    # граф: сервер-то настоящий её знает, а выдуманный сервер теста — нет.
    "LoraBox": {"input": {
        "required": {"model": ["MODEL"], "clip": ["CLIP"]},
        "optional": {"prompt": ["STRING", {"forceInput": True}],
                     "data": ["STRING", {"default": "[]"}]}}},
    "UpscaleModelLoader": {"input": {"required": {
        "model_name": [[MANIFEST["models"]["upscale"]["general"]]]}}},
    "ImageUpscaleWithModel": {"input": {"required": {
        "upscale_model": ["UPSCALE_MODEL"], "image": ["IMAGE"]}}},
    "ImageScaleBy": {"input": {"required": {
        "image": ["IMAGE"],
        "upscale_method": [["nearest-exact", "bilinear", "area", "bicubic",
                            "lanczos"]],
        "scale_by": ["FLOAT", {"default": 1.0}]}}},
    "LoraLoaderModelOnly": {"input": {"required": {
        "model": ["MODEL"], "lora_name": [_LORAS],
        "strength_model": ["FLOAT", {"default": 1.0}]}}},
    "CLIPTextEncode": {"input": {"required": {
        "text": ["STRING", {"multiline": True}], "clip": ["CLIP"]}}},
    "ConditioningZeroOut": {"input": {"required": {
        "conditioning": ["CONDITIONING"]}}},
    "EmptyLatentImage": {"input": {"required": {
        "width": ["INT", {"default": 512}], "height": ["INT", {"default": 512}],
        "batch_size": ["INT", {"default": 1}]}}},
    "KSampler": {"input": {"required": {
        "model": ["MODEL"], "seed": ["INT", {"default": 0}],
        "steps": ["INT", {"default": 20}], "cfg": ["FLOAT", {"default": 8.0}],
        "sampler_name": [SAMPLERS], "scheduler": [SCHEDULERS],
        "positive": ["CONDITIONING"], "negative": ["CONDITIONING"],
        "latent_image": ["LATENT"], "denoise": ["FLOAT", {"default": 1.0}]}}},
    "VAEDecode": {"input": {"required": {
        "samples": ["LATENT"], "vae": ["VAE"]}}},
    "PreviewImage": {"input": {"required": {"images": ["IMAGE"]}}},
    "SaveImage": {"input": {"required": {
        "images": ["IMAGE"],
        "filename_prefix": ["STRING", {"default": "ComfyUI"}]}}},
}


@pytest.fixture
def fake_server(monkeypatch):
    """Подменить /object_info заглушкой. Сети в тестах нет и быть не должно.

    АДРЕС ЗАДАЁТСЯ ЗДЕСЬ ЖЕ, И БЕЗ ЭТОГО ФИКСТУРА НЕ ДЕРЖАЛА ОБЕЩАНИЯ.
    Заглушка перехватывает `urlopen`, но `comfy_client._default_host()` зовётся
    РАНЬШЕ запроса и падает `SystemExit: адрес ComfyUI не задан`, когда нет ни
    COMFY_HOST, ни assets.local.json. На чистом клоне это роняло четыре теста
    этого файла; CI выживал только потому, что ci.yml пинит адрес переменной
    окружения. То есть проверка держалась на настройке раннера, а не на себе.
    Адрес заведомо мёртвый: единственный, кто мог бы по нему пойти, уже подменён.
    """
    monkeypatch.setenv("COMFY_HOST", "http://127.0.0.1:9")

    def urlopen(url, *a, **kw):
        cls = str(url).rsplit("/", 1)[-1]
        if cls not in OBJECT_INFO:
            raise urllib.error.URLError(f"нет ноды {cls}")
        return io.StringIO(json.dumps({cls: OBJECT_INFO[cls]}))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)


def test_sampler_choices_do_not_overlap():
    """Страховка самой заглушки: списки sampler и scheduler различны."""
    assert not set(SAMPLERS) & set(SCHEDULERS)


def test_clean_workflow_verifies(fake_server):
    """Собранный воркфлоу должен сходиться с сервером как есть."""
    bad, seen, _skipped = build_ui.verify_widgets(build_ui.build("P1"))
    assert bad == []
    assert seen["KSampler"] == ["seed", "control_after_generate", "steps", "cfg",
                                "sampler_name", "scheduler", "denoise"]


def test_swapped_sampler_and_scheduler_is_caught(fake_server):
    """Перестановка sampler_name и scheduler обязана падать.

    Длина списка при перестановке не меняется — ловится только сверкой
    содержимого каждого слота со списком вариантов ноды.
    """
    wf = build_ui.build("P1")
    ks = next(n for n in wf["nodes"] if n["type"] == "KSampler")
    i = 4  # seed, control_after_generate, steps, cfg, sampler_name, scheduler
    ks["widgets_values"][i], ks["widgets_values"][i + 1] = \
        ks["widgets_values"][i + 1], ks["widgets_values"][i]

    bad, _, _skipped = build_ui.verify_widgets(wf)
    assert bad, "перестановка сэмплера и планировщика прошла как «чисто»"
    assert any("sampler_name" in b for b in bad), bad
    assert any("scheduler" in b for b in bad), bad


def test_missing_widget_is_caught(fake_server):
    """Недостача слота — тот самый случай, когда steps уезжает в чужое поле."""
    wf = build_ui.build("P1")
    ks = next(n for n in wf["nodes"] if n["type"] == "KSampler")
    ks["widgets_values"].pop(1)          # control_after_generate
    bad, _, _skipped = build_ui.verify_widgets(wf)
    assert any("KSampler" in b for b in bad), bad


def test_unreachable_server_is_a_problem_not_a_pass(fake_server, monkeypatch):
    """Молчащий сервер = НЕ ПРОВЕРЕНО, а не «чисто».

    Ворота, которые выключаются при отсутствии зависимости, дают ложный PASS;
    у сверки виджетов ровно та же ловушка.
    """
    def dead(url, *a, **kw):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", dead)
    bad, seen, _skipped = build_ui.verify_widgets(build_ui.build("P1"))
    assert bad and not seen


def test_rebuild_is_byte_identical():
    """Две сборки подряд — байт в байт.

    Со случайным uuid каждый прогон делал отслеживаемый файл «изменённым», и
    сверку «пересобранное == закоммиченное» нельзя было ни глазом сделать, ни
    поставить в CI. Сравниваются именно байты сериализации, а не словари.
    """
    a = json.dumps(build_ui.build("P1"), ensure_ascii=False, indent=1).encode()
    b = json.dumps(build_ui.build("P1"), ensure_ascii=False, indent=1).encode()
    assert a == b
    assert build_ui.build("P2")["id"] != build_ui.build("P1")["id"]


def test_cli_rebuild_is_byte_identical(tmp_path):
    """То же самое через CLI: недетерминизм мог жить и в main(), а не в build()."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               PERSONA_WORK_ROOT=str(tmp_path / "work"))
    out = []
    for i in (1, 2):
        dest = tmp_path / f"wf{i}.json"
        subprocess.run([sys.executable,
                        os.path.join(ROOT, "scripts", "build_ui.py"),
                        "--out", str(dest)],
                       check=True, env=env, capture_output=True)
        out.append(dest.read_bytes())
    assert out[0] == out[1]


def test_committed_workflow_matches_rebuild():
    """Закоммиченный UI-двойник не должен расходиться со сборщиком по структуре.

    Сверяется скелет — ноды, связи, группы, порядок виджетов, — но не текст
    промпта: он законно меняется при каждой правке карточки персонажа, а
    расходятся эти два файла ОПАСНО в другом месте (порядок виджетов, номера
    нод), и именно это молчит без проверки.
    """
    committed = os.path.join(ROOT, "templates", "comfy",
                             "PERSONA_MANUAL_CHECK.json")
    if not os.path.exists(committed):
        pytest.skip("UI-двойник ещё не закоммичен")
    with open(committed, encoding="utf-8") as fh:
        old = _skeleton(json.load(fh))
    assert old == _skeleton(build_ui.build("P1"))


def _skeleton(wf):
    """Воркфлоу без текста промпта — всё остальное обязано совпадать."""
    out = json.loads(json.dumps(wf))
    for node in out["nodes"]:
        if node["type"] == "CLIPTextEncode":
            node["widgets_values"] = ["<prompt>"]
    return out


def test_saveimage_stays_disabled():
    """Сейв выключен намеренно: машина общая, удалить из output/ по API нечем."""
    wf = build_ui.build("P1")
    save = next(n for n in wf["nodes"] if n["type"] == "SaveImage")
    assert save["mode"] == 2
    assert any(n["type"] == "PreviewImage" and n["mode"] == 0
               for n in wf["nodes"])


def test_layout_has_no_overlaps():
    """Группы не пересекаются, вертикальный зазор не меньше нормы (70 px)."""
    problems, min_gap = build_ui.check_layout(build_ui.build("P1"))
    assert problems == []
    assert min_gap is None or min_gap >= 70
