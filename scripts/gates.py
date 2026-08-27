#!/usr/bin/env python3
"""Ворота качества по всему набору: реестр кадров → таблица и файл вердикта.

  py -3 gates.py <project_dir> [--anchor <img>] [--json <out>] [--only P1,P3]
  py -3 gates.py <project_dir> --shotlist shotlist_story.json   # Part 2

Как модуль:
  from gates import run_gates, report

ЧИТАЕТСЯ РЕЕСТР, А НЕ ДИСК. Вход — <work_root>/<project>/frames/frames.json;
у каждой раскадровки реестр свой (Part 2 лежит в frames_story/), и папку
выбирает --shotlist по тому же правилу, что и generate.py: без него ворота
молча смотрели бы только в Part 1, а отсутствие вердикта по второй части
неотличимо от её прохождения.

Кадр, лежащий рядом, но не записанный в реестр, в вердикт не попадает: у него
неизвестны сид и промпт, то есть он невоспроизводим и сдавать его нельзя. Такие
файлы пересчитываются и называются вслух — молча их игнорировать значит
показывать «5 кадров прошли» там, где на диске лежит сорок.

ГЛАВНОЕ ЧИСЛО ЗДЕСЬ — РАЗБРОС ПО НАБОРУ, А НЕ КОСИНУС К ЯКОРЮ. Критерий ТЗ
номер один — «во всех изображениях один и тот же человек» — это свойство
НАБОРА, а не отдельного кадра. Сравнение кадра с якорем почти тавтологично:
якорь и кадр получены одним и тем же свопом с одного и того же банка лиц,
поэтому косинус к якорю высок даже тогда, когда кадры разъезжаются между
собой. Работающая проверка — попарная матрица косинусов по отгружаемым кадрам:
её МИНИМУМ и есть худшая пара, которую увидит проверяющий. Поэтому у каждого
кадра есть колонка «сет» — средний косинус этого кадра ко всем остальным
кадрам прогона. По ней сразу видно не «набор плохой», а какой именно кадр
выбивается и что перегонять.

Чисел этого замера здесь НЕТ намеренно. Раньше в шапке стояла матрица косинусов
с сидом 70001 и порогом 0.75 — она осталась от удалённой ветки фейс-свопа, её
PNG-исходники стёрты, а порог с тех пор стал 0.72. Проза с числами рядом с
кодом, который эти числа меняет, разошлась с реальностью четыре раунда подряд
(см. assets.json → gates._identity_erratum). Актуальный разброс печатает сам
этот скрипт внизу отчёта, а калибровку — scripts/identity_calibration.py.

Смысл же остаётся: минимум даёт самая далёкая пара — фронтальный портрет против
тёмного и косого кадра, — и именно поэтому судить надо по минимуму, а не по
среднему, которое худшую пару прячет. Правая колонка «сет» отвечает на
исполнимый вопрос: какой кадр дальше всех от набора и что перегонять первым.

ТРИ СОСТОЯНИЯ, А НЕ ДВА. PASS / FAIL / NOT_MEASURED — правила и их обоснование
живут в metrics/verdict.py, здесь они только применяются. Короткая версия:
ворота, которое при отсутствии зависимости молча выключается, выдаёт ложный
PASS, поэтому незамер ОБЯЗАТЕЛЬНЫХ ворот блокирует отгрузку так же, как провал.
Дополнительно в таблице есть n/a — ворота, неприменимые к этому кадру (тату на
кадре без tattoo_visible). Это не деградация: такие ворота исключаются из
списка обязательных для конкретного кадра, а не подделываются под PASS.

ПОРОГОВ В ЭТОМ ФАЙЛЕ НЕТ. Все до одного берутся из assets.json → gates, а
метрики сами решают, что с ними делать; список обязательных ворот — оттуда же
(gates.required). Если ключа required в манифесте ещё нет, берётся список
REQUIRED ниже и об этом печатается строка: пустой список обязательных ворот
означал бы, что блокировать отгрузку нечем, и весь смысл трёх состояний
пропадал бы молча. Имена из required проходят через ALIAS и сверяются с
колонками: незнакомое имя ворот не «строгая проверка», а вечный незамер, и
о нём тоже печатается строка.

--only считает подмножество ячеек и всё равно кладёт результат в gates.json —
это удобно при перегоне одной ячейки, но вердикт становится частичным, поэтому
он помечен полем only и отдельной строкой в отчёте.

ИМПОРТ МЕТРИК ЛЕНИВЫЙ. Ни один тяжёлый модуль не грузится на старте: без
insightface ворота идентичности и возраста дают NOT_MEASURED, а не ImportError
посреди прогона на сорока кадрах. Модуль метрики обязан отдать словарь ворот
metrics.verdict.gate(); имена функций ищутся по списку кандидатов, потому что
метрики пишутся параллельно с этим файлом, и разойтись в имени здесь дешевле,
чем получить NOT_MEASURED на живой метрике. Если у функции есть параметр face
(или **kwargs), в неё передаётся уже посчитанное лицо — детектор за кадр
гоняется один раз.
"""
import importlib, inspect, math, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (setup_console, manifest, work_dir, read_json, write_json,
                   project_name, gate_fingerprint, age_band)
