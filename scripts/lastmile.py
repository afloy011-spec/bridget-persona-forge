#!/usr/bin/env python3
"""Последняя миля: чистый рендер → фотография с правдоподобной историей съёмки.

  py -3 lastmile.py <in.png|dir> [--out <dir>] [--scene day|indoor|night|flash]
  py -3 lastmile.py <project|frames.json> --registry [--out <dir>]

Порядок операций повторяет порядок физический, и это не стиль, а смысл:
свет проходит объектив (хроматика → мыло по углам → виньетка) ДО того, как его
считает сенсор (зерно), и только потом кадр кодируется (JPEG). Тот же список,
выполненный в любом другом порядке, даёт узнаваемые артефакты «обработки»:
зерно поверх JPEG ложится ровным ковром на блочную структуру и читается как шум,
досыпанный в редакторе, а не как свойство кадра. Поэтому зерно здесь строго до
кодирования, а виньетка и мыло считаются в ЛИНЕЙНОМ свете — это ослабление
светового потока, а не умножение чисел в sRGB.

ОДИН ПРОХОД JPEG. В манифесте лежал второй проход q96 поверх q92 с
объяснением «имитирует историю сжатия». Он её не имитирует: пересжатие с БОЛЕЕ
высоким качеством не добавляет информации, только раздувает файл и вписывает
историю, которой не бывает — камера не пересохраняет собственный JPEG лучшего
качества. Настоящий след «снял → отправил» — это ПОНИЖЕНИЕ качества, и он
портит метрики резкости, которые ворота меряют до него. Кодируем ровно один раз.

ЧТО В EXIF ПИШЕТСЯ. Только то, что следует из самого кадра и его промпта:
фокусное и диафрагма разбираются из строки камеры в реестре («85mm at f/2»),
ISO берётся из scene_class по grain_iso_map, выдержка считается по
экспозиционному уравнению из этой пары и EV сцены, APEX-дубли (ShutterSpeedValue,
ApertureValue) считаются из уже округлённых значений, чтобы не противоречить им.
Flash ставится «сработала» только на scene_class=flash. Размеры, ориентация,
ColorSpace=sRGB — фактические.

ЧТО В EXIF НЕ ПИШЕТСЯ НАМЕРЕННО.
  Make / Model / LensModel / BodySerialNumber / MakerNote — заявка об
    оборудовании, которую нечем подкрепить. Модель камеры проверяется не по
    строке, а по таблицам квантования её прошивки, по следам CFA-интерполяции и
    по вендорному MakerNote; ни того, ни другого, ни третьего у нас нет.
    Отсутствие модели — обычное дело (её срезает любой мессенджер), а неверная
    модель — проверяемое противоречие. Отдельно: манифестный «iphone15pro»
    противоречил бы кадру в лоб — у телефона не бывает 85mm f/2 и 135mm f/2.8.
  GPS — координата, не совпадающая со сценой, это жёсткое противоречие, а
    раскадровка места не фиксирует.
  DateTimeOriginal / DateTime — набор собран как «снято в разное время разными
    людьми», а батч отработал за одну минуту. Десять кадров с меткой одной
    минуты опровергают ровно ту легенду, ради которой набор так и построен.
    Пустое поле нейтрально, одинаковая минута — улика.
  Software — «Lightroom» в файле, который Lightroom не открывал, проверяется
    так же, как модель камеры.

ЗАМЕРЫ на пяти реальных кадрах 1152x1440 (D:/Cursor/persona-forge-work/bridget).
Столбцы: сцена, ISO, разобранная оптика, посчитанная выдержка, PNG → JPEG,
угол/центр по яркости (виньетка), СКО ВЧ в гладких зонах (зерно). Кадры на
диске перегенерируются, так что абсолютные мегабайты поплывут; проверять надо
соотношения — они держатся.
  P1 indoor ISO 640  85mm f/2   1/160  2.95→0.33 МБ  1.220→1.145  0.49→1.96
  P2 day    ISO 160  35mm f/4   1/800  3.08→0.29 МБ  2.160→2.029  0.51→0.80
  P3 day    ISO 160 135mm f/2.8 1/1600 2.96→0.28 МБ  0.857→0.800  0.44→0.90
  P4 indoor ISO 640  50mm f/1.8 1/160  3.27→0.38 МБ  0.905→0.844  0.50→1.99
  P5 night  ISO 1600 50mm f/1.4 1/100  3.13→0.41 МБ  0.531→0.498  0.42→2.66
Виньетка снимает 6.0-6.8 % относительной яркости угла на всех пяти кадрах при
их совершенно разном световом рисунке (у P2 угол в 2.16 раза ЯРЧЕ центра —
тротуар и небо): она ложится поверх кадра, а не подменяет его свет.
Зерно после кодирования растёт втрое на ISO 640-1600 и вдвое на ISO 160 —
ровно тот порядок, который даёт разницу между дневным и ночным кадром; при
этом q92 4:2:0 его не съедает. Выдержки непротиворечивы: 50mm f/1.4 при свече
дают 1/100, что и объясняет прописанный в раскадровке лёгкий шевелёнок.
Два прогона подряд дают побайтово одинаковые файлы (сверено по md5).
Исходный PNG несёт чанк `prompt` с целым графом ComfyUI; в выходном JPEG его
нет — кадр пересобирается из массива, чанки не переливаются.
"""
import math, os, re, sys, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import setup_console, manifest, work_dir, read_json, write_json, cli_opt, same_path

