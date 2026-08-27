#!/usr/bin/env python3
"""Ворота качества: метрики кадра и сборка вердикта.

  py -3 scripts/metrics/chroma.py               # самотест цветности на реальных кадрах
  py -3 scripts/metrics/faces.py <png> [<png>…] # что видит детектор лиц
  py -3 scripts/metrics/sharpness.py <png> …    # резкость лица против полнокадровой
  py -3 scripts/metrics/skin.py <png> …         # микрорельеф кожи
  py -3 scripts/metrics/verdict.py              # самотест правил вердикта

Каждая метрика возвращает словарь с сырыми числами и состоянием
`PASS` / `FAIL` / `NOT_MEASURED` (константы в `verdict.py`). Третье состояние
заведено не для красоты: метрика, которая молча выключается без своей
зависимости, отдавала вердикту ложный PASS, и кадр уходил в поставку как
проверенный. Незамер обязательных ворот блокирует отгрузку так же, как провал.

Пороги берутся из `assets.json → gates` и откалиброваны на реальных кадрах —
конкретные числа замеров лежат в докстрингах соответствующих модулей.
"""
import os

import numpy as np
import cv2


def load_bgr(src):
    """Кадр как BGR-массив: путь, os.PathLike или уже готовый массив.

    Читаем файл питоном и декодируем из буфера, а не через `cv2.imread`:
    imread отдаёт путь в C++ в ANSI-кодировке и на пути с кириллицей
    (`C:/Users/<имя>/…`, `D:/<кириллица>/…`) молча возвращает None — ошибка вылезала
    не здесь, а строкой ниже, в виде невнятного «NoneType has no shape».
    """
    if isinstance(src, np.ndarray):
        return src
    path = os.fspath(src)
    with open(path, "rb") as fh:
        buf = np.frombuffer(fh.read(), np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"не декодируется как изображение: {path}")
    return img