from prompts import load_project

# ворота → (модули-кандидаты, функции-кандидаты).
METRICS = {
    "faces": (("metrics.faces",), ("analyse", "analyze", "faces", "measure")),
    "chroma": (("metrics.chroma", "metrics.colour"), ("chroma", "colour", "measure")),
    "sharp": (("metrics.sharpness", "metrics.sharp", "metrics.focus"),
              ("sharpness", "sharp", "face_sharpness", "measure")),
    "skin": (("metrics.skin",), ("skin", "skin_smooth", "measure")),
    # Метрики опознавания: каждая проверяет ОДИН признак из карточки
    # персонажа. Заведены потому, что косинус ArcFace к таким деталям
    # равнодушен, и признаки были объявлены, но не проверялись ничем.
    # Родинки здесь больше нет: 14.08.2026 заказчик снял её с карточки, и
    # ворота сняты вместе с признаком, а не оставлены висеть незамеренными.
    # Незамеренные ворота со временем читаются как исправные.
    "brows": (("metrics.brows",), ("brows", "measure")),
    "iris": (("metrics.iris",), ("iris", "measure")),
    "lips": (("metrics.lips",), ("lips", "measure")),
    # Волосы — ДВОЕ ворот, а не одни: «корни темнее длины» и многотонность
    # окраски меряются по-разному и разделяют по-разному (первое почти не
    # разделяет вовсе). Складывать их в одно число значило бы спрятать
    # слабое за сильным.
    "hair_roots": (("metrics.hair",), ("roots_darker",)),
    "hair_tone": (("metrics.hair",), ("tone_spread",)),
    # Тату проверяется СОВПАДЕНИЕМ С ФОРМОЙ ассета в том самом месте, куда её
    # кладёт вклейка (рамку даёт metrics/wrist.py). Ворота применимы не ко всем
    # кадрам и часто отвечают NOT_MEASURED: нужная сторона запястья попадает в
    # кадр редко. Замеренная щель и порог — в докстринге metrics/tattoo.py.
    "tattoo": (("metrics.tattoo",), ("tattoo", "match", "measure")),
    # ДЕТЕКТОРА «ИИ-ПРОИСХОЖДЕНИЯ» ЗДЕСЬ БОЛЬШЕ НЕТ, И ЭТО РЕШЕНИЕ, А НЕ
    # НЕДОДЕЛКА. Он стоял в этой таблице и в COLUMNS, а модулей metrics.detector
    # и metrics.ai_detector на диске не было никогда: колонка «ИИ» печатала NM
    # у каждого кадра, сорок раз подряд. Объявленные-но-несуществующие ворота
    # ХУЖЕ отсутствующих — пустая колонка читается как «проверка есть, в этот
    # раз не сработала» и неотличима от временной поломки, а отсутствие колонки
    # отличимо сразу. То же самое про них уже записано в .env.example (четыре
    # ключа к сервисам, которых в коде не существует) и в assets.json →
    # gates._no_tattoo_no_detector.
    # ЛОКАЛЬНУЮ ЭВРИСТИКУ Я ЗАМЕРИЛА, ПРЕЖДЕ ЧЕМ ОТКАЗАТЬСЯ. Классический
    # признак генерации — периодический след сетки в верхних частотах (пик
    # решётки с периодом 8 и 4 px к медиане полосы). Пик к медиане:
    #   сырые кадры конвейера (PNG прямо из модели)    9.1 … 12.9
    #   сданные кадры (JPEG после последней мили)      6.2 … 62.5
    #   НАСТОЯЩИЕ ФОТОГРАФИИ (референсы заказчика)     23.7 и 24.5
    # То есть статистика объявляет настоящее фото ИСКУССТВЕННЕЕ, чем любой наш
    # сырой кадр: её ведёт блок 8x8 JPEG и передискретизация, а не
    # происхождение. Разделяющей способности нет, порог был бы монеткой. И
    # калибровать её не на чем: отрицательный класс — две фотографии, обе кропы
    # одного снимка.
}

# Порядок колонок таблицы. Идентичность и разброс по набору стоят первыми
# потому, что это первый критерий ТЗ.
COLUMNS = [("identity", "иден"), ("cohort", "сет"), ("age", "возр"),
           ("brows", "брови"), ("iris", "глаза"),
           ("lips", "губы"), ("hair_roots", "корни"), ("hair_tone", "тон"),
           ("chroma", "цвет"), ("sharp", "резк"), ("skin", "кожа"),
           ("tattoo", "тату")]

