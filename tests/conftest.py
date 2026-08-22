"""Общее для всех тестов: пути, карточки персонажей, раскадровки.

  py -3 -m pytest -q                       # весь набор
  py -3 -m pytest tests/test_prompts.py    # один файл
  py -3 -m pytest -q -k tattoo             # по имени

Набор проверяет ТОЛЬКО то, что уже ломалось, и делает это без сети: ни один
тест не ходит в ComfyUI и не читает модели. Ответ сервера в тестах виджетов
подставляется заглушкой — иначе набор был бы зелёным ровно там, где рядом стоит
включённый ComfyUI, то есть на машине автора и нигде больше.
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# scripts/ кладётся в путь здесь, а не только через pytest.ini: скрипты
# импортируют друг друга по короткому имени (build_ui → from prompts import …),
# и без этого набор собирается только из корня репозитория.
for p in (os.path.join(ROOT, "scripts"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest  # noqa: E402  — путь к scripts/ должен быть готов раньше импортов

from _util import manifest, read_json  # noqa: E402

MANIFEST = manifest()


def project_dirs():
    """Папки проектов — те, где лежит карточка персонажа."""
    return sorted(os.path.dirname(p) for p in
                  glob.glob(os.path.join(ROOT, "projects", "*", "character.json")))


def shotlists(project_dir):
    """Все раскадровки проекта: и Part 1, и story, и любая будущая.

    Именно ВСЕ, а не shotlist.json: договорённости вроде «тату видно там, где
    карточка обещала» обязаны держаться на объединении частей, иначе вторая
    часть проекта заводит собственную правду и расходится с первой молча.
    """
    return sorted(glob.glob(os.path.join(project_dir, "shotlist*.json")))


def _collect():
    out = []
    for pdir in project_dirs():
        char = read_json(os.path.join(pdir, "character.json"))
        for spath in shotlists(pdir):
            out.append((pdir, char, spath, read_json(spath)))
    return out


PROJECTS = _collect()


def cell_params():
    """Параметры «одна ячейка = один тест».

    Разворачивать ячейки в параметры, а не крутить цикл внутри теста, нужно
    ради отчёта: цикл падает на первой же ячейке и молчит про остальные
    четыре, а править раскадровку удобнее, когда видно все промахи сразу.
    """
    params = []
    for pdir, char, spath, shots in PROJECTS:
        for cell in shots["cells"]:
            name = f"{os.path.basename(pdir)}/{os.path.basename(spath)}/{cell['id']}"
            params.append(pytest.param(char, cell, id=name))
    return params


def shotlist_params():
    params = []
    for pdir, char, spath, shots in PROJECTS:
        name = f"{os.path.basename(pdir)}/{os.path.basename(spath)}"
        params.append(pytest.param(char, spath, shots, id=name))
    return params


def chunks(prompt):
    """Промпт как список требований: сборщик склеивает их через запятую."""
    return [c.strip() for c in prompt.split(",") if c.strip()]


def work_root():
    """Корень рабочей папки БЕЗ создания каталогов.

    _util.work_dir() делает mkdir, а тест обязан уметь сказать «кадров ещё
    нет» и пропуститься, а не заводить пустое дерево на машине рецензента.
    """
    root = os.environ.get("PERSONA_WORK_ROOT") or MANIFEST["paths"]["work_root"]
    root = os.path.expanduser(root)
    return root if os.path.isabs(root) else os.path.join(ROOT, root)


def scripts_sources():
    """Все .py конвейера — для проверок домашнего стиля."""
    return sorted(glob.glob(os.path.join(ROOT, "scripts", "**", "*.py"),
                            recursive=True))


def case_insensitive_fs(tmp_path):
    """Различает ли файловая система регистр в именах. Спрашивается У НЕЁ.

    ЗАЧЕМ. Часть тестов проверяет, что шаг отказывается писать поверх своего
    входа, и перечисляет ПСЕВДОНИМЫ одного пути: сам путь, «/./», junction,
    короткое имя 8.3 и ВЕРХНИЙ РЕГИСТР. Последний — псевдоним только там, где
    регистр не различается. На linux это ДРУГОЙ путь, и правильное поведение
    скрипта — не отказ, а попытка записи; в CI это дало
    PermissionError: '/TMP' и три красных теста на первом же прогоне,
    выполнившемся по-настоящему.

    Проверяется созданием файла, а не по os.name: регистр — свойство тома, а
    не системы (на macOS по умолчанию не различается, на смонтированном
    томе — как настроено).
    """
    probe = tmp_path / "CaseProbe.tmp"
    probe.write_bytes(b"")
    try:
        return os.path.exists(str(tmp_path / "caseprobe.tmp"))
    finally:
        probe.unlink()


def link_dir(target, name):
    """Каталог-ссылка: junction на windows, симлинк на posix. True, если вышло.

    Нужна тестам, которые строят теневой рабочий корень: реестры копируются,
    а гигабайты кадров подключаются ссылкой. Первая редакция звала
    _winapi.CreateJunction напрямую, и весь файл тестов падал на linux с
    ModuleNotFoundError ещё в фикстуре — шесть ошибок до единой проверки.
    """
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(name))
        else:
            os.symlink(str(target), str(name), target_is_directory=True)
        return True
    except Exception:
        return False
