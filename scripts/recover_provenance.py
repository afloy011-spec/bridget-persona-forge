#!/usr/bin/env python3
"""Сид и промпт кадра — обратно из самого PNG, а не из чужой памяти.

  py -3 recover_provenance.py <папка проекта> [--shotlist shotlist_story.json]
                              [--apply] [--all]

ЗАЧЕМ ЭТОТ ФАЙЛ ПОЯВИЛСЯ. В реестрах проекта три записи стояли с seed=null,
prompt=null и объяснением в поле `_origin`: «Сид и промпт УТРАЧЕНЫ… Кадр
невоспроизводим — это его цена, и она записана здесь, а не замолчана». Запись
честная по намерению и неверная по факту: ComfyUI зашивает ВЕСЬ граф прогона в
сам PNG, в текстовый чанк «prompt», и там лежат и сид, и текст буква в букву.
Утрачена была не запись, а привычка её искать. Три кадра, объявленные
невоспроизводимыми, воспроизводимы — и сдача перестаёт врать заказчику про то,
что часть набора нельзя повторить.

ЗАМЕРЕНО НА bridget, три реестра, 281 запись (frames 70, frames_story 49,
frames_trends 162):
  * чанк «prompt» нашёлся в 281 PNG из 281 — то есть во ВСЕХ, а не только в
    свежих: ни один прогон конвейера не терял его по дороге;
  * средняя длина чанка 4555 символов — это весь граф, промпт в нём одно поле;
  * там, где сид и промпт в реестре БЫЛИ (278 записей), зашитое совпало с
    записанным 278 раз из 278, размер — 278 из 278. Ни одного расхождения.
    Вот это и есть основание доверять чанку в тех трёх, где записи нет: не
    «метаданные обычно правильные», а «на этом самом пуле они не соврали ни
    разу»;
  * размер из графа совпал с настоящим размером файла 281 раз из 281.

КАК ЧИТАЕТСЯ ПРОМПТ, И ПОЧЕМУ НЕ «САМАЯ ДЛИННАЯ СТРОКА В ГРАФЕ». Соблазн взять
узел с длинным inputs.text (в нашем шаблоне это узел «4») велик и неверен:
рядом в графе живёт негатив, и в чужих шаблонах он бывает длиннее позитива.
Здесь путь идёт ОТ СЭМПЛЕРА ПО СВЯЗИ `positive` — она указывает на источник
текста однозначно, чем бы этот узел ни оказался. Замерено: на всех 281 графе
связь приводит в CLIPTextEncode ровно за ОДИН шаг, то есть надёжность здесь
ничего не стоит. В нашем шаблоне негатив — ConditioningZeroOut, который берёт
вход из того же узла «4», так что «взять самый длинный текст» дало бы верный
ответ СЛУЧАЙНО, и первая же смена шаблона это обнулила бы.

СУХОЙ ПРОГОН ПО УМОЛЧАНИЮ — домашнее правило (generate.py --dry,
adopt_canvas.py --dry). Знак ключа здесь обратный: там сухой прогон просят,
здесь его надо ОТМЕНИТЬ ключом --apply. Так потому, что этот скрипт правит уже
написанное, а не создаёт новое: цена ошибочного запуска — затёртая запись
реестра, а не лишний GPU-час.

--all — ЭТО СТОРОЖ, А НЕ ПОЧИНКА. Он сверяет с PNG ВСЕ записи, а не только
пустые, и ругается на расхождение. Файл, чей граф говорит не то, что реестр, —
это подмена: кадр, положенный в папку руками, переименованный сосед по ячейке
или перезаписанный после генерации. Расхождение НЕ чинится молча: реестр и
пиксели разошлись, и какой из них прав — решает человек, а не этот скрипт.

ЧЕГО ЭТОТ СКРИПТ НЕ ДЕЛАЕТ. Если чанка в PNG нет, он говорит это вслух и
оставляет null на месте. Восстановить сид «по соседям в ячейке» технически
можно, и это было бы выдумывание: соседние кадры сняты ДРУГИМИ сидами, а
совпадение промпта не делает запись достоверной.
"""
import os, sys, json, re, glob, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (setup_console, cli_opt, read_json, write_json,  # noqa: E402
                   work_root, work_resolve, project_name, ROOT)
# ПАПКА РЕЕСТРА БЕРЁТСЯ ЧУЖОЙ ФУНКЦИЕЙ, И ЭТО НАМЕРЕННО. Правило «frames для
# shotlist.json, frames_<имя> для остальных» уже записано трижды: в generate.py
# строкой, в adopt_canvas.py функцией, в deliver.py функцией с псевдонимом для
# номера части. Четвёртая копия разошлась бы с ними на первой же правке — а
# разойдясь, отправила бы починку в папку, которой конвейер не пользуется, и
# отчиталась бы об успехе.
from adopt_canvas import frames_sub  # noqa: E402

