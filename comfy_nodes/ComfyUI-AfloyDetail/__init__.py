"""Afloy Detail — точечная правка кадра в ComfyUI.

Пакет ставится копированием папки в custom_nodes и требует перезапуска
сервера: узлы читаются один раз при старте.
"""
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
