"""Реестр кадров: кадр без записи — мусор, и в вердикт он попасть не должен.

  py -3 -m pytest tests/test_registry.py -q

Тест работает по НАСТОЯЩИМ кадрам в work_root, если они есть, и пропускается,
если их ещё нет. Смысл — поймать расхождение между тем, что лежит на диске, и
тем, что о нём знает конвейер: PNG без записи в frames.json невозможно ни
пересобрать, ни объяснить, а вердикт по нему выглядит как вердикт по кадру.

Картинки не открываются и не переписываются: размер читается из заголовка PNG
стандартной библиотекой.
"""
import glob
import os
import struct

import pytest

from conftest import MANIFEST, PROJECTS, work_root

CELLS = {cell["id"]: cell
         for _pdir, _char, _spath, shots in PROJECTS
         for cell in shots["cells"]}
CHARS = {os.path.basename(pdir): char for pdir, char, _s, _sh in PROJECTS}

REQUIRED_FIELDS = ("file", "cell", "label", "seed", "prompt", "tattoo_visible",
                   "scene_class", "caption", "nudity_level", "mirror_selfie",
                   "size")


def _registries():
    root = work_root()
    return sorted(glob.glob(os.path.join(root, "*", "frames", "frames.json")))


def _load():
    import json
    out = []
    for path in _registries():
        with open(path, encoding="utf-8") as fh:
            out.append((path, json.load(fh)))
    return out


REGISTRIES = _load() if os.path.isdir(work_root()) else []

pytestmark = pytest.mark.skipif(not REGISTRIES,
                                reason="кадров ещё нет — реестр не создавался")


def _png_size(path):
    """Ширина и высота из IHDR. Открывать картинку целиком незачем."""
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def test_every_png_on_disk_is_registered():
    """Незарегистрированный PNG рядом с зарегистрированными — тихая ловушка.

    Он выглядит таким же кадром, попадает в борд глазами человека и уезжает в
    сдачу без промпта, сида и вердикта.
    """
    for path, entries in _load():
        frames_dir = os.path.dirname(path)
        known = {os.path.normcase(os.path.basename(e["file"])) for e in entries}
        on_disk = glob.glob(os.path.join(frames_dir, "*", "*.png"))
        orphans = [p for p in on_disk
                   if os.path.normcase(os.path.basename(p)) not in known]
        assert not orphans, f"{path}: вне реестра {orphans}"


def test_entries_have_the_full_schema():
    """Поля реестра читают ворота и борд; отсутствующее поле там — KeyError."""
    for path, entries in _load():
        for entry in entries:
            missing = [k for k in REQUIRED_FIELDS if k not in entry]
            assert not missing, f"{path}: {entry.get('file')} без {missing}"


def test_entry_prompt_carries_identity_blocks():
    """В реестре лежит промпт, которым кадр реально снят.

    Это единственное место, где обещание «идентичность в каждом кадре» можно
    проверить постфактум, по факту генерации, а не по коду сборщика.

    КАРТОЧКА ЖИВЁТ ДОЛЬШЕ КАДРА, и это не нарушение договора, а его условие.
    Когда приходит референс персонажа, блок опознавания меняется — у Бриджит
    так сменились волосы: «blonde with grown-out darker roots» на замеренный по
    референсу «warm mid-brown». Кадры, снятые ДО правки, содержат прежний текст
    и содержать новый не могут. Требовать от них текущий блок — значит требовать
    перегенерировать весь пул в тот же момент, когда правится одно слово, и
    ровно это и означало бы «карточку править нельзя».

    Поэтому принимается текущий блок ИЛИ любой из явно записанных прежних
    (`_superseded_identity_cores`). Прежний блок обязан лежать в карточке
    дословно: промпт, не совпавший НИ С ОДНИМ из них, — это либо правка
    карточки без записи, либо промпт, собранный мимо сборщика, и то и другое
    настоящая поломка. Список чистится, когда пул пересняли; пока он не пуст,
    он и есть список того, что осталось переснять.
    """
    for path, entries in _load():
        project = os.path.basename(os.path.dirname(os.path.dirname(path)))
        char = CHARS.get(project)
        if char is None:
            continue
        cores = [char["identity_core"]] + list(
            char.get("_superseded_identity_cores") or [])
        ages = [char["age_markers"]] + list(
            char.get("_superseded_age_markers") or [])
        for entry in entries:
            assert any(c in entry["prompt"] for c in cores), (
                f"{entry['file']}: промпт не содержит ни текущий блок "
                f"опознавания, ни один из {len(cores) - 1} записанных прежних — "
                f"карточку правили, не записав прежний текст, либо промпт "
                f"собирали мимо prompts.build_cell")
            assert any(a in entry["prompt"] for a in ages), entry["file"]


def test_superseded_identity_is_declared_not_just_listed():
    """Прежний блок опознавания без причины — это молчаливый долг.

    Список `_superseded_identity_cores` разрешает старым кадрам жить в реестре.
    Без объяснения, ПОЧЕМУ блок сменился и что теперь надо переснять, он
    превращается в вечную амнистию: любой будущий разлад карточки и пула
    закрывается дописыванием ещё одной строки.
    """
    for project, char in CHARS.items():
        old = char.get("_superseded_identity_cores") or []
        if not old:
            continue
        why = str(char.get("_superseded_identity_cores_why") or "").strip()
        assert why, (
            f"{project}: есть {len(old)} прежних блока опознавания и нет "
            f"_superseded_identity_cores_why — не сказано, что и почему "
            f"переснимать")
        assert char["identity_core"] not in old, (
            f"{project}: текущий блок опознавания записан и как прежний")


def test_entry_matches_its_cell():
    """Флаги кадра не должны расходиться с ячейкой, по которой он снят."""
    for path, entries in _load():
        for entry in entries:
            cell = CELLS.get(entry["cell"])
            if cell is None:
                pytest.fail(f"{path}: ячейка {entry['cell']} не найдена "
                            "ни в одной раскадровке")
            assert entry["tattoo_visible"] == bool(cell.get("tattoo_visible"))
            assert entry["scene_class"] == cell.get("scene_class", "indoor")


def test_files_exist_and_match_declared_size():
    """Заявленный размер обязан совпадать с реальным PNG.

    Кадр не того размера — это сорванная последняя миля или чужой файл,
    подложенный в папку; в вердикте это выглядит нормальным кадром.
    """
    for path, entries in _load():
        for entry in entries:
            f = entry["file"]
            if not os.path.exists(f):        # реестр переносим, файлы — нет
                f = os.path.join(os.path.dirname(path), entry["cell"],
                                 os.path.basename(f))
            assert os.path.exists(f), entry["file"]
            size = _png_size(f)
            if size is None:
                continue
            assert list(size) == list(entry["size"]), f


def test_declared_size_is_a_manifest_format():
    """Размер кадра — один из объявленных форматов, а не случайное число."""
    # Берутся ВСЕ объявленные форматы, а не два поимённо: у кадра в полный
    # рост своя форма (fulllength_size), и жёсткий список из двух ключей
    # означал бы, что добавление честно объявленного формата валит тест.
    allowed = [list(v) for k, v in MANIFEST["output"].items()
               if k.endswith("_size")]
    for path, entries in _load():
        for entry in entries:
            assert list(entry["size"]) in allowed, f"{path}: {entry['size']}"
