#!/usr/bin/env python3
"""Лицо кадра одним проходом buffalo_l: бокс, 5 точек, эмбеддинг, возраст, пол.

  py -3 scripts/metrics/faces.py [<png> …]

Без аргументов проходит по `<work_root>/bridget/frames`.

ОДИН АНАЛИЗАТОР НА ПРОЦЕСС. `FaceAnalysis` поднимает пять onnx-моделей общим
весом ~340 МБ; на этой машине загрузка занимает 3.3 с, а сам разбор кадра —
0.9 с. Создавать его на кадр — значит потратить на батче в сорок кадров две
минуты впустую и получить пилу по памяти. Поэтому анализатор лежит в глобале и
поднимается один раз, лениво: модуль обязан импортироваться и там, где лица
никто не спросит.

ДЕГРАДАЦИЯ ЧЕСТНАЯ. Нет onnxruntime, нет insightface, не скачались веса, не
нашлось лица — это `NOT_MEASURED` с текстовой причиной, а не ноль, не None и
не исключение на импорте. Ноль здесь особенно опасен: возраст 0 попал бы в
полосу «моложе 45» и прочитался бы как ЗАМЕРЕННЫЙ провал, то есть кадр
переснимали бы вместо того, чтобы поставить зависимость.

ДВА ИНТЕРФЕЙСА НА ОДНОМ ЗАМЕРЕ:
  `detect()` — не бросает никогда, возвращает словарь с полем `state`;
  `analyse()` — бросает `RuntimeError` с причиной, если лица нет. Так его ждут
  `gates.py` и `casting.py`: там исключение ловится и его текст становится
  объяснением NOT_MEASURED, а молчаливый None объяснением не становится.

ЧТО ВОРОТА ВОЗРАСТА МЕРЯЮТ НА САМОМ ДЕЛЕ. На 29 реальных кадрах ОДНОГО
персонажа (те же четыре ячейки, один и тот же блок маркеров возраста в
промпте) genderage выдаёт разброс 36-64 года при заявленном 51, и девять
кадров не попадают в полосу манифеста 45-58. Разброс в 28 лет на одном
человеке — это шум оценщика, а не разброс кадров, и на предыдущем поколении
тех же ячеек он был смещён в другую сторону: 30-57 при том же персонаже, с
31 кадром из 45 вне полосы.

Отсюда два следствия, оба неприятных. Полосу двигать здесь нельзя — её задаёт
ТЗ на персонажа, а не калибровка. Но и трактовать провал по возрасту как
приговор кадру нельзя тоже: чаще это промах оценщика. Разбирать такие провалы
надо глазами, а не перегоном.

ПОЛ genderage тоже путает: на двух кадрах из 29 он вернул M. Поле `sex`
поэтому отдаётся наружу как есть и воротами не судится.
"""
import sys, os, glob, math, warnings, contextlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _util import age_band, cli_opt, setup_console, manifest
from metrics import load_bgr
from metrics.verdict import PASS, NOT_MEASURED, not_measured

MODEL = "buffalo_l"
DET_SIZE = (640, 640)

_APP = None      # (анализатор | None, причина отказа | None)


def analyser():
    """Кэшированный `FaceAnalysis`. Возвращает (анализатор|None, причина|None)."""
    global _APP
    if _APP is not None:
        return _APP
    try:
        # insightface тянет skimage, а тот на каждом выравнивании лица кидает
        # FutureWarning про SimilarityTransform. На батче это сорок одинаковых
        # абзацев в stderr поверх таблицы ворот.
        warnings.filterwarnings("ignore", category=FutureWarning,
                                message=".*estimate.*deprecated.*")
        import onnxruntime
        from insightface.app import FaceAnalysis

        have_cuda = "CUDAExecutionProvider" in onnxruntime.get_available_providers()
        providers = (["CUDAExecutionProvider", "CPUExecutionProvider"]
                     if have_cuda else ["CPUExecutionProvider"])
        # insightface печатает пути к моделям и список провайдеров в stdout.
        # Ворота умеют отдавать отчёт в stdout как JSON — семь строк «find
        # model: …» посреди него ломают разбор у любого, кто читает пайп.
        with contextlib.redirect_stdout(sys.stderr):
            app = FaceAnalysis(name=MODEL, providers=providers)
            app.prepare(ctx_id=0 if have_cuda else -1, det_size=DET_SIZE)
        _APP = (app, None)
    except Exception as e:
        # Скачивание весов при первом запуске тоже падает сюда: без сети
        # insightface бросает прямо из prepare().
        _APP = (None, f"{type(e).__name__}: {e}")
    return _APP


