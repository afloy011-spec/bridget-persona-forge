"""Домашний стиль конвейера — то, что уже ломалось молча.

  py -3 -m pytest tests/test_house_style.py -q

Правила здесь не косметические. Русская Windows отдаёт консоли cp1251, и
первый же «décolleté» в промпте роняет скрипт с UnicodeEncodeError посреди
батча — поэтому setup_console() обязателен в каждом main(). Блок запуска в
докстринге — единственная документация CLI: у скриптов нет --help, и без него
способ вызова знает только автор.
"""
import ast
import os

import pytest

from conftest import scripts_sources


def _module(path):
    with open(path, encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=path)


def _defs(tree, name):
    return [n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == name]


@pytest.mark.parametrize("path", scripts_sources(),
                         ids=lambda p: os.path.basename(p))
def test_module_has_docstring(path):
    assert ast.get_docstring(_module(path)), "нет докстринга модуля"


@pytest.mark.parametrize("path", scripts_sources(),
                         ids=lambda p: os.path.basename(p))
def test_cli_usage_block_in_docstring(path):
    """У скрипта с main() докстринг обязан показывать, как его звать."""
    tree = _module(path)
    if not _defs(tree, "main"):
        pytest.skip("не CLI-скрипт")
    doc = ast.get_docstring(tree) or ""
    assert "py -3" in doc, "в докстринге нет блока запуска"


@pytest.mark.parametrize("path", scripts_sources(),
                         ids=lambda p: os.path.basename(p))
def test_main_sets_up_console(path):
    """setup_console() внутри main() — иначе батч падает на первом же акценте.

    Проверяется именно вызов в main(), а не импорт: импорт без вызова выглядит
    так же аккуратно и не делает ничего.
    """
    fns = _defs(_module(path), "main")
    if not fns:
        pytest.skip("не CLI-скрипт")
    calls = [n.func.id for n in ast.walk(fns[0])
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "setup_console" in calls, "main() без setup_console()"


@pytest.mark.parametrize("path", scripts_sources(),
                         ids=lambda p: os.path.basename(p))
def test_files_are_read_and_written_in_utf8(path):
    """open() без encoding берёт кодировку системы — на русской Windows cp1251.

    Карточка персонажа и раскадровки на UTF-8 с кириллицей в комментариях: тот
    же файл читается на Linux и падает на Windows, причём у автора всё хорошо.
    """
    tree = _module(path)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "open"):
            continue
        kwargs = {k.arg for k in node.keywords}
        mode = node.args[1].value if len(node.args) > 1 and \
            isinstance(node.args[1], ast.Constant) else ""
        if "b" in str(mode):                 # бинарный режим кодировки не знает
            continue
        assert "encoding" in kwargs, \
            f"{os.path.basename(path)}:{node.lineno} open() без encoding"
