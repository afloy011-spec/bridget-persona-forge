#!/usr/bin/env python3
"""Обучение персонажной LoRA в Ostris AI Toolkit по HTTP.

  py -3 lora_train.py gpu                      # чем занята карта
  py -3 lora_train.py archs                    # какие архитектуры тулкит умеет
  py -3 lora_train.py jobs                     # что уже заведено
  py -3 lora_train.py create <project_dir> --dataset <путь НА СЕРВЕРЕ>
        [--arch zimage] [--name ...] [--steps N] [--rank N] [--gpu 0]
        [--local <папка датасета>] [--trigger <слово>] [--dry] [--send]
  py -3 lora_train.py start  <имя|id> [--send]
  py -3 lora_train.py watch  <имя|id> [--every 30] [--for 0]
  py -3 lora_train.py stop   <имя|id> [--send]
  py -3 lora_train.py result <имя|id>

Как модуль:
  from lora_train import job_config, supported_archs, api, job_of

АДРЕСА ТУЛКИТА В ОТСЛЕЖИВАЕМОМ МАНИФЕСТЕ НЕТ — по той же причине, по которой
там нет адреса ComfyUI (см. comfy_client._default_host): репозиторий задуман
публичным, а адрес личной машины — не его дело. AITK_HOST в окружении или
{"aitk_host": "http://…:<порт>"} в assets.local.json.

ПО УМОЛЧАНИЮ ЭТОТ СКРИПТ НЕ ПИШЕТ НА СЕРВЕР НИЧЕГО. Всё, что меняет чужую
машину — завести задание, запустить, остановить, — требует явного --send;
без него печатается ровно тот запрос, который был бы отправлен. Причина та же,
что у политики эфемерности в comfy_client: машина общая, а обучение занимает
её карту на часы. --dry — это умолчание, ключ понимается ради явности в
скриптах.

ЧТО ТУЛКИТ УМЕЕТ, СПРАШИВАЕТСЯ У НЕГО, А НЕ ПОМНИТСЯ. Список архитектур
обучения не отдаёт ни один /api/*: он вшит в бандл его же веб-морды. Команда
archs скачивает страницу /jobs/new, забирает её чанки и достаёт список оттуда.
Способ хрупкий, поэтому у него ТРИ СОСТОЯНИЯ: список получен, список не
получен (тогда так и говорится и создание задания отказывается идти вслепую),
и «список получен, вашей архитектуры в нём нет» — это отказ с перечислением
того, что есть. Догадка «наверное, поддерживается» здесь стоит двух часов GPU
и чужого времени.

ОТКУДА БЕРУТСЯ ЧИСЛА ОБУЧЕНИЯ. Из формы самого тулкита: TRAIN_DEFAULTS ниже
дословно повторяет её умолчания, а не подобран здесь. Строковые умолчания
конкретной архитектуры (какие веса тянуть, какой adapter) достаются из того же
бандла и печатаются с пометкой, откуда взялись. Своих чисел этот файл не
выдумывает — выдуманный гиперпараметр неотличим от обоснованного, пока не
кончится обучение.

ЗАБРАТЬ ВЕСА ЭТИМ API НЕЛЬЗЯ, и команда result это доказывает, а не
утверждает: /api/img/<путь> — единственная отдача файлов, и она отвечает 403
на всё, что не картинка. Листинга каталога в API нет вовсе. result печатает
серверные пути и код ответа на пробу, чтобы решение «тащить по SSH» опиралось
на замер.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (setup_console, manifest, read_json, project_name, cli_opt,
                   ROOT)
from prompts import load_project
import lora_dataset

# Умолчания обучения — дословно с формы /jobs/new живого тулкита (снято с её
# бандла). Здесь они лежат затем, чтобы задание собиралось без сети и чтобы
# любое отличие от умолчаний тулкита было видно как правка ЭТОГО словаря, а не
# как молчаливое расхождение с веб-мордой.
TRAIN_DEFAULTS = {
    "network": {"type": "lora", "linear": 32, "linear_alpha": 32,
                "conv": 16, "conv_alpha": 16, "lokr_full_rank": True,
                "lokr_factor": -1, "network_kwargs": {"ignore_if_contains": []}},
    "save": {"dtype": "bf16", "save_every": 250, "max_step_saves_to_keep": 4,
             "save_format": "diffusers", "push_to_hub": False},
    "dataset": {"mask_path": None, "mask_min_value": 0.1, "default_caption": "",
                # ДРОПАУТ ПОДПИСЕЙ ДЛЯ ПЕРСОНАЖНОЙ ЛОРЫ — ВРЕД, А НЕ
                # РЕГУЛЯРИЗАЦИЯ. Он выбрасывает подпись ЦЕЛИКОМ, вместе с
                # триггером, и учит модель связке «пустой промпт → её лицо».
                # У стилевой лоры это желаемое поведение, у персонажной —
                # прямо обратное: лицо обязано приходить на слово и не
                # приходить без него. Умолчание тулкита 0.05 писалось под
                # стили.
                "caption_ext": "txt", "caption_dropout_rate": 0.0,
                "cache_latents_to_disk": False, "is_reg": False,
                "network_weight": 1, "resolution": [512, 768, 1024],
                "controls": [], "shrink_video_to_frames": True,
                "num_frames": 1, "flip_x": False, "flip_y": False,
                "num_repeats": 1},
    "train": {"batch_size": 1, "bypass_guidance_embedding": True, "steps": 3000,
              "gradient_accumulation": 1, "train_unet": True,
              "train_text_encoder": False, "gradient_checkpointing": True,
              "noise_scheduler": "flowmatch", "optimizer": "adamw8bit",
              "timestep_type": "sigmoid", "content_or_style": "balanced",
              "optimizer_params": {"weight_decay": 0.0001},
              "unload_text_encoder": False, "cache_text_embeddings": False,
              "lr": 0.0001, "ema_config": {"use_ema": False, "ema_decay": 0.99},
              "skip_first_sample": True, "force_first_sample": False,
              # ПРОБНЫЕ СЭМПЛЫ ВЫКЛЮЧЕНЫ, И ЭТО НЕ ЭКОНОМИЯ. На арке krea2
              # тулкит падает ДО первого шага обучения, на генерации базовых
              # сэмплов: extensions_built_in/diffusion_models/krea2/src/
              # text_encoder.py делает PROMPT_TEMPLATE_ENCODE_PREFIX + prompt,
              # а prompt приезжает булевым — gen_config.negative_prompt у
              # сэмпла без явного негатива оказывается False. Обучение при
              # этом полностью исправно: падает только показ.
              #
              # Отказ от сэмплов ничего не отнимает у контроля: чекпоинты всё
              # равно проверяются ЗАМЕРОМ через ComfyUI (косинус к базе плюс
              # детекторы рисованности), а не глазами по картинке в морде
              # тулкита. Смотреть на сэмпл и решать «вроде похоже» — ровно тот
              # способ принятия решений, от которого этот проект уходит.
              "disable_sampling": True, "dtype": "bf16",
              "diff_output_preservation": False,
              "diff_output_preservation_multiplier": 1,
              "diff_output_preservation_class": "person",
              "switch_boundary_every": 1, "loss_type": "mse"},
    "model": {"quantize": True, "qtype": "qfloat8", "quantize_te": True,
              "qtype_te": "qfloat8", "low_vram": False, "model_kwargs": {}},
    "sample": {"sampler": "flowmatch", "sample_every": 250},
}

# Статусы задания в тулките — из его же морды. Перечислены здесь потому, что
# watch обязан отличать «кончилось» от «незнакомое слово»: незнакомый статус,
# принятый за рабочий, крутит опрос вечно, а принятый за конечный — молча
# сообщает, что обучение закончилось, когда оно идёт.
LIVE = ("running", "queued")
DONE = ("completed", "stopped", "error")


def host():
    """Адрес тулкита: AITK_HOST → assets.local.json → внятная ошибка."""
    env = os.environ.get("AITK_HOST")
    if env:
        return env.rstrip("/")
    local = os.path.join(ROOT, "assets.local.json")
    if os.path.exists(local):
        try:
            h = read_json(local).get("aitk_host")
        except Exception as e:
            print(f"assets.local.json не разобран ({e})", file=sys.stderr)
            h = None
        if h:
            return h.rstrip("/")
    raise SystemExit(
        "адрес AI Toolkit не задан. Любое из двух:\n"
        "  set AITK_HOST=http://<хост>:<порт>\n"
        '  добавьте {"aitk_host": "http://<хост>:<порт>"} в assets.local.json')


def start_queue(gpu_ids="0"):
    """Включить очередь КАРТЫ. Возвращает (код, тело), как `api`.

    ДВА РУБИЛЬНИКА, А НЕ ОДИН, И ВТОРОЙ МОЛЧИТ. У тулкита есть отдельная
    сущность «очередь карты» (таблица Queue: gpu_ids, is_running), и воркер
    (ui/dist/cron/actions/processQueue.js) обходит именно ЕЁ, а не список
    заданий: для каждой очереди с is_running берёт первое задание со статусом
    queued и тем же gpu_ids. Пока очередь выключена, задание висит в queued
    вечно — без ошибки, без строки в логе, без единого признака. Ровно это и
    случилось: задание простояло больше получаса при полностью свободной
    карте, и ни рестарт тулкита, ни выгрузка моделей ComfyUI ничего не дали,
    потому что чинили не то.

    ПОРЯДОК ОБРАТНЫЙ ТОМУ, КОТОРЫЙ КАЖЕТСЯ ВЕРНЫМ: сначала задание, потом
    очередь. Здесь стояло наоборот, и это не работало — воркер ГАСИТ очередь,
    в которой нет ни одного queued-задания, и успевал сделать это между двумя
    вызовами. Замер: после `start --send` задание висело в queued, а
    /api/queue отдавал is_running: false у обеих карт; тот же GET, повторённый
    вручную секундой позже — уже при стоящем в очереди задании, — поднял её, и
    обучение пошло немедленно.

    ОТВЕТ РОУТА ВСЕГДА ГОВОРИТ is_running: false, и это не отказ. Обработчик
    (ui/src/app/api/queue/[queueID]/start/route.ts) читает строку, потом
    обновляет её, а возвращает ПРОЧИТАННОЕ — то есть состояние ДО включения.
    Судить об успехе по этому ответу нельзя, надо спрашивать /api/queue.

    В МАРШРУТЕ СТОИТ НОМЕР КАРТЫ, А НЕ ID СТРОКИ ОЧЕРЕДИ. Проверено дорого:
    `/api/queue/1/start` при единственной очереди с id = 1 и gpu_ids = "0"
    завёл ВТОРУЮ очередь для несуществующей карты 1. Смотреть надо на
    gpu_ids задания, а не на id, который вернул /api/queue.
    """
    return api(f"/api/queue/{gpu_ids}/start")


def free_comfy():
    """Попросить ComfyUI выгрузить модели перед обучением. Тихо и необязательно.

    ЗАЧЕМ. Обучение и генерация живут на одной машине, и делят они не только
    карту, но и ХОСТОВУЮ память. Замер: ComfyUI после дня работы держал 45 ГБ
    закоммиченной памяти, свободного коммита оставалось 4.4 ГБ из 106, и
    задание падало на загрузке весов трансформера с «файл подкачки слишком мал
    для завершения операции (os error 1455)» — сообщение, по которому виновника
    не угадать, потому что ни ComfyUI, ни тулкит в нём не упомянуты. Выгрузка
    подняла свободный коммит до 36 ГБ.

    ОЧЕРЕДЬ ПРОВЕРЯЕТСЯ ПЕРЕД ВЫГРУЗКОЙ. Машина общая: выбить модели из-под
    чужого идущего прогона — это испортить чужую работу ради своей. Если
    очередь занята, шаг пропускается и говорит об этом вслух.

    Отказ здесь никогда не роняет запуск: ComfyUI может быть выключен, на
    другом хосте или незнаком с /free, а обучение к нему отношения не имеет.
    """
    try:
        import comfy_client as cc
        host = cc._default_host() if hasattr(cc, "_default_host") else None
        host = (host or os.environ.get("COMFY_HOST") or "").rstrip("/")
        if not host:
            return None
        with urllib.request.urlopen(host + "/queue", timeout=10) as r:
            q = json.loads(r.read().decode("utf-8", "replace"))
        busy = len(q.get("queue_running") or []) + len(q.get("queue_pending") or [])
        if busy:
            print(f"ComfyUI занят ({busy} задач) — модели не выгружаю, "
                  f"обучению может не хватить хостовой памяти")
            return False
        req = urllib.request.Request(
            host + "/free",
            data=json.dumps({"unload_models": True,
                             "free_memory": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=60).read()
        print("ComfyUI: модели выгружены (освобождает хостовую память под "
              "загрузку весов обучения)")
        return True
    except Exception as e:
        print(f"ComfyUI не отозвался на выгрузку ({type(e).__name__}) — "
              f"это не помеха запуску")
        return None


def api(path, data=None, method=None, timeout=60, raw=False):
    """Запрос к тулкиту. Возвращает (код, тело). НЕ бросает на 4xx/5xx.

    Код возвращается наружу нарочно: половина разведки этого API — про то,
    ЧЕМ именно он отвечает на неправильный запрос (403 против 404 на отдаче
    файлов, 409 на занятое имя задания). Исключение вместо кода превращает
    замер в трейсбек.
    """
    url = host() + path
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload, code = r.read(), r.status
    except urllib.error.HTTPError as e:
        payload, code = e.read(), e.code
    except urllib.error.URLError as e:
        raise SystemExit(f"AI Toolkit не отвечает на {url}: {e.reason}")
    if raw:
        return code, payload
    try:
        return code, json.loads(payload)
    except Exception:
        return code, payload.decode("utf-8", "replace")


# ------------------------------------------------------------ разведка


def settings():
    return api("/api/settings")[1]


def jobs():
    code, data = api("/api/jobs")
    return (data or {}).get("jobs", []) if isinstance(data, dict) else []


def job_of(ident):
    """Задание по id или по имени. (задание|None, причина|None).

    По имени тоже, потому что id тулкит выдаёт при создании и человек его не
    помнит, а имя задаём мы сами и оно уникально — тулкит отвечает 409 на
    повтор. Промах по обоим ключам — это причина, а не None: «задания нет» и
    «задание есть, но опечатка в id» чинятся по-разному.
    """
    code, data = api("/api/jobs?id=" + urllib.parse.quote(str(ident)))
    if isinstance(data, dict) and data.get("id"):
        return data, None
    for j in jobs():
        if j.get("name") == ident:
            return j, None
    return None, (f"задания {ident!r} нет: ни по id, ни по имени среди "
                  f"{[j.get('name') for j in jobs()] or '—'}")


_ARCH_BLOCK = re.compile(r'\{name:"([a-z0-9_:.]+)",label:"([^"]*)",'
                         r'group:"([a-z]+)"')
_ARCH_STR_DEFAULT = re.compile(
    r'"config\.process\[0\]\.model\.([a-z_0-9]+)":\["([^"]*)"')


def _ui_bundle():
    """Текст всех js-чанков страницы /jobs/new. (текст, причина отказа|None).

    Морда — next.js, имена чанков содержат хеш сборки и меняются с каждым
    обновлением тулкита, поэтому они читаются со страницы, а не помнятся.
    """
    code, page = api("/jobs/new", raw=True)
    if code != 200:
        return "", f"GET /jobs/new вернул {code}"
    page = page.decode("utf-8", "replace")
    names = sorted(set(re.findall(r"static/chunks/[A-Za-z0-9/_.-]+\.js", page)))
    if not names:
        return "", "на странице /jobs/new не нашлось ни одного чанка"
    out = []
    for n in names:
        c, body = api("/_next/" + n, timeout=60, raw=True)
        if c == 200:
            out.append(body.decode("utf-8", "replace"))
    if not out:
        return "", f"ни один из {len(names)} чанков не скачался"
    return "\n".join(out), None


def supported_archs():
    """Архитектуры обучения тулкита: (список|None, причина|None).

    Список — [{name, label, group, name_or_path, …строковые умолчания модели}].
    None — это НЕ «пусто», а «не выяснено»: см. три состояния в докстринге.
    """
    text, why = _ui_bundle()
    if why:
        return None, why
    found, order = {}, []
    for m in _ARCH_BLOCK.finditer(text):
        name, label, group = m.groups()
        if name in found:
            continue
        # Блок архитектуры кончается там, где начинается следующий; его
        # строковые умолчания и есть то, что нельзя угадать: репозиторий весов
        # и путь к обучающему адаптеру.
        nxt = _ARCH_BLOCK.search(text, m.end())
        block = text[m.end():nxt.start() if nxt else m.end() + 4000]
        rec = {"name": name, "label": label, "group": group}
        rec.update(dict(_ARCH_STR_DEFAULT.findall(block)))
        found[name] = rec
        order.append(name)
    if not found:
        return None, ("в бандле /jobs/new не нашлось ни одного описания "
                      "архитектуры — морда тулкита изменилась, разбор устарел")
    return [found[n] for n in sorted(order)], None


# ------------------------------------------------------------ сборка задания


def _slug(raw):
    """Имя задания в латинице: тулкит кладёт его в ПУТЬ выходной папки.

    Кириллица в имени персонажа доехала бы до D:\\ai-toolkit\\output\\<имя> на
    чужой машине, и разбирать её кодировку пришлось бы уже там. Ровно этот
    дефект раунд 4 чинил в именах сдачи.
    """
    return re.sub(r"[^a-z0-9]+", "_", str(raw).lower()).strip("_")


def local_dataset(path):
    """Что лежит в локальной папке датасета. (данные|None, причина|None).

    Читается dataset.json, который пишет lora_dataset.py: он единственный
    знает, каким СЛОВОМ подписаны кадры. Триггер задания и триггер подписей —
    это одно и то же слово, и разойтись им нельзя молча: обучение пройдёт, лора
    ляжет на диск, а в кадре не появится ничего.
    """
    if not path:
        return None, "локальная папка датасета не задана"
    marker = os.path.join(path, "dataset.json")
    if not os.path.exists(marker):
        return None, f"нет {marker} — сверить триггер и состав не с чем"
    return read_json(marker), None


def sample_prompts(project_dir, shotlist, trigger, limit=4):
    """Промпты для контрольных генераций в ходе обучения.

    Собираются тем же caption_for, что и подписи датасета: лора отвечает на то
    слово и на тот язык описания, которым её учили, и контрольная генерация,
    написанная в другом стиле, показывает не качество обучения, а разницу
    формулировок.
    """
    _, shots = load_project(project_dir, shotlist)
    cells = shots.get("cells", [])[:limit]
    return [{"prompt": lora_dataset.caption_for(c, trigger)} for c in cells]


def job_config(project_dir, dataset, arch, trigger, name=None,
               shotlist="shotlist.json", steps=None, rank=None,
               training_folder=None, arch_defaults=None, size=None):
    """Готовый job_config для POST /api/jobs. Ничего не отправляет."""
    char, shots = load_project(project_dir, shotlist)
    project = project_name(project_dir, shots, char)
    name = name or f"{_slug(project)}_{_slug(trigger)}_v1"
    d = TRAIN_DEFAULTS
    w, h = size or manifest()["output"]["profile_size"]

    model = dict(d["model"])
    # Строковые умолчания архитектуры (веса, адаптер) — от самого тулкита.
    # Своего значения у name_or_path здесь нет намеренно: угаданный репозиторий
    # весов скачивается десятками гигабайт и падает уже в обучении.
    model.update({k: v for k, v in (arch_defaults or {}).items()
                  if k not in ("name", "label", "group")})
    model["arch"] = arch

    net = dict(d["network"])
    if rank:
        net["linear"] = net["linear_alpha"] = rank
    train = dict(d["train"])
    if steps:
        train["steps"] = steps
    ds = dict(d["dataset"])
    ds["folder_path"] = dataset

    save = dict(d["save"])
    # СКОЛЬКО ЧЕКПОЙНТОВ ХРАНИТЬ — ОТ ДЛИНЫ ПРОГОНА, А НЕ КОНСТАНТА.
    # Умолчание тулкита (4) писалось под короткие прогоны. На 3000 шагах с
    # шагом сохранения 250 это 12 срезов, из которых доживают последние
    # четыре, то есть 2250-3000, — а у персонажной лоры лучший шаг почти
    # никогда не последний: сначала приходит сходство, потом переобучение на
    # позах и фоне датасета. Чекпойнты здесь единственный способ вернуться:
    # сэмплы на арке krea2 выключены (тулкит на них падает, см. TRAIN_DEFAULTS),
    # и годность каждого среза меряется отдельно через ComfyUI. Выбрасывать
    # ранние срезы значит выбрасывать те, ради которых прогон и делался.
    save["max_step_saves_to_keep"] = max(
        save.get("max_step_saves_to_keep", 4),
        train["steps"] // max(1, save.get("save_every", 250)) + 1)

    return {
        "job": "extension",
        "config": {
            "name": name,
            "process": [{
                "type": "diffusion_trainer",
                "training_folder": training_folder or "output",
                "sqlite_db_path": "./aitk_db.db",
                "device": "cuda",
                "trigger_word": trigger,
                "performance_log_every": 10,
                "network": net,
                "save": save,
                "datasets": [ds],
                "train": train,
                "logging": {"log_every": 1, "use_ui_logger": True},
                "model": model,
                "sample": dict(d["sample"], width=w, height=h,
                               samples=sample_prompts(project_dir, shotlist,
                                                      trigger)),
            }],
        },
        "meta": {"name": "[name]", "version": "1.0"},
    }


def _dataset_state(dataset, sets):
    """Виден ли серверу каталог датасета. (состояние, пояснение).

    ТРИ СОСТОЯНИЯ. Тулкит перечисляет только то, что лежит внутри его
    DATASETS_FOLDER (/api/datasets/list), а folder_path в задании — любой путь
    на сервере. Значит «нет в списке» доказательно только для путей ВНУТРИ этой
    папки; для остальных ответ честно NOT_MEASURED, а не PASS. Молчаливый PASS
    здесь стоит дороже всего: обучение стартует, съедает карту и падает на
    первом батче.
    """
    root = (sets or {}).get("DATASETS_FOLDER")
    if not root:
        return "NOT_MEASURED", "/api/settings не отдал DATASETS_FOLDER"
    a, b = os.path.normcase(dataset).replace("/", "\\"), \
        os.path.normcase(root).replace("/", "\\").rstrip("\\")
    if not a.startswith(b + "\\"):
        return "NOT_MEASURED", (f"путь вне DATASETS_FOLDER ({root}) — "
                                f"проверить его существование этим API нечем")
    rest = a[len(b) + 1:].split("\\")[0]
    code, names = api("/api/datasets/list")
    if code != 200 or not isinstance(names, list):
        return "NOT_MEASURED", f"/api/datasets/list вернул {code}"
    return (("PASS", f"тулкит видит датасет {rest!r}") if rest in names
            else ("FAIL", f"датасета {rest!r} нет в {root}; там есть: "
                          f"{', '.join(names) or '—'}"))


def prepare(project_dir, dataset, arch=None, trigger=None, name=None,
            shotlist="shotlist.json", steps=None, rank=None, local=None,
            gpu_ids="0"):
    """Собрать задание и проверить всё, что можно проверить до отправки."""
    char, shots = load_project(project_dir, shotlist)
    project = project_name(project_dir, shots, char)
    local = local if local is not None else lora_dataset.default_out(project)
    ds_local, ds_why = local_dataset(local)

    # Триггер: подписи датасета → ключ → манифест. Подписи первыми потому, что
    # именно на них обучается лора; ключ и манифест — это намерение, а подписи
    # — факт, и при расхождении прав факт.
    trig_local = (ds_local or {}).get("trigger")
    trig_arg, trig_from = lora_dataset.resolve_trigger(trigger)
    trigger = trig_local or trig_arg
    if not trigger:
        raise SystemExit(
            "триггер неизвестен: в датасете нет dataset.json, ключ --trigger не "
            "задан\n  и assets.json → models.character_lora.trigger пуст.\n"
            f"  ({ds_why})")
    cross = ("NOT_MEASURED", ds_why) if trig_local is None else (
        ("PASS", f"подписи датасета и {trig_from or 'ключ'} говорят "
                 f"«{trigger}»") if trig_arg in (None, trig_local) else
        ("FAIL", f"подписи датасета обучены слову «{trig_local}», а "
                 f"{trig_from} говорит «{trig_arg}» — лора не включится"))
    if cross[0] == "FAIL":
        raise SystemExit(f"ТРИГГЕРЫ РАСХОДЯТСЯ: {cross[1]}")

    archs, arch_why = supported_archs()
    arch = arch or (manifest().get("training") or {}).get("arch")
    known = {a["name"]: a for a in archs} if archs else {}
    if archs is None:
        raise SystemExit(
            f"список архитектур тулкита не выяснен: {arch_why}\n"
            f"  Собирать задание вслепую нельзя: неверная arch — это часы GPU\n"
            f"  и чужая занятая карта. Проверьте морду тулкита руками.")
    if not arch:
        raise SystemExit(
            "не задана архитектура обучения (--arch).\n  Тулкит умеет:\n"
            + _arch_table(archs))
    if arch not in known:
        raise SystemExit(
            f"архитектуры {arch!r} тулкит не умеет. Умеет:\n"
            + _arch_table(archs))

    sets = settings()
    ds_state = _dataset_state(dataset, sets)
    cfg = job_config(project_dir, dataset, arch, trigger, name=name,
                     shotlist=shotlist, steps=steps, rank=rank,
                     training_folder=sets.get("TRAINING_FOLDER"),
                     arch_defaults=known[arch])
    job_name = cfg["config"]["name"]
    taken = [j for j in jobs() if j.get("name") == job_name]
    return {
        "project": project, "arch": known[arch], "trigger": trigger,
        "dataset": dataset, "dataset_state": ds_state,
        "local": local, "local_frames": (ds_local or {}).get("composition"),
        "trigger_cross_check": cross,
        "name": job_name, "name_taken": bool(taken),
        "gpu_ids": gpu_ids, "settings": sets, "job_config": cfg,
    }


def _arch_table(archs):
    by = {}
    for a in archs:
        by.setdefault(a["group"], []).append(a["name"])
    return "\n".join(f"    {g:12} {', '.join(sorted(v))}"
                     for g, v in sorted(by.items()))


# ------------------------------------------------------------------ печать


def report_prepare(res, send=False):
    a, c = res["arch"], res["job_config"]["config"]["process"][0]
    print(f"проект {res['project']} · задание {res['name']}"
          + ("  ИМЯ ЗАНЯТО — тулкит ответит 409" if res["name_taken"] else ""))
    print(f"архитектура {a['name']} ({a['label']}, {a['group']})")
    for k, v in sorted(a.items()):
        if k not in ("name", "label", "group"):
            print(f"  от тулкита: model.{k} = {v}")
    print(f"триггер «{res['trigger']}» — сверка с подписями датасета: "
          f"{res['trigger_cross_check'][0]} ({res['trigger_cross_check'][1]})")
    print(f"датасет на сервере {res['dataset']} — {res['dataset_state'][0]} "
          f"({res['dataset_state'][1]})")
    if res["local_frames"]:
        f = res["local_frames"]
        print(f"локальная копия {res['local']}: {f['n']} кадров, "
              f"ячейки {f['cells']}, худшая пара {f['worst_pair']}")
    print(f"шагов {c['train']['steps']}, ранг {c['network']['linear']}, "
          f"сохранение каждые {c['save']['save_every']}, "
          f"выход {c['training_folder']}\\{res['name']}")
    print("\n--- job_config ---")
    print(json.dumps(res["job_config"], ensure_ascii=False, indent=2))
    if not send:
        print(f"\nне отправлено (--dry по умолчанию). Отправить: --send\n"
              f"  POST {host()}/api/jobs  "
              f"{{name, gpu_ids: {res['gpu_ids']!r}, job_config}}")


def create(res, send=False):
    if res["dataset_state"][0] == "FAIL":
        raise SystemExit(f"датасет серверу не виден: {res['dataset_state'][1]}\n"
                         "  Залейте папку датасета на машину тулкита.")
    if not send:
        return None
    if res["name_taken"]:
        raise SystemExit(f"задание {res['name']} уже заведено — тулкит ответит "
                         f"409. Задайте другое имя ключом --name.")
    code, data = api("/api/jobs", {"name": res["name"],
                                   "gpu_ids": res["gpu_ids"],
                                   "job_config": res["job_config"]})
    if code >= 400:
        raise SystemExit(f"POST /api/jobs → {code}: {data}")
    print(f"заведено: id {data.get('id')} · имя {res['name']}\n"
          f"  запуск: py -3 lora_train.py start {res['name']} --send")
    return data


def _progress(job):
    """Шаг, всего шагов и статус задания. Любое поле может отсутствовать."""
    try:
        cfg = json.loads(job.get("job_config") or "{}")
        total = cfg["config"]["process"][0]["train"]["steps"]
    except Exception:
        total = None
    return job.get("status"), job.get("step"), total, job.get("info")


def watch(ident, every=30, limit=0):
    """Следить за заданием. Только чтение, ничего не меняет.

    Незнакомый статус прекращает опрос и говорит об этом: крутить опрос вечно
    на слове, которого нет ни в LIVE, ни в DONE, — это тихое зависание, а
    считать его концом — тихая ложь про законченное обучение.
    """
    t0 = time.time()
    while True:
        job, why = job_of(ident)
        if job is None:
            raise SystemExit(why)
        status, step, total, info = _progress(job)
        print(f"{time.strftime('%H:%M:%S')}  {status}  шаг "
              f"{step if step is not None else '?'}"
              f"/{total if total is not None else '?'}"
              + (f"  {info}" if info else ""))
        if status in DONE:
            return job
        if status not in LIVE:
            print(f"статус {status!r} тулкиту неизвестен (знаем "
                  f"{LIVE + DONE}) — опрос прекращён, состояние NOT_MEASURED")
            return job
        if limit and time.time() - t0 >= limit:
            print(f"истекло --for {limit} с, задание ещё {status}")
            return job
        time.sleep(every)


def result(ident):
    """Где лежит результат и чем его забрать. Печатает замер, а не мнение."""
    job, why = job_of(ident)
    if job is None:
        raise SystemExit(why)
    cfg = json.loads(job.get("job_config") or "{}")
    proc = cfg["config"]["process"][0]
    folder = proc.get("training_folder") or "output"
    name = cfg["config"]["name"]
    base = f"{folder}\\{name}"
    weights = f"{base}\\{name}.safetensors"
    status, step, total, _ = _progress(job)
    print(f"задание {name}: {status}, шаг {step}/{total}")
    print(f"папка на сервере: {base}")
    print(f"веса:             {weights}")
    print(f"контрольные кадры:{base}\\samples\\")
    code, _body = api("/api/img/" + urllib.parse.quote(weights, safe=""),
                      raw=True)
    print(f"\nпроба отдачи файла: GET /api/img/<веса> → {code}")
    print("  API тулкита отдаёт только картинки и не умеет листать каталог,\n"
          "  поэтому веса забираются с машины тулкита мимо HTTP (SSH/pscp).")
    return {"job": name, "status": status, "folder": base, "weights": weights,
            "img_probe": code}


# -------------------------------------------------------------------- CLI


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)

    def opt(k, d=None):
        return cli_opt(args, k, d)

    cmd, rest = args[0], args[1:]
    send = "--send" in args

    if cmd == "gpu":
        print(json.dumps(api("/api/gpu")[1], ensure_ascii=False, indent=2))
    elif cmd == "archs":
        archs, why = supported_archs()
        if archs is None:
            # NOT_MEASURED, а не пустой список: пустой список читается как
            # «тулкит не умеет ничего» и толкает к неверному выводу.
            raise SystemExit(f"NOT_MEASURED: {why}")
        print(_arch_table(archs))
        print(f"\nвсего {len(archs)}; строковые умолчания модели — "
              f"py -3 lora_train.py create … покажет для выбранной")
    elif cmd == "jobs":
        rows = jobs()
        if not rows:
            print("заданий нет")
        for j in rows:
            s, step, total, info = _progress(j)
            print(f"{j.get('id')}  {j.get('name')}  {s}  {step}/{total}"
                  + (f"  {info}" if info else ""))
    elif cmd == "create":
        if not rest:
            raise SystemExit("создание задания: create <project_dir> --dataset …")
        dataset = opt("--dataset")
        if not dataset:
            raise SystemExit(
                "--dataset обязателен: это путь к папке датасета НА МАШИНЕ\n"
                "  тулкита. Локальный путь сюда не годится — обучение идёт там.")
        res = prepare(rest[0], dataset, arch=opt("--arch"),
                      trigger=opt("--trigger"), name=opt("--name"),
                      shotlist=opt("--shotlist", "shotlist.json"),
                      steps=(int(opt("--steps")) if opt("--steps") else None),
                      rank=(int(opt("--rank")) if opt("--rank") else None),
                      local=opt("--local"), gpu_ids=opt("--gpu", "0"))
        report_prepare(res, send)
        create(res, send)
    elif cmd in ("start", "stop"):
        if not rest:
            raise SystemExit(f"{cmd} <имя|id>")
        job, why = job_of(rest[0])
        if job is None:
            raise SystemExit(why)
        gpu = str(job.get("gpu_ids") or opt("--gpu", "0"))
        path = f"/api/jobs/{job['id']}/{cmd}"
        if not send:
            print("не отправлено (--dry по умолчанию). Отправить: --send\n"
                  + (f"  GET {host()}/api/queue/{gpu}/start   # очередь карты "
                     f"{gpu}\n" if cmd == "start" else "")
                  + f"  GET {host()}{path}   # задание {job.get('name')}")
            return
        if cmd == "start":
            free_comfy()
        code, data = api(path)
        print(f"{path} → {code}: {data}")
        if cmd == "start":
            # ОЧЕРЕДЬ ВКЛЮЧАЕТСЯ ПОСЛЕ ЗАДАНИЯ, А НЕ ДО НЕГО. Прежний порядок
            # (сначала очередь, потом задание) выглядел логичнее и не работал:
            # воркер гасит очередь, в которой нет ни одного queued-задания, и
            # успевал сделать это раньше, чем задание вставало в очередь.
            # Замер: после `start --send` задание висело в queued, а
            # /api/queue отдавал is_running: false у обеих карт; тот же GET,
            # повторённый вручную секундой позже, поднял очередь, и обучение
            # пошло немедленно.
            qcode, qdata = start_queue(gpu)
            print(f"/api/queue/{gpu}/start → {qcode}: {qdata}")
            # Ответ роута — объект ДО обновления, поэтому в нём всегда
            # is_running: false. Судить по нему нельзя, спрашиваем состояние.
            _, q = api("/api/queue")
            live = [x for x in (q or {}).get("queues", [])
                    if str(x.get("gpu_ids")) == gpu and x.get("is_running")]
            print(f"очередь карты {gpu}: "
                  + ("включена" if live else
                     "ВЫКЛЮЧЕНА — задание будет висеть в queued без ошибки; "
                     f"повторите GET {host()}/api/queue/{gpu}/start"))
    elif cmd == "watch":
        if not rest:
            raise SystemExit("watch <имя|id>")
        watch(rest[0], int(opt("--every", 30)), int(opt("--for", 0)))
    elif cmd == "result":
        if not rest:
            raise SystemExit("result <имя|id>")
        result(rest[0])
    else:
        print(__doc__)
        raise SystemExit(f"неизвестная команда {cmd!r}")


if __name__ == "__main__":
    main()