def inter_pupillary_distance(kps):
    """Расстояние между зрачками, px — единственная величина лица, не зависящая
    от кадрирования, поворота головы и щедрости детектора к боксу.

    Все масштабы в `sharpness.py` и `skin.py` заданы в её долях: в пикселях
    «поры кожи» означали бы разное на портрете и на ростовом плане, и метрика
    мерила бы крупность плана, а не кожу.
    """
    k = np.asarray(kps, np.float32)
    return float(math.hypot(*(k[1] - k[0])))


def main_face(found):
    """Лицо героини из всех найденных. Выбор по МЕЖЗРАЧКОВОМУ РАССТОЯНИЮ.

    Раньше выбиралось самое крупное по ПЛОЩАДИ БОКСА, и рассуждение было
    такое: героиня ближе всех к камере, значит её лицо больше. Рассуждение
    верное, мера — нет. Бокс детектора растягивается на срезанной и размытой
    голове: на кадре ресторана голова собеседника на переднем плане, обрезанная
    краем кадра и лежащая вне фокуса, дала бокс 176x378 (площадь 66436) при
    МЕЖЗРАЧКОВОМ РАССТОЯНИИ 15 px и уверенности 0.51, а героиня — бокс 211x298
    (площадь 62793) при IPD 101 и уверенности 0.88. Победил по площади мусор, и
    косинус к референсу вышел -0.003 вместо +0.226. Такой кадр читался как
    «совсем чужое лицо» и вылетал из датасета — притом что на нём она.

    Межзрачковое расстояние этим не обманывается: оно меряет ЛИЦО, а не
    прямоугольник вокруг него, и не растёт от того, что рамку вытянуло. По той
    же причине в нём считаются все прочие масштабы конвейера (sharpness.py,
    skin.py, mark.py) — мера крупности лица здесь ровно одна.

    При равном IPD побеждает уверенность детектора: два одинаково крупных лица
    в кадре — это уже не «фон», а вторая героиня, и брать надо ту, в которой
    детектор уверен.
    """
    return max(found, key=lambda f: (inter_pupillary_distance(f.kps),
                                     float(f.det_score)))


def detect(src, min_det_score=0.5):
    """Лицо героини в кадре. Никогда не бросает.

    Какое именно из найденных — см. `main_face`. Число найденных отдаётся
    наружу полем `faces_in_frame`: кадр с двумя лицами для обучения лоры не
    годится независимо от того, чьё лицо мы измерили, и знать об этом надо.
    """
    app, why = analyser()
    if app is None:
        return not_measured("face", f"детектор недоступен — {why}")
    try:
        img = load_bgr(src)
    except Exception as e:
        return not_measured("face", f"кадр не читается — {e}")
    with contextlib.redirect_stdout(sys.stderr):
        faces = app.get(img)
    faces = [f for f in faces if float(f.det_score) >= min_det_score]
    if not faces:
        return not_measured("face", "лица не найдено")

    f = main_face(faces)
    kps = [[float(a), float(b)] for a, b in np.asarray(f.kps, np.float32)]
    return {"gate": "face", "state": PASS, "value": float(f.det_score),
            "faces_in_frame": len(faces),
            "min": None, "max": None, "note": "",
            "bbox": [float(v) for v in f.bbox],
            "kps": kps,
            "embedding": [float(v) for v in f.normed_embedding],
            "age": int(f.age) if f.age is not None else None,
            "sex": str(f.sex) if f.sex else None,
            "det_score": float(f.det_score),
            "ipd_px": inter_pupillary_distance(kps),
            # РАЗМЕТКА В 106 ТОЧЕК — ОСНОВА МЕТРИК ОПОЗНАВАНИЯ. Пять точек
            # детектора (два зрачка, нос, два угла рта) не описывают ни бровей,
            # ни контура губ, ни радужки — то есть ни одного из признаков,
            # которыми карточка персонажа его опознаёт. Модель 2d106det уже
            # входит в buffalo_l и считается тем же проходом, так что отдавать
            # её наружу бесплатно, а не отдавать — значит заставить каждую
            # метрику поднимать детектор заново (3.3 с загрузки, 0.9 с на кадр).
            "kps106": ([[float(a), float(b)] for a, b in
                        np.asarray(f.landmark_2d_106, np.float32)]
                       if getattr(f, "landmark_2d_106", None) is not None
                       else None),
            "frame_size": [int(img.shape[1]), int(img.shape[0])]}


