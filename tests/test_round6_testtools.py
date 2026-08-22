"""Проверка самого инструмента проверки — tests/mutation_check.py.

Раунд 6 нашёл дыру ровно в том месте, на котором держится вся стратегия
сьюта. mutation_check вносит дефект и смотрит, покраснеет ли pytest, но
«покраснел» было написано как `if r.returncode:` — то есть ЛЮБОЙ ненулевой
код. pytest возвращает 5, когда `-k` не выбрал ни одного теста, поэтому
обычное переименование теста превращало строку таблицы в штамп: не
запускалось ничего, а прогон рапортовал «ловится». Инструмент, который
хвалит сам себя, дороже любой отдельной починки — отсюда этот файл.

Каждый тест ниже строит подставной репозиторий во временной папке (свой
pytest.ini, свой «скрипт», свой тест) и зовёт mutation_check.run() на нём.
Настоящий репозиторий при этом не трогается: run() правит файл на диске и
гоняет pytest, и делать это внутри живого прогона нельзя.
"""
import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))

# Правки в подставном «скрипте»: что ищем, чем подменяем.
GOOD = 'VALUE = "good"'
BAD = 'VALUE = "bad"'
BROKEN = "VALUE = ("


def _mutation_check():
    """mutation_check лежит рядом, но не собирается pytest'ом (не test_*),
    поэтому импортируется по пути, а не по имени."""
    path = os.path.join(HERE, "mutation_check.py")
    spec = importlib.util.spec_from_file_location("_mutation_check_r6", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MC = _mutation_check()


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """Подставной репозиторий + подмена ROOT у mutation_check.

    В pytest.ini кладётся addopts с -q — как в настоящем репозитории.
    Это не украшение: при сложении с собственным -q инструмента сборка
    перестаёт печатать имена тестов, и подсчёт выбранных тестов обязан это
    переживать.
    """
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -q -ra\n",
                                         encoding="utf-8")
    (tmp_path / "payload.py").write_text(GOOD + "\n", encoding="utf-8")
    monkeypatch.setattr(MC, "ROOT", str(tmp_path))
    return tmp_path


def _tests(repo, body):
    (repo / "test_fake.py").write_text(body, encoding="utf-8")


def _mut(k, new=BAD):
    return ("подставной дефект", "payload.py", GOOD, new, k)


SEES_VALUE = (
    "import payload\n"
    "\n"
    "\n"
    "def test_payload_value():\n"
    "    assert payload.VALUE == 'good'\n"
    "\n"
    "\n"
    "def test_payload_value_again():\n"
    "    assert payload.VALUE.startswith('go')\n"
)


def test_filter_matching_no_tests_is_an_error_not_a_catch(fake_repo, capsys):
    """Главная находка: `-k`, не выбравший ничего, — протухшая строка, а не
    пойманный дефект. Это код 5, и раньше он проходил за «ловится»."""
    _tests(fake_repo, SEES_VALUE)
    ok = MC.run(_mut("test_pereimenovan_v_proshlom_raunde"))
    out = capsys.readouterr().out
    assert ok is False
    assert "ловится" not in out
    assert "ОШИБКА" in out
    assert "не выбрал ни одного теста" in out


def test_suite_red_before_the_mutation_is_an_error_not_a_catch(fake_repo, capsys):
    """Красный до мутации красен и после неё. «Ловится» в такой строке
    означало бы «упало то же, что падало и так»."""
    _tests(fake_repo, "def test_payload_value():\n    assert False\n")
    ok = MC.run(_mut("payload_value"))
    out = capsys.readouterr().out
    assert ok is False
    assert "ловится" not in out
    assert "ОШИБКА" in out
    assert "ДО мутации" in out


def test_catch_is_reported_with_the_number_of_selected_tests(fake_repo, capsys):
    """Честный улов: тесты были зелёные, дефект их покрасил. Число
    выбранных тестов печатается, иначе `-k` из одной буквы выглядит как
    проверка ровно одной починки."""
    _tests(fake_repo, SEES_VALUE)
    ok = MC.run(_mut("payload_value"))
    out = capsys.readouterr().out
    assert ok is True
    assert "ловится" in out
    assert "тестов: 2" in out
    # Исходник обязан вернуться на место, иначе следующая строка таблицы
    # проверяет уже сломанный репозиторий.
    assert (fake_repo / "payload.py").read_text(encoding="utf-8") == GOOD + "\n"


def test_blind_suite_is_reported_with_the_number_of_selected_tests(fake_repo,
                                                                   capsys):
    """Слепота остаётся слепотой — и тоже с числом тестов: строка «зелёный
    при дефекте» без счётчика не говорит, сколько тестов промолчало."""
    _tests(fake_repo, "import payload\n\n\ndef test_payload_value():\n"
                      "    assert payload is not None\n")
    ok = MC.run(_mut("payload_value"))
    out = capsys.readouterr().out
    assert ok is False
    assert "ловится" not in out
    assert "СЛЕПОТА" in out
    assert "тестов: 1" in out


def test_suite_that_never_ran_is_not_proof(fake_repo, capsys):
    """Мутация, обрушившая сборку (код 2), — не доказательство: тест не
    дошёл до проверки поведения, а прежняя проверка «код не ноль» засчитала
    бы и это."""
    _tests(fake_repo, SEES_VALUE)
    ok = MC.run(_mut("payload_value", new=BROKEN))
    out = capsys.readouterr().out
    assert ok is False
    assert "ловится" not in out
    assert "ОШИБКА" in out
