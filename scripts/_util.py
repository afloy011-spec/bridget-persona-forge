#!/usr/bin/env python3
"""Мелочи, общие для всех скриптов скилла."""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def setup_console():
    """Заставить stdout говорить в UTF-8.

    Русская Windows отдаёт консоли cp1251, и первый же 'décolleté' в промпте
    роняет скрипт с UnicodeEncodeError посреди батча. Вызывать первой строкой
    в main() каждого скрипта.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def manifest():
    with open(os.path.join(ROOT, "assets.json"), encoding="utf-8") as fh:
        return json.load(fh)


def character_lora(char_id=None, man=None):
    """Персонажная лора манифеста, проверенная на принадлежность персонажу.

    ЗАЧЕМ ЭТА ФУНКЦИЯ ЕСТЬ. `models.character_lora` — ключ ГЛОБАЛЬНЫЙ, а
    личность в нём принадлежит конкретному человеку. Пока проект был один,
    это совпадало случайно. Замер на втором и третьем: `py -3
    scripts/prompts.py projects/marek` печатал `brdgt_w, a candid photograph
    of a real man, ... a 57-year-old man...` — то есть лицо 51-летней женщины
    на полной силе уезжало в кадры 57-летнего мужчины, молча. Папки выхода
    при этом разводились правильно, поэтому подмену было видно только в
    пикселях.

    Ключ `for` называет id персонажа, которому лора принадлежит. Несовпадение
    — ОТКАЗ, а не тихий пропуск: лора ставит лицо В САМУ МОДЕЛЬ, и потерять
    полминуты на отказе дешевле, чем полчаса GPU на сорока кадрах чужого
    человека. Отсутствие `for` — старый манифест: работаем как раньше, но
    говорим об этом вслух.

    Возвращает словарь лоры либо {}: вызывающему не нужно знать, отключена
    она, не настроена или не подошла.
    """
    ch = ((man or manifest())["models"].get("character_lora") or {})
    if not ch.get("name"):
        return {}
    owner = ch.get("for")
    if owner and char_id and owner != char_id:
        _say_once(
            "персонажной лоры для «{}» нет: {} обучена на «{}». Идентичность "
            "берётся отбором набора (select_set.py) — это штатный режим, а не "
            "поломка. Своя лора заводится в assets.json -> "
            "models.character_lora.".format(char_id, ch["name"], owner))
        return {}
    if owner is None:
        _say_once(
            "у персонажной лоры {} нет ключа `for` — некому проверить, тому "
            "ли персонажу она принадлежит.".format(ch["name"]))
    return ch


_SAID = set()


def _say_once(msg):
    """Сказать в stderr ОДИН РАЗ за процесс.

    Батч зовёт разрешение лоры на каждый кадр, и без этого сорок одинаковых
    строк утопили бы всё остальное — а предупреждение, которое печатается
    сорок раз, читается как шум и перестаёт работать предупреждением.
    """
    if msg not in _SAID:
        _SAID.add(msg)
        sys.stderr.write("ВНИМАНИЕ: " + msg + "\n")


def work_root():
    """Корень рабочей папки. PERSONA_WORK_ROOT перебивает манифест.

    Отдельной функцией потому, что то же разрешение нужно и без создания
    каталогов: `generate.py --dry` обещан как «ничего не отправляя», значит и
    папок не создаёт, а раньше он ради этого читал манифест НАПРЯМУЮ и
    переменную окружения игнорировал — то есть печатал план для одной папки,
    а писал бы в другую.
    """
    root = os.environ.get("PERSONA_WORK_ROOT") or manifest()["paths"]["work_root"]
    root = os.path.expanduser(root)
    return root if os.path.isabs(root) else os.path.join(ROOT, root)


def work_relative(path):
    """Путь кадра ОТ РАБОЧЕГО КОРНЯ, а не от диска.

    ПОЧЕМУ НЕ АБСОЛЮТНЫЙ. `selection.json` едет в сдачу и в репозиторий, а
    абсолютный путь несёт в себе имя пользователя машины, на которой снимали
    (`C:/Users/<имя>/...`). Для чтения оно не нужно ни одному скрипту —
    рабочий корень и так известен из окружения, — а при передаче файла
    третьей стороне это личные данные, попавшие туда без всякой надобности.

    Путь вне рабочего корня возвращается как есть: выдумывать ему
    относительность не от чего.
    """
    root = work_root()
    try:
        rel = os.path.relpath(os.path.abspath(path), root)
    except ValueError:              # другой диск
        return str(path).replace("\\", "/")
    if rel.startswith(".."):
        return str(path).replace("\\", "/")
    return rel.replace("\\", "/")


def work_resolve(rel):
    """Обратное к work_relative: относительный путь снова в абсолютный."""
    if not rel:
        return rel
    if os.path.isabs(rel):
        return rel
    return os.path.join(work_root(), rel).replace("\\", "/")


def work_dir(*parts):
    """Рабочая папка проекта. Всё локально — на сервере не остаётся ничего."""
    p = os.path.join(work_root(), *[str(x) for x in parts])
    os.makedirs(p, exist_ok=True)
    return p


def imread(path, flags=None):
    """cv2.imread, который работает на пути с кириллицей.

    cv2 на Windows отдаёт путь в системную ANSI-кодировку и на
    C:/Users/<имя>/... молча возвращает None — а imwrite так же молча ничего
    не пишет и возвращает False, который никто не проверяет. Файл читается
    питоном и декодируется из буфера.
    """
    import numpy as np, cv2
    if flags is None:
        flags = cv2.IMREAD_COLOR
    with open(path, "rb") as fh:
        buf = np.frombuffer(fh.read(), dtype=np.uint8)
    return cv2.imdecode(buf, flags)


def imwrite(path, img):
    """cv2.imwrite для пути с кириллицей. Бросает, а не возвращает False."""
    import cv2
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise OSError(f"не закодировалось в {ext}: {path}")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(buf.tobytes())
    return path


def project_name(project_dir, shots=None, char=None):
    """Имя проекта — ОДНО правило на весь конвейер.

    Раньше правил было четыре: generate/gates/casting брали
    shots["project"] с запасным вариантом по имени папки, select_set и
    deliver — тот же ключ БЕЗ запасного (и получали None, а с ним каталог
    «None» и ложное «сначала запусти generate.py»), qa_report подставлял
    жёстко 'bridget'. Каталог рабочей папки при этом собирается из этого
    имени, то есть ступени конвейера расходились по разным папкам молча.
    """
    # ПОРЯДОК: карточка → раскадровка → имя папки. Карточка первая потому,
    # что она и есть персонаж; раскадровок у проекта несколько, и её ключ
    # project легко забыть поправить при копировании — именно так у
    # скопированного персонажа все ступени 3-7 писали в папку донора, а шаг 12
    # искал в своей и находил пусто.
    if char and char.get("id"):
        return char["id"]
    if shots and shots.get("project"):
        return shots["project"]
    return os.path.basename(str(project_dir).rstrip("/\\"))


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def cli_opt(args, key, default=None):
    """Значение ключа командной строки — с одним и тем же сторожем везде.

    Ключ последним аргументом или ключ, за которым стоит другой ключ, — это
    обычная опечатка. Голый args[i+1] даёт IndexError с трейсбеком вместо
    имени ключа, а int('--dry') падает ещё непонятнее.

    ПОЧЕМУ ОБЩИЙ, А НЕ ПО КОПИИ В КАЖДОМ ФАЙЛЕ. Копий было четырнадцать, а
    сторож стоял в трёх — и это подавалось как «обход завершён». Разбор
    аргументов у всех скриптов одинаков ровно настолько, насколько одинакова
    и ошибка; чинить его по одному файлу значит чинить его бесконечно.
    """
    if key not in args:
        return default
    i = args.index(key) + 1
    if i >= len(args) or args[i].startswith("--"):
        raise SystemExit(f"у ключа {key} нет значения")
    return args[i]


def same_path(a, b):
    """Один ли это файл (или каталог) — по иноду, а не по строке пути.

    Строковое сравнение ловит только те псевдонимы, которые придумал
    сравнивающий: abspath пропускает смену регистра, normcase пропускает
    junction (mklink /J) и короткое имя 8.3 — а именно в него раскрывается
    %TEMP% на этой машине, — и оба они пропускают ЖЁСТКУЮ ССЫЛКУ, у которой
    realpath честно возвращает другое имя того же файла. os.path.samefile
    спрашивает файловую систему и закрывает их все разом.

    Копий этой функции было две — в lastmile и в composite_tattoo, — и обе
    защищали от одного и того же: шаг, который не идемпотентен, писал поверх
    своего входа. Две копии одного сторожа расходятся на первой же правке.

    Строковое сравнение остаётся запасным: samefile требует, чтобы оба пути
    существовали, а приёмника обычно ещё нет.
    """
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except OSError:
        pass
    norm = lambda p: os.path.normcase(os.path.normpath(os.path.realpath(p)))
    return norm(a) == norm(b)


def age_band(char, gates=None):
    """Полоса возраста ЭТОГО персонажа: (нижняя, верхняя).

    Считается от character.json → age и допуска из манифеста, а не берётся
    готовыми числами. Прежние age_min/age_max были верны ровно для одной
    карточки, и второй персонаж проваливал ворота возраста самим фактом
    своего существования — ворота, зашитые под одного человека, это не ворота
    системы.

    Старые ключи поддерживаются как запасной вариант: вердикт, снятый до
    правки, читается без перепрогона.
    """
    g = gates if gates is not None else manifest()["gates"]
    if "age_below" not in g or "age_above" not in g:
        return float(g["age_min"]), float(g["age_max"])
    age = (char or {}).get("age")
    if age is None:
        raise SystemExit("в карточке персонажа нет поля age — полосу возраста "
                         "не от чего считать")
    return float(age) - float(g["age_below"]), float(age) + float(g["age_above"])


def gate_fingerprint(gates=None):
    """Отпечаток настройки ворот: имена + ВСЕ числовые пороги.

    Одна функция на всех — тот, кто пишет вердикт, тот, кто его читает, и
    тесты. Три копии этого словаря разошлись бы на первой же новой строке
    манифеста, и разошлись бы молча: читатель сравнивал бы с тем, чего писатель
    не кладёт, и отвергал бы каждый вердикт — либо наоборот.
    """
    g = gates if gates is not None else manifest()["gates"]
    return {"required": sorted(g.get("required") or []),
            "informational": sorted(g.get("informational") or []),
            "thresholds": {k: v for k, v in sorted(g.items())
                           if not k.startswith("_")
                           and isinstance(v, (int, float))}}


def read_verdict(path, strict=True):
    """Прочитать gates.json и УБЕДИТЬСЯ, что он про сегодняшний манифест.

    Вердикт живёт дольше своего прогона: отбор, сдача и отчёт читают его как
    истину, и никто из них не спрашивает, каким набором ворот он получен.
    Поэтому один эксперимент с другим манифестом подменяет его целиком —
    именно это и случилось: тест, проверяющий отказ ворот при пустом
    required, прогнал настоящий gates.py по настоящему рабочему корню и
    оставил на диске правдоподобный вердикт, где не отгружалось НИЧЕГО.
    Кадры при этом были в порядке. Следующий человек ищет причину в кадрах.

    СВЕРЯЮТСЯ И ПОРОГИ, А НЕ ТОЛЬКО ИМЕНА ВОРОТ. Первая редакция сравнивала
    два списка имён и пропускала вердикт, снятый при face_sharp_min 70, туда,
    где в манифесте стоит 118: ворота те же, числа другие, а разница между
    ними — это ровно то, что ворота и делают.

    Возвращает (данные, причина расхождения|None). При strict расхождение —
    это отказ, а не предупреждение: работать по чужому вердикту хуже, чем
    не работать вовсе, потому что результат выглядит законным.
    """
    data = read_json(path)
    want = gate_fingerprint()
    got = data.get("gate_config")
    why = None
    if got is None:
        why = ("вердикт написан до того, как в него начали класть настройку "
               "ворот — сверить не с чем")
    elif "thresholds" not in got:
        why = ("вердикт написан до того, как в отпечаток стали класть пороги "
               "— имена ворот совпадают, а числа сверить не с чем")
    elif got != want:
        diff = [f"{k}: в файле {got['thresholds'].get(k, '—')}, "
                f"в манифесте {v}"
                for k, v in want["thresholds"].items()
                if got["thresholds"].get(k) != v]
        diff += [f"{k}: в файле {v}, в манифесте — (порога больше нет)"
                 for k, v in got["thresholds"].items()
                 if k not in want["thresholds"]]
        why = (f"вердикт получен другой настройкой ворот:\n"
               f"    в файле:     обязательные {got.get('required')}, "
               f"справочные {got.get('informational')}\n"
               f"    в манифесте: обязательные {want['required']}, "
               f"справочные {want['informational']}"
               + ("\n    пороги: " + "; ".join(diff) if diff else ""))
    if why and strict:
        raise SystemExit(f"ВЕРДИКТ НЕ ТОТ: {path}\n  {why}\n"
                         f"  Перепрогнать: py -3 scripts/gates.py <project>")
    return data, why


def verdict_coverage(data):
    """Что этот вердикт НЕ покрывает. Возвращает причину или None.

    --only перезаписывает gates.json целиком: строки остальных ячеек из файла
    исчезают, и отсутствие строки неотличимо от «кадра не было». Отбор читал
    это как «прошёл» и рекомендовал непромеренный кадр готовой строкой
    --pick — тот же дефект, который раунд 4 уже чинил в сдаче; qa_report
    печатал «8 of 8» про часть из сорока кадров. Предупреждение gates.py о
    частичности печаталось только в stdout и до потребителя не доезжало.

    Старые вердикты (без поля coverage) определяются по полю only, которое
    пишется с самого начала: без этой ветки починка не действовала бы на том
    единственном файле, ради которого написана.
    """
    cov = data.get("coverage") or {}
    partial = cov.get("partial")
    if partial is None:
        partial = bool(data.get("only"))
    if not partial:
        return None
    cells = cov.get("cells_measured") or data.get("only") or []
    missing = sorted(set(cov.get("cells_in_registry") or []) - set(cells))
    return (f"вердикт ЧАСТИЧНЫЙ: ворота считались только по "
            f"{', '.join(map(str, cells)) or '?'}"
            + (f"; не измерены {', '.join(map(str, missing))}" if missing else "")
            + f" ({cov.get('frames_measured', '?')} кадров из "
              f"{cov.get('frames_in_registry', '?')} в реестре)")


def write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return path
