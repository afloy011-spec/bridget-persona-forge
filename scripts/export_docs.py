#!/usr/bin/env python3
"""Экспорт проектных JSON в Markdown, который читает клиент.

  py -3 export_docs.py <project_dir> [--out docs/] [--strict]

Пишет <out>/character_bible.md, <out>/shotlist_part1.md и — если в проекте
лежит shotlist_story.json — <out>/shotlist_part2.md.

ПОЧЕМУ ЭКСПОРТЁР, А НЕ ДОКУМЕНТ РУКАМИ. Карточка и раскадровка правятся до
самого последнего кадра. Написанный руками документ расходится с ними молча, и
клиент читает промпт, которым ничего не генерировалось. Здесь текст кадра
собирает та же prompts.build_cell, что и сам кадр, — расходиться нечему.

ПОЧЕМУ ТАБЛИЦА ПЕРЕВОДА, А НЕ ПЕРЕВОД НА ЛЕТУ. Рецензент читает по-английски, а
режиссёрские обоснования в JSON написаны по-русски — они писались для того, кто
ведёт проект. Переводить в рантайме нечем (скилл живёт на голой стандартной
библиотеке), поэтому перевод лежит таблицей EN ниже, ключ — путь до поля.

Правило жёсткое: кириллица попадает в документ ТОЛЬКО через EN. Поле без
перевода не печатается — но и не исчезает молча: оно уходит в список пропусков
в конце прогона, а --strict превращает пропуск в ненулевой код возврата. Иначе
дописанное в карточку поле выпадет из документа, и никто этого не заметит.

Модельные поля (свет, камера, подпись, сам промпт) печатаются дословно и через
EN не проходят, поэтому готовый документ дополнительно просматривается на
кириллицу целиком: правило проверяется по результату, а не по маршруту.
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import setup_console, read_json, ROOT, project_name
from prompts import load_project, build_cell

CYRILLIC = re.compile(r"[А-Яа-яЁё]")

# Ключ — путь до поля в JSON проекта. Перевод не дословный: в JSON обоснования
# написаны для себя и держат историю правок, клиенту нужен режиссёрский смысл.
# Служебные обоснования (какое поле какой эвристикой заменили) сюда не попадают
# намеренно — они объясняют устройство кода, а не кадр.
EN = {
    "bridget.character._": (
        "The blocks below go into every prompt of the set verbatim. Identity "
        "holds by repetition, not by luck — rewriting a description by hand a "
        "sixth time produces a synonym, and a synonym produces a different "
        "woman. Once the batch is running the wording is frozen: changing it "
        "would move every frame that has already passed the gates."),
    "bridget.character._medium": (
        "The medium is the first block of every prompt. A model that is not "
        "told it is taking a photograph makes a portrait — and a portrait is "
        "exactly what an AI detector flags."),
    "bridget.character._identity_core": (
        "The asymmetry is not decoration, it is the anti-AI-look device. A "
        "generically symmetric face reads as generated to both a viewer and a "
        "detector; one specific irregularity turns a type into a person. The "
        "styling lives in the hair rules rather than here, because in the "
        "candid frame her hair is tied back and two contradictory "
        "instructions would fight inside one prompt."),
    "bridget.character._age_markers": (
        "This is the automatic failure of the whole task: base models pull any "
        "woman back toward twenty-seven. Age lives here, not in the words "
        "'51-year-old' — a model does not believe a number, it believes "
        "detail. The neck and the backs of the hands are mandatory: diffusion "
        "hides them, and they are precisely what proves maturity to a viewer."),
    "bridget.character._hair_rules": (
        "Length and grown-out roots are per-person markers, so they ride in "
        "every prompt rather than being left to whichever frame happens to get "
        "them right."),
    "bridget.character.tattoo._placement": (
        "The side changed with the second reference photograph, and this is a "
        "different place rather than a refinement. It used to read 'inner "
        "left wrist'. In the photograph all four fingernails face the camera, "
        "so the hand is seen from the BACK — and so is the wrist the lettering "
        "sits on. The hand is the left one: seen from the back with the "
        "fingers to the left, a left thumb points up, and it does. From this "
        "follows the whole rule the client set: composite the tattoo only "
        "where that surface is visible, and where it is not, do not composite "
        "it at all."),
    "bridget.character.tattoo._prompt_clause": (
        "The composite needs somewhere to land, and that somewhere has to be "
        "the right surface AND empty. The first half follows the placement. "
        "The second was added by measurement: in both delivered frames that "
        "show the back of the wrist, the model put the watch and bangle on "
        "the LEFT arm — against the wardrobe rule that separates metal from "
        "ink by arm. The rule was stated in the jewellery block and broken "
        "there; at cfg 1.0 an instruction acts where it stands, and it stood "
        "next to the word 'right'. So the ban is repeated here, in the clause "
        "that asks for the wrist, and phrased as a requirement rather than a "
        "prohibition. A gate backs it: metrics/wrist.py cancels the composite "
        "when an object covers more than 2% of the lettering's footprint, and "
        "on the delivery it cancelled both (9% and 11%)."),
    "bridget.character.tattoo._measured": (
        "Three numbers measured off the photograph rather than chosen. The "
        "lettering is 679 px long where the forearm is 551 and 576 px wide at "
        "two points along it — hence 1.20. From the wrist to the centre of the "
        "line is 0.88 forearm widths, and the line sits on the arm's midline "
        "to within 0.07 of its width. Everything is measured against WIDTH "
        "rather than the length of the arm: the elbow is rarely in frame, "
        "while the width of the wrist is always visible when the wrist "
        "itself is. size_mm is derived and informational: 1.20 x 63 mm. The "
        "first photograph gave 0.74 and 45 mm for the same measurements; the "
        "second reference shows a larger tattoo, and its number is now the "
        "working one."),
    "bridget.character.tattoo._visible_in": (
        "The list of cells where the wrist is ASKED for. It does not decide "
        "whether the tattoo appears: that is decided by measuring the frame "
        "(metrics/wrist.py). A request and a result are different things, and "
        "on the delivery they diverged on all five frames."),
    "bridget.character.tattoo._orientation": (
        "The direction of the line is not a choice, it follows from anatomy: "
        "the lettering is inked along the skin from wrist to elbow, so the "
        "rotation of the composite is fixed by that vector, and it never needs "
        "mirroring — the back of the wrist is one surface, and from whichever "
        "side you look at it the letters read the same way. While the "
        "composite went anywhere at all, both questions were open; the "
        "client's rule closed both."),
    "bridget.character.tattoo._": (
        "The model does not draw this, and neither do we. The tattoo exists on "
        "the character reference, and it is LETTERING rather than a graphic: "
        "the name either matches letter for letter or it is somebody else's "
        "tattoo — there is no drawing one in the spirit of the "
        "original — while diffusion turns fine script on a wrist into a "
        "different mush of letters in every frame. So the ink is lifted out of "
        "the reference photograph (scripts/tattoo_from_photo.py: separated "
        "from skin by darkness relative to the local background, straightened "
        "along its principal axis) and composited in — identical letter for "
        "letter in every frame. The ink colour is sampled from the photograph "
        "(RGB 75,60,65) rather than set to black: a fifteen-year-old tattoo "
        "has faded to a warm grey-brown, and substituting crisp black would "
        "lend the frame a freshness the character does not have."),
    "bridget.character.tattoo._reference": (
        "The asset has been replaced twice. First there was a drawn stiletto "
        "silhouette, assets/tattoo_stiletto.png — an invented tattoo, set "
        "down before any reference existed; the reference turned out to be "
        "lettering. Then the client sent a second photograph of the same "
        "lettering, larger and cleaner, and the asset was rebuilt from it: "
        "689x165 px instead of 484x91, ink RGB 75,60,65. The source crop is "
        "kept in the repository so that the asset can be rebuilt rather than "
        "held as a single surviving copy."),
    "bridget.character.wardrobe_bible._": (
        "Wardrobe is characterisation. The Manolo Blahnik tattoo dates her: "
        "she was around thirty in 2005, her taste was formed by the luxury of "
        "that decade and has grown up with her. Expensive cloth, never a loud "
        "logo."),
    "bridget.character.wardrobe_bible._jewelry": (
        "The same jewellery in every frame is the cheapest and most visible "
        "proof that this is one person in one period of her life, rather than "
        "ten separate generations."),
    "bridget.character.wardrobe_bible._laterality": (
        "Laterality is split once and hard: the tattoo is on the BACK of the "
        "LEFT wrist, the metal on the RIGHT. Otherwise the bangle and the "
        "watch sit on top of the landing area for the composite, and the "
        "paste-in either does not fit or lands on metal."),
    "bridget.character.wardrobe_bible._laterality_broken": (
        "And it was broken — not in the rule but in the frames. In both "
        "delivered frames that show the back of the wrist (the dog and the "
        "restaurant), the watch and bangle ended up on the LEFT arm, right on "
        "the landing area. The rule was stated in the jewellery block, which "
        "reads 'on her right wrist', and at cfg 1.0 that was not enough: the "
        "model repeated the object, not the side. So the requirement is "
        "restated in tattoo.prompt_clause, where the wrist itself is asked "
        "for, and backed by a measurement of the frame rather than by trust "
        "in the prompt."),
    "bridget.character.personality_in_frame._": (
        "The personality traits from the brief are translated into what is "
        "physically visible in a frame. Anything that stays an adjective never "
        "reaches the image at all."),
    "bridget.character.personality_in_frame._guarded": (
        "Each trait describes ONE frame. How many frames in the set look away "
        "is a decision for the shotlist, not for the character card — a "
        "note to the director written into a prompt only acts as noise."),
    "bridget.character._realism_clause": (
        "This tail is attached to every prompt, and it is phrased as a demand "
        "on purpose. Krea 2 Turbo runs at cfg = 1.0, where the negative "
        "conditioning has no effect on the result at all. 'No plastic skin' "
        "does nothing; 'visible skin pores' works."),
    "bridget.character.forbidden_as_positive._": (
        "The same rule applied to the prohibitions in the brief: each one is "
        "restated as a requirement, because at cfg = 1.0 there is nothing to "
        "prohibit with."),
    "bridget.character.forbidden_as_positive.__": (
        "These items deliberately do not overlap with the identity block or "
        "the realism tail, where asymmetry and untouched skin are already "
        "required. At cfg = 1.0 a repeated requirement is a doubled weight, "
        "and the frame drifts into exaggerated texture."),
    "bridget.character.anchor._": (
        "Filled in by the casting stage. The anchor image is the single "
        "chosen frame the whole project is measured against; the embedding is "
        "the ArcFace vector every later frame is compared to for drift."),

    "bridget.shotlist1._": (
        "Five frames, and the rule that matters is that they are five "
        "different FUNCTIONS rather than five poses. A real set of photographs "
        "of a person consists of frames taken on different occasions by "
        "different people — that is exactly what separates a set of "
        "photographs from an hour in a studio."),
    "bridget.shotlist1._seeds": (
        "Forty frames generated, five delivered. Generation is cheap; the "
        "craft is in the selection."),
    "bridget.shotlist1._trait": (
        "Each cell names which personality trait from the character card goes "
        "into its prompt. It is assigned here rather than inferred from the "
        "text of the frame, and \"none\" is a deliberate refusal — a second "
        "behavioural instruction would fight the one the frame already has. "
        "Across the set of five, each of the four traits from the brief is "
        "used at least once."),
    "bridget.shotlist1._body_in_frame": (
        "Whether the build block — posture, shoulders, legs — belongs in this "
        "prompt. In a chest-up portrait a description of legs is noise that "
        "takes weight away from the face."),
    "bridget.shotlist1._scene_class": (
        "The scene class (day / indoor / night / flash) selects the strength "
        "of the disposable-camera LoRA and the grain profile of the last-mile "
        "pass. Under daylight that LoRA casts the frame green, so it is only "
        "raised for night and flash."),

    "bridget.cells.P1.label": "Hero portrait",
    "bridget.cells.P1.function": (
        "This is her face — the frame she is recognised by in all the others."),
    "bridget.cells.P1.notes": (
        "Window light with no fill is mandatory: an even studio scheme erases "
        "age and texture together. The shadow across the right half of her "
        "face is what does the work of 'emotional depth' in the brief."),
    "bridget.cells.P2.label": "Full length",
    "bridget.cells.P2.function": (
        "Proves the build and the age at the same time — body, posture and "
        "hands all in frame."),
    "bridget.cells.P2.notes": (
        "The off-camera gaze already reads as guarded, so the trait assigned "
        "to this cell is independent: she occupies the centre of her own frame "
        "and is waiting for no one. 35mm from slightly below eye level gives "
        "height without the distortion a wider lens would add."),
    "bridget.cells.P3.label": "Candid, in motion",
    "bridget.cells.P3.function": (
        "Authenticity. The one frame in which she does not know she is being "
        "photographed."),
    "bridget.cells.P3.notes": (
        "This is where the tattoo composite goes: the left wrist is open and "
        "close to the lens. The motion blur in the racket hand is mandatory — "
        "a perfectly sharp frame in mid-movement reads as a render. The flat "
        "overcast light is deliberate: it shows the skin as it is."),
    "bridget.cells.P4.label": "With the dog",
    "bridget.cells.P4.function": (
        "Warmth and vulnerability — the beat the brief calls emotional "
        "complexity."),
    "bridget.cells.P4.notes": (
        "The only frame with a real smile rather than a half one. The creases "
        "at her eyes must be visible here; they prove age and aliveness in the "
        "same gesture. An old greyhound rather than a puppy: the dog's age "
        "supports hers."),
    "bridget.cells.P5.label": "Her world",
    "bridget.cells.P5.function": (
        "The context of a life. Shot by someone else across a table — the kind "
        "of frame that reads as a real life in a profile."),
    "bridget.cells.P5.notes": (
        "The raised glass is a natural reason to bring the left wrist close to "
        "the lens, and the second tattoo composite goes here. The slight shake "
        "and the near-miss focus are deliberate: a perfect frame by candlelight "
        "is physically impossible, and the eye knows it. Watch the colour gate "
        "on this one — a warm restaurant in the dark drifts toward "
        "near-monochrome and fails the brief's explicit requirement on colour."),

    "bridget.shotlist2._": (
        "Part 2 of the brief: a five-frame story Bridget sends to her man over "
        "the course of one evening. The 9:16 format is her phone, not a "
        "photographer's camera — a cinematic 16:9 'selfie' reads as fake "
        "instantly."),
    "bridget.shotlist2._tone": (
        "The brief says it literally: building up the tension but always "
        "staying tasteful and teasing. So the story is built on CLOSING rather "
        "than opening — steam, backlight, a reflection, the edge of the frame, "
        "her back. That is not a softened version of the assignment, it is the "
        "assignment taken at its word, and at the same time the only way to "
        "shoot a series like this so that it reads as real photographs of a "
        "grown woman rather than as a catalogue. Undressing is done with light "
        "and composition; in no frame is the camera anywhere her own phone "
        "could not have been."),
    "bridget.shotlist2._progression": (
        "Dressed and playing (S1) → the mirror and the phone in "
        "frame, the robe slipping (S2) → the bed, closer and warmer (S3) → the "
        "bathroom, steam, seen from behind (S4) → the shower, a silhouette "
        "behind glass (S5). Each frame takes away distance rather than "
        "clothing."),
    "bridget.shotlist2._captions": (
        "The caption is the line under the slide, in her own voice. The brief "
        "asks for them as a separate item: a brief text caption under each "
        "slide to hint at the narrative. `caption_ru` carries the same line "
        "for the Russian version of the deck."),
    "bridget.shotlist2._mandatory": (
        "S2 is the frame the brief requires outright: a mirror selfie with the "
        "phone physically visible. It is also the hardest frame in the task — "
        "hand, phone and reflection all at once — which is why it gets its own "
        "feasibility check and more seeds than the rest."),

    "bridget.cells.S1.label": "The robe",
    "bridget.cells.S1.function": (
        "The start of the evening. She is dressed, she is enjoying herself, "
        "and she started it."),
    "bridget.cells.S1.notes": (
        "The warm lamp against the cool window is not decoration, it is "
        "insurance against near-monochrome: a night scene in a single orange "
        "tone fails the brief's explicit requirement on colour. The tilt is "
        "mandatory — a perfectly level handheld selfie does not exist."),
    "bridget.cells.S2.label": "Mirror selfie — the required frame",
    "bridget.cells.S2.function": (
        "The brief's requirement, word for word: the phone has to be visible "
        "in the frame. It is also what makes the frame honest — this is a "
        "photograph she really did take herself."),
    "bridget.cells.S2.notes": (
        "The light of the phone screen on her face is the detail this frame "
        "lives or dies by: in a real mirror selfie it is always there. Her "
        "free hand at the waist opens the inner wrist — the tattoo composite "
        "goes here. More seeds than the other cells: hands holding a phone, "
        "plus a reflection, is where frames break most often."),
    "bridget.cells.S3.label": "The bed",
    "bridget.cells.S3.function": (
        "Closer and quieter. The game of S1 gives way to something real — this "
        "is where the vulnerability from the brief appears."),
    "bridget.cells.S3.notes": (
        "The only frame in the series without a smile. The brief says 'trust "
        "issues but open to love'; this is exactly that beat, and it belongs "
        "here, between the game and the shower. Cropped at the ribs rather "
        "than lower: a tease holds on what was not shown."),
    "bridget.cells.S4.label": "Bathroom, steam",
    "bridget.cells.S4.function": (
        "The transition. She leaves the frame for the shower — and photographs "
        "it from behind."),
    "bridget.cells.S4.notes": (
        "The nudity here is shoulders and a back in steam, which is precisely "
        "what the brief calls tasteful. The fogged mirror works twice: as a "
        "device, and as insurance — it takes her face out of the frame, so no "
        "face swap runs on this one and the likeness cannot drift. The steam "
        "has to stay warm and the doorway cold, or the frame collapses into a "
        "single tone."),
    "bridget.cells.S5.label": "Shower, silhouette",
    "bridget.cells.S5.function": (
        "The end. The camera goes no further — and that is the tease."),
    "bridget.cells.S5.notes": (
        "Focus on the droplets and on her hand rather than on her body is both "
        "a compositional choice and a technical one: a sharp hand in the "
        "foreground gives the frame an anchor of sharpness, which is what "
        "makes the soft silhouette read as optics rather than as mush. The "
        "palm flat on the glass is the one hard detail in the whole series, "
        "and its point."),
}

MISSING = []
LEAKED = []
VISITED = set()


PROJECT = None      # имя текущего проекта; ставится export() перед обходом


def en(path, value):
    """Английский текст поля или None, если печатать нечего.

    КЛЮЧ ТАБЛИЦЫ ПРОЕКТНЫЙ. Раньше он был глобальным («cells.S1.label»), и
    второй персонаж с той же нумерацией ячеек молча получал бы в сдаточный
    документ ЧУЖОЙ перевод — русская подпись Imani искалась бы как
    cells.S1.label и находила английский текст Бриджит. Поймано тестом
    test_cell_ids_are_unique_across_projects, который требовал разводить
    номера ячеек руками; требование к данным ради дефекта в коде — плохой
    договор, и третий персонаж всё равно однажды забыл бы.

    Непереведённое поле теперь честно копится в MISSING, а не подменяется
    соседским.

    Английское значение проходит насквозь: промпты, свет и камера в JSON и так
    написаны для модели по-английски, дублировать их в EN бессмысленно.
    Русское — только через EN; иначе пропуск копится в MISSING.
    """
    # ПОСЕЩЁННОЕ ХРАНИТСЯ БЕЗ ПРЕФИКСА, а префикс идёт только в поиск
    # перевода. audit_rationales сверяет со VISITED свои пути — они
    # непрефиксованные, — и от общего ключа он решил, что документ не
    # запрашивает НИ ОДНОГО поля: непереведённых стало 32 вместо 4.
    key = f"{PROJECT}.{path}" if PROJECT else path
    VISITED.add(path)
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if not CYRILLIC.search(text):
        return text
    if key in EN:
        return EN[key]
    MISSING.append(key)
    return None


def plain(d):
    """Пары ключ-значение без служебных: ключи на '_' — это обоснования."""
    return [(k, v) for k, v in (d or {}).items() if not k.startswith("_")]


def audit_rationales(prefix, obj):
    """Обоснования, которых документ вообще не спрашивал.

    Пропуск перевода видно сразу — поле спросили и не нашли в EN. А вот поле,
    дописанное в JSON под новым именем, не спрашивает никто: раздел раскадровки
    Part 2 (_tone, _progression, _captions, _mandatory) выпал из документа
    целиком и не попал даже в отчёт. Здесь обход идёт от данных, а не от
    списка полей в коде, — тогда «никто не заметил» невозможно.
    """
    if not isinstance(obj, dict):
        return
    for k, v in obj.items():
        if isinstance(v, dict):
            audit_rationales(f"{prefix}.{k}", v)
        elif k.startswith("_") and str(v or "").strip():
            path = f"{prefix}.{k}"
            if path not in VISITED:
                MISSING.append(f"{path} (документ этого поля не запрашивает)")


def table(header, rows):
    """Markdown-таблица; строки с пустым значением выбрасываются."""
    rows = [(k, v) for k, v in rows if v]
    if not rows:
        return []
    out = ["| %s | %s |" % header, "|---|---|"]
    # Вертикальная черта внутри значения рвёт таблицу — экранируем.
    out += ["| %s | %s |" % (k, str(v).replace("|", "\\|")) for k, v in rows]
    return out + [""]


def why(path, value, lead="**Why.**"):
    """Абзац обоснования. Ничего не печатает, если перевода нет."""
    text = en(path, value)
    return [" ".join(x for x in (lead, text) if x), ""] if text else []


def quote(value):
    """Блок промпта дословно — клиент должен видеть тот же текст, что модель."""
    return [f"> {value}", ""] if value else []


def character_bible(char):
    name = char.get("display_name") or char.get("id", "character")
    L = [f"# {name} — character bible", "",
         f"**{name}, age {char.get('age', '?')}.** A fictional person. Every "
         f"image in this project is generated; no real individual is depicted.",
         "",
         "*Generated from `character.json` by `scripts/export_docs.py` — edit "
         "the JSON, not this file.*", "",
         "---", ""]

    L += ["## How this card is used", ""]
    L += why("character._", char.get("_"), lead="")

    L += ["## What the model is told it is making", ""]
    L += quote(char.get("medium"))
    L += why("character._medium", char.get("_medium"))

    L += ["## The face", ""]
    L += quote(char.get("identity_core"))
    L += why("character._identity_core", char.get("_identity_core"))

    L += ["## Age, in detail", ""]
    L += quote(char.get("age_markers"))
    L += why("character._age_markers", char.get("_age_markers"))

    L += ["## Build", ""]
    L += quote(char.get("build"))

    L += ["## Hair", ""]
    L += quote(char.get("hair_rules"))
    L += why("character._hair_rules", char.get("_hair_rules"))

    wb = char.get("wardrobe_bible", {})
    if wb:
        L += ["## Wardrobe", ""]
        L += table(("element", "rule"),
                   [(k.replace("_", " "), v) for k, v in plain(wb)])
        L += why("character.wardrobe_bible._", wb.get("_"))
        L += why("character.wardrobe_bible._jewelry", wb.get("_jewelry"),
                 lead="**Why the same jewellery every time.**")
        L += why("character.wardrobe_bible._laterality_broken",
                 wb.get("_laterality_broken"),
                 lead="**And how the frames broke it.**")
        L += why("character.wardrobe_bible._laterality", wb.get("_laterality"),
                 lead="**Left and right.**")

    tat = char.get("tattoo", {})
    if tat:
        L += ["## The tattoo", ""]
        L += quote(tat.get("description"))
        L += table(("field", "value"), [
            ("placement", tat.get("placement")),
            ("size", f"{tat['size_mm']} mm" if tat.get("size_mm") else None),
            ("length / forearm width", tat.get("length_over_forearm_width")),
            ("from wrist, in forearm widths", tat.get("along_forearm_widths")),
            ("graphic asset", f"`{tat['asset']}`" if tat.get("asset") else None),
            ("source photograph",
             f"`{tat['source_photo']}`" if tat.get("source_photo") else None),
            ("asked for in", ", ".join(tat.get("visible_in", [])) or None),
        ])
        L += why("character.tattoo._", tat.get("_"),
                 lead="**Why it is composited, not generated.**")
        L += why("character.tattoo._visible_in", tat.get("_visible_in"),
                 lead="**Asked for is not the same as delivered.**")
        L += why("character.tattoo._placement", tat.get("_placement"),
                 lead="**Which side of the wrist, and how we know.**")
        L += why("character.tattoo._measured", tat.get("_measured"),
                 lead="**Where the three numbers come from.**")
        L += why("character.tattoo._orientation", tat.get("_orientation"),
                 lead="**Which way the line runs.**")
        L += why("character.tattoo._reference", tat.get("_reference"),
                 lead="**What changed when the reference arrived.**")
        L += why("character.tattoo._prompt_clause", tat.get("_prompt_clause"),
                 lead="**The clause in the prompt.**")
        if tat.get("prompt_clause"):
            L += quote(tat["prompt_clause"])

    pers = char.get("personality_in_frame", {})
    if pers:
        L += ["## Personality, as something visible", ""]
        L += table(("trait", "what it looks like in the frame"), plain(pers))
        L += why("character.personality_in_frame._", pers.get("_"))
        L += why("character.personality_in_frame._guarded", pers.get("_guarded"),
                 lead="**One frame at a time.**")

    L += ["## Camera and realism", ""]
    L += quote(char.get("camera_default"))
    L += quote(char.get("realism_clause"))
    L += why("character._realism_clause", char.get("_realism_clause"))

    fb = char.get("forbidden_as_positive", {})
    if fb:
        L += ["## Prohibitions rewritten as requirements", ""]
        L += table(("prohibition", "how it is asked for instead"),
                   [(k.replace("_", " "), v) for k, v in plain(fb)])
        L += why("character.forbidden_as_positive._", fb.get("_"))
        L += why("character.forbidden_as_positive.__", fb.get("__"),
                 lead="**No overlap.**")

    anc = char.get("anchor", {})
    if anc:
        img = anc.get("image")
        L += ["## Identity anchor", ""]
        L += table(("field", "value"), [
            ("anchor image", f"`{img}`" if img else "not chosen yet"),
            ("face model", anc.get("face_model")),
            ("ArcFace embedding",
             "recorded" if anc.get("embedding") else "not recorded yet"),
        ])
        L += why("character.anchor._", anc.get("_"))

    return "\n".join(L).rstrip() + "\n"


CELL_FIELDS = [
    ("framing", "framing"),
    ("gaze", "gaze"),
    ("wardrobe", "wardrobe"),
    ("jewelry_override", "jewellery (overrides the bible)"),
    ("trait", "personality trait in this prompt"),
    ("scene_class", "scene class"),
    ("nudity_level", "nudity level"),
]

# Булево поле нельзя гнать через CELL_FIELDS: False печатается как "False" и,
# что хуже, отсутствие поля становится неотличимо от осознанного «нет».
YES_NO = {True: "yes", False: "no"}


def cell_section(char, cell):
    cid = cell.get("id", "?")
    label = en(f"cells.{cid}.label", cell.get("label"))
    L = [f"## {cid} · {label}" if label else f"## {cid}", ""]

    func = en(f"cells.{cid}.function", cell.get("function"))
    if func:
        L += [f"**Function.** {func}", ""]

    rows = [(title, cell.get(key)) for key, title in CELL_FIELDS]
    rows += [("body in frame", YES_NO.get(cell.get("body_in_frame"))),
             ("tattoo visible", YES_NO.get(cell.get("tattoo_visible"))),
             ("mirror selfie", YES_NO.get(cell.get("mirror_selfie"))),
             # Телефон в кадре — не деталь реквизита, а дословный пункт ТЗ по
             # Part 2, и проверять его будут по документу.
             ("phone visible in frame", YES_NO.get(cell.get("phone_visible")))]
    L += table(("field", "value"), rows)

    if cell.get("light"):
        L += [f"**Light.** {cell['light']}", ""]
    if cell.get("camera"):
        L += [f"**Camera.** {cell['camera']}", ""]

    cap = cell.get("caption")
    if cap:
        # Подпись — часть кадра Part 2, а не комментарий к нему: её читает
        # зритель ленты, поэтому она стоит рядом с кадром, а не в примечаниях.
        L += [f"**Caption.** “{cap}”", ""]

    note = en(f"cells.{cid}.notes", cell.get("notes"))
    if note:
        L += [f"**Director's note.** {note}", ""]

    # Промпт собирается тем же кодом, что и кадр. Ячейка с испорченными
    # данными не роняет весь документ, но и не притворяется целой: блок
    # промпта просто не печатается, а путь уходит в список пропусков.
    try:
        prompt = build_cell(char, cell)
    except KeyError as e:
        MISSING.append(f"cells.{cid}.prompt ({e.args[0]})")
        prompt = None
    if prompt:
        L += ["**Prompt**", "", "```text", prompt, "```", ""]
    return L


# Подзаголовок абзаца обоснования. Неизвестный ключ получает заголовок из
# своего имени — так новое поле выглядит в документе неказисто, но видно, а не
# пропадает.
LEADS = {
    "_": "",
    "_seeds": "**Selection, not generation.**",
    "_trait": "**The trait field.**",
    "_body_in_frame": "**The body-in-frame field.**",
    "_scene_class": "**The scene-class field.**",
    "_tone": "**Tone.**",
    "_progression": "**The arc of the evening.**",
    "_captions": "**Captions.**",
    "_mandatory": "**The required frame.**",
}


def shotlist_doc(char, shots, part_no):
    name = char.get("display_name") or char.get("id", "character")
    title = shots.get("part") or f"Part {part_no}"
    # Заголовок части в JSON помечен буквой набора ("P — profile set");
    # клиенту нужен номер части, поэтому буква идёт подзаголовком.
    L = [f"# {name} — Part {part_no} shotlist", "", f"*{title}*", ""]

    size = shots.get("size")
    n = len(shots.get("cells", []))
    facts = [f"{n} cell" + ("s" if n != 1 else "")]
    if size:
        facts.append(f"{size[0]} × {size[1]} px")
    if shots.get("seeds_per_cell"):
        facts.append(f"{shots['seeds_per_cell']} seeds per cell")
    L += [" · ".join(facts), "",
          "*Generated from the project JSON by `scripts/export_docs.py`. The "
          "prompt under each cell is the exact string sent to the model.*", "",
          "---", ""]

    # Ключ перевода помечен номером части, а не просто «shotlist»: у обеих
    # раскадровок поля называются одинаково, и на общем ключе Part 2 молча
    # печаталась бы объяснялка от Part 1 — ровно та ошибка, ради которой здесь
    # вообще заведена таблица переводов.
    key = f"shotlist{part_no}"
    # Обход по ключам JSON, а не по списку в коде: список был написан под поля
    # Part 1, и обоснования Part 2 (_tone, _progression, _captions, _mandatory)
    # в документ не попадали вовсе. Порядок — как в файле: он сюжетный.
    intro = []
    for k, v in shots.items():
        if not k.startswith("_"):
            continue
        intro += why(f"{key}.{k}", v, lead=LEADS.get(
            k, "**%s.**" % k.strip("_").replace("_", " ").capitalize()))
    # Пустой заголовок хуже отсутствующего: клиент читает его как «раздел есть,
    # писать было нечего», хотя на деле блок просто не переведён.
    if intro:
        L += ["## How the set is built", ""] + intro + ["---", ""]

    for cell in shots.get("cells", []):
        L += cell_section(char, cell)
    return "\n".join(L).rstrip() + "\n"


def write_text(path, text):
    # Через en() проходят только человеческие поля (label, function, notes,
    # обоснования). Модельные — свет, камера, подпись, сам промпт — печатаются
    # дословно, и там правило «кириллица только через EN» ничем не держалось:
    # русская подпись в ячейке Part 2 уехала бы клиенту молча. Проверяем
    # готовый документ целиком. Текст при этом НЕ режем: если по-русски написан
    # промпт, документ обязан показать ровно то, что уйдёт в модель, — это
    # ошибка данных, а не документа, и чинить её надо в JSON.
    for i, line in enumerate(text.split("\n"), 1):
        if CYRILLIC.search(line):
            LEAKED.append(f"{os.path.basename(path)}:{i}")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    # newline="\n": документ уезжает клиенту и в git, CRLF от Windows там лишний.
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def _reset_reports():
    """Сбросить накопители отчёта. Они модульные, и во втором проекте одного
    процесса отчёт первого не исчезал: MISSING указывал на чужие поля, LEAKED —
    на строку файла с тем же именем, а VISITED глушил проверку второго."""
    MISSING.clear(); LEAKED.clear(); VISITED.clear()


def default_out(project):
    """Куда пишется комплект документов, если путь не задан.

    Отдельной функцией потому, что это ОБЕЩАНИЕ («второй персонаж не
    затирает первого»), и проверять его надо у того, кто его даёт. Тест,
    который собирал этот путь у себя, оставался зелёным, когда имя
    проекта из пути убирали: он сверял свою формулу со своей же.
    """
    return os.path.join(ROOT, "docs", project)

def export(project_dir, out_dir):
    _reset_reports()
    char, shots = load_project(project_dir)
    # ИМЯ ПРОЕКТА СТАВИТСЯ ДО ПЕРВОГО ОБРАЩЕНИЯ К ТАБЛИЦЕ. Ключи переводов
    # проектные, и обход, начавшийся с пустым PROJECT, искал бы их без
    # префикса — то есть не находил бы ни одного и вывалил бы весь документ
    # в MISSING. Ставится глобально, а не тащится аргументом: en() зовётся из
    # десятка мест, и протаскивать одно слово через все — переписать половину
    # файла ради него.
    global PROJECT
    PROJECT = project_name(project_dir, shots, char)
    made = [write_text(os.path.join(out_dir, "character_bible.md"),
                       character_bible(char)),
            write_text(os.path.join(out_dir, "shotlist_part1.md"),
                       shotlist_doc(char, shots, 1))]
    audit_rationales("character", char)
    audit_rationales("shotlist1", shots)

    story_path = os.path.join(project_dir, "shotlist_story.json")
    if os.path.exists(story_path):
        story = read_json(story_path)
        made.append(write_text(os.path.join(out_dir, "shotlist_part2.md"),
                               shotlist_doc(char, story, 2)))
        audit_rationales("shotlist2", story)
    else:
        # Пустышку не пишем: документ с разделом «Part 2» и без кадров клиент
        # читает как сданную часть работы. Молчать тоже нельзя — Part 2 в ТЗ
        # есть, и её отсутствие должно быть видно тому, кто запустил экспорт.
        print(f"Part 2 пропущена: нет {story_path} — shotlist_part2.md не "
              f"создан", file=sys.stderr)
        stale = os.path.join(out_dir, "shotlist_part2.md")
        if os.path.exists(stale):
            print(f"ВНИМАНИЕ: {stale} остался от прошлого прогона и сейчас "
                  f"ничем не подтверждён", file=sys.stderr)
    return made


def main():
    setup_console()
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        print(__doc__); raise SystemExit(1)

    project_dir = args[0]
    if not os.path.isdir(project_dir):
        raise SystemExit(f"нет такой папки проекта: {project_dir}")

    # Имя проекта в пути: без него второй персонаж затирал документы первого.
    # Карточка читается ради него же — правило разрешения имени одно на весь
    # конвейер и живёт в _util.project_name.
    _char = read_json(os.path.join(project_dir, "character.json"))
    out_dir = default_out(project_name(project_dir, None, _char))
    if "--out" in args:
        # Значение --out бралось без проверки: «--out --strict» заводило каталог
        # с именем «--strict» и заодно молча выключало сам --strict, а «--out»
        # последним аргументом падал трассировкой из недр разбора.
        i = args.index("--out") + 1
        if i >= len(args) or args[i].startswith("-"):
            raise SystemExit("--out требует путь к каталогу")
        out_dir = args[i]

    for path in export(project_dir, out_dir):
        print(path)

    if MISSING:
        print(f"\nбез перевода и потому НЕ напечатано ({len(MISSING)}):",
              file=sys.stderr)
        for path in MISSING:
            print(f"  {path}", file=sys.stderr)
        print("дописать перевод в таблицу EN в scripts/export_docs.py; "
              "«не запрашивает» — значит, поле ещё негде показать",
              file=sys.stderr)
    if LEAKED:
        print(f"\nкириллица в готовом документе ({len(LEAKED)} строк):",
              file=sys.stderr)
        for place in LEAKED:
            print(f"  {place}", file=sys.stderr)
        print("чинить в JSON проекта — эти поля идут в документ дословно",
              file=sys.stderr)
    if (MISSING or LEAKED) and "--strict" in args:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