# Запасной список обязательных ворот — на случай, если манифест ещё не объявил
# gates.required.
# ТАТУ ЗДЕСЬ БОЛЬШЕ НЕТ, И ЭТО СЛЕДСТВИЕ ЗАМЕРА, А НЕ ОСЛАБЛЕНИЕ ТРЕБОВАНИЙ.
# Ворота тату отвечают NOT_MEASURED всякий раз, когда нужной стороны запястья
# в кадре не видно, а видно её редко: надпись легла на 4 кадра из 100
# (projects/bridget/wrist_axes.json → _why), и на 17 кадрах, прогнанных через
# разметку при калибровке метрики, площадку удалось найти на 12. Обязательные
# ворота с незамером блокируют отгрузку — то есть «тату» в этом списке
# означало бы, что почти весь набор не отгружается за то, что модель не
# показала руку. Сдача Part 1 это и подтверждает: три кадра из пяти ушли
# клиенту без надписи. Ворота считаются, печатаются и лежат в gates.json;
# блокировать они не должны.
REQUIRED = ["identity", "cohort", "age", "chroma", "sharp", "skin"]

# Синонимы имён ворот. Одни и те же ворота цветности манифест называет colour,
# а модуль метрики — chroma; необъявленный синоним стоит дорого: имя из
# gates.required, которого нет среди ворот кадра, по правилам verdict.py
# считается незамером, и НИ ОДИН кадр не отгрузится никогда, молча.
# Синонима «ai» здесь тоже больше нет: он вёл на снятые ворота детектора, то
# есть на имя, которого не существует среди колонок. Такое имя в
# gates.required — вечный незамер, и об этом печатается строка; синоним, ведущий
# в пустоту, эту строку бы отключил и спрятал опечатку в манифесте.
ALIAS = {"colour": "chroma", "color": "chroma", "hue": "chroma",
         "sharpness": "sharp", "ink": "tattoo", "face": "identity"}

_LOADED = {}


def _verdict_api():
    """metrics/verdict.py — единственный обязательный импорт скрипта.

    Именно он определяет, что значат PASS/FAIL/NOT_MEASURED. Раннер, который
    определял бы их у себя, разошёлся бы с метриками на первой же правке
    правил, поэтому дублировать их здесь нельзя. Если пакета нет вовсе —
    это не деградация одной метрики, а отсутствие ворот как таковых, и об этом
    надо падать вслух.
    """
    try:
        return importlib.import_module("metrics.verdict")
    except Exception as e:
        raise SystemExit(f"metrics/verdict.py не импортируется ({e}).\n"
                         f"Ворота считать нечем: проверьте scripts/metrics/ и "
                         f"py -3 -m pip install numpy opencv-python pillow")


def _entry(gate):
    """Найти функцию метрики. Возвращает (функция|None, причина отказа|None)."""
    if gate in _LOADED:
        return _LOADED[gate]
    modules, funcs = METRICS[gate]
    why = f"модуль не найден: {', '.join(modules)}"
    for mod_name in modules:
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:
            why = f"{mod_name}: {e}"
            continue
        for fn in funcs:
            f = getattr(mod, fn, None)
            if callable(f):
                _LOADED[gate] = (f, None)
                return _LOADED[gate]
        why = f"{mod_name}: нет функции {'/'.join(funcs)}"
    _LOADED[gate] = (None, why)
    return _LOADED[gate]


def _call(gate, path, ctx):
    """Вызвать метрику. Возвращает (результат|None, причина отказа|None).

    Исключение внутри метрики не роняет прогон: сорок кадров считаются
    минутами, и падение на третьем из-за одного битого файла стоило бы всех
    остальных. Причина при этом доезжает до вердикта — NOT_MEASURED обязано
    быть объяснимым, иначе оно неотличимо от «метрика ещё не написана».
    """
    fn, why = _entry(gate)
    if fn is None:
        return None, why
    try:
        params = inspect.signature(fn).parameters
        anykw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
        kw = {k: v for k, v in ctx.items() if anykw or k in params}
        return fn(path, **kw), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _metric_gate(V, name, path, ctx):
    """Ворота от модуля метрики, приведённые к общему виду."""
    res, why = _call(name, path, ctx)
    if res is None:
        return V.not_measured(name, why or "метрика вернула пусто")
    if isinstance(res, dict) and "state" in res:
        res["gate"] = name
        return res
    # Число без порога — это ещё не ворота: сравнивать не с чем, а выдумать
    # порог здесь значило бы завести вторую точку правды рядом с манифестом.
    return V.not_measured(name, f"метрика вернула {type(res).__name__} без "
                                f"состояния ворот — порог не объявлен")