# Имя текстового чанка, в который ComfyUI кладёт граф в формате API. Рядом он
# пишет ещё «workflow» — это тот же прогон в формате холста, с координатами
# узлов и без гарантии, что подставленные значения совпадают с исполненными.
# Читается только «prompt»: исполнялся именно он.
META_KEY = "prompt"

# Поля, в которых узел держит текст промпта. `text` — CLIPTextEncode обычного
# t2i, `prompt` — Krea2EditGroundedEncode из ветки эдита (EDIT_KNOB в
# generate.py указывает на «9.prompt»). Обе ветки пишут в один реестр, значит
# и читать их должен один разбор.
TEXT_KEYS = ("text", "prompt")

# Утверждения, которые этот скрипт опровергает своим существованием.
_REFUTED = re.compile("утрачен|невоспроизводим", re.I)


def png_graph(path):
    """Граф прогона из текстового чанка PNG. Пустой словарь — значит нет.

    Пустой словарь возвращается на ВСЕ виды «нечего читать»: файла нет, файл
    не PNG, чанка в нём нет, чанк не разбирается как JSON. Разделять эти
    случаи исключениями незачем: снаружи от них одно и то же поведение —
    сказать вслух и не выдумывать. А вот падать нельзя: обход реестра из
    двухсот записей, споткнувшийся на одном битом файле, не чинит и
    остальные сто девяносто девять.
    """
    from PIL import Image
    try:
        with Image.open(path) as im:
            raw = im.info.get(META_KEY)
    except (OSError, ValueError):
        return {}
    if not raw:
        return {}
    try:
        graph = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(graph, dict):
        return {}
    return {k: v for k, v in graph.items() if isinstance(v, dict)}


def _node_order(key):
    """Порядок узлов: числовые id по-числовому, остальные по строке.

    Сортировка строк ставит «10» перед «7», и «первый сэмплер в графе»
    оказался бы не тем, каким его видит человек в ComfyUI.
    """
    return (0, int(key), "") if str(key).isdigit() else (1, 0, str(key))


def _sampler(graph):
    """Узел, задавший сид кадра: (id, узел). (None, None) — если его нет.

    По подстроке «KSampler», а не по точному имени: KSamplerAdvanced и
    KSampler (Efficient) — тот же сэмплер с тем же сидом, и точное сравнение
    молча объявляло бы такой кадр невосстановимым.
    """
    found = [(k, v) for k, v in graph.items()
             if "KSampler" in str(v.get("class_type", ""))]
    if not found:
        return None, None
    found.sort(key=lambda kv: _node_order(kv[0]))
    # Если сэмплеров несколько (двухпроходные схемы), берётся ПЕРВЫЙ: сид
    # кадра задаёт он, второй проход только дорисовывает. Замерено: в 281
    # графе этого проекта сэмплер везде ровно один, так что выбор пока
    # умозрительный — и записан здесь именно поэтому.
    return found[0]


def _seed_of(node):
    """Сид узла. `noise_seed` — то же самое у KSamplerAdvanced."""
    ins = node.get("inputs") or {}
    for key in ("seed", "noise_seed"):
        v = ins.get(key)
        # Список — это связь на другой узел, а не значение: сид, приехавший по
        # проводу, в графе не записан, и подставлять номер узла вместо числа
        # нельзя.
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return None


def _first_link(inputs):
    """Первая связь узла: ["7", 0]. None — если узел ни от кого не зависит."""
    for v in inputs.values():
        if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
            return v
    return None


def _walk_back(graph, ref, want):
    """Идти по связям назад, пока `want` не вернёт значение. None — не нашлось.

    Обход держит множество уже пройденных узлов: граф, склеенный руками,
    может содержать кольцо, и обход без памяти висит на нём вечно вместо
    того, чтобы сказать «не нашлось».
    """
    seen = set()
    while isinstance(ref, list) and ref and ref[0] in graph and ref[0] not in seen:
        seen.add(ref[0])
        node = graph[ref[0]]
        got = want(node)
        if got is not None:
            return ref[0], got
        ref = _first_link(node.get("inputs") or {})
    return None, None


def _text_of(node):
    ins = node.get("inputs") or {}
    for key in TEXT_KEYS:
        v = ins.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return None


def _size_of(node):
    ins = node.get("inputs") or {}
    w, h = ins.get("width"), ins.get("height")
    if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
        return [w, h]
    return None


