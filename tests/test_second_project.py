"""Конвейер работает на ЛЮБОМ проекте, а не на том единственном, под который писался.

  py -3 -m pytest tests/test_second_project.py -q

ЗАЧЕМ ЭТОТ ФАЙЛ. Пока в projects/ лежал один персонаж, «инструмент» и «одна
выполненная работа» были неразличимы: любая захардкоженная под него мелочь —
таблица имён файлов, полоса возраста, ключ словаря переводов — выглядела как
настройка конвейера и молчала. Второй персонаж, прошедший тот же путь без
единой правки кода, эту разницу проявляет. Но проявляет он её ОДИН РАЗ, в тот
день, когда его завели; чтобы проявлял и дальше, проверки ниже
ПАРАМЕТРИЗОВАНЫ ПО ВСЕМ ПАПКАМ В projects/ — третий персонаж покрывается сам
собой, ничего дописывать не надо.

GPU ЗДЕСЬ НЕ ТРОГАЕТСЯ. Дорогие пути проверяются тем, чем их и обещали
проверять: `--dry` печатает план и обязан ничего не создать. Рабочий корень
каждому подпроцессу подставляется во временную папку — тест не имеет права
трогать состояние, по которому потом работает конвейер.
"""
import json
import os
import re
import subprocess
import sys

import pytest

from conftest import MANIFEST, PROJECTS, ROOT, project_dirs, shotlists

# Русская подпись — единственная, которая вообще ходит в таблицу переводов:
# английские значения проходят насквозь без обращения к ней.
CYRILLIC = re.compile(r"[А-Яа-яЁё]")

SCRIPTS = os.path.join(ROOT, "scripts")


def _pdirs():
    """Папки проектов как параметры, с читаемым id в отчёте."""
    return [pytest.param(p, id=os.path.basename(p)) for p in project_dirs()]