def cosine(a, b):
    """Косинус между эмбеддингами. Голый стдлиб: 512 чисел и полсотни пар —
    не повод тащить numpy в скрипт, который обязан работать без метрик."""
    if not a or not b or len(a) != len(b):
        return None
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return None
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def pairwise(items):
    """Попарные косинусы набора: {min, mean, worst_pair, per_file}.

    per_file — средний косинус кадра ко ВСЕМ остальным. Матрица отвечает на
    вопрос «набор сходится?», per_file — на вопрос «кто именно портит», и
    только второй ответ можно исполнить.
    """
    embs = {n: e for n, e in items if e}
    names = sorted(embs)
    pairs = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            c = cosine(embs[a], embs[b])
            if c is not None:
                pairs.append((c, a, b))
    if not pairs:
        return {"n": len(names), "pairs": 0, "min": None, "mean": None,
                "worst_pair": None, "per_file": {}}
    per = {}
    for n in names:
        near = [c for c, a, b in pairs if n in (a, b)]
        per[n] = round(sum(near) / len(near), 4)
    lo = min(pairs)
    return {"n": len(names), "pairs": len(pairs), "min": round(lo[0], 4),
            "mean": round(sum(c for c, _, _ in pairs) / len(pairs), 4),
            "worst_pair": [os.path.basename(lo[1]), os.path.basename(lo[2])],
            "per_file": per}


def _margin(g):
    """Запас ворот в долях порога; отрицательное — провал.

    Нужен только для сортировки: косинус 0.62 при пороге 0.75 и возраст 38 при
    полосе 45-58 иначе несравнимы, а «худшие первыми» обязано быть одним
    порядком, а не пятью.
    """
    v, lo, hi = g.get("value"), g.get("min"), g.get("max")
    if v is None:
        return None
    if lo is not None and hi is not None:
        half = (hi - lo) / 2.0
        return min(v - lo, hi - v) / half if half else 0.0
    if lo is not None:
        return (v - lo) / abs(lo) if lo else v
    if hi is not None:
        return (hi - v) / abs(hi) if hi else -v
    return None


def _anchor_embedding(char, project_dir, anchor_arg):
    """Эмбеддинг якоря: аргумент командной строки → anchor.embedding →
    anchor.image. Возвращает (вектор|None, источник, причина отказа|None)."""
    anchor = char.get("anchor") or {}
    if not anchor_arg:
        emb = anchor.get("embedding")
        if isinstance(emb, list) and emb:
            return [float(x) for x in emb], anchor.get("image"), None
        if not anchor.get("image"):
            return None, None, "anchor.embedding пуст и anchor.image не задан"
    # Картинка есть, вектора нет — снимаем на лету. Так ворота работают сразу
    # после ручного выбора якоря, не дожидаясь перезаписи карточки.
    src = anchor_arg or anchor["image"]
    path = src if os.path.isabs(src) else os.path.join(project_dir, src)
    face, why = _call("faces", path, {})
    emb = face.get("embedding") if isinstance(face, dict) else None
    return ([float(x) for x in emb] if emb else None, src,
            None if emb else (why or f"лицо не найдено в {src}"))


def _orphans(frames_dir, known):
    """Файлы на диске, которых нет в реестре: по правилу generate.py у них
    неизвестны сид и промпт, значит они невоспроизводимы и это мусор."""
    known = {os.path.normcase(os.path.abspath(f)) for f in known}
    out = []
    for root, _, files in os.walk(frames_dir):
        for f in files:
            if f.lower().endswith((".png", ".jpg", ".jpeg")):
                p = os.path.join(root, f)
                if os.path.normcase(os.path.abspath(p)) not in known:
                    out.append(p)
    return sorted(out)


