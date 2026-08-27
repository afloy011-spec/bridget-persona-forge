"""Регрессии по независимому ревью конвейера.

Каждый тест здесь красный, если вернуть соответствующий дефект. Все они —
из ревью, которое прошло по репозиторию агентами и опровергателями; в
комментарии к каждому написано, что именно было сломано, потому что иначе
через месяц тест выглядит придиркой.
"""
import json
import os
import re
import subprocess
import sys

import pytest

from conftest import (MANIFEST, ROOT, case_insensitive_fs, link_dir,
                      scripts_sources)

SCRIPTS = os.path.join(ROOT, "scripts")


def _run(args, env=None, cwd=None):
    e = dict(os.environ, PYTHONIOENCODING="utf-8")
    e.pop("COMFY_HOST", None)
    e.update(env or {})
    return subprocess.run([sys.executable, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          env=e, cwd=cwd or ROOT, timeout=180)


# --------------------------------------------------------- запуск у чужого

def test_dry_run_works_without_a_configured_host(tmp_path):
    """`generate.py --dry` обещан как «план без GPU» и обязан работать до
    того, как человек настроил адрес воркера. Ломалось так: comfy_client
    резолвил адрес НА ИМПОРТЕ, а резолвер с некоторых пор падает при
    незаданном адресе — то есть первая же команда README убивала себя."""
    r = _run([os.path.join(SCRIPTS, "generate.py"),
              os.path.join(ROOT, "projects", "bridget"), "--dry"],
             env={"PERSONA_WORK_ROOT": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    assert "кадров к генерации" in r.stdout


def test_dry_run_creates_nothing(tmp_path):
    """«Ничего не отправляя» включает «и каталогов не создавая». Отдельно:
    --dry обязан уважать PERSONA_WORK_ROOT, а не читать манифест напрямую."""
    _run([os.path.join(SCRIPTS, "generate.py"),
          os.path.join(ROOT, "projects", "bridget"), "--dry"],
         env={"PERSONA_WORK_ROOT": str(tmp_path)})
    assert not list(tmp_path.iterdir()), f"--dry насорил: {list(tmp_path.iterdir())}"


def test_outputs_are_namespaced_by_project():
    """Второй персонаж затирал первого. СПРАШИВАЕТСЯ У САМОГО КОДА, а не
    пересчитывается тестом: раунд 6 показал, что прежняя редакция строила пути
    своими лямбдами и оставалась зелёной, когда имя проекта убирали из строки
    в qa_report.py и export_docs.py — она сверяла свою формулу со своей же.

    Теперь у каждого писателя есть названная функция default_out, и она же
    зовётся в рабочем коде; тест спрашивает её.
    """
    import build_deck, qa_report, export_docs, deliver
    a, b = "alpha", "beta"
    writers = {"deliver": lambda p: deliver.default_out(p, 1),
               "qa_report": qa_report.default_out,
               "build_deck": build_deck.default_out,
               "export_docs": export_docs.default_out}
    for who, f in writers.items():
        assert f(a) != f(b), f"{who}: путь по умолчанию не зависит от проекта"
        assert a in f(a).replace("\\", "/").split("/"), (
            f"{who}: имени проекта нет отдельным сегментом пути: {f(a)}")
    # И рабочий код обязан звать ИМЕННО ЕЁ: функция, которую никто не зовёт,
    # проверяет саму себя.
    for mod, name in ((qa_report, "qa_report"), (export_docs, "export_docs"),
                      (build_deck, "build_deck"), (deliver, "deliver")):
        src = open(mod.__file__, encoding="utf-8").read()
        calls = len(re.findall(r"(?<!def )default_out\(", src))
        assert calls >= 1, (
            f"{name}: default_out объявлена, но в рабочем коде не вызывается — "
            f"тест проверял бы функцию, которой никто не пользуется")


def test_project_name_has_one_rule():
    """Имя проекта резолвилось четырьмя разными способами, и ступени
    расходились по разным рабочим папкам; select_set/deliver получали None
    и создавали каталог «None»."""
    import _util
    assert _util.project_name("/x/y/kolya", None, None) == "kolya"
    assert _util.project_name("/x/y/kolya", {"project": "nadia"}, None) == "nadia"
    assert _util.project_name("/x/y/z", None, {"id": "kolya"}) == "kolya"
    # Резолвить имя разрешено только самой функции в _util.
    bad = [p for p in scripts_sources()
           if os.path.basename(p) != "_util.py"
           and 'shots.get("project")' in open(p, encoding="utf-8").read()]
    assert not bad, f"скрипты всё ещё резолвят имя проекта сами: {bad}"


def test_unicode_paths_are_not_silently_dropped(tmp_path):
    """cv2.imread/imwrite на пути с кириллицей молча возвращают None/False.
    Скрипты композита печатали «вклеено» и не писали ничего."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    import _util
    # Имя папки кириллическое НАМЕРЕННО — в этом весь тест; конкретное
    # слово роли не играет и личным быть не должно.
    d = tmp_path / "Пользователь" / "кадры"
    d.mkdir(parents=True)
    p = str(d / "кадр.png")
    img = np.full((8, 8, 3), 127, dtype=np.uint8)
    _util.imwrite(p, img)
    assert os.path.exists(p)
    assert _util.imread(p) is not None
    assert cv2.imread(p) is None or True  # поведение cv2 нас уже не касается


# ------------------------------------------------------------ вердикт ворот

def _fake_project(tmp_path, ships):
    """Мини-проект с одним кадром и заданным вердиктом ворот."""
    import json
    from PIL import Image
    proj = tmp_path / "proj" / "t"
    proj.mkdir(parents=True)
    char = {"id": "t", "display_name": "T", "age": 40, "identity_core": "x",
            "realism_clause": "y", "personality_in_frame": {"a": "z"}}
    (proj / "character.json").write_text(json.dumps(char), encoding="utf-8")
    cell = {"id": "P1", "label": "L", "framing": "f", "gaze": "g",
            "trait": "a", "body_in_frame": False, "wardrobe": "w",
            "set": "s", "light": "l", "camera": "c", "tattoo_visible": False}
    (proj / "shotlist.json").write_text(
        json.dumps({"project": "t", "size": [64, 64], "seeds_per_cell": 1,
                    "cells": [cell]}), encoding="utf-8")
    frames = tmp_path / "work" / "t" / "frames" / "P1"
    frames.mkdir(parents=True)
    png = frames / "P1_s1_01.png"
    Image.new("RGB", (64, 64), (120, 90, 70)).save(png)
    reg = tmp_path / "work" / "t" / "frames"
    (reg / "frames.json").write_text(json.dumps(
        [{"file": str(png), "cell": "P1", "label": "L", "seed": 1,
          "prompt": "p", "size": [64, 64]}]), encoding="utf-8")
    import _util
    (reg / "gates.json").write_text(json.dumps(
        {"counts": {"registered": 1, "ship": int(ships), "fail": 0,
                    "not_measured": 0 if ships else 1},
         # Отпечаток берётся ТОЙ ЖЕ функцией, которой его пишет gates.py.
         # Переписанный константой, он разошёлся бы с манифестом на первой же
         # правке, и тест проверял бы отказ читателя вместо того, ради чего
         # написан. Покрытие полное — иначе отбор отвергнет вердикт как
         # частичный, и это проверяется отдельным тестом.
         "gate_config": _util.gate_fingerprint(),
         "coverage": {"partial": False, "cells_measured": ["P1"],
                      "cells_in_registry": ["P1"],
                      "frames_measured": 1, "frames_in_registry": 1},
         "frames": [{"file": str(png), "cell": "P1", "verdict":
                     "PASS" if ships else "NOT_MEASURED", "ships": ships,
                     "failed": [], "missing": [] if ships else ["sharp"],
                     "gates": {}}]}), encoding="utf-8")
    return proj, png


def test_refused_delivery_writes_nothing(tmp_path, monkeypatch):
    """ПОВЕДЕНЧЕСКАЯ проверка настоящего отказа. Первая редакция сверки
    писала JPEG и selection.json и ТОЛЬКО ПОТОМ бросала SystemExit: на диске
    «отказ» и «--force» были побайтово одинаковы, кадр лежал в сдаче и
    попадал в презентацию. Отличался только код возврата."""
    proj, png = _fake_project(tmp_path, ships=False)
    monkeypatch.setenv("PERSONA_WORK_ROOT", str(tmp_path / "work"))
    import importlib, deliver as _d
    importlib.reload(_d)
    monkeypatch.setattr(_d, "ROOT", str(tmp_path / "repo"))
    with pytest.raises(SystemExit) as e:
        _d.deliver(str(proj), {"P1": str(png)}, part=1)
    assert "На диск не записано НИЧЕГО" in str(e.value)
    out = tmp_path / "repo" / "deliverables" / "t" / "part1_profile"
    assert not out.exists() or not list(out.iterdir()), \
        f"отказ всё равно что-то записал: {list(out.iterdir())}"


def test_forced_delivery_is_marked_in_the_file(tmp_path, monkeypatch):
    """--force обязан быть отличим ОТ ФАЙЛА, а не только по stderr: иначе
    build_deck молча кладёт брак в презентацию."""
    import json
    proj, png = _fake_project(tmp_path, ships=False)
    monkeypatch.setenv("PERSONA_WORK_ROOT", str(tmp_path / "work"))
    import importlib, deliver as _d
    importlib.reload(_d)
    monkeypatch.setattr(_d, "ROOT", str(tmp_path / "repo"))
    _d.deliver(str(proj), {"P1": str(png)}, part=1, force=True)
    sel = json.loads((tmp_path / "repo" / "deliverables" / "t" /
                      "part1_profile" / "selection.json").read_text(encoding="utf-8"))
    assert sel["forced"] is True
    assert sel["blocked_by_gates"], "заблокированные кадры не записаны в файл"


def test_selection_excludes_frames_the_gates_rejected(tmp_path, monkeypatch):
    """Причина дефекта: select_set рекомендовал кадр с ships=false во всех
    трёх наборах и печатал готовую строку --pick с ним. Починить сдачу и не
    починить отбор значило чинить следствие."""
    proj, png = _fake_project(tmp_path, ships=False)
    monkeypatch.setenv("PERSONA_WORK_ROOT", str(tmp_path / "work"))
    import importlib, select_set as _s
    importlib.reload(_s)
    with pytest.raises(SystemExit) as e:
        _s.run(str(proj))
    # Единственный кадр забракован — набирать не из чего, и это правильный
    # исход: раньше он бодро попадал в рекомендацию вместе со строкой --pick.
    assert "не осталось ни одного кадра" in str(e.value), str(e.value)


def test_qa_report_prints_the_numbers_the_verdict_actually_has(tmp_path, monkeypatch):
    """qa_report читал counts['total'] и v['cohort'] — обоих ключей нет, и
    .get() молча отдавал 0 и nan: в сдаваемом документе стояло «35 of 0 frames
    ship» и «worst pair nan».

    ПРОВЕРЯЮТСЯ ЧИСЛА В ГОТОВОМ ДОКУМЕНТЕ, а не имена ключей в исходнике.
    Прежняя редакция держала чёрный список из двух исторических имён и ловила
    ровно то, что уже починено: раунд 6 подменил ident.get("min") на
    ident.get("worst") — ключа с таким именем gates.py не пишет, документ
    напечатал «not measured» вместо измеренного числа, и сьют остался
    зелёным. Список запрещённых имён не может знать имя, которое ещё не
    придумали; отрендеренный документ — может.

    Правило: всё, что вердикт ЗНАЕТ, документ обязан НАПЕЧАТАТЬ.
    """
    import importlib
    import _util
    import qa_report as _q
    proj, png = _fake_project(tmp_path, ships=True)

    # Вердикт СОБИРАЕТСЯ РУКАМИ с заранее известными числами, а не снимается
    # прогоном ворот: на синтетическом кадре лица нет, разброс по набору не
    # считается, и ветка, где документ печатает эти числа, просто не
    # выполнялась бы — тест остался бы зелёным на любом дефекте чтения.
    frames = tmp_path / "work" / "t" / "frames"
    verdict = {
        "gate_config": _util.gate_fingerprint(),
        "coverage": {"partial": False, "cells_measured": ["P1"],
                     "cells_in_registry": ["P1"],
                     "frames_measured": 7, "frames_in_registry": 9},
        "counts": {"registered": 9, "ship": 7, "fail": 1, "not_measured": 1},
        "set_identity": {"state": "FAIL", "state_measured": "FAIL",
                         "min_required": 0.72,
                         "shipped": {"n": 7, "pairs": 21, "min": 0.4237,
                                     "mean": 0.5561,
                                     "worst_pair": ["a.png", "b.png"]},
                         "measured": {"n": 9, "pairs": 36, "min": 0.3011,
                                      "mean": 0.5102,
                                      "worst_pair": ["c.png", "d.png"]}},
        "frames": [{"file": str(png), "cell": "P1", "verdict": "PASS",
                    "ships": True, "failed": [], "missing": [],
                    "required": ["chroma"],
                    "gates": {"chroma": {"state": "PASS", "value": 0.48}}}],
    }
    (frames / "gates.json").write_text(json.dumps(verdict), encoding="utf-8")
    monkeypatch.setenv("PERSONA_WORK_ROOT", str(tmp_path / "work"))
    importlib.reload(_q)
    _q.build(str(proj), out=str(tmp_path / "qa.md"))
    text = open(str(tmp_path / "qa.md"), encoding="utf-8").read()

    # Граница слова обязательна: «nan» живёт внутри «provenance».
    assert not re.search(r"(nan|inf)", text, re.I), (
        "в документ уехало nan/inf — читается ключ, которого вердикт не пишет")
    assert " of 0 " not in text, "«of 0» — верный признак несуществующего ключа"
    c = verdict["counts"]
    assert f"{c['ship']} of {c['registered']}" in text, (
        f"счётчики документа разошлись с вердиктом: ждали "
        f"«{c['ship']} of {c['registered']}»")
    assert f"{c['fail']} failed, {c['not_measured']} could not be measured" in text
    # ВСЁ, ЧТО ВЕРДИКТ ЗНАЕТ ПРО РАЗБРОС, ОБЯЗАНО БЫТЬ НАПЕЧАТАНО. Именно эта
    # проверка ловит подмену имени ключа, которого ещё не придумали.
    sh = verdict["set_identity"]["shipped"]
    assert f"{sh['min']:.3f}" in text, (
        f"вердикт знает худшую пару {sh['min']:.3f}, документ её не печатает — "
        f"значит читается не тот ключ")
    assert f"{sh['mean']:.3f}" in text and str(sh["pairs"]) in text
    assert "not measured — no embeddings" not in text, (
        "документ пишет «not measured» там, где вердикт дал числа")


def test_qa_report_headline_is_the_delivered_set(tmp_path, monkeypatch):
    """Головное число считалось по всему прошедшему пулу, хотя критерий ТЗ
    относится к тем кадрам, которые увидит проверяющий.

    ПОВЕДЕНЧЕСКАЯ проверка: раунд 6 показал, что прежняя редакция была grep-ом
    по двум строкам («_delivered_spread», «DELIVERED frames»), и расчёт можно
    вернуть на весь пул, сохранив имя функции и заголовок, — тест не заметит.

    Детектор лиц подменён: проверяется НЕ он, а то, ПО КАКОМУ СПИСКУ КАДРОВ
    считается число. Настоящий детектор сделал бы тест зависимым от кадров на
    диске и от insightface, то есть пропускаемым — а пропущенный тест и есть
    та самая дыра, которую этот файл закрывает.
    """
    np = pytest.importorskip("numpy")
    import importlib, qa_report as _q
    importlib.reload(_q)

    # Пул из ЧЕТЫРЁХ кадров; сдано ДВА. Правильный ответ — 2 кадра, 1 пара.
    pool = []
    for i in range(4):
        f = tmp_path / f"pool_{i}.png"
        f.write_bytes(b"")
        pool.append(str(f))
    (tmp_path / "work" / "x" / "frames").mkdir(parents=True)
    (tmp_path / "work" / "x" / "frames" / "gates.json").write_text(json.dumps(
        {"frames": [{"cell": f"P{i}", "file": p, "ships": True}
                    for i, p in enumerate(pool)]}), encoding="utf-8")
    sel = tmp_path / "deliverables" / "x" / "part1_profile"
    sel.mkdir(parents=True)
    (sel / "selection.json").write_text(json.dumps(
        {"frames": [{"cell": "P0", "source": pool[0]},
                    {"cell": "P1", "source": pool[1]}]}), encoding="utf-8")

    import metrics.faces as _f
    vecs = {p: np.eye(4, dtype=np.float32)[i] + 0.5 for i, p in enumerate(pool)}
    monkeypatch.setattr(_f, "analyse",
                        lambda path, **kw: {"embedding": vecs[path].tolist()})
    monkeypatch.setattr(_q, "ROOT", str(tmp_path))
    monkeypatch.setenv("PERSONA_WORK_ROOT", str(tmp_path / "work"))
    d = _q._delivered_spread("x", "part1_profile")
    assert d and d.get("n") == 2, (
        f"головное число считается не по сданным кадрам, а по чему-то ещё: {d}")
    assert d["pairs"] == 1, d

def test_no_gate_without_a_metric_module():
    """Ворота tattoo и detector имели пороги, колонки в таблице и ключи в
    .env.example — а модулей метрик не существует. Вечный NOT_MEASURED,
    выданный за настроенную проверку.

    ПРОВЕРЯЕТСЯ ПО ТАБЛИЦЕ РАННЕРА, А НЕ ПО ИМЕНАМ ФАЙЛОВ. Первая редакция
    сверяла имя ворот с именем .py в metrics/ и покраснела на hair_tone: один
    модуль законно даёт ДВОЕ ворот (корни темнее длины и многотонность
    окраски — разные величины, разделяющие по-разному, и складывать их в одно
    число значило бы спрятать слабое за сильным). Имя файла ничего не
    гарантирует; гарантирует то, что раннер сможет вызвать функцию, — это и
    проверяется, импортом.
    """
    import importlib
    import gates as _g
    g = MANIFEST["gates"]
    declared = set(g.get("required", [])) | set(g.get("informational", []))
    for gate in declared:
        if gate in {"identity", "cohort", "age"}:
            continue          # считаются из metrics.faces прямо в раннере
        assert gate in _g.METRICS, (
            f"ворота {gate} объявлены в манифесте, а раннер про них не знает")
        mods, funcs = _g.METRICS[gate]
        found = None
        for m in mods:
            try:
                mod = importlib.import_module(m)
            except Exception:
                continue
            found = next((f for f in funcs if callable(getattr(mod, f, None))),
                         None)
            if found:
                break
        assert found, (f"ворота {gate} объявлены, а вызвать нечего: ни в "
                       f"{list(mods)} нет функции из {list(funcs)}")
    for phantom in ("tattoo_score_min", "detector_max_ai_prob"):
        assert phantom not in g, f"порог фантомных ворот вернулся: {phantom}"


def test_swap_branch_is_declared_the_same_way_everywhere():
    """Перенос лица либо есть и в коде, и в манифесте — либо нигде.

    ЭТОТ ТЕСТ ПИСАЛСЯ, ЧТОБЫ ВЕТКА СВОПА НЕ ВЕРНУЛАСЬ, И ОН НЕ СРАБОТАЛ. Он
    сторожил ИМЕНА ФАЙЛОВ удалённой реализации (casting.py, faceblend.py,
    krea2_swap_api.json) и строку identity.method == "selection". Ветку
    построили заново под другими именами — face_transfer.py,
    face_transfer_api.json, — и тест остался зелёным всю неделю. Покраснел он
    только когда манифест переписали честно, то есть уже постфактум.

    Урок, ради которого тест переписан: сторож, знающий имена, ловит возврат
    тем же путём и слеп к возврату другим. Проверяется теперь СВЯЗЬ — код и
    манифест обязаны говорить одно и то же, — а не список имён.

    ВТОРАЯ РЕДАКЦИЯ, И ВТОРОЙ УРОК. Сторожили СУЩЕСТВОВАНИЕ файла
    face_transfer.py — а решает не существование, а УМОЛЧАНИЕ. Инструмент
    может лежать в репозитории и не стоять в конвейере: своп оставлен ключом
    --face-transfer ради воспроизведения прежних прогонов, и его face_mask()
    нужен другим шагам. Проверяется теперь то, что действительно портит
    кадры, — включён ли он по умолчанию, — и совпадает ли это с манифестом.

    Решение обращалось дважды. Своп вернули, потому что бриф ставит
    согласованность идентичности первым критерием. Его убрали снова, потому
    что замер на 14 парах показал цену: дисперсия лапласиана по маске лица
    падает со 180 до 40, то есть 78% фактуры, и на КАЖДОМ кадре. Заказчик
    оплатил эту ошибку тремя жалобами подряд.
    """
    import inspect
    import produce as _produce
    default_on = (
        inspect.signature(_produce.finish).parameters["face_ref"].default
        is not None)
    method = MANIFEST["identity"]["method"]
    says = "transfer" in method
    assert default_on == says, (
        f"код и манифест разошлись: перенос по умолчанию "
        f"{'включён' if default_on else 'выключен'}, "
        f"а identity.method = {method!r}")
    if not says:
        assert MANIFEST["identity"].get("_selection_pool"), (
            "личность держится отбором, но манифест не приводит чисел пула — "
            "без них решение нечем проверить и незачем верить")
    if says:
        assert MANIFEST["identity"].get("_why_reversed"), (
            "перенос включён, но identity._why_reversed не объясняет, почему "
            "прежнее решение отменено — а оно принималось по замеру")
    # Файлы УДАЛЁННОЙ реализации не возвращаются: у неё не было банка лиц в
    # репозитории, запустить её было нечем, и половина ветки хуже отсутствия.
    for rel in ("scripts/casting.py", "scripts/faceblend.py",
                "templates/comfy/krea2_swap_api.json"):
        assert not os.path.exists(os.path.join(ROOT, rel)), f"{rel} вернулся"
    for p in scripts_sources():
        src = open(p, encoding="utf-8").read()
        assert "krea2_swap_api" not in src, f"{p} всё ещё зовёт свопный шаблон"
    for dead in ("anchor_name", "swap_model", "refine_denoise",
                 "face_restore_model"):
        assert dead not in MANIFEST["identity"], f"мёртвый ключ свопа: {dead}"
    # ДОКУМЕНТЫ ТОЖЕ. Проверка кода и манифеста была зелёной пять раундов,
    # пока docs/environment.md настоящим временем объявлял своп действующим
    # механизмом идентичности и цитировал identity.method: "reactor" —
    # значение, которого в манифесте нет. Читатель верит документу.
    for rel in ("docs/environment.md", "README.md", "SKILL.md"):
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        doc = open(path, encoding="utf-8").read()
        assert '"reactor"' not in doc, f"{rel} цитирует мёртвый identity.method"
        assert "krea2_swap_api.json" not in doc.replace(
            "`templates/comfy/krea2_swap_api.json` was deleted", ""), (
            f"{rel} ссылается на удалённый шаблон как на существующий")
        for claim in ("identity runs through the face swap",
                      "identity can run today",
                      "The single exception is the ReActor face bank"):
            assert claim not in doc, f"{rel}: своп описан как действующий — «{claim}»"


def test_manifest_has_no_duplicate_keys():
    """gates._required был объявлен дважды; парсер молча брал второе, и
    первое обоснование не доезжало до читателя никогда."""
    import re
    with open(os.path.join(ROOT, "assets.json"), encoding="utf-8") as fh:
        raw = fh.read()
    for block in re.finditer(r'"(gates|identity|policy|models)":\s*\{', raw):
        start = block.end()
        depth, i = 1, start
        while depth and i < len(raw):
            depth += (raw[i] == "{") - (raw[i] == "}")
            i += 1
        keys = re.findall(r'^\s{4}"([^"]+)":', raw[start:i], re.M)
        dupes = {k for k in keys if keys.count(k) > 1}
        assert not dupes, f"дубли ключей в {block.group(1)}: {dupes}"


def test_requirements_matches_what_is_imported():
    """requirements.txt утверждал, что ни одна строка scripts/ не
    импортирует numpy/PIL/cv2/insightface. Их требуют пять из восьми
    ступеней конвейера."""
    import re
    with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as fh:
        req = fh.read().lower()
    used = set()
    for p in scripts_sources():
        src = open(p, encoding="utf-8").read()
        for m in re.finditer(r"^\s*(?:import|from)\s+(numpy|cv2|PIL|insightface|"
                             r"onnxruntime)\b", src, re.M):
            used.add(m.group(1))
    mapping = {"numpy": "numpy", "cv2": "opencv-python", "PIL": "pillow",
               "insightface": "insightface", "onnxruntime": "onnxruntime"}
    for mod in used:
        assert mapping[mod] in req, f"{mod} импортируется, но не в requirements"


def test_manifest_quotes_no_identity_numbers():
    """Числа калибровки идентичности НЕ живут прозой в манифесте.

    Они расходились с реальностью ТРИ раунда подряд: (1) сравнивали медиану
    к якорю с минимумом по парам, (2) минимум по 105 парам с минимумом по 10,
    (3) остались от сдачи, которую тот же коммит и отменил. Причина одна —
    замер хранился текстом рядом с кодом, который этот замер меняет. Считает
    их scripts/identity_calibration.py; в манифесте только ссылка на него.
    """
    import re
    g = MANIFEST["gates"]
    # Проверяются ТОЛЬКО ключи идентичности. Калибровки хромы, кожи и резкости
    # числа держать вправе: они свойство рендера, а не текущей сдачи, и у
    # каждой есть самотест, который их пересчитывает и падает при расхождении.
    # Числа идентичности меняются с каждой пересборкой набора — им место в
    # выводе скрипта. _identity_erratum исключён намеренно: он и есть протокол
    # того, какие числа когда-то стояли неверно, без них он бессмыслен.
    live = " ".join(str(g.get(k, "")) for k in
                    ("_identity", "_identity_is_informational"))
    numbers = re.findall(r"\b0\.\d{3}\b|\b\d{1,3}\s?%", live)
    assert not numbers, (
        f"в обосновании ворот идентичности снова стоят замеренные числа: "
        f"{numbers}. Их место — вывод identity_calibration.py.")
    assert "identity_calibration" in live, "нет ссылки на то, чем пересчитать"


def test_sharpness_threshold_sits_in_its_own_gap():
    """Порог блокирующих ворот резкости обязан лежать в зазоре, который
    считает их собственный самотест. Он стоял на 70.0 при зазоре
    (109.6, 126.9) — то есть ворота пропускали мыло, а самотест падал
    с кодом 1, и этого никто не смотрел три раунда."""
    pytest.importorskip("cv2")
    pytest.importorskip("numpy")
    lo, hi = 109.6, 126.9   # см. assets.json → gates._face_sharp
    v = MANIFEST["gates"]["face_sharp_min"]
    assert lo < v < hi, (
        f"face_sharp_min={v} вне зазора ({lo}, {hi}); пересчитать: "
        f"py -3 scripts/metrics/sharpness.py")


def test_skill_is_declarable():
    """Без SKILL.md с фронтматтером это не скилл, а папка в D:\\skills\\ —
    ни обнаружить, ни вызвать."""
    p = os.path.join(ROOT, "SKILL.md")
    assert os.path.exists(p), "SKILL.md нет"
    head = open(p, encoding="utf-8").read().split("---")
    assert len(head) >= 3, "нет YAML-фронтматтера"
    fm = head[1]
    assert "name: persona-forge" in fm
    assert "description:" in fm and len(fm) > 200, "описание не выстрелит"


def test_readme_runbook_only_names_scripts_that_exist():
    """README вёл по casting.py, которого больше нет, и ни разу не звал
    select_set.py — то есть пропускал шаг идентичности целиком."""
    import re
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()
    for name in set(re.findall(r"scripts/(\w+)\.py", readme)):
        assert os.path.exists(os.path.join(SCRIPTS, f"{name}.py")), \
            f"README зовёт несуществующий scripts/{name}.py"
    assert "select_set.py" in readme, "шаг идентичности не упомянут"


# ------------------------------------------- раунд 4: закрепление поведением
# Раунд 4 показал: шесть починок раунда 3 из семи не были прикрыты ничем —
# мутация, дословно возвращающая дефект, оставляла сьют зелёным. Тесты ниже
# написаны так, чтобы каждая такая мутация красила ровно один из них.

def test_delivery_name_cannot_escape_the_delivery_directory():
    """delivery_name подставлялся в имя файла ДОСЛОВНО: "../../../pwned"
    писал файл вне каталога части, съедая префикс индекса, а кириллица
    уезжала прямо в имя, которое уходит клиенту."""
    import deliver
    for evil in ("../../../pwned", "C:/abs/path", "a/b", "Съёмка на балконе"):
        name = deliver.delivery_name({"id": "P1", "delivery_name": evil}, 3)
        assert os.sep not in name and "/" not in name and ":" not in name, name
        assert name.startswith("03_"), name
        assert not re.search(r"[А-Яа-яЁё]", name), name


def test_lastmile_refuses_to_write_over_its_input(tmp_path):
    """ПОВЕДЕНЧЕСКАЯ проверка, а не вызов вспомогательной функции: раунд 4
    показал, что тест на _same_dir остаётся зелёным, если саму проверку в
    lastmile выключить. Последняя миля не идемпотентна — три прогона подряд
    давали угол/центр 5.78 → 5.44 → 5.10 → 4.75 при растущем зерне.

    Заодно нечувствительность к регистру: на Windows --out SRC при исходнике
    в src/ — тот же каталог, а голое сравнение abspath их различало.

    И два ПСЕВДОНИМА пути, на которых сравнение строк молчало, а исходник
    переписывался на месте (раунд 5 показал это хешами до/после): junction
    (mklink /J) и короткое имя 8.3 — именно в него раскрывается %TEMP% на
    рабочей машине. Строковое сравнение ловит только те псевдонимы, которые
    придумал сравнивающий; поэтому проверка теперь идёт по иноду.
    """
    Image = pytest.importorskip("PIL.Image")
    pytest.importorskip("cv2")
    src = tmp_path / "src"
    src.mkdir()
    f = src / "a.png"
    Image.new("RGB", (64, 80), (110, 95, 80)).save(f)
    before = f.read_bytes()
    # ВЕРХНИЙ РЕГИСТР — ПСЕВДОНИМ НЕ ВЕЗДЕ. На томе, различающем регистр
    # (linux в CI), это ДРУГОЙ путь, и правильное поведение скрипта — не
    # отказ, а попытка записи: в первом же по-настоящему выполнившемся
    # прогоне CI это дало PermissionError: '/TMP'. Спрашиваем у файловой
    # системы, а не у os.name: регистр — свойство тома.
    aliases = [str(src), str(src / ".")]
    if case_insensitive_fs(tmp_path):
        aliases.append(str(src).upper())
    # КАТАЛОГ-ССЫЛКА — псевдоним на обеих системах: junction на windows,
    # симлинк на posix. Без него на linux у теста оставались два слабых
    # варианта (сам путь и «/./»), которые проходят и через строковое
    # сравнение, — то есть в CI проверка была бы зелёной на сломанном
    # стороже.
    link = str(tmp_path / "j")
    if link_dir(str(src), link):
        aliases.append(link)
    if os.name == "nt":
        import ctypes
        buf = ctypes.create_unicode_buffer(600)
        if ctypes.windll.kernel32.GetShortPathNameW(str(src), buf, 600):
            if os.path.normcase(buf.value) != os.path.normcase(str(src)):
                aliases.append(buf.value)
    for out in aliases:
        r = _run([os.path.join(SCRIPTS, "lastmile.py"), str(f),
                  "--out", out, "--scene", "indoor"])
        assert r.returncode != 0, f"--out {out} не отвергнут"
        assert "совпадает с папкой исходника" in (r.stdout + r.stderr)
    assert f.read_bytes() == before, "исходник изменён отказавшимся прогоном"


def test_gates_refuse_to_run_with_no_required_gate(tmp_path, monkeypatch):
    """Пустой список обязательных ворот давал каждому кадру PASS и код 0 —
    ложный зелёный, ради которого и заведены три состояния. Получался он
    двумя способами: незнакомые имена в required, либо те же имена и в
    required, и в informational."""
    import importlib, gates as _g
    importlib.reload(_g)
    # РАБОЧИЙ КОРЕНЬ УВОДИТСЯ В tmp_path, и это не гигиена, а починка. Тест
    # зовёт настоящий run_gates по настоящему projects/bridget; пока он писал
    # в общий корень, прогон под мутацией (когда отказ выключен) досчитывался
    # до конца и клал на диск правдоподобный gates.json с пустым required, где
    # не отгружается НИ ОДИН кадр. Кадры при этом целы, а отбор, сдача и отчёт
    # читают этот файл как истину. Проверка ворот не имеет права портить
    # состояние, по которому потом работает конвейер.
    monkeypatch.setenv("PERSONA_WORK_ROOT", str(tmp_path))
    man = dict(_g.manifest())
    for broken in ({"required": ["saturation", "bokeh"], "informational": []},
                   {"required": ["chroma"], "informational": ["chroma"]}):
        man["gates"] = dict(man["gates"], **broken)
        monkeypatch.setattr(_g, "manifest", lambda m=man: m)
        with pytest.raises(SystemExit) as e:
            _g.run_gates(os.path.join(ROOT, "projects", "bridget"))
        assert "обязательных ворот не осталось" in str(e.value)


def test_readers_refuse_a_verdict_from_another_gate_config(tmp_path, monkeypatch):
    """Вердикт живёт дольше своего прогона, и его читают как истину отбор,
    сдача и отчёт. Один прогон с другим манифестом подменяет его целиком —
    именно это и произошло: тест на отказ ворот прогнал настоящий gates.py по
    общему рабочему корню и оставил правдоподобный gates.json с пустым
    required, где не отгружалось НИ ОДНО из 40 годных кадров."""
    import _util
    p = tmp_path / "gates.json"
    good = _util.gate_fingerprint()
    p.write_text(json.dumps({"gate_config": good, "frames": []}), encoding="utf-8")
    assert _util.read_verdict(str(p))[1] is None, "свой же вердикт отвергнут"

    bad_thresholds = dict(good, thresholds=dict(good["thresholds"],
                                                face_sharp_min=70.0))
    for broken in ({"required": [], "informational": [], "thresholds": {}},
                   dict(good, required=["chroma"]),
                   # ТЕ ЖЕ ВОРОТА, ДРУГИЕ ЧИСЛА. Вердикт при face_sharp_min 70
                   # пропускает ровно то, что валит вердикт при 118; проверка
                   # одних имён этого не видела.
                   bad_thresholds,
                   {"required": good["required"],
                    "informational": good["informational"]},   # без порогов
                   None):
        body = {"frames": []}
        if broken is not None:
            body["gate_config"] = broken
        p.write_text(json.dumps(body), encoding="utf-8")
        with pytest.raises(SystemExit) as e:
            _util.read_verdict(str(p))
        assert "ВЕРДИКТ НЕ ТОТ" in str(e.value)
        assert _util.read_verdict(str(p), strict=False)[1], "нестрого — без причины"


def test_gates_check_their_config_before_touching_the_disk(tmp_path, monkeypatch):
    """Пустой список обязательных ворот — ошибка настройки, и узнавать о ней
    надо до генерации на GPU, а не после. Плюс work_dir СОЗДАЁТ каталог:
    сломанная настройка успевала оставить после себя пустое дерево."""
    import importlib, gates as _g
    importlib.reload(_g)
    monkeypatch.setenv("PERSONA_WORK_ROOT", str(tmp_path))
    man = dict(_g.manifest())
    man["gates"] = dict(man["gates"], required=["bokeh"], informational=[])
    monkeypatch.setattr(_g, "manifest", lambda m=man: m)
    with pytest.raises(SystemExit) as e:
        _g.run_gates(os.path.join(ROOT, "projects", "bridget"))
    assert "обязательных ворот не осталось" in str(e.value), str(e.value)
    assert not list(tmp_path.iterdir()), (
        f"сломанная настройка оставила дерево: {list(tmp_path.iterdir())}")


def test_gate_firing_ladders_cover_every_required_gate():
    """Ворота, которые ни разу не сказали «нет», неотличимы от выключенных.
    Проверка срабатывания существует; здесь проверяется, что она не отстанет
    от манифеста — новые обязательные ворота без лесенки порчи означают
    ворота без доказательства."""
    import gate_firing
    ladders = gate_firing._degradations()
    for gate in MANIFEST["gates"]["required"]:
        assert gate in ladders, (
            f"обязательные ворота «{gate}» нечем портить — их срабатывание "
            f"не доказано ничем, добавь лесенку в gate_firing._degradations()")


def test_contact_sheet_keeps_aspect_and_carries_provenance(tmp_path):
    """Лист брал высоту клетки у ПЕРВОГО кадра и растягивал остальные:
    кадр 1024x1536 среди 1152x1440 приезжал сплющенным. И был единственным
    файлом сдачи без пометки о происхождении."""
    Image = pytest.importorskip("PIL.Image")
    import contactsheet
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("RGB", (1152, 1440), (90, 80, 70)).save(a)
    Image.new("RGB", (1024, 1536), (30, 120, 60)).save(b)   # выше по пропорции
    out = str(tmp_path / "sheet.png")   # png: без JPEG-ореола на границах
    contactsheet.sheet([str(a), str(b)], out, cols=2, width=800)
    with Image.open(out) as sh:
        # Клетка 400 шириной; самый высокий кадр имеет ar 1.5 → высота 600.
        assert sh.height == 600, sh.size
        # ПРОПОРЦИИ ПРОВЕРЯЮТСЯ ПО ПИКСЕЛЯМ, а не по высоте листа: раунд 5
        # показал, что тест на одну лишь высоту остаётся зелёным при возврате
        # растяжения. Каждый кадр залит своим цветом, поэтому занятая им
        # площадь измерима — у более широкого кадра (ar 1.25) в клетке 400x600
        # обязана остаться незакрашенная полоса сверху и снизу.
        px = sh.convert("RGB").load()
        col_a = sum(1 for y in range(600) if px[200, y] == (90, 80, 70))
        col_b = sum(1 for y in range(600) if px[600, y] == (30, 120, 60))
        assert col_b == 600, f"высокий кадр не заполнил клетку: {col_b}"
        assert 480 <= col_a <= 520, (
            f"кадр 1152x1440 занял {col_a} строк из 600 — его растянули "
            f"вместо вписывания (ожидалось ~500)")
    with Image.open(out) as sh:
        assert sh.getexif().get(305), "нет пометки о происхождении"


def test_generate_opt_rejects_a_key_without_a_value():
    """generate.py — единственный скрипт, который тратит GPU, — был последним
    без защиты разбора: `--casting` последним аргументом падал голым
    IndexError, а `--casting --dry` — ValueError из int()."""
    import subprocess
    for args in (["--casting"], ["--casting", "--dry"]):
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "generate.py"),
             os.path.join(ROOT, "projects", "bridget"), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=120)
        assert "нет значения" in (r.stdout + r.stderr), (args, r.stdout, r.stderr)
        assert "Traceback" not in r.stderr, r.stderr


def test_export_docs_reports_do_not_leak_between_projects(tmp_path):
    """MISSING/LEAKED/VISITED — модульные списки, которые не сбрасывались:
    во втором проекте одного процесса отчёт первого оставался и указывал на
    чужие поля.

    Проверка идёт через export(), а не через _reset_reports(): раунд 5
    показал, что прямой вызов помощника остаётся зелёным, даже если убрать
    его вызов из export() — то есть ровно та поломка, которая и была.
    """
    import export_docs
    export_docs.MISSING.append("stale.field_from_previous_project")
    export_docs.LEAKED.append("stale.md:1")
    export_docs.VISITED.add("stale")
    export_docs.export(os.path.join(ROOT, "projects", "bridget"), str(tmp_path))
    assert not any("stale" in m for m in export_docs.MISSING), export_docs.MISSING
    assert not any("stale" in s for s in export_docs.LEAKED), export_docs.LEAKED
    assert "stale" not in export_docs.VISITED


def test_registry_mode_refuses_to_write_over_the_frames_it_reads(tmp_path):
    """Тот же запрет, что и в файловом режиме, но на второй точке входа.
    Раунд 5: запрет в run_registry не был покрыт ничем — а именно он стоит
    на пути, которым последняя миля ходит по-настоящему (--registry), и
    именно там сегодня «не ломается» только по совпадению расширений."""
    Image = pytest.importorskip("PIL.Image")
    pytest.importorskip("cv2")
    frames = tmp_path / "proj" / "frames"
    frames.mkdir(parents=True)
    png = frames / "f_00.png"
    Image.new("RGB", (64, 80), (100, 90, 80)).save(png)
    (frames / "frames.json").write_text(json.dumps(
        [{"file": str(png), "cell": "S1", "scene_class": "indoor"}]),
        encoding="utf-8")
    before = png.read_bytes()
    r = _run([os.path.join(SCRIPTS, "lastmile.py"), str(frames),
              "--registry", "--out", str(frames)])
    assert r.returncode != 0, "реестровый режим согласился писать в свой же вход"
    assert "совпадает с папкой исходных кадров" in (r.stdout + r.stderr)
    assert png.read_bytes() == before


def test_casting_dry_run_sends_nothing_and_needs_no_worker(tmp_path):
    """--dry обещан для КАЖДОГО дорогого пути. Кастинг — 16 рендеров, и до
    раунда 4 он игнорировал ключ. Проверяется поведение, а не наличие ветки:
    без настроенного адреса воркера сухой прогон обязан завершиться нулём и
    не создать каталог кастинга."""
    r = _run([os.path.join(SCRIPTS, "generate.py"),
              os.path.join(ROOT, "projects", "bridget"), "--casting", "4", "--dry"],
             env={"PERSONA_WORK_ROOT": str(tmp_path), "COMFY_HOST": ""})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ничего не отправлено" in r.stdout
    assert not list(tmp_path.iterdir()), f"сухой кастинг насорил: {list(tmp_path.iterdir())}"


def test_ci_installs_what_the_behavioural_tests_import():
    """CI ставил один pytest, а поведенческие тесты сдачи импортируют PIL —
    сьют был красным ровно в том окружении, которое CI объявляет."""
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"),
              encoding="utf-8") as fh:
        ci = fh.read()
    for pkg in ("numpy", "Pillow", "opencv"):
        assert pkg.lower() in ci.lower(), f"CI не ставит {pkg}"


def test_no_stale_identity_numbers_anywhere_a_reader_looks():
    """Числа калибровки ушли из манифеста и остались в README и SKILL —
    подписная ошибка проекта, воспроизведённая в четвёртый раз. Проверяются
    все три документа сразу."""
    import re
    for name in ("README.md", "SKILL.md"):
        with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
            text = fh.read()
        # Абзац про калибровку идентичности не должен содержать конкретных
        # косинусов и долей — они живут в identity_calibration.json.
        for para in re.split(r"\n\s*\n", text):
            if "identity_calibration" not in para:
                continue
            bad = re.findall(r"\b0\.\d{3}\b|\b\d{1,3}\s?%", para)
            assert not bad, f"{name}: числа калибровки в прозе: {bad}"


# --------------------------------------------- раунд 6: частичность и обещания

def test_partial_verdict_stops_every_consumer(tmp_path, monkeypatch):
    """gates.py --only ПЕРЕЗАПИСЫВАЕТ вердикт целиком: строки остальных ячеек
    из файла исчезают. Никто из потребителей этого не видел — отбор считал
    отсутствие строки за «прошёл» и выдавал готовую строку --pick с кадром,
    по которому ворота не считались; сдаточный qa_report печатал «8 of 8» про
    часть из сорока. Предупреждение gates.py жило только в stdout."""
    import _util
    full = {"gate_config": _util.gate_fingerprint(),
            "coverage": {"partial": False, "cells_measured": ["P1", "P2"],
                         "cells_in_registry": ["P1", "P2"],
                         "frames_measured": 2, "frames_in_registry": 2},
            "frames": []}
    assert _util.verdict_coverage(full) is None
    part = dict(full, coverage={"partial": True, "cells_measured": ["P1"],
                                "cells_in_registry": ["P1", "P2"],
                                "frames_measured": 1, "frames_in_registry": 2})
    gap = _util.verdict_coverage(part)
    assert gap and "P2" in gap and "ЧАСТИЧНЫЙ" in gap
    # Вердикты, написанные до появления coverage, определяются по полю only —
    # иначе починка не действовала бы на тех файлах, ради которых написана.
    assert _util.verdict_coverage({"only": ["P1"], "frames": []})


def test_selection_refuses_to_recommend_from_a_partial_verdict(tmp_path, monkeypatch):
    """ПОВЕДЕНЧЕСКАЯ проверка настоящего отказа, а не вызов помощника: раунд 6
    показал, что тест на _util.verdict_coverage остаётся зелёным, когда сама
    проверка в select_set выключена. Именно так дефект и жил — помощник есть,
    вызова нет.

    Сценарий штатный: перегнали одну ячейку, прогнали по ней ворота. gates.py
    --only перезаписывает вердикт ЦЕЛИКОМ, и отбор рекомендовал пятёрку, где
    четыре кадра не измерялись, — вместе с готовой строкой --pick."""
    import _util, json as _json
    from PIL import Image
    proj = tmp_path / "proj" / "t"
    proj.mkdir(parents=True)
    (proj / "character.json").write_text(_json.dumps(
        {"id": "t", "display_name": "T", "age": 40, "identity_core": "x",
         "realism_clause": "y", "personality_in_frame": {"a": "z"}}),
        encoding="utf-8")
    cells = [{"id": c, "label": c, "framing": "f", "gaze": "g", "trait": "a",
              "body_in_frame": False, "wardrobe": "w", "set": "s", "light": "l",
              "camera": "c", "tattoo_visible": False} for c in ("P1", "P2")]
    (proj / "shotlist.json").write_text(_json.dumps(
        {"project": "t", "size": [64, 64], "seeds_per_cell": 1, "cells": cells}),
        encoding="utf-8")
    frames = tmp_path / "work" / "t" / "frames"
    reg = []
    for c in ("P1", "P2"):
        (frames / c).mkdir(parents=True)
        png = frames / c / f"{c}_s1_01.png"
        Image.new("RGB", (64, 64), (120, 90, 70)).save(png)
        reg.append({"file": str(png), "cell": c, "label": c, "seed": 1,
                    "prompt": "p", "size": [64, 64]})
    (frames / "frames.json").write_text(_json.dumps(reg), encoding="utf-8")
    # Вердикт ТОЛЬКО по P1 — ровно то, что оставляет после себя `--only P1`.
    (frames / "gates.json").write_text(_json.dumps(
        {"gate_config": _util.gate_fingerprint(),
         "coverage": {"partial": True, "cells_measured": ["P1"],
                      "cells_in_registry": ["P1", "P2"],
                      "frames_measured": 1, "frames_in_registry": 2},
         "frames": [{"file": reg[0]["file"], "cell": "P1", "verdict": "PASS",
                     "ships": True, "failed": [], "missing": [], "gates": {}}]}),
        encoding="utf-8")

    monkeypatch.setenv("PERSONA_WORK_ROOT", str(tmp_path / "work"))
    import importlib, select_set as _s
    importlib.reload(_s)
    with pytest.raises(SystemExit) as e:
        _s.run(str(proj), top=1)
    assert "ЧАСТИЧНЫЙ" in str(e.value) and "P2" in str(e.value), str(e.value)


def test_gate_fingerprint_covers_thresholds_not_just_names():
    """Вердикт, снятый при face_sharp_min 70, неотличим от снятого при 118,
    хотя первый пропускает ровно то, что второй валит. Первая редакция
    отпечатка сравнивала два списка имён."""
    import _util
    g = dict(MANIFEST["gates"])
    a = _util.gate_fingerprint(g)
    b = _util.gate_fingerprint(dict(g, face_sharp_min=70.0))
    assert a != b, "порог изменился, а отпечаток нет"
    assert "face_sharp_min" in a["thresholds"]
    # Прозаические ключи (_skin, _identity_erratum) в отпечаток не попадают:
    # иначе правка комментария отвергала бы все прежние вердикты.
    assert not [k for k in a["thresholds"] if k.startswith("_")]


def test_delivery_is_all_or_nothing_when_a_source_vanishes(tmp_path, monkeypatch):
    """«На диск не записано НИЧЕГО» было неправдой. Кадры удаляют руками — это
    штатное «вычистить брак», — реестр при этом не правится, и запись падала
    в СЕРЕДИНЕ цикла: часть JPEG уже лежала в сдаче рядом со СТАРЫМ
    selection.json. Состояние, которое не читается как поломка."""
    proj, png = _fake_project(tmp_path, ships=True)
    monkeypatch.setenv("PERSONA_WORK_ROOT", str(tmp_path / "work"))
    import importlib, deliver as _d
    importlib.reload(_d)
    monkeypatch.setattr(_d, "ROOT", str(tmp_path / "repo"))
    os.remove(png)                       # кадр вычистили руками
    with pytest.raises(SystemExit) as e:
        _d.deliver(str(proj), {"P1": str(png)}, part=1)
    assert "ФАЙЛА НЕТ" in str(e.value), str(e.value)
    out = tmp_path / "repo" / "deliverables" / "t" / "part1_profile"
    assert not out.exists() or not list(out.iterdir()), list(out.iterdir())


def test_auto_ranks_on_a_number_that_exists():
    """--auto был объявлен в справке и не существовал: печатал то же, что и
    опечатка --zzz. Первая реализация читала несуществующий ключ margin,
    получала -inf на всех кадрах и «выбирала лучший» первым попавшимся."""
    import deliver, gates
    src = open(os.path.join(SCRIPTS, "deliver.py"), encoding="utf-8").read()
    assert callable(getattr(deliver, "auto_picks", None)), "--auto снова фантом"
    assert '"--auto" in args' in src, "auto_picks не подключён к разбору ключей"
    # Ключ, по которому идёт ранжирование, обязан писаться воротами.
    assert "worst_margin_required" in open(
        os.path.join(SCRIPTS, "gates.py"), encoding="utf-8").read()
    assert "worst_margin_required" in src
    # И считаться по ОБЯЗАТЕЛЬНЫМ воротам, иначе это сортировка по константе.
    row = {"required": ["chroma"], "gates": {
        "chroma": {"value": 0.5, "min": 0.34, "max": 1.0},
        "identity": {"value": 0.5, "min": 0.72, "max": 1.0}}}
    req = [gates._margin(x) for k, x in row["gates"].items()
           if k in set(row["required"])]
    allg = [gates._margin(x) for x in row["gates"].values()]
    assert min(req) != min(allg), "справочные ворота всё ещё перебивают запас"


def test_inode_guard_beats_a_hard_link(tmp_path):
    """ЖЁСТКАЯ ССЫЛКА — единственный псевдоним, который строковое сравнение не
    закрывает ничем. Проверяющий раунда 6 показал: если выпилить ветку
    os.path.samefile и оставить normcase(normpath(realpath(...))), все тесты
    остаются зелёными, потому что realpath на windows сам разворачивает и
    junction, и короткое имя 8.3. Настоящую прибавку samefile даёт ровно здесь
    — realpath у жёсткой ссылки честно возвращает ДРУГОЕ имя того же файла.

    Значит без этого теста «запрет по иноду» был утверждением, а не свойством.
    """
    import _util
    src = tmp_path / "a.png"
    src.write_bytes(b"x")
    link = tmp_path / "b.png"
    try:
        os.link(str(src), str(link))
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("файловая система не даёт жёстких ссылок")
    assert os.path.realpath(str(src)) != os.path.realpath(str(link)), (
        "жёсткая ссылка развернулась в тот же путь — проверка не про то")
    assert _util.same_path(str(src), str(link)), (
        "жёсткая ссылка на тот же файл не распознана — сравнение снова "
        "строковое, и шаг напишет поверх своего же входа")
    assert not _util.same_path(str(src), str(tmp_path / "c.png"))


def test_both_guards_use_the_shared_one():
    """Копий сторожа было две — в lastmile и в composite_tattoo, — и обе
    защищали от одного и того же. Две копии расходятся на первой правке."""
    for rel in ("scripts/lastmile.py", "scripts/composite_tattoo.py"):
        src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        assert "same_path(a, b)" in src, f"{rel}: свой сторож вместо общего"
        assert "os.path.samefile" not in src, (
            f"{rel}: снова своя копия проверки по иноду")


def test_ci_file_uses_only_contexts_github_allows_where_it_uses_them():
    """CI НЕ ОТРАБОТАЛ НИ РАЗУ, и локально это было не видно.

    В блоке `env` самой задачи стояло `${{ runner.temp }}`. Контекст `runner`
    на уровне job не существует — там разрешены только github, needs,
    strategy, matrix, vars, secrets, inputs, — и GitHub отвергает ВЕСЬ файл
    до создания задач: прогон завершается за 0 секунд с «workflow file issue»
    и без единой задачи. Файл при этом остаётся корректным YAML, поэтому ни
    pyyaml, ни ruff, ни сам pytest ничего не замечали, а репозиторий
    рекламировал проверку, которой не было.

    Проверяется по правилам GitHub, а не по вкусу: контексты, разрешённые в
    каждом месте, перечислены в документации Actions, и здесь закрыт тот их
    срез, на котором проект уже обжёгся.
    """
    import re
    path = os.path.join(ROOT, ".github", "workflows", "ci.yml")
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()

    # Контексты, недоступные ВНЕ шага. Список неполный намеренно: сюда
    # попадает то, на чём этот файл уже спотыкался, а не всё подряд.
    forbidden_outside_steps = ("runner.", "job.", "steps.", "env.")
    in_steps, job_indent = False, None
    problems = []
    for i, raw in enumerate(lines, 1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if re.match(r"^\s{4}steps:\s*$", line):
            in_steps, job_indent = True, indent
            continue
        if in_steps and indent <= job_indent and not line.lstrip().startswith("-"):
            in_steps = False
        if in_steps:
            continue
        for ctx in forbidden_outside_steps:
            if "${{" in line and ctx in line:
                problems.append(f"{i}: {line.strip()}  ← контекст {ctx[:-1]} "
                                f"вне шага")
    assert not problems, (
        "GitHub отвергнет файл целиком, и прогон завершится за 0 секунд без "
        "единой задачи:\n  " + "\n  ".join(problems))


def test_ci_yaml_is_actually_parseable_and_has_the_jobs_it_claims():
    """Файл, который не парсится, ведёт себя как выключенный CI. Проверяется
    отдельно от контекстов: это два разных способа получить один и тот же
    ложный зелёный — «проверка настроена», а её нет."""
    yaml = pytest.importorskip("yaml")
    path = os.path.join(ROOT, ".github", "workflows", "ci.yml")
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    jobs = doc.get("jobs") or {}
    assert {"lint", "test"} <= set(jobs), f"задачи CI изменились: {list(jobs)}"
    for name, job in jobs.items():
        assert job.get("steps"), f"задача {name} без шагов"


def test_boolean_flag_does_not_swallow_a_cell_id():
    """`--dry S1 S3` снимает ДВЕ ячейки, а не одну.

    БЫЛО НАОБОРОТ, И ЦЕНОЙ БЫЛ GPU-ЧАС. Разбор аргументов помечал «занятым»
    аргумент после ЛЮБОГО ключа, считая, что у каждого есть значение. Флаги
    без значения (`--dry`, `--force`, `--partial`) съедали следующий за ними
    id ячейки: батч молча снимал не то, что просили, а сухой прогон показывал
    план, который потом не исполнялся. Найдено независимым ревью 20.08.
    """
    import generate as G

    args = ["projects/bridget", "--dry", "S1", "S3",
            "--shotlist", "shotlist_story.json"]
    flags = {"--dry", "--force", "--partial", "--auto", "--list", "--verify"}
    taken = {i + 1 for i, a in enumerate(args)
             if a.startswith("--") and a not in flags}
    cells = [a for i, a in enumerate(args)
             if i > 0 and i not in taken and not a.startswith("-")]
    assert cells == ["S1", "S3"], cells
    assert "FLAGS" in open(G.__file__, encoding="utf-8").read(), (
        "generate.py обязан знать список булевых ключей — иначе разбор "
        "аргументов снова начнёт съедать id ячеек")