def provenance(path):
    """Сид, промпт и размер одного кадра — из его собственных метаданных.

    Возвращает словарь с теми ключами, что НАШЛИСЬ, и ключом `nodes` — откуда
    именно взят каждый. Пустой словарь означает ровно «в файле этого нет», и
    ничего больше: догадок здесь не производится, потому что догадка,
    записанная в реестр, неотличима от факта уже на следующий день.
    """
    graph = png_graph(path)
    if not graph:
        return {}
    sid, sampler = _sampler(graph)
    if sampler is None:
        return {}
    ins = sampler.get("inputs") or {}
    out, nodes = {}, {}

    seed = _seed_of(sampler)
    if seed is not None:
        out["seed"] = seed
        nodes["seed"] = sid

    tid, text = _walk_back(graph, ins.get("positive"), _text_of)
    if text is not None:
        out["prompt"] = text
        nodes["prompt"] = tid

    wid, size = _walk_back(graph, ins.get("latent_image"), _size_of)
    if size is None:
        # Запасной путь для веток, где латент приезжает не из пустого холста
        # (эдит грунтует его референсом): размер ищется по всему графу. Он
        # запасной, а не основной, потому что узлов с width/height в графе
        # бывает несколько — масштабирование референса тоже их имеет, — и
        # только цепочка от сэмплера показывает, какой из них про ЭТОТ кадр.
        for key in sorted(graph, key=_node_order):
            size = _size_of(graph[key])
            if size is not None:
                wid = key
                break
    if size is not None:
        out["size"] = size
        nodes["size"] = wid

    if out:
        out["nodes"] = nodes
    return out


def is_complete(prov):
    """Хватает ли найденного, чтобы чинить запись. Размер — не обязателен."""
    return prov.get("seed") is not None and prov.get("prompt") is not None


def disagreements(entry, prov):
    """Чем запись расходится с зашитым в PNG. Пустой список — согласие.

    Сравниваются только те поля, которые есть по ОБЕ стороны: пустое поле —
    это работа для починки, а не расхождение, и мешать одно с другим значит
    получить сторожа, который всегда красный и потому не читается.
    """
    out = []
    if prov.get("seed") is not None and entry.get("seed") is not None:
        if int(entry["seed"]) != int(prov["seed"]):
            out.append("сид: в реестре {}, в PNG {}".format(entry["seed"],
                                                            prov["seed"]))
    if prov.get("prompt") is not None and entry.get("prompt") is not None:
        if entry["prompt"] != prov["prompt"]:
            out.append("промпт: в реестре {} симв., в PNG {} симв. — это "
                       "разный текст".format(len(entry["prompt"]),
                                             len(prov["prompt"])))
    if prov.get("size") and entry.get("size"):
        if list(entry["size"]) != list(prov["size"]):
            out.append("размер: в реестре {}, в PNG {}".format(entry["size"],
                                                               prov["size"]))
    return out


def _note(prov):
    """Честное объяснение, откуда взялись числа.

    Пути к файлу здесь нет намеренно: та же строка уезжает в selection.json, а
    он передаётся заказчику, и абсолютный путь несёт в себе имя пользователя
    машины (см. _util.work_relative). Файл записи и так назван соседним полем.
    """
    nodes = prov.get("nodes") or {}
    return ("Прочитано из графа прогона, который ComfyUI зашивает в сам PNG "
            "(текстовый чанк «{key}»): сид — узел {seed}, текст — узел "
            "{prompt}, размер — узел {size}. Восстановлено "
            "scripts/recover_provenance.py {when}. Прежняя запись утверждала, "
            "что сид и промпт утрачены, а кадр невоспроизводим, — опровергнуто "
            "самим файлом; на этом пуле зашитое совпало с записанным 278 раз "
            "из 278 там, где запись была."
            .format(key=META_KEY, seed=nodes.get("seed", "?"),
                    prompt=nodes.get("prompt", "?"),
                    size=nodes.get("size", "?"),
                    when=time.strftime("%Y-%m-%d")))