def _shotlists():
    """Пары «проект × раскадровка»: у проекта их несколько, и договор общий."""
    out = []
    for pdir in project_dirs():
        for spath in shotlists(pdir):
            out.append(pytest.param(pdir, spath,
                                    id=f"{os.path.basename(pdir)}/"
                                       f"{os.path.basename(spath)}"))
    return out


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _run(args, work_root):
    """Скрипт конвейера в подпроцессе, с рабочим корнем во временной папке.

    COMFY_HOST выбрасывается намеренно: `--dry` обещан как «план без воркера»,
    и проверять его надо в среде, где воркера нет, а не там, где он рядом.
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               PERSONA_WORK_ROOT=str(work_root))
    env.pop("COMFY_HOST", None)
    return subprocess.run([sys.executable, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          env=env, cwd=ROOT, timeout=180)


# ----------------------------------------------- проект как единица работы

def test_the_repository_holds_more_than_one_character():
    """Второй персонаж — это и есть доказательство, что здесь инструмент.

    Проверка выглядит странной ровно до того момента, когда кто-нибудь удалит
    второй проект «за ненадобностью»: вместе с ним из репозитория молча
    исчезает единственное свидетельство того, что конвейер не подогнан под
    одного человека, и все проверки ниже становятся тавтологией — они
    параметризованы по папкам, а папка остаётся одна.
    """
    dirs = project_dirs()
    assert len(dirs) >= 2, (
        f"в projects/ только {[os.path.basename(d) for d in dirs]}; конвейер, "
        f"проверенный на одном персонаже, неотличим от разовой работы")


def test_no_two_characters_share_their_identity_blocks():
    """Второй персонаж обязан быть ДРУГИМ человеком, а не переименованным.

    Идентичность в этом конвейере целиком лежит в двух блоках: описание лица и
    маркеры возраста. Совпадение любого из них означает, что «второй проект» —
    это копия карточки с новым именем папки, то есть доказательство не
    состоялось, хотя все остальные тесты зелёные.
    """
    for field in ("identity_core", "age_markers"):
        seen = {}
        for pdir, char, _spath, _shots in PROJECTS:
            text = " ".join(str(char.get(field, "")).split())
            if text in seen and seen[text] != pdir:
                pytest.fail(f"{field} дословно совпадает у "
                            f"{os.path.basename(seen[text])} и "
                            f"{os.path.basename(pdir)}")
            seen[text] = pdir


@pytest.mark.parametrize("pdir", _pdirs())
def test_project_id_matches_its_folder(pdir):
    """character.json → id обязан совпадать с именем папки.

    Имя проекта разрешает _util.project_name, и КАРТОЧКА В НЁМ ПЕРВАЯ. Значит
    карточка, скопированная у соседа вместе с его id, уводит все ступени
    конвейера в чужой рабочий каталог: генерация пишет туда, ворота читают
    оттуда, а сдача ищет в своей папке и находит пусто. Ошибка бесшумная —
    отличить её от «ещё не сгенерировано» нечем.
    """
    char = _read(os.path.join(pdir, "character.json"))
    assert char.get("id") == os.path.basename(pdir), (
        f"id={char.get('id')!r}, папка {os.path.basename(pdir)!r}")


def test_translations_do_not_leak_between_projects():
    """Перевод одного проекта не должен попадать в документ другого.

    ДЕФЕКТ БЫЛ НАСТОЯЩИЙ И НАШЁЛСЯ ВТОРЫМ ПЕРСОНАЖЕМ. Таблица переводов в
    scripts/export_docs.py ключевалась путём вида `cells.<id>.label`, БЕЗ
    имени проекта: вторая героиня с ячейками S1..S5 получала бы в клиентский
    документ английские подписи первой — «The robe» поверх совершенно другого
    кадра, молча и правдоподобно.

    Первая редакция этого теста требовала разводить номера ячеек РУКАМИ.
    Требование к данным ради дефекта в коде — плохой договор: третий персонаж
    однажды забыл бы, а проверка выглядела бы придиркой. Ключ таблицы стал
    проектным, и тест проверяет то, что важно на самом деле, — что подмены
    не происходит, — а номера ячеек снова свободны.
    """
    import export_docs as E
    pairs = []
    for pdir, _char, _spath, shots in PROJECTS:
        pid = os.path.basename(pdir)
        for cell in shots["cells"]:
            if CYRILLIC.search(str(cell.get("label", ""))):
                pairs.append((pid, cell["id"], cell["label"]))
    if len(pairs) < 2:
        pytest.skip("нужны хотя бы два проекта с русскими подписями")

    seen = {}
    for pid, cid, label in pairs:
        E._reset_reports()
        E.PROJECT = pid
        got = E.en(f"cells.{cid}.label", label)
        # Один и тот же id в разных проектах с РАЗНЫМИ подписями обязан дать
        # либо разные переводы, либо честный None — но не чужой текст.
        for (other_pid, other_cid, other_label), other_got in seen.items():
            if other_cid == cid and other_label != label:
                assert not (got is not None and got == other_got), (
                    f"перевод протёк: {pid}/{cid} «{label}» и "
                    f"{other_pid}/{other_cid} «{other_label}» получили один и "
                    f"тот же английский текст «{got}»")
        seen[(pid, cid, label)] = got
    E.PROJECT = None


def test_the_translation_key_carries_the_project():
    """Ключ таблицы обязан начинаться с имени проекта. Проверка отдельная от
    поведенческой выше: без неё возврат к глобальному ключу заметен, только
    если в репозитории лежат два проекта с совпадающими номерами ячеек, — а
    это как раз то, чего от автора больше не требуют."""
    import export_docs as E
    bad = [k for k in E.EN if "." not in k or k.split(".", 1)[0] in
           ("character", "cells", "shotlist", "shotlist1", "shotlist2", "story")]
    assert not bad, (
        f"ключи таблицы EN без имени проекта: {bad[:5]} — перевод снова может "
        f"уехать в документ чужого персонажа")


# ------------------------------------------------ дорогие пути без единого GPU

@pytest.mark.parametrize("pdir", _pdirs())
def test_prompts_cli_builds_a_prompt_for_every_cell(pdir):
    """`prompts.py <проект>` печатает промпт каждой ячейки и не падает.

    Это самый дешёвый способ поймать данные, на которых конвейер спотыкается:
    build_cell бросает KeyError на незаданной или незнакомой черте, а
    незаполненная карточка теряет блок идентичности молча. Проверяется
    подпроцессом, а не вызовом функции: у скрипта своя точка входа, и она
    ломалась отдельно от библиотеки.
    """
    char = _read(os.path.join(pdir, "character.json"))
    shots = _read(os.path.join(pdir, "shotlist.json"))
    r = _run([os.path.join(SCRIPTS, "prompts.py"), pdir], ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    for cell in shots["cells"]:
        assert f"--- {cell['id']} " in r.stdout, f"нет промпта для {cell['id']}"
    assert char["identity_core"] in r.stdout


@pytest.mark.parametrize("pdir,spath", _shotlists())
def test_dry_run_prints_a_plan_and_creates_nothing(tmp_path, pdir, spath):
    """`generate.py --dry` обязан отработать нулём и не оставить ни файла.

    Оба обещания проверяются на КАЖДОЙ раскадровке КАЖДОГО проекта: сухой
    прогон — единственная предпродажная проверка перед сорока минутами GPU, и
    если он спотыкается на второй части нового персонажа, узнать об этом надо
    здесь. Пустая временная папка после прогона — вторая половина обещания:
    «ничего не отправляя» включает «и каталогов не создавая».
    """
    char = _read(os.path.join(pdir, "character.json"))
    r = _run([os.path.join(SCRIPTS, "generate.py"), pdir,
              "--shotlist", os.path.basename(spath), "--dry"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"проект {char['id']}" in r.stdout, r.stdout[:400]
    assert "кадров к генерации" in r.stdout
    assert not list(tmp_path.iterdir()), f"--dry насорил: {list(tmp_path.iterdir())}"


@pytest.mark.parametrize("pdir", _pdirs())
def test_gates_refuse_to_judge_a_project_without_frames(tmp_path, pdir):
    """Ворота на пустом проекте обязаны ОТКАЗАТЬСЯ, а не выдать зелёный.

    Новый персонаж — это ровно то состояние, в котором кадров ещё нет, и
    именно здесь ложный зелёный дешевле всего получить: вердикт по нулю кадров
    формально не содержит ни одного провала. Правило трёх состояний требует
    обратного — отказ с указанием, чем его лечить.

    ЗАПУСК ТОЛЬКО ПОДПРОЦЕССОМ, И ЭТО НЕ СТИЛЬ. gates.run_gates разрешает
    рабочий корень через переменную окружения В МОМЕНТ ВЫЗОВА, поэтому
    прямой вызов из теста ушёл бы в БОЕВОЙ корень, нашёл там настоящий реестр
    первого персонажа, посчитал по нему ворота и перезаписал его gates.json —
    ровно тот дефект, про который написано в _util.read_verdict. Проверено:
    первая редакция этого теста так и сделала.
    """
    r = _run([os.path.join(SCRIPTS, "gates.py"), pdir], tmp_path)
    assert r.returncode != 0, r.stdout
    assert "generate.py" in (r.stdout + r.stderr), r.stdout + r.stderr


# --------------------------------------------- договор данных с конвейером

@pytest.mark.parametrize("pdir,spath", _shotlists())
def test_scene_class_of_every_cell_is_known_to_the_pipeline(pdir, spath):
    """scene_class ячейки обязан быть известен И генератору, И последней миле.

    Класс сцены — не подпись, а две ручки: сила лоры «одноразовая камера» в
    generate.py и профиль зерна в манифесте. Незнакомое значение (dusk, studio)
    обе они молча трактуют как «ничего»: лора получает ноль, зерно — умолчание,
    и кадр выходит не тем, что заказан, без единого сообщения.
    """
    from generate import DISPOSABLE_BY_SCENE
    known = set(DISPOSABLE_BY_SCENE) & set(MANIFEST["lastmile"]["grain_iso_map"])
    for cell in _read(spath)["cells"]:
        sc = cell.get("scene_class", "indoor")
        assert sc in known, f"{cell['id']}: scene_class {sc!r}, известны {sorted(known)}"


@pytest.mark.parametrize("pdir,spath", _shotlists())
def test_every_declared_frame_size_is_a_manifest_format(pdir, spath):
    """Размеры раскадровки и ячеек — из объявленных форматов манифеста.

    Реестр кадров это уже проверяет, но ПОСЛЕ генерации, то есть после того,
    как GPU потратил час на формат, который никто не объявлял. Здесь то же
    правило применяется к данным до первого кадра.
    """
    allowed = [list(v) for k, v in MANIFEST["output"].items() if k.endswith("_size")]
    shots = _read(spath)
    sizes = [("раскадровка", shots["size"])] if shots.get("size") else []
    sizes += [(c["id"], c["size"]) for c in shots["cells"] if c.get("size")]
    for who, size in sizes:
        assert list(size) in allowed, f"{who}: {size} нет среди {allowed}"


@pytest.mark.parametrize("pdir,spath", _shotlists())
def test_delivery_names_are_latin_and_unique(pdir, spath):
    """Имя файла сдачи строится из ячейки и обязано быть разным у разных кадров.

    Спрашивается у самой сдачи (deliver.delivery_name), а не пересчитывается
    тестом: в предыдущей редакции имя жило таблицей P1→01_hero_portrait,
    зашитой под сцены первого персонажа, и второй получал в папке клиента
    03_paddle_court.jpg без единого корта в кадре. Совпадение имён внутри части
    хуже кириллицы: второй кадр молча затирает первый.
    """
    from deliver import delivery_name
    shots = _read(spath)
    names = {}
    for i, cell in enumerate(shots["cells"], 1):
        name = delivery_name(cell, i)
        assert name == name.encode("ascii", "ignore").decode(), name
        assert not name.endswith(cell["id"].lower()), (
            f"{cell['id']}: имя сдачи {name!r} откатилось к id ячейки — "
            f"задайте delivery_name")
        assert name[3:] not in names, (
            f"{cell['id']} и {names.get(name[3:])} дают одно имя файла: {name}")
        names[name[3:]] = cell["id"]


@pytest.mark.parametrize("pdir", _pdirs())
def test_story_part_declares_caption_and_nudity_for_every_cell(pdir):
    """Вторая часть: подпись и уровень откровенности объявлены у каждой ячейки.

    Оба поля уезжают в реестр кадров и дальше в презентацию. nudity_level имеет
    умолчание («clothed»), и поэтому необъявленное поле неотличимо от
    осознанно одетого кадра — а состав набора по этому полю потом считают.
    Подпись без текста доезжает до слайда пустой строкой.

    Имя файла второй части берётся у самой сдачи, а не пишется здесь: части
    проекта нумерует deliver.PART_SHOTLIST, и вторая точка правды разошлась бы
    с ним на первой же правке.
    """
    from deliver import PART_SHOTLIST
    path = os.path.join(pdir, PART_SHOTLIST[2])
    if not os.path.exists(path):
        pytest.skip(f"{os.path.basename(pdir)}: второй части ещё нет")
    shots = _read(path)
    size = shots.get("size") or MANIFEST["output"]["story_size"]
    assert size[1] > size[0], f"история не вертикальная: {size}"
    for cell in shots["cells"]:
        assert str(cell.get("caption", "")).strip(), f"{cell['id']}: пустая подпись"
        assert "nudity_level" in cell, f"{cell['id']}: уровень не объявлен"


@pytest.mark.parametrize("pdir", _pdirs())
def test_tattoo_placements_never_pretend_to_be_measured(pdir):
    """Координаты вклейки — замер ГЛАЗАМИ по конкретному кадру, и он бывает не сделан.

    Разметка тату подбирается циклом «--preview → поправить → перевклеить» по
    уже сданному файлу. Пока файла нет, подбирать не по чему, но числа в JSON
    всё равно чем-то заполнены — и правдоподобные числа неотличимы от
    подобранных. Это ровно тот ложный зелёный, ради которого во всём остальном
    конвейере заведено третье состояние; здесь оно записывается полем _state.

    Проверяются обе стороны: неподобранная запись обязана быть помечена, а
    помеченная — не пережить появление кадра, иначе метка протухает и врёт в
    другую сторону.
    """
    path = os.path.join(pdir, "tattoo_placements.json")
    if not os.path.exists(path):
        pytest.skip(f"{os.path.basename(pdir)}: разметки тату нет")
    for i, place in enumerate(_read(path), 1):
        frame = os.path.join(ROOT, place["frame"])
        marked = place.get("_state") == "NOT_MEASURED"
        if not os.path.exists(frame):
            assert marked, (
                f"запись {i}: кадра {place['frame']} на диске нет, значит "
                f"координаты никто не подбирал — пометьте "
                f"\"_state\": \"NOT_MEASURED\"")
        else:
            assert not marked, (
                f"запись {i}: кадр {place['frame']} на месте, а пометка "
                f"NOT_MEASURED осталась с тех пор, когда его не было")
