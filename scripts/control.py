#!/usr/bin/env python3
"""Управление кадром: композиция ВЫБИРАЕТСЯ опорой, а не выпадает по сиду.

  py -3 control.py probe                       схемы нод контроля с живого воркера
  py -3 control.py measure <project_dir> --ref <снимок> [--cell P3]
        [--strength 1.0] [--seeds 101,202,303] [--out <файл.md>] [--dry]
  py -3 control.py scrub                       затереть залитые опоры заглушкой

Как модуль:
  from control import attach_control, control_state, depth_agreement
  graph = attach_control(graph, {"image": "ref.jpg", "strength": 1.0,
                                 "kind": "depth"})

ЧТО ЭТО ДЕЛАЕТ. В графе появляется пять узлов: снимок-опора грузится с сервера,
проходит препроцессор глубины ПРЯМО В ГРАФЕ, карта кодируется в латент опоры,
на модель кладётся depth-control-лора, и Krea2ControlApply вешает латент на
модель. Сэмплер после этого цепляется за выход Apply.

ПРЕПРОЦЕССОР В ГРАФЕ, А НЕ СНАРУЖИ — это условие задачи и оно же условие
пользы: опорой должен работать ЛЮБОЙ снимок (сданный кадр, фотография из
телефона), а не заранее приготовленная карта глубины. Готовить её отдельным
шагом значит завести второй артефакт, который надо хранить, версионировать и
случайно рассинхронизировать с опорой.

KREA 2 — СВОЯ АРХИТЕКТУРА. ControlNet-модели SD/SDXL/Flux к ней неприменимы, и
это не «работают хуже»: ControlNetLoader на этой машине показывает ПУСТОЙ
список моделей, а интерфейс обусловливания у Krea 2 другой — control-лора на
модель плюс латент опоры, а не conditioning. Публично существует только depth,
поэтому поза и ракурс выражаются картой глубины, и другого kind тут нет.

СИЛА 0 ЗАПРЕЩЕНА. Граф с нулевой силой выглядит управляемым и не управляется —
ровно тот ложный зелёный, ради которого написан control_state(). Прогон без
контроля строится тем, что attach_control просто не зовут.

Числа замера этот файл не содержит: их печатает `measure` и кладёт в
docs/<project>/control.md. Проза с числами рядом с кодом, который эти числа
меняет, — подписная ошибка этого репозитория.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (ROOT, cli_opt, imread, manifest, project_name,  # noqa: E402
                   setup_console, work_dir)
import comfy_client as cc  # noqa: E402

# Классы нод пака Krea 2 ControlNet. Разведаны на живом воркере через
# /object_info/<Имя>; ровно эти входы и выходы у них и есть.
LORA_LOADER = "Krea2ControlLoRALoader"      # MODEL, lora_name, strength → MODEL
ENCODE = "Krea2ControlImageEncode"          # IMAGE, VAE, [LATENT] → LATENT, IMAGE
APPLY = "Krea2ControlApply"                 # MODEL, LATENT → MODEL

# Препроцессор глубины и его веса. Здесь, а не в манифесте, потому что это
# СТРОЕНИЕ графа, а не настройка: сменить их — значит сменить схему, и тогда
# правится именно этот файл вместе с шаблоном.
DEPTH_PREPROCESSOR = "DepthAnythingV2Preprocessor"
DEPTH_CKPT = "depth_anything_v2_vitl.pth"
DEPTH_RESOLUTION = 1024

CONTROL_LORA = {"depth": "krea2-depth-control-lora.safetensors"}

# Значение image в шаблоне templates/comfy/krea2_t2i_control_api.json — по
# образцу «PLACEHOLDER PROMPT» из базового шаблона. Заглушка обязана быть
# заведомо нерабочей: шаблон с чьей-нибудь настоящей опорой внутри однажды уедет
# в прогон как есть, и подмена заметится по кадрам, а не по ошибке.
PLACEHOLDER_IMAGE = "PLACEHOLDER CONTROL IMAGE"

SAMPLER_CLASSES = ("KSampler", "KSamplerAdvanced")

# Состояния контроля. Три, а не два, по той же причине, что и у ворот: «блока
# в графе нет» и «блок есть, но силы у него нет» чинятся разными руками, а
# сливаясь в одно «не работает», отправляют оператора искать не там.
ON, OFF, ABSENT = "ON", "OFF", "ABSENT"

_SAID = set()


def _cfg(key, default):
    """Ключ models.control из манифеста — с ГРОМКИМ запасным значением.

    Молчаливый запасной вариант превращает пропажу ключа в поведение по
    умолчанию, и манифест перестаёт быть местом правды незаметно для всех.
    Строка печатается один раз на процесс: в батче на сорок кадров сорок
    одинаковых предупреждений читаются как шум и не читаются вовсе.
    """
    ctl = (manifest().get("models") or {}).get("control") or {}
    if key in ctl:
        return ctl[key]
    if key not in _SAID:
        _SAID.add(key)
        print(f"assets.json → models.control.{key} нет, беру {default!r}",
              file=sys.stderr)
    return default


# ------------------------------------------------------------------ разбор графа

def _one(graph, classes, what):
    """Единственный узел такого класса. Ноль и два — одинаково повод упасть.

    Молча взять первый попавшийся сэмплер значит подключить контроль к одной
    ветке графа и отрапортовать об успехе, пока кадр рисует другая.
    """
    ids = sorted((nid for nid, n in graph.items()
                  if isinstance(n, dict) and n.get("class_type") in classes),
                 key=lambda s: (len(s), s))
    if len(ids) != 1:
        raise SystemExit(
            f"в графе должен быть ровно один узел «{what}» "
            f"({'/'.join(classes)}), найдено {len(ids)}: {ids or '—'}")
    return ids[0]


def _link(graph, nid, port):
    """Ссылка [узел, выход] у входа port. Не ссылка — значит вход зашит числом."""
    v = graph[nid]["inputs"].get(port)
    return v if isinstance(v, list) and len(v) == 2 else None


def _vae_link(graph):
    """Откуда брать VAE для кодирования опоры.

    Спрашивается у VAEDecode, а не ищется класс VAELoader: в графе может стоять
    CheckpointLoaderSimple или второй VAE для отдельной ветки, и «нашёлся
    загрузчик» не равно «этим VAE декодируется кадр». Опора обязана кодироваться
    ТЕМ ЖЕ VAE, которым кадр декодируется, иначе латент опоры лежит в другом
    пространстве и контроль тянет кадр в шум.
    """
    dec = _one(graph, ("VAEDecode", "VAEDecodeTiled"), "VAEDecode")
    vae = _link(graph, dec, "vae")
    if vae is None:
        raise SystemExit(f"у узла {dec} (VAEDecode) вход vae не связан")
    return vae


def _free_ids(graph, n):
    """n свободных числовых id. Так же, как их выдаёт generate._apply_loras."""
    nxt = max((int(k) for k in graph if str(k).isdigit()), default=0) + 1
    return [str(nxt + i) for i in range(n)]


def model_path(graph, sampler=None):
    """Узлы на пути MODEL от базовой модели к сэмплеру, в порядке применения.

    Именно ПУТЬ, а не список узлов графа: узел, который лежит в графе, но до
    сэмплера не доходит, на кадр не влияет никак. Вся проверка контроля держится
    на этой разнице.
    """
    sampler = sampler or _one(graph, SAMPLER_CLASSES, "сэмплер")
    chain, seen, link = [], set(), _link(graph, sampler, "model")
    while link is not None:
        nid = link[0]
        if nid in seen:
            raise SystemExit(f"цикл в цепочке model на узле {nid}")
        seen.add(nid)
        chain.append(nid)
        link = _link(graph, nid, "model")
    return list(reversed(chain))


# ------------------------------------------------------------------ состояние

def control_state(graph):
    """Что с управлением кадром В ЭТОМ графе: ON / OFF / ABSENT.

    ЭТО ГЛАВНАЯ ФУНКЦИЯ ФАЙЛА, а не attach_control. Сборка графа ошибается
    тихо: пять узлов на месте, ссылки красивые, а сэмплер по-прежнему висит на
    хвосте лор — и прогон честно рисует лотерею, отчитываясь как управляемый.
    Отличить это глазами по JSON нельзя, поэтому проверку делает код и делает её
    ОТ СЭМПЛЕРА НАЗАД: единственный вопрос, на который стоит отвечать, — дошёл
    ли контроль до того, что рисует кадр.

    Возвращает словарь со state, kind, strength, image, why и картой узлов.
    """
    sampler = _one(graph, SAMPLER_CLASSES, "сэмплер")
    chain = model_path(graph, sampler)
    out = {"state": ABSENT, "kind": None, "strength": None, "image": None,
           "sampler": sampler, "nodes": {}, "why": ""}

    applies = [n for n in chain if graph[n].get("class_type") == APPLY]
    if not applies:
        stray = sorted(n for n, v in graph.items()
                       if isinstance(v, dict) and v.get("class_type") == APPLY)
        out["why"] = f"на пути model к сэмплеру {sampler} нет {APPLY}"
        if stray:
            # Самый частый способ собрать ложный зелёный: блок построен, а
            # последняя ссылка (сэмплер → Apply) не переставлена.
            out["why"] += (f"; узлы {stray} в графе есть, но к сэмплеру не "
                           f"подключены — кадр их не увидит")
        return out
    if len(applies) > 1:
        # Не состояние, а сломанный граф: два контроля на одном пути — это не
        # «слабее» и не «сильнее», это неопределённость. Падать здесь
        # последовательно с _one(), который так же поступает с двумя сэмплерами.
        raise SystemExit(f"{APPLY} на пути к сэмплеру больше одного: {applies}; "
                         f"какой из контролей победит — не определено. Скорее "
                         f"всего attach_control позвали дважды на одном графе")

    ap = applies[0]
    out["nodes"]["apply"] = ap
    enc = _link(graph, ap, "control_latent")
    lora = _link(graph, ap, "model")
    if enc is None or graph[enc[0]].get("class_type") != ENCODE:
        out["why"] = f"вход control_latent узла {ap} идёт не из {ENCODE}"
        return out
    out["nodes"]["encode"] = enc[0]
    if lora is None or graph[lora[0]].get("class_type") != LORA_LOADER:
        # Apply без control-лоры перед ним — это Apply в пустоту: веса,
        # которые должны читать латент опоры, в модель не подмешаны.
        out["state"] = OFF
        out["why"] = f"перед {ap} нет {LORA_LOADER} — контрольные веса не загружены"
        return out
    out["nodes"]["lora"] = lora[0]

    name = graph[lora[0]]["inputs"].get("lora_name")
    out["kind"] = next((k for k, v in CONTROL_LORA.items() if v == name), None)
    out["strength"] = graph[lora[0]]["inputs"].get("strength")

    dep = _link(graph, enc[0], "control_image")
    if dep is not None:
        out["nodes"]["depth"] = dep[0]
        src = _link(graph, dep[0], "image")
        if src is not None:
            out["nodes"]["image"] = src[0]
            out["image"] = graph[src[0]]["inputs"].get("image")

    if out["kind"] is None:
        out["state"] = OFF
        out["why"] = (f"узел {lora[0]} грузит {name!r} — это не control-лора "
                      f"(известны: {sorted(CONTROL_LORA.values())})")
    elif not out["strength"]:
        out["state"] = OFF
        out["why"] = "сила контроля 0 — блок собран, но на кадр не влияет"
    else:
        out["state"] = ON
        out["why"] = (f"{out['kind']} с опоры {out['image']!r}, "
                      f"сила {out['strength']}")
    return out


def require_control(graph, kind=None, strength=None):
    """Убедиться, что обещанный контроль ДЕЙСТВИТЕЛЬНО в графе, иначе упасть.

    Зовётся самим attach_control: функция, которая может вернуть граф без
    контроля и не сказать об этом, дороже, чем её отсутствие — GPU-час уходит
    на кадр, который потом кладут в набор как управляемый.
    """
    st = control_state(graph)
    if st["state"] != ON:
        raise SystemExit(f"контроль не подключён ({st['state']}): {st['why']}")
    if kind is not None and st["kind"] != kind:
        raise SystemExit(f"в графе контроль {st['kind']}, просили {kind}")
    if strength is not None and abs(float(st["strength"]) - float(strength)) > 1e-9:
        raise SystemExit(f"в графе сила {st['strength']}, просили {strength}")
    return st


# ------------------------------------------------------------------ сборка

_UPLOADED = {}


def _upload(path):
    """Залить опору на сервер один раз за процесс.

    Ключ — путь, размер и время правки, а не один путь: батч на сорок кадров
    иначе перезаливает один и тот же файл сорок раз, а подменённый на ходу файл
    иначе остался бы старым.
    """
    if not os.path.exists(path):
        raise SystemExit(f"опоры нет на диске: {path}")
    st = os.stat(path)
    key = (os.path.abspath(path), st.st_size, int(st.st_mtime))
    if key not in _UPLOADED:
        _UPLOADED[key] = cc.upload(path)
    return _UPLOADED[key]


def scrub_uploads(uploader=None):
    """Затереть залитые опоры заглушкой 1x1. Возвращает список имён.

    УДАЛИТЬ ФАЙЛ ИЗ input/ ПО API НЕЧЕМ — это разобрано в comfy_client: там
    работает только user/, а ноды удаления нет. Но опора — это СДАННЫЙ КАДР
    ЗАКАЗЧИКА, лежащий на чужой машине, и оставлять его там на неделю ради
    пятиминутного замера нельзя. Перезалить под тем же именем картинку в
    несколько десятков байт API позволяет: имя в папке остаётся, содержимого
    не остаётся. Это максимум, который доступен без SSH, и его надо делать —
    «удалить нечем» не то же самое, что «пусть лежит».
    """
    import tempfile
    from PIL import Image
    done = []
    for key, ref in list(_UPLOADED.items()):
        name = os.path.basename(ref)
        tmp = os.path.join(tempfile.mkdtemp(prefix="pf_scrub_"), name)
        # Формат по расширению: заглушка обязана открываться как картинка, иначе
        # LoadImage на сервере начнёт падать вместо того, чтобы отдать пустышку.
        Image.new("RGB", (1, 1), (0, 0, 0)).save(tmp)
        (uploader or cc.upload)(tmp)
        os.remove(tmp)
        os.rmdir(os.path.dirname(tmp))
        _UPLOADED.pop(key, None)
        done.append(ref)
    return done


def attach_control(graph, spec, uploader=None):
    """Граф + спецификация управления → тот же граф с подключённым контролем.

    spec: {"image": путь к снимку-опоре, "strength": число, "kind": "depth"}.
    uploader подменяется в тестах; по умолчанию — заливка на сервер.

    Узлы ищутся ПО КЛАССАМ, а не по номерам из шаблона: перед контролем граф
    успевает пройти generate._apply_loras, который достраивает цепочку лор и
    двигает номера. Прибитый номер сэмплера означал бы, что контроль работает
    ровно до появления персонажной лоры в манифесте.
    """
    spec = dict(spec or {})
    kind = spec.get("kind", "depth")
    if kind not in CONTROL_LORA:
        raise SystemExit(f"kind={kind!r} не поддержан; есть только "
                         f"{sorted(CONTROL_LORA)} — у Krea 2 публично "
                         f"существует одна control-лора, depth")
    image = spec.get("image")
    if not image:
        raise SystemExit("в спецификации управления нет image — опоры")
    strength = float(spec.get("strength", _cfg("strength", 1.0)))
    if strength == 0:
        raise SystemExit(
            "сила 0: такой граф выглядит управляемым и не управляется. "
            "Прогон без контроля — это граф, которому attach_control не звали")

    sampler = _one(graph, SAMPLER_CLASSES, "сэмплер")
    tail = _link(graph, sampler, "model")
    if tail is None:
        raise SystemExit(f"у сэмплера {sampler} вход model не связан")
    # Латент опоры обязан совпасть по размеру с латентом кадра, иначе Apply
    # складывает тензоры разной формы. Размер берётся у ТОГО ЖЕ латента, из
    # которого рисуется кадр, — тогда смена формата кадра (ячейка P2 просит
    # 1024x1536) переносится на опору сама.
    latent = _link(graph, sampler, "latent_image")
    if latent is None:
        raise SystemExit(f"у сэмплера {sampler} вход latent_image не связан")
    vae = _vae_link(graph)
    ref = (uploader or _upload)(image)

    load, depth, enc, lora, ap = _free_ids(graph, 5)
    graph[load] = {"class_type": "LoadImage", "inputs": {"image": ref}}
    graph[depth] = {"class_type": DEPTH_PREPROCESSOR,
                    "inputs": {"image": [load, 0], "ckpt_name": DEPTH_CKPT,
                               "resolution": DEPTH_RESOLUTION}}
    graph[enc] = {"class_type": ENCODE,
                  "inputs": {"control_image": [depth, 0], "vae": vae,
                             "latent": latent,
                             "resize": "match_latent_size",
                             "upscale_method": "lanczos", "crop": "center",
                             # rgb/none/invert=false: карта отдаётся кодировщику
                             # ровно такой, какой её нарисовал препроцессор.
                             # Любая правка здесь меняет смысл «ближе — светлее»
                             # и переворачивает сцену задом наперёд.
                             "channel_mode": "rgb", "normalize": "none",
                             "invert": False,
                             "batch_mode": "independent_images"}}
    graph[lora] = {"class_type": LORA_LOADER,
                   "inputs": {"model": tail, "lora_name": CONTROL_LORA[kind],
                              "strength": strength}}
    graph[ap] = {"class_type": APPLY,
                 "inputs": {"model": [lora, 0], "control_latent": [enc, 0]}}
    # Контроль встаёт В ХВОСТ цепочки модели, поверх всех лор: он не спорит с
    # ними за слот и переживает любую длину стека.
    graph[sampler]["inputs"]["model"] = [ap, 0]
    require_control(graph, kind, strength)
    return graph


def add_depth_probe(graph, prefix="depth_out"):
    """Карта глубины ТОГО, ЧТО НАРИСОВАЛОСЬ, — прямо в графе.

    Считать её потом отдельным прогоном значит залить сорок готовых кадров
    обратно на общую машину и оставить их в input/. Здесь она снимается с
    выхода VAEDecode тем же препроцессором и теми же весами, что и опора, —
    иначе сравнивались бы две разные функции, а не две композиции.
    """
    dec = _one(graph, ("VAEDecode", "VAEDecodeTiled"), "VAEDecode")
    d, s = _free_ids(graph, 2)
    graph[d] = {"class_type": DEPTH_PREPROCESSOR,
                "inputs": {"image": [dec, 0], "ckpt_name": DEPTH_CKPT,
                           "resolution": DEPTH_RESOLUTION}}
    graph[s] = {"class_type": "SaveImage",
                "inputs": {"images": [d, 0],
                           "filename_prefix": f"persona-forge/{prefix}"}}
    return graph


def add_control_probe(graph, prefix="depth_ref"):
    """Забрать то, ЧТО УВИДЕЛА МОДЕЛЬ, — второй выход кодировщика.

    Сравнивать результат с исходным снимком-опорой нечестно: до модели опора
    доходит после препроцессора, ресайза до размера латента и центрального
    кропа. encoded_control_image — это она же после всех этих правок.
    """
    st = control_state(graph)
    if st["state"] == ABSENT:
        raise SystemExit(f"контроля в графе нет, снимать нечего: {st['why']}")
    s = _free_ids(graph, 1)[0]
    graph[s] = {"class_type": "SaveImage",
                "inputs": {"images": [st["nodes"]["encode"], 1],
                           "filename_prefix": f"persona-forge/{prefix}"}}
    return graph


# ------------------------------------------------------------------ замер

def figure_mask(depth):
    """Маска ближнего плана карты глубины — порогом Оцу. (маска, порог|None).

    НЕ ФИКСИРОВАННАЯ ЯРКОСТЬ, И ЭТО ВЫЯСНИЛОСЬ НА ЖИВОМ ЗАМЕРЕ. DepthAnything
    растягивает каждую карту на весь диапазон отдельно, поэтому одна вытянутая
    к камере рука забирает себе верх шкалы, а вся фигура съезжает в середину.
    С фиксированным порогом ближняя площадь такого кадра выходила ВО МНОГО РАЗ
    меньше опорной при том, что фигуры на обеих картах одного размера, — то
    есть метрика отвечала «контроль промахнулся» там, где он попал. Оцу ищет
    естественную границу «ближе/дальше» внутри самой карты и такую нормировку
    переживает; проверка на этом случае — в tests/test_control.py.

    НЕ ПЕРЦЕНТИЛЬ. Перцентиль вырезает одинаковую площадь по построению, и
    масштаб фигуры после него всегда равен единице — показатель, который не
    может показать промах.

    Вырожденный раздел (карта почти одноцветна, маска пуста или во весь кадр) —
    это НЕ ноль совпадения, а «мерить нечем»: возвращается (None, None).
    """
    import cv2
    if float(depth.std()) < 1.0:
        return None, None
    thr, _ = cv2.threshold(depth, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = depth > thr
    frac = float(mask.mean())
    if frac <= 0.0 or frac >= 1.0:
        return None, None
    return mask, float(thr)


def depth_agreement(ref_path, out_path, grid=128):
    """Насколько композиция кадра совпала с композицией опоры. Только числа.

    Обе карты приводятся к одной мелкой сетке и сравниваются четырьмя числами,
    потому что каждое по отдельности врёт:

      corr  — корреляция глубины пиксель к пикселю; общая планировка сцены;
      iou   — пересечение масок ближнего плана: попал ли силуэт туда же;
      shift — сдвиг центра тяжести маски в долях кадра: где стоит фигура;
      scale — корень из отношения площадей: насколько она крупнее опорной.

    Формы карт обязаны совпасть: сравнить портрет 4:5 с кадром 2:3 через ресайз
    можно, число получится, и оно будет ни о чём.
    """
    import numpy as np, cv2
    a = imread(ref_path, cv2.IMREAD_GRAYSCALE)
    b = imread(out_path, cv2.IMREAD_GRAYSCALE)
    for p, img in ((ref_path, a), (out_path, b)):
        if img is None:
            raise SystemExit(f"не прочиталось как изображение: {p}")
    ar, br = a.shape[0] / a.shape[1], b.shape[0] / b.shape[1]
    if abs(ar - br) / ar > 0.02:
        raise SystemExit(
            f"карты разной формы: опора {a.shape[1]}x{a.shape[0]}, "
            f"кадр {b.shape[1]}x{b.shape[0]} — сравнивать их бессмысленно")

    h = max(2, int(round(grid * ar)))
    a = cv2.resize(a, (grid, h), interpolation=cv2.INTER_AREA)
    b = cv2.resize(b, (grid, h), interpolation=cv2.INTER_AREA)
    res = {"grid": [grid, h], "otsu_ref": None, "otsu_out": None,
           "corr": None, "iou": None, "scale": None, "shift": None,
           "dx": None, "dy": None, "area_ref": None, "area_out": None,
           "why": ""}
    fa, fb = a.astype("float64"), b.astype("float64")
    if fa.std() > 0 and fb.std() > 0:
        res["corr"] = float(np.corrcoef(fa.ravel(), fb.ravel())[0, 1])
    else:
        res["why"] = "одна из карт одноцветна — корреляции нет"

    (ma, ta), (mb, tb) = figure_mask(a), figure_mask(b)
    res["otsu_ref"], res["otsu_out"] = ta, tb
    if ma is None or mb is None:
        # Три состояния и здесь: неразделимая карта — это НЕ нулевое совпадение.
        # Ноль читается как «промахнулись мимо опоры», а мерить было нечем.
        res["why"] = (res["why"] + "; " if res["why"] else "") + \
            "ближний план не отделяется от дальнего — фигура не замерена"
        return res
    res["area_ref"], res["area_out"] = float(ma.mean()), float(mb.mean())
    res["iou"] = float((ma & mb).sum() / (ma | mb).sum())
    res["scale"] = float(math.sqrt(res["area_out"] / res["area_ref"]))
    ys, xs = np.nonzero(ma)
    yo, xo = np.nonzero(mb)
    res["dx"] = float((xo.mean() - xs.mean()) / grid)
    res["dy"] = float((yo.mean() - ys.mean()) / h)
    res["shift"] = float(math.hypot(res["dx"], res["dy"]))
    return res


def _fmt(res):
    def n(k, d=3):
        v = res.get(k)
        return "—" if v is None else f"{v:.{d}f}"
    return (f"corr {n('corr')}  iou {n('iou')}  shift {n('shift')}  "
            f"scale {n('scale')}  (dx {n('dx')}, dy {n('dy')}, "
            f"площадь опоры {n('area_ref')} → кадра {n('area_out')})"
            + (f"\n      {res['why']}" if res.get("why") else ""))


def _pick(files, tag):
    hit = [f for f in files if os.path.basename(f).startswith(tag)]
    if not hit:
        raise SystemExit(f"сервер не вернул файл {tag}: "
                         f"{[os.path.basename(f) for f in files]}")
    return sorted(hit)[0]


def save_names(graph):
    """Имена, под которыми кадры графа лягут на диск.

    comfy_client.ephemeral подменяет SaveImage на PreviewImage и запоминает
    basename префикса; fetch() кладёт файл в папку прогона под этим именем.
    Значит два графа, у которых имена совпали, пишут в ОДИН файл.
    """
    return {os.path.basename(n["inputs"].get("filename_prefix") or "")
            for n in graph.values()
            if isinstance(n, dict) and n.get("class_type") in cc.SAVE_CLASSES}


def build_pair(prompt, seed, size, ref, strength, scene="indoor", uploader=None):
    """Два графа одного замера: с контролем и без. Всё прочее — общее.

    ИМЕНА ФАЙЛОВ РАЗВЕДЕНЫ И ПО ВЕТКЕ, И ПО СИДУ, И ЭТО ПРОВЕРЯЕТСЯ ЗДЕСЬ ЖЕ.
    Первая редакция давала обеим веткам пробу «depthout»; оба прогона
    забирались в одну папку, второй файл ложился поверх первого, и обе строки
    отчёта считались по одной и той же карте. Отчёт при этом выглядел
    совершенно правдоподобно — две одинаковые строки читаются как «контроль
    ничего не меняет», то есть замер отвечал ровно наоборот и не падал.
    """
    # generate импортируется здесь, а не сверху: он владелец шаблона и стека
    # лор, и когда конвейер начнёт звать контроль из generate, модульный импорт
    # в обе стороны превратится в круговой на ровном месте.
    import generate as G

    on = G.build_graph(prompt, seed, size, f"persona-forge/frame_on_{seed}",
                       scene)
    attach_control(on, {"image": ref, "strength": strength, "kind": "depth"},
                   uploader=uploader)
    add_control_probe(on, f"depth_ref_{seed}")
    add_depth_probe(on, f"depth_on_{seed}")

    off = G.build_graph(prompt, seed, size, f"persona-forge/frame_off_{seed}",
                        scene)
    add_depth_probe(off, f"depth_off_{seed}")
    # Контрольная проверка самой проверки: ветка «без контроля» обязана
    # читаться как ABSENT. Иначе разница двух строк отчёта означала бы шум
    # сида, а не работу контроля.
    if control_state(off)["state"] != ABSENT:
        raise SystemExit("ветка без контроля собралась с контролем")
    clash = save_names(on) & save_names(off)
    if clash:
        raise SystemExit(f"ветки замера пишут в одни файлы: {sorted(clash)} — "
                         f"второй прогон затрёт первый, и обе строки отчёта "
                         f"посчитаются по одной карте")
    return on, off


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def measure(project_dir, ref, cell_id=None, strength=None, seeds=None,
            out_md=None, dry=False, shotlist="shotlist.json"):
    """Живой замер: один промпт, несколько сидов, каждый — с контролем и без.

    СИДОВ НЕСКОЛЬКО, И ЭТО НЕ ПЕДАНТИЗМ. На одном сиде разница двух строк
    объясняется сидом ничуть не хуже, чем контролем: замер по одной паре уже
    дал случай, где с контролем пересечение силуэтов ВЫШЕ, и случай, где ниже.
    Вывод делается по среднему, а строки по сидам остаются в отчёте — по ним
    видно разброс, а не только удобное число.

    Оба прогона сами считают карту глубины своего кадра, контрольный ещё и
    отдаёт то, что увидела модель. Ничего, кроме одной залитой опоры, на общей
    машине не остаётся.
    """
    import random
    from prompts import build_cell, load_project

    char, shots = load_project(project_dir, shotlist)
    project = project_name(project_dir, shots, char)
    cells = shots["cells"]
    cell = next((c for c in cells if c["id"] == cell_id), None) if cell_id \
        else cells[0]
    if cell is None:
        raise SystemExit(f"ячейки {cell_id} нет; есть: {[c['id'] for c in cells]}")
    size = cell.get("size") or shots.get("size") or \
        manifest()["output"]["profile_size"]
    strength = float(_cfg("strength", 1.0) if strength is None else strength)
    seeds = [int(s) for s in seeds] if seeds else \
        [random.randint(1, 2 ** 31 - 1) for _ in range(3)]
    prompt = build_cell(char, cell)
    scene = cell.get("scene_class", "indoor")
    out_md = out_md or os.path.join(ROOT, "docs", project, "control.md")

    print(f"замер контроля · проект {project} · ячейка {cell['id']} "
          f"({cell['label']}) · {size[0]}x{size[1]} · сила {strength} · "
          f"сиды {seeds} ({2 * len(seeds)} рендеров)\n"
          f"опора: {ref}\nотчёт: {out_md}")
    if dry:
        print("сухой прогон: на сервер ничего не отправлено")
        return None
    if not os.path.exists(ref):
        raise SystemExit(f"опоры нет на диске: {ref}")
    if not cc.preflight():
        raise SystemExit("воркер не отвечает — замер не начат")

    out_dir = work_dir(project, "control")
    runs = []
    try:
        for seed in seeds:
            on, off = build_pair(prompt, seed, size, ref, strength, scene)
            files_on = cc.run_graph(on, out_dir, timeout=1800)
            files_off = cc.run_graph(off, out_dir, timeout=1800)
            ref_depth = _pick(files_on, f"depth_ref_{seed}")
            run = {"seed": seed, "ref_depth": ref_depth,
                   "frame_on": _pick(files_on, f"frame_on_{seed}"),
                   "frame_off": _pick(files_off, f"frame_off_{seed}"),
                   "on": depth_agreement(ref_depth,
                                         _pick(files_on, f"depth_on_{seed}")),
                   "off": depth_agreement(ref_depth,
                                          _pick(files_off, f"depth_off_{seed}"))}
            runs.append(run)
            print(f"\nсид {seed} · опора после препроцессора: {ref_depth}")
            for key, title in (("on", "с контролем"), ("off", "без контроля")):
                print(f"  {title:13} {_fmt(run[key])}\n"
                      f"      кадр: {run['frame_' + key]}")
    finally:
        # В finally, а не после цикла: падение на третьем сиде из трёх оставляло
        # бы сданный кадр заказчика лежать в input/ чужой машины, и именно в
        # этом случае убрать его руками забывают наверняка.
        for name in scrub_uploads():
            print(f"опора на сервере затёрта заглушкой: {name}")

    avg = {k: {m: _mean([r[k][m] for r in runs])
               for m in ("corr", "iou", "shift", "scale", "area_out")}
           for k in ("on", "off")}
    first = runs[0]["on"]
    lines = [
        f"# Управление кадром — {project}",
        "",
        "Файл пишет `scripts/control.py measure`. Руками не править: числа",
        "принадлежат прогону, а не тексту.",
        "",
        f"- опора: `{ref}`",
        f"- ячейка: `{cell['id']}` — {cell['label']}",
        f"- кадр: {size[0]}x{size[1]}, сила контроля `{strength}`",
        f"- сиды: {', '.join('`%d`' % s for s in seeds)}",
        f"- сетка сравнения: {first['grid'][0]}x{first['grid'][1]}, маска "
        f"ближнего плана — порог Оцу (у опоры {first['otsu_ref']})",
        "",
        "| сид | прогон | corr | iou | сдвиг центра | масштаб фигуры |",
        "|---|---|---|---|---|---|",
    ]

    def cell_of(r, k):
        return "—" if r.get(k) is None else f"{r[k]:.3f}"

    for run in runs:
        for key, title in (("on", "с контролем"), ("off", "без контроля")):
            r = run[key]
            lines.append(f"| {run['seed']} | {title} | {cell_of(r, 'corr')} | "
                         f"{cell_of(r, 'iou')} | {cell_of(r, 'shift')} | "
                         f"{cell_of(r, 'scale')} |")
    for key, title in (("on", "с контролем"), ("off", "без контроля")):
        r = avg[key]
        lines.append(f"| **среднее** | **{title}** | {cell_of(r, 'corr')} | "
                     f"{cell_of(r, 'iou')} | {cell_of(r, 'shift')} | "
                     f"{cell_of(r, 'scale')} |")
    lines += [
        "",
        "Площадь ближней маски у опоры: "
        + ("—" if first["area_ref"] is None else f"{first['area_ref']:.3f}") + ".",
        "",
        "Что означают колонки — см. докстринг `depth_agreement`. Коротко:",
        "corr — совпадение планировки сцены, iou — пересечение силуэтов",
        "ближнего плана, сдвиг — смещение центра фигуры в долях кадра,",
        "масштаб — во сколько раз фигура крупнее опорной (1.0 = точно как на",
        "опоре).",
        "",
        "Опору и ячейку берут из РАЗНЫХ сцен намеренно. Если промпт ячейки сам",
        "по себе даёт композицию опоры, обе строки окажутся близки и замер не",
        "покажет ничего: разница двух строк тогда объясняется промптом, а не",
        "контролем.",
        "",
    ]
    if avg["on"]["iou"] is not None and avg["off"]["iou"] is not None:
        lines.append(f"Среднее «с контролем» минус «без»: corr "
                     f"{avg['on']['corr'] - avg['off']['corr']:+.3f}, iou "
                     f"{avg['on']['iou'] - avg['off']['iou']:+.3f}, масштаб "
                     f"{avg['on']['scale'] - avg['off']['scale']:+.3f} "
                     f"(ближе к 1.0 — ближе к опоре).")
    else:
        lines.append("Часть чисел не замерена — см. поле why в выводе скрипта.")
    os.makedirs(os.path.dirname(os.path.abspath(out_md)), exist_ok=True)
    with open(out_md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\nсреднее по {len(seeds)} сидам:")
    for key, title in (("on", "с контролем"), ("off", "без контроля")):
        print(f"  {title:13} {_fmt(avg[key])}")
    print(f"отчёт: {out_md}")
    return {"runs": runs, "avg": avg, "seeds": seeds, "report": out_md}


def probe():
    """Схемы нод контроля с ЖИВОГО воркера. Read-only, в очередь не встаёт.

    Нужна ровно затем, чтобы схему не сочиняли по памяти: пак ставится с
    неизвестного апстрима (docs/environment.md: URL не записан), и набор входов
    у него — вопрос к машине, а не к документации.
    """
    ok = True
    for cls in (LORA_LOADER, ENCODE, APPLY, DEPTH_PREPROCESSOR):
        try:
            info = cc.object_info(cls)[cls]
        except Exception as e:
            print(f"{cls}: НЕ НАЙДЕН ({e})", file=sys.stderr)
            ok = False
            continue
        req = info["input"].get("required", {})
        opt = info["input"].get("optional", {})
        print(f"{cls}")
        for tag, d in (("вход", req), ("необяз.", opt)):
            for k, v in d.items():
                t = v[0] if isinstance(v[0], str) else "выбор"
                print(f"   {tag:8} {k:16} {t}")
        print(f"   выход   {list(zip(info['output'], info['output_name']))}")
    if not ok:
        raise SystemExit("пак Krea 2 ControlNet на воркере неполон")
    lst = cc.object_info(LORA_LOADER)[LORA_LOADER]["input"]["required"]["lora_name"][0]
    for kind, name in CONTROL_LORA.items():
        print(f"лора {kind}: {name} — "
              f"{'есть на воркере' if name in lst else 'НЕТ В СПИСКЕ'}")


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    if args[0] == "probe":
        probe()
        return
    if args[0] == "scrub":
        # Ручная уборка: если замер убили по Ctrl+C, finally не отработал.
        # Берётся ВЕСЬ реестр заливок comfy_client, а не только опоры этого
        # процесса, — иначе после падения затирать было бы нечего. Значит и
        # чужие входные картинки этого репозитория тоже; звать при живом батче
        # нельзя.
        from _util import read_json
        refs = read_json(cc.UPLOAD_LEDGER) if os.path.exists(cc.UPLOAD_LEDGER) \
            else []
        print(f"затираю всё, что репозиторий заливал на сервер ({len(refs)}):")
        for ref in refs:
            _UPLOADED[ref] = ref
        print("\n".join(scrub_uploads()) or "нечего затирать")
        return
    if args[0] != "measure":
        print(__doc__)
        raise SystemExit(1)
    if len(args) < 2 or args[1].startswith("--"):
        raise SystemExit("нужен путь к папке проекта: measure <project_dir> --ref …")
    ref = cli_opt(args, "--ref")
    if not ref:
        raise SystemExit("нужен снимок-опора: --ref <файл>")
    st = cli_opt(args, "--strength")
    seeds = cli_opt(args, "--seeds")
    measure(args[1], ref, cli_opt(args, "--cell"),
            float(st) if st else None,
            [int(s) for s in seeds.split(",")] if seeds else None,
            cli_opt(args, "--out"), dry="--dry" in args,
            shotlist=cli_opt(args, "--shotlist", "shotlist.json"))


if __name__ == "__main__":
    main()