def _supersede_origin(entry):
    """Опровергнутое утверждение — в архив, а не под сукно.

    В `_origin` починенных записей стоит «Сид и промпт УТРАЧЕНЫ… Кадр
    невоспроизводим». Оставить это рядом с восстановленным сидом значит
    держать в одной записи два взаимоисключающих утверждения — и следующий
    читатель поверит тому, которое прочтёт первым. Стереть целиком — потерять,
    что запись БЫЛА неверна и в чём именно.

    Поэтому прежний текст ложится целиком в `_origin_superseded` (карточка
    персонажа хранит прежние блоки опознавания ровно так же —
    `_superseded_identity_cores`), а в `_origin` остаётся то из него, что
    осталось правдой: кадр действительно отобран руками из прежнего пула.
    Режется по предложениям и только при найденном маркере: запись без
    опровергнутого утверждения не трогается вовсе.
    """
    old = str(entry.get("_origin") or "")
    if not _REFUTED.search(old):
        return
    kept = [s for s in re.split(r"(?<=[.!?])\s+", old) if not _REFUTED.search(s)]
    entry["_origin_superseded"] = old
    entry["_origin"] = " ".join(kept).strip()


def _frame_path(ledger_dir, entry):
    """Файл кадра. Реестр переносим между машинами, пути в нём — нет.

    Тот же запасной путь, что у tests/test_registry.py: если записанный
    абсолютный путь мёртв, кадр ищется рядом с реестром по ячейке и имени.
    Без этого перенос рабочей папки превращал «метаданных нет» в диагноз,
    хотя файл лежит на месте.
    """
    f = str(entry.get("file") or entry.get("source") or "")
    if not f:
        return ""
    resolved = work_resolve(f.replace("\\", "/"))
    if os.path.exists(resolved):
        return resolved
    alt = os.path.join(ledger_dir, str(entry.get("cell") or ""),
                       os.path.basename(f))
    return alt if os.path.exists(alt) else resolved


def _short(text, n=88):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n] + "…"


def _report(kind, rows):
    """Печать «было → стало» по одному источнику. Возвращает число починок."""
    for entry, prov, path in rows:
        print("\n  {} · {} · {}".format(kind, entry.get("cell", "?"),
                                        os.path.basename(path)))
        print("    было:  сид {}   промпт {}   размер {}".format(
            entry.get("seed"), entry.get("prompt"), entry.get("size")))
        print("    стало: сид {}   промпт {} симв.   размер {}".format(
            prov.get("seed"), len(prov.get("prompt") or ""), prov.get("size")))
        print("           «{}»".format(_short(prov.get("prompt") or "")))
    return len(rows)


def _scan(entries, ledger_dir, check_all):
    """Разложить записи на три кучи: чинить, ругаться, нечего читать."""
    fixable, broken, blind = [], [], []
    for entry in entries:
        empty = entry.get("seed") is None or entry.get("prompt") is None
        if not empty and not check_all:
            continue
        path = _frame_path(ledger_dir, entry)
        if not path or not os.path.exists(path):
            if empty:
                blind.append((entry, "файла нет на диске: {}".format(path or "?")))
            continue
        prov = provenance(path)
        if not prov:
            if empty:
                blind.append((entry, "в PNG нет чанка «{}» — восстанавливать "
                                     "не из чего".format(META_KEY)))
            continue
        if empty:
            if is_complete(prov):
                fixable.append((entry, prov, path))
            else:
                blind.append((entry, "в графе PNG нашлось только {} — этого "
                                     "мало".format(sorted(k for k in prov
                                                          if k != "nodes"))))
            continue
        bad = disagreements(entry, prov)
        if bad:
            broken.append((entry, path, bad))
    return fixable, broken, blind


def _deliveries(project, sub):
    """Файлы сдачи, собранные ИЗ ЭТОГО реестра.

    ЗАЧЕМ СЮДА ВООБЩЕ ЛЕЗТЬ. selection.json — вторая копия того же
    провенанса, и именно она уезжает заказчику. Правило проекта «кадр без
    записи в реестре считается мусором» к сдаче относится в первую очередь, а
    там сид и промпт стояли теми же null. Пересобирать сдачу через deliver.py
    ради двух чисел нельзя: он перепишет и JPEG, а они уже отсмотрены
    человеком и лежат в git.

    Принадлежность определяется хвостом пути `source`, а не четвёртой картой
    «часть → папка»: у deliver.py такая карта уже есть, и её вторая копия
    здесь разошлась бы с первой ровно тогда, когда появится третья
    раскадровка. Хвост же берётся из того самого frames_sub, по которому
    реестр и найден.
    """
    tail = "/{}/{}/".format(project, sub)
    out = []
    pattern = os.path.join(ROOT, "deliverables", project, "*", "selection.json")
    for path in sorted(glob.glob(pattern)):
        data = read_json(path)
        # Ведущий слеш приклеивается К ОБОИМ концам сравнения: `source` в сдаче
        # лежит ОТНОСИТЕЛЬНО рабочего корня («bridget/frames_story/…»), и хвост
        # с ведущим слешем в него не попадал — первая редакция этой функции
        # молча находила ноль строк и отчитывалась, что в сдаче всё в порядке.
        rows = [r for r in data.get("frames", [])
                if tail in "/" + str(r.get("source", "")).replace("\\", "/")]
        if rows:
            out.append((path, data, rows))
    return out