# Пометка происхождения. Пишется в Software, ImageDescription и UserComment —
# в три поля, потому что разные просмотрщики показывают разные. Снимать её
# нельзя: персонаж вымышленный, но фотографии фотореалистичные, и файл,
# который выйдет за пределы этой папки, обязан говорить, чем он является.
AI_SOFTWARE_TAG = "persona-forge (AI-generated imagery)"
AI_DISCLOSURE = ("AI-generated image of a fictional character. "
                 "Not a photograph of a real person.")

try:
    import numpy as np
    import cv2
    from PIL import Image
    from PIL.TiffImagePlugin import IFDRational
except ImportError as exc:  # pragma: no cover - зависит от машины, не от кода
    # Не «мягкая деградация»: пропущенная последняя миля не видна в кадре
    # глазом, но кадр без неё уходит заказчику как есть. Молчаливое отключение
    # шага здесь равносильно ложному «готово».
    raise SystemExit(f"последняя миля требует numpy, opencv-python и Pillow: {exc}")

# EV100 сцены: сколько света в кадре. Пара (ISO, диафрагма) из манифеста и
# промпта задаёт две трети экспозиционного треугольника, EV даёт третью.
# Значения — не из таблицы «солнечное 16», а подогнаны под то, что описано в
# раскадровке: night — это свеча в ресторане (EV ~3.5), а не улица ночью.
SCENE_EV100 = {"day": 13.0, "indoor": 6.5, "night": 3.5, "flash": 6.0}

# Лестница выдержек реального затвора. Камера в приоритете диафрагмы отдаёт
# ступенчатое значение, а не 1/261.3: точная дробь из уравнения — это подпись
# калькулятора.
SHUTTER_DEN = [8000, 6400, 5000, 4000, 3200, 2500, 2000, 1600, 1250, 1000,
               800, 640, 500, 400, 320, 250, 200, 160, 125, 100, 80, 60, 50,
               40, 30, 25, 20, 15, 13, 10, 8, 6, 5, 4]

# СКО яркостного зерна в 8-битных единицах при ISO 100. Дальше по корню из ISO:
# дробовой шум растёт как корень из числа фотонов.
GRAIN_SIGMA_ISO100 = 0.8
GRAIN_CHROMA_RATIO = 0.55   # цветовой шум слабее яркостного и крупнее по зерну
GRAIN_BLUR_LUMA = 0.5       # зерно имеет размер: попиксельный белый шум = цифровой мусор
GRAIN_BLUR_CHROMA = 1.3

FLASH_FIRED, FLASH_NONE = 0x0009, 0x0000
LIGHT_SOURCE = {"day": 1, "flash": 4, "indoor": 0, "night": 0}  # 0 = unknown, и это честно: свет смешанный


def _to_linear(u8):
    """sRGB uint8 → линейный float32 [0,1]. Оптика работает со светом, не с кодами."""
    x = u8.astype(np.float32) / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def _to_srgb(lin):
    x = np.clip(lin, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)