def run_gates(project_dir, anchor=None, out=None, only=None,
              shotlist="shotlist.json"):
    """Прогнать реестр проекта через ворота. Возвращает словарь вердикта."""
    V = _verdict_api()
    if not os.path.isdir(project_dir):
        # Иначе первым сообщением рецензент видит трейсбек из prompts.py про
        # character.json, а настоящая ошибка — опечатка в пути к проекту.
        raise SystemExit(f"папки проекта нет: {project_dir}\n"
                         "ожидается путь вида projects/bridget")
    char, shots = load_project(project_dir, shotlist)
    project = project_name(project_dir, shots, char)
    # Имя папки принадлежит generate.py и повторено здесь дословно: у каждой
    # раскадровки свой реестр, и жёсткое "frames" оставило бы Part 2 без ворот.
    sub = "frames" if shotlist == "shotlist.json" else \
        "frames_" + os.path.splitext(shotlist)[0].replace("shotlist_", "")
    # НАСТРОЙКА ВОРОТ ПРОВЕРЯЕТСЯ ДО ДИСКА. Порядок не косметический: пустой
    # список обязательных ворот — ошибка настройки, и сообщать о ней надо
    # раньше, чем об отсутствии реестра. Иначе человек сначала гоняет
    # генерацию на GPU и только потом узнаёт, что блокировать отгрузку было
    # нечем. work_dir к тому же СОЗДАЁТ каталог: сломанная настройка успевала
    # оставить после себя пустое дерево.
    g = manifest()["gates"]
    known = {key for key, _ in COLUMNS}
    required = [ALIAS.get(n, n) for n in (g.get("required") or REQUIRED)]
    # Имя, которого нет ни среди ворот, ни среди синонимов, — это не «строгая
    # проверка», а вечный незамер. Молчать об этом нельзя.
    unknown = sorted(set(required) - known)
    required = [n for n in required if n in known]
    # СПРАВОЧНЫЕ ВОРОТА. Считаются и печатаются, но не могут провалить кадр.
    # Заведены потому, что verdict.py валит кадр на ЛЮБОМ FAIL, а метрика,
    # про которую доказано, что она меряет не то (identity здесь меряет
    # ракурс сильнее, чем лицо, — см. gates._identity_is_informational),
    # не должна иметь права брака. Число при этом остаётся в отчёте: отказ
    # блокировать — не отказ измерять.
    informational = {ALIAS.get(n, n) for n in (g.get("informational") or [])}
    required = [n for n in required if n not in informational]
    # ПУСТОЙ СПИСОК ОБЯЗАТЕЛЬНЫХ ВОРОТ — ЭТО ОТКАЗ, А НЕ ЗЕЛЁНЫЙ СВЕТ. Он
    # получается двумя способами: все имена в required незнакомые (опечатка,
    # переименованная метрика) или все они же перечислены в informational.
    # В обоих случаях verdict.py не находил ничего обязательного, каждый кадр
    # выходил PASS, gates возвращал 0 — то есть ровно тот ложный зелёный, ради
    # которого заведены три состояния. Проверено конструкцией: кадр без лица,
    # required=["saturation","bokeh"] → «отгружается 1 из 1», EXIT=0.
    if not required:
        raise SystemExit(
            "обязательных ворот не осталось: "
            + (f"неизвестные имена {unknown}; " if unknown else "")
            + ("всё перечисленное в required попало и в informational; "
               if not unknown else "")
            + "блокировать отгрузку нечем, и каждый кадр вышел бы с ложным "
              "PASS. Проверь assets.json → gates.required / .informational.")

    frames_dir = work_dir(project, sub)
    ledger_path = os.path.join(frames_dir, "frames.json")
    if not os.path.exists(ledger_path):
        raise SystemExit(f"реестра нет: {ledger_path}\n"
                         f"сначала py -3 generate.py {project_dir}"
                         + ("" if sub == "frames" else f" --shotlist {shotlist}"))
    ledger = read_json(ledger_path)
    entries = [e for e in ledger if not only or e.get("cell") in only]
    if not entries:
        raise SystemExit(f"под фильтр {only} не подошёл ни один кадр; в реестре "
                         f"есть: {sorted({e.get('cell') for e in ledger})}")

    age_lo, age_hi = age_band(char, g)
    anchor_emb, anchor_src, anchor_why = _anchor_embedding(char, project_dir, anchor)
    asset = (char.get("tattoo") or {}).get("asset") or ""
    if asset and not os.path.isabs(asset):
        asset = os.path.join(project_dir, asset)

    rows, embeddings = [], []
    for e in entries:
        path = e["file"]
        row = {"file": path, "cell": e.get("cell"), "label": e.get("label"),
               "seed": e.get("seed"), "required": list(required), "gates": {}}
        rows.append(row)
        if not os.path.exists(path):
            # Реестр обещал кадр, файла нет. Это не «не замерено», это дыра в
            # наборе: перегонять придётся в любом случае, поэтому FAIL.
            # Незамером помечаются ВСЕ применимые ворота, включая
            # необязательные: пустая клетка читается в таблице как n/a, то есть
            # «к этому кадру неприменимо», а к пропавшему файлу неприменимо не
            # ворота, а замер вообще. Тату — единственное исключение: её
            # применимость объявлена флагом реестра и от файла не зависит.
            applies = [n for n, _ in COLUMNS
                       if n != "tattoo" or e.get("tattoo_visible")]
            row["required"] = [n for n in required if n in applies]
            row["gates"] = {n: V.not_measured(n, "файла нет на диске")
                            for n in applies}
            row["file_missing"] = True
            continue

        face, face_why = _call("faces", path, {})
        face = face if isinstance(face, dict) else None
        emb = face.get("embedding") if face else None
        emb = [float(x) for x in emb] if emb else None
        embeddings.append((path, emb))

        cos = cosine(emb, anchor_emb)
        if cos is None:
            row["gates"]["identity"] = V.not_measured(
                "identity", face_why or anchor_why or "лицо кадра не найдено")
        else:
            row["gates"]["identity"] = V.gate(
                "identity", cos, lo=g["identity_cosine_min"],
                note="косинус к якорю; проверка почти тавтологична — якорь и "
                     "кадр сделаны одним свопом, смотреть на «сет»",
                anchor=anchor_src)

        age = face.get("age") if face else None
        row["gates"]["age"] = (
            # Полоса считается от возраста ЭТОЙ карточки: жёсткие age_min/
            # age_max были верны ровно для одного человека, и второй персонаж
            # проваливал ворота самим фактом своего существования.
            V.gate("age", float(age), lo=age_lo, hi=age_hi,
                   note=f"персонажу {char.get('age')}")
            if isinstance(age, (int, float)) else
            V.not_measured("age", face_why or "metrics.faces не вернул возраст"))

        # КАРТОЧКА ПЕРСОНАЖА ТОЖЕ ИДЁТ В КОНТЕКСТ. Метрики опознавания берут
        # из неё то, что является свойством ЧЕЛОВЕКА, а не настройки: на какой
        # щеке отметина, какого цвета глаза. Без карточки метрика отметины
        # честно отвечала «проверять нечего» — сорок раз из сорока, и колонка
        # выглядела настроенной, оставаясь пустой.
        ctx = {"face": face, "asset": asset, "scene_class": e.get("scene_class"),
               "gates": g, "char": char}
        # СПИСОК ВОРОТ ВЫЧИСЛЯЕТСЯ, А НЕ ЗАШИТ. Прежняя редакция перечисляла
        # их кортежем, и пять новых метрик опознавания, честно подключённых к
        # METRICS и к COLUMNS, молча не вызывались ни разу: в таблице стояло
        # n/a, то есть «к этому кадру неприменимо», хотя применимо. Ворота,
        # добавленные и не запущенные, — худший вид ложного зелёного: они
        # выглядят настроенными.
        for name, _ in COLUMNS:
            if name in ("identity", "cohort", "age", "tattoo"):
                continue      # считаются отдельно выше либо по флагу ячейки
            if name not in METRICS:
                continue
            row["gates"][name] = _metric_gate(V, name, path, ctx)
        if e.get("tattoo_visible"):
            row["gates"]["tattoo"] = _metric_gate(V, "tattoo", path, ctx)
        else:
            # Ворота не подделываются под PASS, а выводятся из обязательных для
            # ЭТОГО кадра: тату на кадре без запястья не «прошло», его нет.
            row["required"] = [n for n in required if n != "tattoo"]

    # «Сет» считается по всем измеренным кадрам прогона, а не по отгружаемым:
    # иначе получается круг — кадр не отгружается, потому что выбивается из
    # набора отгружаемых, в который он из-за этого не входит.
    cohort = pairwise(embeddings)
    measured = {p for p, emb in embeddings if emb}
    for row in rows:
        if row.get("file_missing"):
            continue
        v = cohort["per_file"].get(row["file"])
        row["gates"]["cohort"] = (
            V.gate("cohort", v, lo=g["identity_cosine_min"],
                   note=f"средний косинус к остальным {cohort['n'] - 1} кадрам "
                        f"набора")
            if v is not None else
            V.not_measured("cohort", "эмбеддинг кадра не снят"
                           if row["file"] not in measured else
                           "в наборе нет второго кадра с лицом"))

    for row in rows:
        # Справочные ворота изымаются из вердикта, но остаются в отчёте: их
        # значение печатается в таблице и лежит в gates.json.
        judged = {k: v for k, v in row["gates"].items()
                  if k not in informational}
        res = V.verdict(judged, required=row["required"])
        row.update({k: res[k] for k in ("verdict", "ships", "failed", "missing")})
        row["rank_fail"] = len(res["failed"])
        if row.get("file_missing"):
            # Обещанный реестром кадр отсутствует: замерить нечего, но и ждать
            # нечего — перегонять придётся. Наверх списка, вердикт FAIL.
            row["verdict"], row["ships"] = V.FAIL, False
            row["rank_fail"] = len(row["required"])
        margins = [m for m in (_margin(x) for x in row["gates"].values())
                   if m is not None]
        row["worst_margin"] = round(min(margins), 3) if margins else None
        # ОТДЕЛЬНО — ЗАПАС ПО ОБЯЗАТЕЛЬНЫМ ВОРОТАМ. worst_margin считается по
        # всем воротам подряд, а справочные (identity, cohort) на этом
        # конвейере провалены у всех кадров и перебивают собой любую разницу:
        # у каждого кадра выходит примерно -1.7, и сортировать по этому числу
        # значит сортировать по константе. Тот, кто выбирает лучший кадр
        # ячейки, спрашивает именно про блокирующие ворота, и формула должна
        # жить здесь, рядом с _margin, а не переписываться у потребителя.
        req_margins = [m for m in (_margin(x) for k, x in row["gates"].items()
                                   if k in set(row["required"]))
                       if m is not None]
        row["worst_margin_required"] = (round(min(req_margins), 3)
                                        if req_margins else None)

    # Худшие первыми: сначала кадры с провалами, затем непромеренные, внутри —
    # по глубине худшего провала. Инструмент существует, чтобы отвечать на
    # вопрос «что перегонять», и ответ обязан быть в первой строке.
    rows.sort(key=lambda r: (-r["rank_fail"], -len(r["missing"]),
                             r["worst_margin"] if r["worst_margin"] is not None
                             else 0.0))

    ships = {r["file"] for r in rows if r["ships"]}
    ship_set = pairwise([(p, e) for p, e in embeddings if p in ships])

    # ПОРОГ ОБЪЯВЛЕН ДЛЯ НАБОРА ИЗ scope КАДРОВ, И ПРЕДЪЯВЛЯТЬ ЕГО НАБОРУ
    # БОЛЬШЕГО РАЗМЕРА НЕЛЬЗЯ. Минимум по парам падает с числом пар: у пятёрки
    # их 10, у тридцатки 435, и один и тот же материал даёт 0.735 и 0.657.
    # Пока это не читалось кодом, отчёт по всем тридцати печатал FAIL и
    # выглядел как провал сходства, хотя мерил другую величину. Замеры и
    # доказательство недостижимости — assets.json → gates.
    # _identity_cosine_min_scope. Ключ манифеста, который никто не читает,
    # в этом проекте уже случался (models.base.clip), поэтому он читается ЗДЕСЬ.
    scope = int(g.get("identity_cosine_min_scope") or 0)

    def state_of(stats):
        if stats["min"] is None:
            return V.NOT_MEASURED
        if scope and stats["n"] > scope:
            # Не PASS и не FAIL: величина посчитана, а порога для неё нет.
            return V.NOT_MEASURED
        return V.PASS if stats["min"] >= g["identity_cosine_min"] else V.FAIL

    verdict = {
        "project": project,
        "registry": ledger_path,
        "out": out or os.path.join(frames_dir, "gates.json"),
        "only": list(only) if only else None,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "anchor": {"source": anchor_src, "measured": anchor_emb is not None,
                   "why": anchor_why},
        "required": required,
        # ОТПЕЧАТОК НАСТРОЙКИ ВОРОТ. Вердикт — файл, который переживает свой
        # прогон и который потом читают отбор, сдача и отчёт как истину. Один
        # эксперимент с другим манифестом (или тест, который забыл увести
        # PERSONA_WORK_ROOT в свою папку) молча подменяет его: на диске остаётся
        # правдоподобный gates.json, где не отгружается ничего, и следующий
        # человек ищет причину в кадрах. Читатели сверяют этот отпечаток со
        # своим манифестом и отказываются работать по чужому вердикту.
        # Отпечаток настройки — из _util, чтобы писатель и читатель вердикта
        # не могли разойтись определением: пороги сверяются наравне с именами
        # ворот, потому что вердикт при face_sharp_min 70 неотличим от вердикта
        # при 118, хотя первый пропускает ровно то, что второй валит.
        "gate_config": gate_fingerprint(g),
        # ПОКРЫТИЕ. --only перезаписывает gates.json ЦЕЛИКОМ: строки остальных
        # ячеек из файла исчезают. Ни один потребитель этого не замечал —
        # отбор считал отсутствие строки за «прошёл» и рекомендовал
        # непромеренный кадр готовой строкой --pick, а сдаточный qa_report
        # печатал «8 of 8» про часть из сорока кадров. Предупреждение о
        # частичности печаталось только в stdout, то есть жило до конца
        # прогона и в файл не попадало.
        "coverage": {"partial": bool(only),
                     "cells_measured": sorted({e.get("cell") for e in entries}),
                     "cells_in_registry": sorted({e.get("cell") for e in ledger}),
                     "frames_measured": len(entries),
                     "frames_in_registry": len(ledger)},
        "required_unknown": unknown,
        "required_declared": bool(g.get("required")),
        "required_from": ("assets.json → gates.required" if g.get("required")
                          else "REQUIRED в gates.py (в манифесте ключа нет)"),
        "metrics": {name: (_entry(name)[1] or "ok") for name in METRICS},
        "counts": {"registered": len(entries), "ship": len(ships),
                   "fail": sum(1 for r in rows if r["verdict"] == V.FAIL),
                   "not_measured": sum(1 for r in rows
                                       if r["verdict"] == V.NOT_MEASURED)},
        # Авторитетна строка по ОТГРУЖАЕМЫМ кадрам: набор сдаётся целиком, и
        # разброс по нему — это и есть первый критерий ТЗ. Разброс по всем
        # измеренным держится рядом, чтобы число было видно и до первой отгрузки.
        "set_identity": {"state": state_of(ship_set),
                         "state_measured": state_of(cohort),
                         "min_required": g["identity_cosine_min"],
                         "min_required_scope": scope,
                         "shipped": ship_set, "measured": cohort},
        "orphans": _orphans(frames_dir, [e["file"] for e in ledger]),
        "frames": rows,
    }
    write_json(verdict["out"], verdict)
    return verdict


