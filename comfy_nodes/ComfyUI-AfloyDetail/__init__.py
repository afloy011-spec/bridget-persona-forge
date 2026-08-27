"""Afloy Detail — точечная правка кадра в ComfyUI.

Пакет ставится копированием папки в custom_nodes и требует перезапуска
сервера: узлы читаются один раз при старте.

ИМПОРТ НАПИСАН ДВУМЯ СПОСОБАМИ, И ЭТО НЕ ПЕРЕСТРАХОВКА. ComfyUI грузит папку
КАК ПАКЕТ, и там работает относительный импорт. Но тот же файл читают и
инструменты, которые пакета не собирают — pytest, поднимаясь по дереву от
файла теста, видит этот __init__.py и пытается его исполнить; относительный
импорт тогда падает с «attempted relative import with no known parent
package». Локально это не воспроизводилось, а все четыре ячейки CI краснели.
Две строки вместо одной делают файл пригодным в обоих случаях.
"""
try:                                    # ComfyUI: папка загружена как пакет
    from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
except ImportError:                     # файл прочитан сам по себе
    from nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
