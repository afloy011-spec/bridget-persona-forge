"""Ранбук проверяется ИСПОЛНЕНИЕМ: команды из SKILL.md и README.md запускаются.

ПОЧЕМУ НЕ ПОИСКОМ ПО ТЕКСТУ. Ровно так руководство и проверяли до сих пор —
тестом, который ищет в файле подстроку. Он был зелёным на инструкции, где шаг 8
предлагал `contactsheet.py deliverables/projects/bridget/part1_profile`: строка
на месте, скрипт назван правильно, ключи правильные, а каталога с таким именем
нет и не будет, потому что `<proj>` объявлен ПУТЁМ, а папку сдачи именует id
персонажа. Подстрока не отличает команду от строки, похожей на команду.
Отличает только запуск.

ЧТО ЗДЕСЬ ПРОИСХОДИТ. Из фенсед-блоков обоих файлов вынимаются все строки
`py -3 …` (склеиваются переносы `\\`, отрезаются хвостовые комментарии),
плейсхолдеры подставляются значениями, которые сами эти файлы и объявляют, и
каждая команда, выполнимая без GPU и без сети, запускается по-настоящему.
Плейсхолдер, которому нечего подставить (`--placements …`), — это дефект
руководства, а не пропуск теста: команда с многоточием не выполняется.

ГДЕ ЭТО РАБОТАЕТ. Репозиторий копируется во временный каталог, и конвейер
пишет сдачу и документы туда: `deliver.py` и `build_deck.py` кладут результат
рядом со скриптами, и прогон теста иначе перезаписывал бы настоящую сдачу.
Кадры при этом настоящие — реестр хранит абсолютные пути, поэтому рабочий
корень не копируется. Нет кадров или нет insightface (так на CI) — шаги,
которым они нужны, пропускаются с названной причиной, и причина уходит
предупреждением, а не в проглатываемый stdout: непроверенная половина ранбука
обязана быть видна, иначе она неотличима от проверенной.

Прогон долгий (ворота, отбор и калибровка считаются по-настоящему, это минуты).
Быстрее его сделать нельзя, не перестав проверять то, ради чего он написан.
"""
import json
import glob
import os
import re
import shutil
import subprocess
import sys
import warnings

import pytest

from conftest import ROOT, link_dir, work_root

SKILL = os.path.join(ROOT, "SKILL.md")
README = os.path.join(ROOT, "README.md")

# Многоточие (U+2026) и троеточие: место, куда автор руководства не подставил
# значение. Для читателя это «допиши сам», для исполнителя — неработающая
# команда, и в нумерованном ранбуке это дефект.
ELLIPSIS = ("…", "...")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _slash(path):
    """Прямые слэши. Одна и та же команда в SKILL.md и в README.md собирается
    из разных кусков, и `D:/…\\bridget` против `D:/…/bridget` разошлись бы в
    двух строках, которые для системы одинаковы: два запуска вместо одного."""
    return str(path).replace("\\", "/")