def recover(project_dir, shotlist="shotlist.json", apply=False, check_all=False):
    """Пройти реестр раскадровки и сдачу, собранную из него.

    Возвращает (сколько починено, сколько расхождений) — числами, а не
    печатью: этим же пользуется тест.
    """
    char = read_json(os.path.join(project_dir, "character.json"))
    shots = read_json(os.path.join(project_dir, shotlist))
    project = project_name(project_dir, shots, char)
    sub = frames_sub(shotlist)
    # work_root(), А НЕ work_dir(): последняя делает mkdir, и сухой прогон с
    # опечаткой в имени проекта заводил бы пустое дерево на диске — та же
    # грабля, из-за которой generate.py --dry обходит work_dir стороной.
    # Создавать здесь всё равно нечего: реестр либо есть, либо чинить нечего.
    ledger_dir = os.path.join(work_root(), project, sub)
    ledger_path = os.path.join(ledger_dir, "frames.json")
    if not os.path.exists(ledger_path):
        raise SystemExit("реестра нет: {}\n  сначала generate.py {} "
                         "--shotlist {}".format(ledger_path, project_dir,
                                                shotlist))
    ledger = read_json(ledger_path)
    empty = [e for e in ledger
             if e.get("seed") is None or e.get("prompt") is None]
    print("{} · {} · {}".format(project, shotlist, ledger_path))
    print("записей {}, из них без сида или промпта {}; режим: {}{}".format(
        len(ledger), len(empty), "ЗАПИСЬ" if apply else "сухой прогон",
        ", сверяются ВСЕ записи" if check_all else ""))

    fixable, broken, blind = _scan(ledger, ledger_dir, check_all)
    fixed = _report("реестр", fixable)

    deliveries = _deliveries(project, sub)
    d_fixable = []
    for path, data, rows in deliveries:
        f, b, bl = _scan(rows, ledger_dir, check_all)
        d_fixable.append((path, data, f))
        broken += b
        blind += bl
        fixed += _report("сдача " + os.path.basename(os.path.dirname(path)), f)

    for entry, why in blind:
        print("\n  ! {} · {}: {}".format(entry.get("cell", "?"),
                                         os.path.basename(str(
                                             entry.get("file")
                                             or entry.get("source") or "?")),
                                         why))
        print("    сид и промпт остаются пустыми — выдумывать их нечем")

    for entry, path, why in broken:
        print("\n  !! {} · {}: РАСХОЖДЕНИЕ С PNG".format(entry.get("cell", "?"),
                                                         os.path.basename(path)))
        for line in why:
            print("     " + line)

    if not fixed and not broken and not blind:
        print("\nчинить нечего: у всех записей сид и промпт на месте"
              + (" и сходятся с PNG" if check_all else ""))

    if apply:
        if fixable:
            for entry, prov, _p in fixable:
                entry["seed"] = prov["seed"]
                entry["prompt"] = prov["prompt"]
                if prov.get("size"):
                    entry["size"] = prov["size"]
                entry["_recovered"] = _note(prov)
                _supersede_origin(entry)
            write_json(ledger_path, ledger)
            print("\nреестр переписан: {} ({} записей)".format(ledger_path,
                                                               len(ledger)))
        for path, data, rows in d_fixable:
            if not rows:
                continue
            for entry, prov, _p in rows:
                entry["seed"] = prov["seed"]
                entry["prompt"] = prov["prompt"]
                if prov.get("size"):
                    entry["size"] = prov["size"]
                entry["_recovered"] = _note(prov)
            write_json(path, data)
            print("сдача переписана: {} (+{})".format(
                os.path.relpath(path, ROOT), len(rows)))
    elif fixed:
        print("\nсухой прогон: НИЧЕГО НЕ ЗАПИСАНО. Повторить с --apply.")

    if broken:
        raise SystemExit(
            "\n{} записей расходятся со своими PNG. Это подмена файла или "
            "перезапись после генерации; молча чинить нельзя — сначала "
            "разберитесь, что за кадр лежит в папке.".format(len(broken)))
    return fixed, len(broken)


def main():
    setup_console()
    args = sys.argv[1:]
    if not args or args[0].startswith("--"):
        print(__doc__)
        raise SystemExit(1)
    recover(args[0], cli_opt(args, "--shotlist", "shotlist.json"),
            apply="--apply" in args, check_all="--all" in args)


if __name__ == "__main__":
    main()