def _num(v):
    if v is None:
        return "—"
    a = abs(v)
    return f"{v:.0f}" if a >= 100 else f"{v:.1f}" if a >= 10 else f"{v:.2f}"


def report(verdict):
    """Таблица в stdout: строка — кадр, колонка — ворота, худшие сверху."""
    name_w = 20
    head = (f"{'кадр':<{name_w}}{'вердикт':<14}"
            + "".join(f"{col:>11}" for _, col in COLUMNS))
    print(head)
    print("-" * len(head))
    for r in verdict["frames"]:
        name = os.path.splitext(os.path.basename(r["file"]))[0][:name_w - 1]
        line = f"{name:<{name_w}}{r['verdict']:<14}"
        for key, _ in COLUMNS:
            # Ворот нет в строке — значит они к этому кадру неприменимы; это
            # n/a, а не незамер, и путать их нельзя: n/a отгрузке не мешает.
            cell = r["gates"].get(key)
            state = cell["state"].replace("NOT_MEASURED", "NM") if cell else "n/a"
            line += f"{state:>5}{_num(cell['value'] if cell else None):>6}"
        print(line)

    c = verdict["counts"]
    print(f"\nотгружается {c['ship']} из {c['registered']} · провалов {c['fail']} "
          f"· не замерено {c['not_measured']}")
    if verdict["only"]:
        # Иначе частичный прогон молча ложится поверх полного вердикта и борд
        # показывает набор из двух ячеек как весь проект.
        print(f"  ВЕРДИКТ ЧАСТИЧНЫЙ: фильтр --only {','.join(verdict['only'])} — "
              f"он перезаписал {os.path.basename(verdict['out'])}")

    s = verdict["set_identity"]
    final = bool(s["shipped"]["pairs"])
    src, state = ((s["shipped"], s["state"]) if final
                  else (s["measured"], s["state_measured"]))
    if src["pairs"]:
        print(f"РАЗБРОС ЛИЦА {'по отгружаемым' if final else 'по всем измеренным'} "
              f"({src['n']} кадров, {src['pairs']} пар): min {src['min']:.3f} на "
              f"паре {' × '.join(src['worst_pair'])}, среднее {src['mean']:.3f} "
              f"— {state} (нужно >= {s['min_required']}"
              + (f" на наборе из {s['min_required_scope']}; здесь кадров "
                 f"{src['n']}, порог к такому набору НЕ ОТНОСИТСЯ"
                 if s.get("min_required_scope")
                 and src["n"] > s["min_required_scope"] else "") + ")"
              + ("" if final else "; отгружаемых кадров пока нет, "
                                  "оценка предварительная"))
    else:
        print("РАЗБРОС ЛИЦА: NOT_MEASURED — ни одной пары кадров с лицами")

    for name, why in verdict["metrics"].items():
        if why != "ok":
            print(f"  ворота «{name}» не считаются — {why}")
    if verdict["anchor"]["why"]:
        print(f"  якорь не задан — {verdict['anchor']['why']}")
    if verdict["required_unknown"]:
        print(f"  ВНИМАНИЕ: gates.required называет ворота, которых нет: "
              f"{', '.join(verdict['required_unknown'])} — проверьте имя в "
              f"assets.json, иначе оно не проверяется вообще")
    if not verdict["required_declared"]:
        print(f"  обязательные ворота взяты из {verdict['required_from']}: "
              f"{', '.join(verdict['required'])}")
    if verdict["orphans"]:
        n = len(verdict["orphans"])
        print(f"  ВНЕ РЕЕСТРА {n} файл(ов), в вердикт не попали: "
              f"{', '.join(os.path.basename(p) for p in verdict['orphans'][:5])}"
              f"{' …' if n > 5 else ''}")

    print("\nNM = не замерено; среди обязательных ворот это значит, что кадр НЕ "
          f"ОТГРУЖАЕТСЯ\nсырые числа каждой метрики: {verdict['out']}")


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__); raise SystemExit(1)

    def opt(k, d=None):
        # Ключ последним аргументом — обычная опечатка, и голый IndexError
        # показывает трейсбек вместо имени ключа, которому не хватило значения.
        if k not in args:
            return d
        i = args.index(k) + 1
        if i >= len(args) or args[i].startswith("--"):
            raise SystemExit(f"у ключа {k} нет значения")
        return args[i]

    only = opt("--only")
    verdict = run_gates(args[0], anchor=opt("--anchor"), out=opt("--json"),
                        only=[c.strip() for c in only.split(",")] if only else None,
                        shotlist=opt("--shotlist", "shotlist.json"))
    report(verdict)
    # Ненулевой код возврата, когда не отгружается ни один кадр: оркестратору и
    # CI нужен признак, не требующий разбора stdout.
    raise SystemExit(0 if verdict["counts"]["ship"] else 1)


if __name__ == "__main__":
    main()