def _fenced(text):
    """Содержимое всех ``` -блоков файла."""
    out, cur, inside = [], [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            if inside:
                out.append(cur)
                cur = []
            inside = not inside
            continue
        if inside:
            cur.append(line)
    return out


def _dedent_comment(cmd):
    """Отрезать хвостовой комментарий.

    В README он начинается с `#`, в SKILL.md комментария-маркера нет вовсе —
    пояснение просто набрано в правой колонке по-русски. Поэтому режется по
    первому токену с кириллицей; токен с угловыми скобками из этого правила
    исключён, потому что `<файл>` и `<куда>` — тоже кириллица, но это аргументы.

    Режется ДО подстановки, а не после: временный каталог теста лежит в
    C:/Users/<имя>/AppData/Local/Temp, и подставленный `<куда>` обрубался
    собственным правилом — команда теряла значение ключа и «не выполнялась»
    по вине проверки, а не руководства.
    """
    cmd = cmd.split("#", 1)[0]
    out = []
    for tok in cmd.split():
        if re.search(r"[А-Яа-яЁё]", tok) and not ("<" in tok and ">" in tok):
            break
        out.append(tok)
    return " ".join(out)


def _resolve(src, ctx):
    """Строка руководства → команда, которую можно запустить."""
    return _substitute(_dedent_comment(src), ctx)


def _commands(text):
    """Все команды `py -3 …` из фенсед-блоков, в порядке следования."""
    raw = []
    for block in _fenced(text):
        acc = ""
        for line in block:
            line = line.rstrip()
            if acc:
                acc += " " + line.strip()
            elif "py -3 " in line:
                acc = line[line.index("py -3 "):]
            else:
                continue
            if acc.endswith("\\"):
                acc = acc[:-1].rstrip()
                continue
            raw.append(acc)
            acc = ""
        if acc:
            raw.append(acc)
    out = []
    for cmd in raw:
        # `a && b` в README — две команды, и падать они должны по отдельности.
        out.extend(p.strip() for p in cmd.split("&&"))
    return [c for c in out if c.startswith("py -3 ")]


def _inline_commands(text):
    """Команды, набранные в прозе одиночными обратными кавычками.

    Не всё руководство живёт в нумерованном блоке: выход из частичного вердикта
    объяснён абзацем, и команда там ровно такая же исполняемая, как в ранбуке.
    Фенсед-блоки вырезаются заранее: иначе одиночная кавычка ловится об
    открывающий ``` и «командой в прозе» оказывается весь ранбук.
    """
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    out = []
    for span in re.findall(r"`([^`]+)`", text, re.S):
        span = " ".join(span.split())
        if span.startswith("py -3 ") and "-m pip" not in span:
            out.append(span)
    return out


def _project():
    """Папка проекта, id персонажа и папка сдачи — из данных, а не из прозы."""
    import glob
    cards = sorted(glob.glob(os.path.join(ROOT, "projects", "*", "character.json")))
    if not cards:
        pytest.skip("в репозитории нет ни одного проекта")
    pdir = os.path.dirname(cards[0])
    with open(cards[0], encoding="utf-8") as fh:
        char = json.load(fh)
    return pdir, char.get("id") or os.path.basename(pdir)


def _delivered_jpg(repo, cid):
    d = os.path.join(repo, "deliverables", cid, "part1_profile")
    if not os.path.isdir(d):
        return None
    for f in sorted(os.listdir(d)):
        if f.lower().endswith(".jpg") and "contact_sheet" not in f.lower():
            return f
    return None


def _delivered_part(repo, cid):
    """Папка одной части сдачи под плейсхолдер `<часть>`.

    Плейсхолдер появился, когда шаги доводки перестали быть написаны под
    part1_profile: ранбук говорил «часть 1» там, где имел в виду «любая
    часть», и из-за этого увеличение получила ровно одна часть из трёх, а
    сдача поехала в трёх разных разрешениях. Значение берётся с диска, а не
    зашивается: если папку переименуют, тест обязан упасть здесь, а не
    показать зелёное на несуществующем пути.
    """
    d = os.path.join(repo, "deliverables", cid)
    if not os.path.isdir(d):
        return None
    for f in sorted(os.listdir(d)):
        if os.path.isdir(os.path.join(d, f)) and f != "presentation":
            return "deliverables/%s/%s" % (cid, f)
    return None


def _substitute(cmd, ctx):
    """Плейсхолдеры → значения, объявленные самими SKILL.md и README.md.

    Значения берутся не из текста, а из репозитория: `<proj>` — папка, где
    лежит character.json, `<id>` — поле id из неё. Именно поэтому подмена
    одного другим здесь и ловится: если в руководстве снова окажется
    `deliverables/<proj>/…`, подстановка даст несуществующий путь и команда
    упадёт, вместо того чтобы «выглядеть правильной».
    """
    for src, dst in ctx["subs"]:
        cmd = cmd.replace(src, dst)
    toks = []
    for tok in cmd.split():
        # `--scene day|indoor|night|flash` — перечисление допустимых значений,
        # а не значение. Берём первое: команда обязана работать хотя бы с ним.
        if "|" in tok and not tok.startswith("-") and "/" not in tok:
            tok = tok.split("|")[0]
        toks.append(tok)
    return " ".join(toks)


def _needs(cmd, work):
    """Чего команде не хватит здесь: GPU, реестра кадров, insightface, пула."""
    # ИМЯ БЕРЁТСЯ И ИЗ ПОДКАТАЛОГА. Регулярка `scripts/(\w+)\.py` не видит
    # `scripts/metrics/wrist.py` — в `\w` нет косой черты, — поэтому script
    # выходило пустым, и правило пропуска `if script == "wrist"` двумя
    # десятками строк ниже НЕ СРАБАТЫВАЛО НИ РАЗУ: оно было мёртвым кодом.
    # Замер запястья при этом всё равно «проходил», потому что на пустом
    # каталоге старый код печатал «видна на 0, не видна на 0» и выходил с
    # нулём. То есть тест проверял шаг 9 ровно в том состоянии, в каком тот
    # ничего не делает, и обе ошибки прикрывали друг друга.
    script = re.search(r"scripts/(?:\w+/)*(\w+)\.py", cmd)
    script = script.group(1) if script else ""
    if script == "generate" and "--dry" not in cmd:
        return "нужен GPU: батч отправляется на воркер"
    if script in ("make_tattoo_asset", "build_ui", "build_ui_edit"):
        # Сборщики холста спрашивают у сервера /object_info: сколько портов
        # он ОБЪЯВИЛ, столько и нарисует, а высоты «на глаз» уже дали ноду,
        # вылезшую из рамки.
        return "нужен живой ComfyUI"
    if script == "detail_tattoo":
        # Проход диффузии по окну: без сервера его не выполнить, как и съёмку.
        return "нужен GPU: чернило рисует диффузия"
    if script == "adopt_canvas":
        # Мост читает историю сервера: снятого на холсте без сервера нет.
        return "нужен живой ComfyUI: кадры забираются из истории"
    # Замер запястья идёт двумя кругами по воркеру: разметка поверхностей тела
    # и сегментация по тексту. Без GPU он не выполняется вовсе — как и съёмка.
    if script == "wrist":
        return "нужен GPU: разметка поверхностей считается на воркере"
    # Папку с тату наполняет шаг 9, а он теперь начинается с замера на воркере.
    # Раньше её создавала вклейка по РУЧНОЙ разметке, которая GPU не требовала;
    # разметки больше нет — место считается, — и без GPU этой папки не бывает.
    if script in ("lastmile", "composite_tattoo") and "tattoo" in cmd:
        return "нужен GPU: кадры с тату делает замер запястья (шаг 9)"
    # Перенос лица идёт кругом по воркеру (ReActor), и папку `face` наполняет
    # только он — значит следующий за ним шаг кожи без GPU тоже не выполнится.
    if script == "face_transfer":
        return "нужен GPU: перенос лица считается на воркере"
    if script == "skin_graft" and "/face" in _slash(cmd):
        return "нужен GPU: кадры для прививки готовит перенос лица (шаг 8a)"
    need = set()
    if script in ("gates", "gate_firing", "select_set", "deliver", "qa_report",
                  "identity_calibration"):
        need.add("registry")
    if script in ("gates", "gate_firing", "select_set", "qa_report",
                  "identity_calibration", "deliver"):
        # deliver сам лица не считает, но читает вердикт ворот, а его пишет
        # шаг, которому insightface нужен. Без этого условия сдача была бы
        # «выполнимой» там, где вердикта взяться неоткуда, и падала бы не по
        # своей вине.
        need.add("face")
    if script == "identity_calibration":
        need.add("casting")
    # Сравнивается с ТЕМ рабочим корнем, которым подставляли, а не с боевым.
    # Теневой корень фикстуры — другой путь, и после его появления условие
    # перестало совпадать никогда: команда шага 4 переставала пропускаться
    # там, где кадров нет, и падала «не выполняется как написана». Увидел это
    # CI на всех четырёх задачах — локально кадры есть, и ветка не бралась.
    if script == "contactsheet" and _slash(work) in _slash(cmd):
        need.add("png")
    return need


def _run(cmd, cwd, env, timeout=900):
    # `py -3` из руководства — это лаунчер windows; на CI его нет. Подменяем на
    # тот интерпретатор, которым запущены тесты: проверяется исполнимость
    # команды, а не наличие лаунчера.
    argv = [sys.executable] + cmd.split()[2:]
    return subprocess.run(argv, cwd=cwd, env=env, timeout=timeout,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _env(work):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PERSONA_WORK_ROOT"] = work
    # Заведомо мёртвый адрес: если команда всё же полезет на воркер, пусть
    # падает здесь, а не стучится в чей-то настоящий ComfyUI.
    env["COMFY_HOST"] = "http://127.0.0.1:9"
    return env


def _copy_repo(dst):
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(
        ".git", ".ruff_cache", "__pycache__", "*.pyc", ".pytest_cache"))
    return dst


def _have(module):
    try:
        __import__(module)
        return True
    except Exception:
        return False


def _shadow_work_root(dst, real, cid):
    """Теневой рабочий корень: читается настоящий, пишется временный.

    ЗАЧЕМ. Ранбук выполняется по-настоящему, а среди его шагов есть gates.py —
    он ПЕРЕЗАПИСЫВАЕТ gates.json в рабочем корне. Пока фикстура подставляла
    боевой PERSONA_WORK_ROOT, обычный `pytest -q` молча пересчитывал вердикт
    проекта и клал рядом мусорный s.jpg. Это тот же дефект, который раунд 6
    чинил в тесте ворот: проверка не имеет права портить состояние, по
    которому потом работает конвейер. Копировать корень целиком нельзя — там
    гигабайты PNG.

    Поэтому реестры копируются (они маленькие, и их правят), а папки кадров и
    пул кастинга подключаются junction-ами: записи ранбука идут в тень,
    чтения — по ссылке в настоящие кадры. Пути внутри реестров абсолютные, так
    что ворота и отбор находят кадры и без ссылок; junction нужен ровно
    контакт-листу шага 4, который получает КАТАЛОГ.
    """
    # Ссылка делается общим помощником: junction на windows (через _winapi, а
    # не `cmd /c mklink /J` — путь временной папки содержит кириллицу, и cmd на
    # русской windows её калечит), симлинк на posix. Первая редакция звала
    # _winapi напрямую, и весь файл падал на linux с ModuleNotFoundError ещё
    # в фикстуре: шесть ошибок до единой проверки, и увидеть это можно было
    # только в CI.
    link = link_dir

    for sub in ("frames", "frames_story"):
        src = os.path.join(real, cid, sub)
        if not os.path.isdir(src):
            continue
        os.makedirs(os.path.join(dst, cid, sub), exist_ok=True)
        reg = os.path.join(src, "frames.json")
        if os.path.isfile(reg):
            shutil.copy2(reg, os.path.join(dst, cid, sub, "frames.json"))
        for cell in sorted(os.listdir(src)):
            if os.path.isdir(os.path.join(src, cell)):
                link(os.path.join(src, cell),
                     os.path.join(dst, cid, sub, cell))
    cast = os.path.join(real, cid, "casting")
    if os.path.isdir(cast):
        link(cast, os.path.join(dst, cid, "casting"))
    return dst


@pytest.fixture(scope="module")
def runbook(tmp_path_factory):
    """Один прогон ранбука на весь файл; тесты ниже разбирают его результат."""
    pdir, cid = _project()
    work = _shadow_work_root(str(tmp_path_factory.mktemp("work")),
                             work_root(), cid)
    repo = _copy_repo(str(tmp_path_factory.mktemp("repo") / "persona-forge"))
    outdir = str(tmp_path_factory.mktemp("lastmile-out"))

    # Артефакты, которые ранбук ОБЯЗАН произвести, убираются из копии до
    # прогона. Иначе «файл на месте» доказывало бы только то, что он лежал в
    # репозитории: шаг 5b с путём из неверного плейсхолдера писал бы мимо, а
    # проверка всё равно была бы зелёной.
    shutil.rmtree(os.path.join(repo, "docs", cid), ignore_errors=True)
    for junk in (os.path.join(repo, "deliverables", cid, "presentation", "index.html"),
                 os.path.join(repo, "deliverables", cid, "part1_profile",
                              "contact_sheet.jpg")):
        if os.path.exists(junk):
            os.remove(junk)

    have = {
        "registry": os.path.isfile(os.path.join(work, cid, "frames", "frames.json")),
        "face": _have("insightface") and _have("onnxruntime"),
        # НАЛИЧИЕ ПАПКИ — НЕ НАЛИЧИЕ ПУЛА, и разница стоила зелёного теста на
        # падающей команде. Условие проверяло `isdir`, а пустая папка кастинга
        # остаётся на диске после любого прерванного прогона: пропуск не
        # срабатывал, identity_calibration запускался и падал с «меньше 6
        # кадров с лицом». Считаем кадры, а не каталог.
        "casting": len(glob.glob(os.path.join(work, cid, "casting", "**",
                                              "*.png"), recursive=True)) >= 6,
        "png": os.path.isdir(os.path.join(work, cid, "frames", "P1")),
    }
    why = {"registry": "нет реестра кадров в рабочем корне",
           "face": "нет insightface/onnxruntime",
           "casting": "нет пула кастинга (generate.py --casting)",
           "png": "нет самих кадров в рабочем корне"}

    ctx = {"subs": [
        # ПЕРВЫМ, и порядок здесь значащий: подстановки применяются по списку,
        # и если `<id>` отработает раньше, до этой строки доедет уже
        # «deliverables/bridget/<часть>», она не совпадёт, и команда уйдёт в
        # запуск с угловыми скобками в пути.
        ("deliverables/<id>/<часть>",
         _delivered_part(repo, cid) or "deliverables/%s/part1_profile" % cid),
        ("$PERSONA_WORK_ROOT", _slash(work)),
        ("<W>", _slash(os.path.join(work, cid))),
        ("<proj>", _slash(os.path.relpath(pdir, ROOT))),
        ("<id>", cid),
        ("<куда>", _slash(outdir)),
        ("<outdir>", _slash(outdir)),
        ("<файл>.jpg", _delivered_jpg(repo, cid) or "<файл>.jpg"),
    ]}

    env = _env(work)
    seen, results, picks = {}, [], None

    def record(doc, src, cmd, code=None, out="", skip=None, defect=None):
        results.append({"doc": os.path.basename(doc), "src": _dedent_comment(src),
                        "cmd": cmd, "code": code, "out": out,
                        "skip": skip, "defect": defect})

    for doc in (SKILL, README):
        for src in _commands(_read(doc)):
            cmd = _resolve(src, ctx)
            if not cmd:
                continue
            if "--pick" in cmd and any(e in cmd for e in ELLIPSIS):
                # Строку --pick печатает предыдущий шаг ранбука. Нет такого
                # шага — заполнить её нечем, и это ДЕФЕКТ руководства, а не
                # повод пропустить проверку: пропуск здесь и был бы тем самым
                # зелёным тестом на неработающей инструкции.
                if picks is None:
                    record(doc, src, cmd, defect=(
                        "нечем заполнить --pick: в руководстве нет команды, "
                        "которая печатает готовую строку"))
                    continue
                if picks == "skipped":
                    record(doc, src, cmd, skip="шаг, печатающий --pick, пропущен")
                    continue
                cmd = cmd[:cmd.index("--pick")] + "--pick " + picks
            if cmd in seen:
                record(doc, src, cmd, *seen[cmd])
                continue
            need = _needs(cmd, work)
            missing = ([need] if isinstance(need, str)
                       else [why[n] for n in sorted(need) if not have[n]])
            if missing:
                record(doc, src, cmd, skip="; ".join(missing))
                if "--auto" in cmd:
                    picks = "skipped"
                continue
            proc = _run(cmd, repo, env)
            seen[cmd] = (proc.returncode, proc.stdout.decode("utf-8", "replace"))
            record(doc, src, cmd, *seen[cmd])
            if "--auto" in cmd:
                m = (re.findall(r"--pick\s+(.+)$", seen[cmd][1], re.M)
                     if proc.returncode == 0 else [])
                picks = m[-1].strip() if m else "skipped"

    return {"repo": repo, "work": work, "cid": cid, "pdir": pdir,
            "outdir": outdir, "results": results, "have": have, "ctx": ctx,
            "env": env}


def test_runbook_has_commands(runbook):
    """Сами команды из руководства вынулись — иначе всё ниже зелено вхолостую."""
    assert len(runbook["results"]) >= 12, runbook["results"]
    assert [r for r in runbook["results"] if r["code"] is not None], \
        "ни одна команда ранбука не выполнялась — проверять нечего"


def test_runbook_commands_execute(runbook):
    """Каждая выполнимая команда руководства отрабатывает как написана."""
    bad, skipped = [], []
    for r in runbook["results"]:
        if r["defect"]:
            bad.append(f"{r['doc']}\n  в руководстве: {r['src']}\n"
                       f"  {r['defect']}")
        elif r["skip"]:
            skipped.append(f"{r['doc']}: {r['src']}\n    пропуск: {r['skip']}")
        elif r["code"] != 0:
            bad.append(f"{r['doc']}\n  в руководстве: {r['src']}\n"
                       f"  запущено:      {r['cmd']}\n  код {r['code']}\n"
                       f"  {r['out'].strip()[-700:]}")
    # Пропуски объявляются ПРЕДУПРЕЖДЕНИЕМ, а не print: на зелёном тесте
    # печать в stdout проглатывается, и «половина ранбука не проверялась»
    # выглядело бы точно так же, как «ранбук проверен целиком». На CI без
    # кадров и без insightface сюда попадает большинство шагов.
    if skipped:
        warnings.warn(UserWarning(
            "команды ранбука, не выполненные в этой среде:\n"
            + "\n".join("  " + s for s in skipped)))
    assert not bad, "команды руководства не выполняются как написаны:\n\n" + \
                    "\n\n".join(bad)


def test_no_unfilled_placeholders(runbook):
    """Многоточие и нераскрытый `<…>` в команде — это невыполнимая команда."""
    bad = []
    for r in runbook["results"]:
        rest = re.sub(r"--pick\s+.*$", "", r["cmd"])
        if any(e in rest for e in ELLIPSIS) or re.search(r"<[^>]+>", rest):
            bad.append(f"{r['doc']}: {r['src']}\n"
                       f"    после подстановки: {r['cmd']}")
    assert not bad, ("в руководстве есть команды, которые нечем заполнить "
                     "(плейсхолдер не объявлен или оставлено многоточие):\n"
                     + "\n".join(bad))


def test_runbook_produces_promised_files(runbook):
    """Файлы, которые руководство обещает, появляются от прогона ранбука.

    Проверка на существование работает потому, что фикстура эти файлы из копии
    удалила. Без удаления она доказывала бы только, что они лежат в git.
    """
    repo, cid = runbook["repo"], runbook["cid"]
    ran = {r["cmd"] for r in runbook["results"] if r["code"] == 0}

    def made_by(needle):
        return any(needle in c for c in ran)

    want = []
    if made_by("export_docs.py"):
        want += [f"docs/{cid}/character_bible.md", f"docs/{cid}/shotlist_part1.md"]
    if made_by("gate_firing.py"):
        want.append(f"docs/{cid}/gate_firing.md")
    if made_by("qa_report.py"):
        want.append(f"docs/{cid}/qa_report.md")
    if made_by("identity_calibration.py"):
        want.append(f"docs/{cid}/identity_calibration.json")
    if made_by("contactsheet.py deliverables"):
        want.append(f"deliverables/{cid}/part1_profile/contact_sheet.jpg")
    if made_by("build_deck.py"):
        want.append(f"deliverables/{cid}/presentation/index.html")

    missing = [w for w in want if not os.path.exists(os.path.join(repo, w))]
    assert not missing, ("ранбук отработал без ошибок, но обещанных файлов "
                         "нет:\n  " + "\n  ".join(missing))


def test_runbook_writes_nowhere_else(runbook):
    """Ранбук не заводит каталогов, собранных из перепутанного плейсхолдера.

    Отдельно от кода возврата: `gate_firing.py --md docs/<proj>/gate_firing.md`
    завершается УСПЕХОМ и молча создаёт `docs/projects/bridget/` — команда
    «работает», а документ уезжает мимо. Ноль на выходе такого не ловит.
    """
    repo = runbook["repo"]
    strays = []
    for parent in ("docs", "deliverables"):
        p = os.path.join(repo, parent)
        if not os.path.isdir(p):
            continue
        for name in sorted(os.listdir(p)):
            if name in ("projects", "deliverables", "docs", "scripts", "assets"):
                strays.append(f"{parent}/{name}")
    assert not strays, ("ранбук создал каталоги, которых в раскладке проекта "
                        "нет — плейсхолдер подставлен не тот:\n  "
                        + "\n  ".join(strays))


def test_partial_verdict_has_a_documented_way_out(runbook, tmp_path):
    """Из частичного вердикта руководство обязано выводить исполнимой командой.

    `gates.py --only …` перезаписывает вердикт целиком, и отбор после него
    отказывается работать — правильно отказывается. Значит в руководстве
    должна стоять команда, которая из этого состояния выводит, и она должна
    работать. Состояние собирается в отдельном рабочем корне: реестр хранит
    абсолютные пути до кадров, поэтому копии подлежит только frames.json, а
    общий вердикт настоящего прогона не трогается.
    """
    if not (runbook["have"]["registry"] and runbook["have"]["face"]):
        pytest.skip("нет реестра кадров или insightface")
    cid, repo = runbook["cid"], runbook["repo"]
    work2 = str(tmp_path / "work")
    os.makedirs(os.path.join(work2, cid, "frames"))
    shutil.copy(os.path.join(runbook["work"], cid, "frames", "frames.json"),
                os.path.join(work2, cid, "frames", "frames.json"))
    env = _env(work2)
    proj = os.path.relpath(runbook["pdir"], ROOT).replace("\\", "/")

    gate = _run(f"py -3 scripts/gates.py {proj} --only P1,P2", repo, env)
    assert gate.returncode == 0, gate.stdout.decode("utf-8", "replace")[-700:]

    strict = _run(f"py -3 scripts/select_set.py {proj} --top 1", repo, env)
    assert strict.returncode != 0, (
        "отбор принял частичный вердикт — про неизмеренные ячейки в файле нет "
        "ничего, и рекомендованный набор был бы наугад")

    ways = [c for c in _inline_commands(_read(SKILL)) + _commands(_read(SKILL))
            if "select_set.py" in c and "--partial-ok" in c]
    assert ways, ("руководство описывает состояние, из которого само же не "
                  "выводит: команды с --partial-ok в SKILL.md нет")
    cmd = _resolve(ways[0], runbook["ctx"])
    ok = _run(cmd, repo, env)
    assert ok.returncode == 0, (
        f"{cmd}\n" + ok.stdout.decode("utf-8", "replace")[-700:])