def analyse(src, min_det_score=0.5):
    """То же, но бросает `RuntimeError` вместо `NOT_MEASURED`.

    Ровно этого ждут `gates.py` и `casting.py`: там исключение перехватывается
    и его текст уходит в отчёт как причина незамера.
    """
    res = detect(src, min_det_score)
    if res["state"] != PASS:
        raise RuntimeError(res["note"])
    return res


def cosine(a, b):
    """Косинус между эмбеддингами; None, если сравнивать нечего."""
    if a is None or b is None or len(a) != len(b):
        return None
    a = np.asarray(a, np.float64)
    b = np.asarray(b, np.float64)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if not na or not nb:
        return None
    return float(a @ b / (na * nb))


def _frames(argv):
    # Ключи и их значения не кадры: без этого --age 34 превращался в два
    # несуществующих пути и самотест падал на чтении файла «--age».
    out, skip = [], False
    for i, a in enumerate(argv):
        if skip:
            skip = False; continue
        if a.startswith("--"):
            skip = a in ("--age",); continue
        out.append(a)
    if out:
        return out
    root = os.path.join(manifest()["paths"]["work_root"], "bridget", "frames")
    return sorted(glob.glob(os.path.join(root, "*", "*.png"))
                  + glob.glob(os.path.join(root, "*.png")))


def main():
    setup_console()
    files = _frames(sys.argv[1:])
    if not files:
        raise SystemExit("нечего разбирать: передайте пути к кадрам")

    app, why = analyser()
    print(f"анализатор {MODEL}: {'поднят' if app else 'НЕДОСТУПЕН — ' + why}")
    # ПОЛОСА ВОЗРАСТА ЗАВИСИТ ОТ КАРТОЧКИ, А САМОТЕСТ КАРТОЧКИ НЕ ЗНАЕТ.
    # Раньше здесь стояли жёсткие age_min/age_max из манифеста — верные ровно
    # для одного персонажа; на кадрах второго строка «вне полосы» врала бы.
    # Теперь полоса показывается только когда её есть от чего считать: ключ
    # --age <лет>. Без него колонка возраста печатается без приговора.
    g = manifest()["gates"]
    lo = hi = None
    want = cli_opt(sys.argv[1:], "--age")
    if want is not None:
        lo, hi = age_band({"age": float(want)}, g)
    elif "age_min" in g:
        lo, hi = float(g["age_min"]), float(g["age_max"])
    print(f"\n{'кадр':26} {'состояние':13} {'бокс, px':>11} {'IPD':>7} "
          f"{'возр':>5} {'пол':>4} {'det':>5}  косинус к первому"
          + (f"   (полоса {lo:.0f}-{hi:.0f})" if lo is not None else ""))

    first = None
    for path in files:
        r = detect(path)
        name = os.path.basename(path)
        if r["state"] != PASS:
            print(f"{name:26} {NOT_MEASURED:13} {'—':>11} {'—':>7} {'—':>5} "
                  f"{'—':>4} {'—':>5}  {r['note']}")
            continue
        first = first if first is not None else r["embedding"]
        w = r["bbox"][2] - r["bbox"][0]
        h = r["bbox"][3] - r["bbox"][1]
        cos = cosine(r["embedding"], first)
        age = r["age"]
        # Полосы возраста у САМОЙ метрики нет: она зависит от карточки
        # персонажа, а самотест метрики карточки не знает и знать не должен.
        # Раньше здесь стояли жёсткие age_min/age_max, верные ровно для одного
        # человека, и на кадрах второго персонажа строка врала бы.
        band = ""
        if lo is not None and not (lo <= age <= hi):
            band = f"  ← вне полосы {lo:.0f}-{hi:.0f}"
        print(f"{name:26} {PASS:13} {w:5.0f}x{h:<5.0f} {r['ipd_px']:7.1f} "
              f"{age:5d} {r['sex'] or '—':>4} {r['det_score']:5.2f}  "
              f"{cos:.4f}{band}")

    print("\nэмбеддинг нормирован (|v| = 1), косинус к самому себе = 1.0000")


if __name__ == "__main__":
    main()
