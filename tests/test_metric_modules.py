"""Каждые объявленные ворота обязаны быть вызываемыми.

  py -3 -m pytest tests/test_metric_modules.py -q

ЭТО ТА САМАЯ ДЫРА, ЧЕРЕЗ КОТОРУЮ ПРОШЛИ ДВОЕ МЁРТВЫХ ВОРОТ. `gates.py`
объявлял `tattoo` и `detector` в METRICS и в COLUMNS, файлов
`metrics/tattoo.py`, `metrics/detector.py` и `metrics/ai_detector.py` на диске
не было, и живой прогон печатал ровно то, что и должен был:

    ворота «tattoo» не считаются — metrics.tattoo: No module named 'metrics.tattoo'
    ворота «detector» не считаются — metrics.ai_detector: No module named ...

Строчка в stdout умирает вместе с прогоном. В таблице при этом стояли две
колонки, «тату» и «ИИ», и обе печатали NM у каждого кадра — то есть выглядели
настроенными проверками, которые «в этот раз не сработали». Хуже того, `tattoo`
стоял в REQUIRED: ворота были одновременно объявлены ОБЯЗАТЕЛЬНЫМИ и
невыполнимыми, и любой манифест без своего `gates.required` не отгрузил бы
ни одного кадра — молча и навсегда.

ЧТО ИМЕННО ЗДЕСЬ СТОРОЖИТСЯ. Не имена файлов: один модуль законно даёт двое
ворот (`metrics/hair.py` → hair_roots и hair_tone), а один и те же ворота
законно ищутся в нескольких модулях-кандидатах. Сторожится ровно то, что
делает раннер, — попытка импортировать модуль и достать из него функцию. Если
она удалась, ворота живые; если нет, красный тест здесь и сейчас, а не строка
в логе через сорок кадров.

Сеть тесты не трогают: импорт метрики не ходит на воркер и не грузит моделей —
`metrics/tattoo.py` тянет разметку поверхностей тела внутри функции, а не на
верхнем уровне, ровно ради этого.
"""
import os
import re

import pytest

import gates as runner
from conftest import MANIFEST, ROOT

# Ворота, у которых нет своего модуля метрики намеренно: раннер считает их сам,
# из одного прохода детектора лиц. Список не «разрешение», а утверждение — тест
# ниже проверяет по исходнику, что раннер их и правда считает.
SELF_COMPUTED = ("identity", "cohort", "age")

# Записи METRICS, которые не ворота, а служебный проход. faces отдаёт лицо
# остальным метрикам и колонки в таблице не имеет.
HELPERS = ("faces",)

COLUMN_NAMES = [name for name, _ in runner.COLUMNS]


@pytest.mark.parametrize("gate", sorted(runner.METRICS))
def test_every_declared_metric_can_be_called(gate):
    """Имя из METRICS обязано доводить до вызываемой функции.

    Проверяется через сам раннер (`gates._entry`), а не своей копией разбора:
    копия разошлась бы с ним на первой же правке списка кандидатов, и тест
    остался бы зелёным ровно тогда, когда сломан прогон.
    """
    fn, why = runner._entry(gate)
    assert fn is not None, f"ворота «{gate}» объявлены, но не вызываются: {why}"


@pytest.mark.parametrize("name", COLUMN_NAMES)
def test_every_column_has_something_behind_it(name):
    """Колонка таблицы обязана кем-то считаться.

    Колонка без метрики — это NM в каждой строке отчёта, а NM в отчёте значит
    «не смогли замерить», а не «такой проверки нет». Разница между ними — это
    разница между «чини окружение» и «не жди этого числа вовсе».
    """
    assert name in runner.METRICS or name in SELF_COMPUTED, (
        f"колонка «{name}» ни в METRICS, ни среди тех, что раннер считает сам "
        f"{SELF_COMPUTED} — в таблице она будет вечным NM")


@pytest.mark.parametrize("name", sorted(set(runner.REQUIRED)))
def test_every_required_gate_exists(name):
    """Обязательные ворота обязаны существовать — иначе не отгрузится ничего.

    По правилам metrics/verdict.py обязательные ворота, которых нет в словаре
    кадра, считаются незамером, а незамер обязательных блокирует отгрузку.
    Значит опечатка или снятая метрика в этом списке — не «строгая проверка»,
    а полная остановка конвейера без единого сообщения об ошибке.
    """
    resolved = runner.ALIAS.get(name, name)
    assert resolved in COLUMN_NAMES, (
        f"REQUIRED называет «{name}», а колонки такой нет: {COLUMN_NAMES}")
    assert resolved in runner.METRICS or resolved in SELF_COMPUTED, (
        f"обязательные ворота «{name}» считать нечем")