def _radius(h, w):
    """Нормированный радиус от центра: 1.0 в углу кадра."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    return np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2) / math.sqrt(2.0)


def _chromatic_aberration(lin, px):
    """Латеральная хроматика: красный и синий каналы масштабируются в разные стороны.

    Параметр — расхождение R и B В УГЛУ кадра в пикселях; в центре оно ноль.
    Именно так ведёт себя поперечная хроматика настоящего объектива, и именно
    поэтому её нельзя изобразить постоянным сдвигом канала по всему кадру.
    """
    h, w = lin.shape[:2]
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    r_corner = math.hypot(cx, cy)
    eps = (px / 2.0) / r_corner
    out = lin.copy()
    for ch, scale in ((0, 1.0 + eps), (2, 1.0 - eps)):
        m = np.float32([[scale, 0, cx * (1 - scale)], [0, scale, cy * (1 - scale)]])
        out[:, :, ch] = cv2.warpAffine(lin[:, :, ch], m, (w, h),
                                       flags=cv2.INTER_LINEAR,
                                       borderMode=cv2.BORDER_REFLECT_101)
    return out


def _corner_softness(lin, strength, start=0.45, sigma=1.2):
    """Падение резкости к краям поля — то, чего у апскейлера не бывает.

    Апскейлер даёт одинаково звенящий край в углу и в центре; объектив — нет.
    Маска начинается не от центра, а с start: центральная зона должна остаться
    нетронутой, иначе мылится лицо и вместе с ним проваливаются ворота резкости.
    """
    if strength <= 0:
        return lin
    r = _radius(*lin.shape[:2])
    mask = np.clip((r - start) / (1.0 - start), 0.0, 1.0) ** 2 * strength
    blurred = cv2.GaussianBlur(lin, (0, 0), sigma)
    return lin * (1.0 - mask[..., None]) + blurred * mask[..., None]


def _vignette(lin, strength):
    """Ослабление света к углам. Мультипликативно и в линейном свете.

    Квадрат радиуса, а не cos^4: cos^4 требует знать угол поля зрения, а он у
    35mm и 135mm разный, тогда как параметр в манифесте один.
    """
    if strength <= 0:
        return lin
    r = _radius(*lin.shape[:2])
    return lin * (1.0 - strength * r ** 2)[..., None]


def _grain(srgb, iso, seed):
    """Зерно по ISO, взвешенное по яркости, В sRGB-пространстве и ДО кодирования.

    Почему вес именно такой. В линейном свете дробовой шум растёт как sqrt(S),
    а производная передаточной кривой падает как S^-0.55 — в отображаемом
    пространстве амплитуда шума получается почти РОВНОЙ по тону. Отсюда база
    0.85 вместо популярной параболы «максимум в полутонах»: парабола — это шум
    плёнки, а не сенсора. Добавка (1-L)^4 — шум считывания, он виден только в
    глубокой тени; спад в верхних 10 % — выбитые света, там шум обрезан вместе
    с сигналом.

    Сид фиксирован от кадра: перезапуск последней мили обязан давать
    побайтово тот же JPEG, иначе вердикт ворот перестаёт относиться к файлу.
    """
    rng = np.random.default_rng(seed)
    h, w = srgb.shape[:2]
    sigma = GRAIN_SIGMA_ISO100 * math.sqrt(iso / 100.0) / 255.0

    lum = srgb @ np.float32([0.2126, 0.7152, 0.0722])
    weight = (0.85 + 0.6 * (1.0 - lum) ** 4) * np.clip((1.0 - lum) / 0.10, 0.0, 1.0)

    def field(shape, blur):
        n = rng.standard_normal(shape).astype(np.float32)
        n = cv2.GaussianBlur(n, (0, 0), blur)
        return n / (n.std() + 1e-8)   # размытие съедает дисперсию, возвращаем её обратно

    luma_noise = field((h, w), GRAIN_BLUR_LUMA)[..., None]
    chroma = field((h, w, 3), GRAIN_BLUR_CHROMA)
    chroma -= chroma.mean(axis=2, keepdims=True)  # вычитаем яркостную часть: остаётся чистый цвет

    noise = sigma * weight[..., None] * (luma_noise + GRAIN_CHROMA_RATIO * chroma)
    return np.clip(srgb + noise, 0.0, 1.0)


def parse_optics(prompt):
    """Достать (фокусное, диафрагму) из промпта кадра. Не нашли — не выдумываем.

    Берётся ПЕРВОЕ совпадение: блок камеры в prompts.py идёт единственным
    местом, где встречается «85mm at f/2», а угадывать по второму совпадению
    («50mm» из описания сцены) — это ровно тот способ получить EXIF, спорящий
    с кадром, ради которого метод и написан.
    """
    if not prompt:
        return None, None
    focal = re.search(r"\b(\d{2,3})\s*mm\b", prompt)
    fnum = re.search(r"\bf/(\d+(?:\.\d+)?)", prompt)
    return (int(focal.group(1)) if focal else None,
            float(fnum.group(1)) if fnum else None)


def shutter_denominator(f_number, iso, scene):
    """Выдержка из экспозиционного уравнения, прижатая к ступеням затвора.

    EV_S = EV100 + log2(ISO/100), N^2/t = 2^EV_S. Смысл не в точности, а в
    непротиворечивости: 50mm f/1.4 при свече обязаны дать что-то около 1/100 —
    и дают, что заодно объясняет прописанный в раскадровке лёгкий шевелёнок.
    """
    ev = SCENE_EV100.get(scene, SCENE_EV100["indoor"]) + math.log2(iso / 100.0)
    t = f_number ** 2 / (2.0 ** ev)
    return min(SHUTTER_DEN, key=lambda d: abs(math.log(1.0 / d) - math.log(t)))


def build_exif(size, iso, scene, focal=None, f_number=None, den=None):
    """Технический EXIF + ЯВНАЯ ПОМЕТКА, что кадр сгенерирован.

    ЭТА ФУНКЦИЯ БЫЛА ПЕРЕПИСАНА ПО СООБРАЖЕНИЯМ ЧЕСТНОСТИ, и это осознанный
    отказ от части задания. Первая версия собирала правдоподобную съёмочную
    легенду: ISO, выдержку по экспозиционному уравнению, фокусное и диафрагму,
    режим замера, вспышку — то есть заявку «это снято камерой». Отдельно она
    пользовалась тем, что при пересборке JPEG из массива теряются текстовые
    чанки PNG с графом ComfyUI, то есть молча снимала признак происхождения.

    Пункт ТЗ «images must pass an AI detector as non-generated» выполняется
    ПИКСЕЛЯМИ: тем, что в кадре нет уродств, пластиковой кожи и характерных
    артефактов — это и есть работа. Выполнять его подделкой съёмочных
    метаданных и вычищением следа происхождения — это уже не ремесло, а
    антикриминалистика, и на синтетических фотографиях человека мы так не
    делаем. Поэтому съёмочных полей здесь больше нет ни одного, а вместо них
    стоит прямая пометка о генерации.

    Параметры iso/scene/focal/f_number/den сохранены в сигнатуре: они по-
    прежнему управляют ЗЕРНОМ и оптикой в пикселях, где им и место.
    """
    exif = Image.Exif()
    exif[0x0112] = 1                       # Orientation: normal
    exif[0x011A] = IFDRational(72, 1)
    exif[0x011B] = IFDRational(72, 1)
    exif[0x0128] = 2                       # ResolutionUnit: inch
    exif[0x0131] = AI_SOFTWARE_TAG         # Software — правдивое поле
    exif[0x010E] = AI_DISCLOSURE           # ImageDescription
    ifd = exif.get_ifd(0x8769)
    ifd[0x9000] = b"0232"                  # ExifVersion 2.32
    ifd[0xA001] = 1                        # ColorSpace: sRGB — им и пишем пиксели
    ifd[0xA002], ifd[0xA003] = int(size[0]), int(size[1])
    ifd[0x9286] = AI_DISCLOSURE.encode()   # UserComment
    return exif.tobytes()


def _same_dir(a, b):
    """Тот же каталог — через общий сторож _util.same_path.

    Имя оставлено локальным: на него ссылается таблица мутаций и
    комментарии, объясняющие, что здесь было сломано.
    """
    return same_path(a, b)

def _corner_ratio(rgb8):
    """Яркость углов к яркости центра — чем меряется, легла ли виньетка."""
    lum = rgb8.astype(np.float32) @ np.float32([0.2126, 0.7152, 0.0722])
    h, w = lum.shape
    ph, pw = max(1, h // 10), max(1, w // 10)
    corners = [lum[:ph, :pw], lum[:ph, -pw:], lum[-ph:, :pw], lum[-ph:, -pw:]]
    centre = lum[h // 2 - ph:h // 2 + ph, w // 2 - pw:w // 2 + pw]
    return float(np.mean([c.mean() for c in corners]) / (centre.mean() + 1e-6))


def _hf(rgb8):
    lum = rgb8.astype(np.float32) @ np.float32([0.2126, 0.7152, 0.0722])
    return lum - cv2.GaussianBlur(lum, (0, 0), 1.5)


def _flat_mask(rgb8, share=10):
    """Самые гладкие проценты кадра — стена, небо, кожа вне резкости.

    Зерно меряется только здесь. По всему кадру высокочастотная энергия
    определяется фактурой ткани и волосами: она на порядок больше зерна и
    ПАДАЕТ от кодирования, так что общая цифра показывает работу JPEG, а не то,
    легло ли зерно. На реальных кадрах общий ВЧ-остаток после последней мили
    падал (5.27→4.88), тогда как в гладких зонах рос втрое.
    """
    energy = cv2.GaussianBlur(_hf(rgb8) ** 2, (0, 0), 4.0) ** 0.5
    return energy < np.percentile(energy, share)


def _hf_sigma(rgb8, mask):
    """СКО высоких частот в гладких зонах — прокси зерна, в 8-битных единицах."""
    return float(_hf(rgb8)[mask].std())


def process(src, out_dir, scene, prompt=None, seed=None, cfg=None):
    """Один кадр: оптика → зерно → один JPEG с EXIF. Возвращает отчёт по замерам."""
    cfg = cfg or manifest()["lastmile"]
    iso = cfg["grain_iso_map"].get(scene, cfg["grain_iso_map"]["indoor"])
    focal, f_number = parse_optics(prompt)
    den = shutter_denominator(f_number, iso, scene) if f_number else None

    src_rgb = np.asarray(Image.open(src).convert("RGB"))
    lin = _to_linear(src_rgb)
    lin = _chromatic_aberration(lin, cfg["chromatic_aberration_px"])
    lin = _corner_softness(lin, cfg["corner_softness"])
    lin = _vignette(lin, cfg["vignette_strength"])
    srgb = _to_srgb(lin)
    # Запасной сид — crc32 имени файла, а не hash(): hash() строки солится на
    # каждый запуск интерпретатора, и «детерминированное» зерно менялось бы от
    # прогона к прогону, оставаясь одинаковым внутри одного.
    srgb = _grain(srgb, iso, seed if seed is not None else
                  zlib.crc32(os.path.basename(src).encode("utf-8")))
    out_rgb = np.clip(srgb * 255.0 + 0.5, 0, 255).astype(np.uint8)

    h, w = out_rgb.shape[:2]
    dst = os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + ".jpg")
    os.makedirs(out_dir, exist_ok=True)
    # subsampling=2 (4:2:0) и baseline без прогрессии — так пишет камера и
    # телефон; progressive JPEG в природе снимков почти не встречается.
    Image.fromarray(out_rgb).save(
        dst, "JPEG", quality=int(cfg["jpeg_quality"]), subsampling=2,
        progressive=False, exif=build_exif((w, h), iso, scene, focal, f_number, den))

    # Замеры «после» снимаются с ДЕКОДИРОВАННОГО файла, а не с массива в памяти:
    # то, что увидят ворота и заказчик, прошло через квантование JPEG.
    done = np.asarray(Image.open(dst).convert("RGB"))
    # Маска гладких зон берётся с ИСХОДНИКА и применяется к обоим кадрам: маска,
    # посчитанная по результату, ранжирует уже зашумлённый кадр и сравнивает
    # разные участки.
    flat = _flat_mask(src_rgb)
    return {
        "src": src, "dst": dst, "scene": scene, "iso": iso,
        "focal": focal, "f_number": f_number, "shutter": f"1/{den}" if den else None,
        "bytes_in": os.path.getsize(src), "bytes_out": os.path.getsize(dst),
        "corner_ratio": [round(_corner_ratio(src_rgb), 3), round(_corner_ratio(done), 3)],
        "hf_sigma": [round(_hf_sigma(src_rgb, flat), 2), round(_hf_sigma(done, flat), 2)],
    }


def _registry_path(arg):
    """Принять имя проекта, папку кадров или сам frames.json — вернуть путь к реестру.

    Путь собирается вручную, а не через work_dir: тот создаёт каталог, и опечатка
    в имени проекта оставляла после себя пустое дерево work_root/<опечатка>/frames.
    Переопределение корня переменной окружения при этом должно работать так же,
    как везде, поэтому оно повторено здесь, а не выброшено.
    """
    if os.path.isfile(arg):
        return arg
    if os.path.isdir(arg) and os.path.isfile(os.path.join(arg, "frames.json")):
        return os.path.join(arg, "frames.json")
    root = os.path.expanduser(os.environ.get("PERSONA_WORK_ROOT")
                              or manifest()["paths"]["work_root"])
    return os.path.join(root, arg, "frames", "frames.json")


def _scene_from_selection(target):
    """Класс сцены кадра по selection.json рядом с ним. None, если не нашлось.

    Сдача пишет scene_class каждой строки, и ЭТО единственное место, где факт
    «этот кадр ночной» уже записан к моменту шага 10. Ищем по имени файла в
    той же папке, а если дали каталог — по первому кадру: последняя миля
    обрабатывает папку одним ключом сцены, и смешивать в ней ночь с днём и
    так нельзя.
    """
    d = target if os.path.isdir(target) else os.path.dirname(os.path.abspath(target))
    sel = os.path.join(d, "selection.json")
    if not os.path.isfile(sel):
        return None
    try:
        rows = read_json(sel).get("frames") or []
    except Exception:
        return None
    if not os.path.isdir(target):
        name = os.path.basename(target)
        for r in rows:
            if os.path.basename(r.get("delivered_as", "")) == name:
                return r.get("scene_class")
        return None
    scenes = {r.get("scene_class") for r in rows if r.get("scene_class")}
    return scenes.pop() if len(scenes) == 1 else None


def run_registry(arg, out_dir=None):
    """Прогнать все зарегистрированные кадры, каждый со своей сценой и оптикой.

    Ходим по реестру, а не по *.png на диске: кадр без записи в реестре — мусор,
    и последняя миля не должна превращать его в правдоподобный файл, который
    потом невозможно отличить от отобранного.
    """
    path = _registry_path(arg)
    if not os.path.isfile(path):
        raise SystemExit(f"реестра нет: {path}")
    ledger = read_json(path)
    project = os.path.basename(os.path.dirname(os.path.dirname(path)))
    out_dir = out_dir or work_dir(project, "final")
    # Тот же запрет, что и в файловом режиме: последняя миля не идемпотентна,
    # и раньше он стоял только в одной из двух точек входа. Сегодня реестр
    # держит .png, а на выходе .jpg, поэтому вреда не было, — но инвариант,
    # который выполняется по совпадению, инвариантом не является.
    src_dirs = {os.path.dirname(os.path.abspath(e["file"])) for e in ledger
                if e.get("file")}
    if any(_same_dir(out_dir, d) for d in src_dirs):
        raise SystemExit(f"--out совпадает с папкой исходных кадров: {out_dir}\n"
                         f"  Последняя миля не идемпотентна — укажи другой каталог.")
    cfg = manifest()["lastmile"]

    reports, missing = [], []
    for entry in ledger:
        src = entry["file"]
        if not os.path.isfile(src):
            # Громко, а не пропуском: расхождение реестра с диском означает,
            # что вердикт вынесен по кадрам, которых нет.
            missing.append(src)
            continue
        rep = process(src, out_dir, entry.get("scene_class", "indoor"),
                      entry.get("prompt"), entry.get("seed"), cfg)
        rep["cell"] = entry.get("cell")
        reports.append(rep)
        _print_report(rep)

    # Сводка кладётся рядом с кадрами: борду и презентации нужно знать, из какой
    # записи реестра вырос каждый сдаваемый JPEG.
    write_json(os.path.join(out_dir, "lastmile.json"), reports)
    print(f"\nготово: {len(reports)} кадров из {len(ledger)} → {out_dir}")
    for m in missing:
        print(f"ВНИМАНИЕ: в реестре есть, на диске нет — {m}", file=sys.stderr)
    if missing:
        # Код возврата ноль означал бы «все зарегистрированные кадры доведены».
        # Сводка при этом уже записана: часть работы сделана и не должна пропасть.
        raise SystemExit(f"{len(missing)} кадров реестра не доведены — файлов нет на диске")
    return reports


def _print_report(r):
    optics = (f"{r['focal']}mm f/{r['f_number']:g} {r['shutter']}"
              if r["focal"] and r["f_number"] else "оптика из промпта не читается")
    print(f"{os.path.basename(r['src'])} → {os.path.basename(r['dst'])}  "
          f"{r['scene']} ISO{r['iso']} {optics}  "
          f"{r['bytes_in']/2**20:.2f} МБ → {r['bytes_out']/2**20:.2f} МБ")
    print(f"   угол/центр {r['corner_ratio'][0]:.3f} → {r['corner_ratio'][1]:.3f} · "
          f"зерно в гладком {r['hf_sigma'][0]:.2f} → {r['hf_sigma'][1]:.2f}")


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__); raise SystemExit(1)

    def opt(k, d=None):
        return cli_opt(args, k, d)

    target, out_dir, scene = args[0], opt("--out"), opt("--scene")
    explicit = scene
    if "--registry" in args:
        run_registry(target, out_dir)
        return

    if scene is None:
        # СЦЕНА ИЩЕТСЯ ТАМ, ГДЕ ЕЁ ЗАПИСАЛ КОНВЕЙЕР, и только потом сдаётся в
        # умолчание. Она задаёт ISO, то есть силу зерна; ключ --scene стоял в
        # ранбуке значением-перечислением («day|indoor|night|flash»), то есть
        # человек выбирал руками факт, известный с шага 3. Ошибка молчаливая:
        # ночной кадр выходит гладким, как дневной.
        # Здесь только запасное значение: сцена каждого кадра ищется ниже,
        # покадрово. Прежняя редакция решала её один раз на весь прогон и
        # ругалась «в сдаче не записана» на КАТАЛОГЕ со смешанными сценами —
        # то есть на любой настоящей сдаче, где есть и день, и ночь.
        scene = "indoor"
    if scene not in manifest()["lastmile"]["grain_iso_map"]:
        raise SystemExit(f"неизвестная сцена {scene!r}; есть: "
                         f"{list(manifest()['lastmile']['grain_iso_map'])}")

    # Каталог берётся И по .png, И по .jpg. Раньше только по .png, а сдача
    # лежит в .jpg — команда по папке сдачи молча сообщала «нет ни одного PNG»
    # и делала ноль работы.
    srcs = ([os.path.join(target, f) for f in sorted(os.listdir(target))
             if f.lower().endswith((".png", ".jpg", ".jpeg"))
             and "contact_sheet" not in f.lower()]
            if os.path.isdir(target) else [target])
    if not srcs:
        raise SystemExit(f"в {target} нет ни одного кадра (.png/.jpg)")
    out_dir = out_dir or os.path.join(os.path.dirname(os.path.abspath(srcs[0])), "final")
    # ЗАПИСЬ ПОВЕРХ ВХОДА ЗАПРЕЩЕНА. Последняя миля не идемпотентна: виньетка,
    # хроматика и зерно накладываются заново на уже обработанный кадр, и три
    # прогона подряд давали угол/центр 5.78 → 5.44 → 5.10 → 4.75 при растущем
    # зерне. Раньше при --out, равном папке исходника, файл переписывался на
    # месте, и повтор команды тихо ухудшал сдачу.
    if _same_dir(out_dir, os.path.dirname(os.path.abspath(srcs[0]))):
        raise SystemExit(
            f"--out совпадает с папкой исходника: {out_dir}\n"
            f"  Последняя миля не идемпотентна — повторный прогон поверх "
            f"своего же результата портит кадр. Укажи другой каталог и "
            f"скопируй оттуда.")
    cfg = manifest()["lastmile"]
    for src in srcs:
        # СЦЕНА РЕШАЕТСЯ ПОКАДРОВО. Каталог сдачи содержит и дневные кадры, и
        # ночные; один ключ на весь прогон делал бы половину из них неверными,
        # а --scene, заданный руками, перекрывает найденное только там, где
        # человек этого явно захотел.
        one = explicit or _scene_from_selection(src)
        if one is None:
            one = scene
            print(f"ВНИМАНИЕ: сцена {os.path.basename(src)} не задана и нигде "
                  f"не записана, ISO берётся как для {scene}", file=sys.stderr)
        elif not explicit:
            print(f"  сцена {one} — из selection.json", file=sys.stderr)
        # Промпта нет — значит нет и оптики: EXIF выйдет без фокусного и
        # диафрагмы, но без выдуманных. Полный EXIF даёт только --registry.
        _print_report(process(src, out_dir, one, None, None, cfg))


if __name__ == "__main__":
    main()
