#!/usr/bin/env python3
"""Сборка вердикта кадра из состояний отдельных ворот.

  py -3 scripts/metrics/verdict.py        # самотест правил на модельных случаях

Три состояния вместо двух. `PASS` — замерено и в допуске, `FAIL` — замерено и
вне допуска, `NOT_MEASURED` — не замерено вообще (нет зависимости, не нашлось
лица, лицо слишком мелкое, нет ключа к внешнему сервису).

Правила ровно два:

  * любой `FAIL` — вердикт `FAIL`, независимо от того, обязательные ворота
    или нет: замеренный провал остаётся провалом;
  * `NOT_MEASURED` среди ОБЯЗАТЕЛЬНЫХ ворот — вердикт `NOT_MEASURED`, кадр не
    отгружается. Незамер необязательных ворот только пишется в отчёт.

Почему так. Раньше ворота без зависимости выключались молча, и вердикт
считался «по остальным метрикам» — то есть кадр, у которого не измерили ни
идентичность, ни возраст, выходил из ворот с тем же зелёным PASS, что и
полностью проверенный. Отличить их постфактум было нечем. Список обязательных
ворот лежит в `assets.json → gates.required`.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _util import setup_console, manifest

PASS = "PASS"
FAIL = "FAIL"
NOT_MEASURED = "NOT_MEASURED"


def gate(name, value, lo=None, hi=None, note="", **extra):
    """Одни ворота по числу и допуску [lo, hi]; None у границы = граница не задана."""
    if value is None:
        return not_measured(name, note or "значение не получено")
    value = float(value)
    # NaN — ЭТО НЕЗАМЕР, А НЕ ПРОХОД. Оба сравнения ниже с NaN дают False,
    # поэтому `bad` выходил False и ворота отдавали PASS с ships=True — ровно
    # тот молчаливый ложный пропуск, ради невозможности которого этот модуль и
    # написан. Вдобавок json.dumps пишет голый NaN, невалидный для строгих
    # разборщиков: вердикт переставал читаться заодно.
    if value != value or value in (float("inf"), float("-inf")):
        return not_measured(name, note or "метрика вернула не-число (NaN/inf)")
    bad = (lo is not None and value < lo) or (hi is not None and value > hi)
    out = {"gate": name, "state": FAIL if bad else PASS, "value": value,
           "min": lo, "max": hi, "note": note}
    out.update(extra)
    return out


def not_measured(name, reason, **extra):
    """Ворота, которые не удалось замерить. reason обязателен — без него в
    отчёте остаётся пустое место, и причина выясняется перезапуском батча."""
    out = {"gate": name, "state": NOT_MEASURED, "value": None,
           "min": None, "max": None, "note": reason}
    out.update(extra)
    return out


def required_gates(man=None):
    """Список обязательных ворот из манифеста.

    Пустой список тоже допустим и означает «блокировать нечем» — но это
    осознанное решение проекта, а не побочный эффект отсутствия ключа.
    """
    return list((man or manifest())["gates"].get("required", []))


def verdict(gates, required=None):
    """Свести словарь ворот {имя: результат} в один вердикт.

    Возвращает `verdict`, `ships` (отгружаем ли кадр), `failed`, `missing` и
    сами ворота. `ships` — единственное, на что смотрит отбор; строковый
    вердикт нужен борду, чтобы показать разницу между «провалено» и «не
    замерено», иначе оператор чинит не то.
    """
    required = required_gates() if required is None else list(required)
    results = {g["gate"]: g for g in gates.values()} if isinstance(gates, dict) \
        else {g["gate"]: g for g in gates}

    failed = sorted(n for n, g in results.items() if g["state"] == FAIL)
    # Обязательные ворота, которых в словаре просто нет, — тоже незамер:
    # отсутствие записи ничем не лучше явного NOT_MEASURED, а раньше именно
    # оно и давало ложный зелёный.
    missing = sorted(n for n in required
                     if results.get(n, {}).get("state", NOT_MEASURED) == NOT_MEASURED)

    if failed:
        state = FAIL
    elif missing:
        state = NOT_MEASURED
    else:
        state = PASS
    return {"verdict": state, "ships": state == PASS, "failed": failed,
            "missing": missing, "gates": results,
            "unmeasured_optional": sorted(
                n for n, g in results.items()
                if g["state"] == NOT_MEASURED and n not in required)}


def format_report(res, title=""):
    """Одна строка на ворота — то, что печатают gate-скрипт и борд."""
    mark = {PASS: "ok  ", FAIL: "FAIL", NOT_MEASURED: "n/m "}
    lines = [f"{title}  →  {res['verdict']}"] if title else [res["verdict"]]
    for name in sorted(res["gates"]):
        g = res["gates"][name]
        v = "—" if g["value"] is None else f"{g['value']:.4g}"
        rng = ""
        if g["min"] is not None or g["max"] is not None:
            rng = f" [{g['min'] if g['min'] is not None else '−∞'}"
            rng += f", {g['max'] if g['max'] is not None else '+∞'}]"
        note = f"  — {g['note']}" if g["note"] else ""
        lines.append(f"  {mark[g['state']]} {name:12} {v:>10}{rng}{note}")
    return "\n".join(lines)


def main():
    setup_console()
    req = ["chroma", "sharp", "skin", "identity"]
    cases = {
        "всё замерено и в допуске": {
            "chroma": gate("chroma", 0.47, lo=0.34),
            "sharp": gate("sharp", 236.9, lo=60, hi=520),
            "skin": gate("skin", 0.05, hi=0.45),
            "identity": gate("identity", 0.81, lo=0.75),
            "detector": gate("detector", 0.12, hi=0.45),
        },
        "провал по резкости": {
            "chroma": gate("chroma", 0.47, lo=0.34),
            "sharp": gate("sharp", 20.6, lo=60, hi=520),
            "skin": gate("skin", 0.86, hi=0.45),
            "identity": gate("identity", 0.81, lo=0.75),
        },
        "нет insightface — идентичность не замерена": {
            "chroma": gate("chroma", 0.47, lo=0.34),
            "sharp": gate("sharp", 236.9, lo=60, hi=520),
            "skin": gate("skin", 0.05, hi=0.45),
            "identity": not_measured("identity", "insightface недоступен"),
        },
        "нет ключа к детектору — необязательные ворота": {
            "chroma": gate("chroma", 0.47, lo=0.34),
            "sharp": gate("sharp", 236.9, lo=60, hi=520),
            "skin": gate("skin", 0.05, hi=0.45),
            "identity": gate("identity", 0.81, lo=0.75),
            "detector": not_measured("detector", "нет ключа в окружении"),
        },
        "обязательных ворот вообще нет в отчёте": {
            "chroma": gate("chroma", 0.47, lo=0.34),
        },
    }
    expect = {"всё замерено и в допуске": PASS,
              "провал по резкости": FAIL,
              "нет insightface — идентичность не замерена": NOT_MEASURED,
              "нет ключа к детектору — необязательные ворота": PASS,
              "обязательных ворот вообще нет в отчёте": NOT_MEASURED}

    bad = 0
    for title, gates in cases.items():
        res = verdict(gates, required=req)
        ok = res["verdict"] == expect[title]
        bad += not ok
        print(format_report(res, title), f"\n  ожидалось {expect[title]}: "
              f"{'сходится' if ok else 'РАСХОЖДЕНИЕ'}\n")
    print(f"обязательные ворота: {req}")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