@pytest.mark.parametrize("src,dst", sorted(runner.ALIAS.items()))
def test_alias_leads_somewhere(src, dst):
    """Синоним обязан вести на существующие ворота.

    Синоним, ведущий в пустоту, опаснее отсутствующего: gates.py печатает
    предупреждение о НЕЗНАКОМОМ имени в gates.required, и синоним это
    предупреждение отключает — имя становится «знакомым» и молча не
    проверяется ничем.
    """
    assert dst in COLUMN_NAMES, (
        f"синоним {src!r} → {dst!r} ведёт на ворота, которых нет")


@pytest.mark.parametrize("gate", SELF_COMPUTED)
def test_self_computed_gates_are_really_computed(gate):
    """«Считается отдельно» — утверждение, а не отговорка, и оно проверяемо.

    Без этого теста SELF_COMPUTED выше превратился бы в белый список, куда
    можно вписать что угодно, чтобы погасить красноту предыдущих проверок.
    Ищем в исходнике раннера присваивание этих ворот.
    """
    with open(os.path.join(ROOT, "scripts", "gates.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert re.search(r'row\["gates"\]\[[\'"]%s[\'"]\]\s*=' % gate, src), (
        f"ворота «{gate}» объявлены считаемыми в самом раннере, а присваивания "
        f"их в gates.py нет — значит колонка пустая")


@pytest.mark.parametrize("gate", sorted(set(runner.METRICS) - set(HELPERS)))
def test_no_metric_is_computed_into_nowhere(gate):
    """Обратная дыра: метрика есть, а колонки для неё нет.

    Она уже случалась в этом файле с другой стороны — пять метрик опознавания
    были подключены к METRICS и к COLUMNS, но список вызываемых ворот стоял
    зашитым кортежем, и метрики не вызывались ни разу. Раз список теперь
    вычисляется из COLUMNS, метрика вне COLUMNS не будет вызвана вообще.
    """
    assert gate in COLUMN_NAMES, (
        f"метрика «{gate}» объявлена, но колонки у неё нет — раннер обходит "
        f"COLUMNS, и вызвана она не будет ни разу")


@pytest.mark.parametrize(
    "name", sorted(set(MANIFEST["gates"].get("required", []))
                   | set(MANIFEST["gates"].get("informational", []))))
def test_manifest_gate_names_resolve_to_columns(name):
    """Имя ворот из манифеста обязано доезжать до колонки.

    Соседний тест (test_review_regressions) сверяет те же имена с METRICS;
    здесь — с таблицей, потому что промахнуться можно и так: ворота, которые
    считаются, но в COLUMNS не попали, в вердикт кадра не попадут, а имя из
    gates.required без записи в вердикте по правилам verdict.py означает
    незамер обязательных ворот, то есть остановку отгрузки.
    """
    resolved = runner.ALIAS.get(name, name)
    assert resolved in COLUMN_NAMES, (
        f"манифест называет ворота «{name}», а колонки такой нет — "
        f"gates.py объявит имя незнакомым и проверять его не будет")


def test_dead_detector_declaration_does_not_come_back():
    """Ворота детектора сняты по замеру — вернуть их можно только с метрикой.

    Замер, по которому они сняты, лежит комментарием в gates.py: локальный
    признак «следа сетки» объявляет настоящую фотографию (23.7 и 24.5)
    искусственнее любого нашего сырого кадра (9.1 … 12.9), потому что его
    ведёт блок 8x8 JPEG, а не происхождение картинки. Тест не запрещает
    детектор — он запрещает ОБЪЯВЛЕНИЕ детектора без работающей метрики, и
    падает ровно в том случае, когда имя вернулось в таблицу пустым.
    """
    for name in ("detector", "ai", "ai_prob"):
        if name in runner.METRICS:
            fn, why = runner._entry(name)
            assert fn is not None, (
                f"ворота «{name}» снова объявлены, а метрики нет: {why}")
        assert name not in COLUMN_NAMES or name in runner.METRICS, (
            f"колонка «{name}» есть, а считать её нечем")
