#!/usr/bin/env python3
"""Собрать презентацию сдачи: один самодостаточный HTML со встроенными кадрами.

  py -3 build_deck.py <project_dir> [--out deliverables/presentation/index.html]
                      [--max-width 1400] [--quality 82]

ПОЧЕМУ HTML, А НЕ .PPTX. ТЗ просит Google Slides. Колода собирается отсюда
одним файлом, который открывается по ссылке, печатается в PDF (Ctrl+P → Save as
PDF) и импортируется в Slides как есть. Сами фотографии при этом лежат в
deliverables/ отдельными файлами — второе требование ТЗ («All photos attached
separately as files»), и колода на них не влияет.

ВСЁ ВНУТРИ ОДНОГО ФАЙЛА. Картинки встроены как data: URI. Колода, которая тянет
файлы из соседней папки, при пересылке ломается — а её будут пересылать.

ЧТО В КОЛОДЕ КРОМЕ КАРТИНОК. Слайд соответствия критериям оценки: ревьюеру не
нужно догадываться, чем закрыт каждый пункт его же таблицы. И метод — коротко,
потому что решения здесь неочевидные и это половина ценности работы.
"""
import os, sys, base64, io, html, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import setup_console, read_json, ROOT, project_name, cli_opt

PARTS = [
    ("part1_profile", "Part One — the profile set",
     "Five photographs that would plausibly sit on one woman's phone. Not five "
     "poses: five different occasions, shot by five different people, one of "
     "whom did not know she was being photographed."),
    ("part2_story", "Part Two — one evening, in her own voice",
     "Sent over the course of a night. The tease is built out of what each "
     "frame withholds, not what it shows — steam, a reflection, the edge of "
     "the crop. The captions are hers."),
]

CRITERIA = [
    ("Consistency of character identity",
     "Every frame is generated, never retouched into place. Eight frames per "
     "scene, then the set whose worst pair of faces is the closest — searched "
     "over embeddings, confirmed by eye on the contact sheet. The four "
     "face-transfer methods that were tried instead, and what each cost the "
     "picture, are in docs/bridget/qa_report.md."),
    ("Creativity and emotional storytelling",
     "Part 1 is built as five functions, not five poses. Part 2 is a single "
     "arc across one evening, where each frame removes distance rather than "
     "clothing."),
    ("Image realism and quality",
     "Krea 2 Turbo with a stacked realism/optics LoRA rig, no face "
     "restoration (it smooths pores into wax), and a last-mile pass adding "
     "chromatic aberration, vignette, scene-appropriate grain and one JPEG "
     "encode."),
    ("Attention to detail (tattoo, styling, mood)",
     "The Manolo tattoo is lifted from the reference photograph and composited by hand, so it is "
     "identical in every frame it appears in; the same bangle, watch and "
     "hoops are specified in every prompt; laterality is fixed once — ink "
     "left wrist, metal right."),
    ("Presentation formatting and clarity",
     "This deck, the photographs as separate files, a character bible and "
     "both shotlists in docs/, and a QA report with the gate numbers."),
]


def _img(path, max_width, quality):
    from PIL import Image
    with Image.open(path) as im:
        ex = im.getexif()
        im = im.convert("RGB")
        if im.width > max_width:
            im = im.resize((max_width, round(im.height * max_width / im.width)),
                           Image.LANCZOS)
        buf = io.BytesIO()
        # EXIF переносится во встроенную копию: правило проекта — не снимать
        # пометку о происхождении, а презентация и есть то, что уходит наружу.
        im.save(buf, "JPEG", quality=quality, subsampling=0,
                exif=ex.tobytes() if ex else b"")
    return ("data:image/jpeg;base64,"
            + base64.b64encode(buf.getvalue()).decode()), im.width, im.height


def default_out(project):
    """Куда пишется колода, если путь не задан.

    Отдельной функцией потому, что это ОБЕЩАНИЕ («второй персонаж не
    затирает первого»), и проверять его надо у того, кто его даёт. Тест,
    который собирал этот путь у себя, оставался зелёным, когда имя
    проекта из пути убирали: он сверял свою формулу со своей же.
    """
    return os.path.join(ROOT, "deliverables", project, "presentation",
                        "index.html")

def build(project_dir, out=None, max_width=1400, quality=82):
    char = read_json(os.path.join(project_dir, "character.json"))
    # Титул и лид берутся из карточки, а не из констант. Раньше карточка
    # читалась и выбрасывалась (ruff F841), а в колоде второго персонажа
    # стояло имя и биография Бриджит.
    who = char.get("display_name") or char.get("id", "").title()
    age = char.get("age")
    project = project_name(project_dir, None, char)
    # Путь по умолчанию — с именем проекта. Раньше он был глобальным, и колода
    # второго персонажа затирала колоду первого.
    out = out or default_out(project)
    slides, counts, forced = [], {}, []

    for folder, title, blurb in PARTS:
        sel_path = os.path.join(ROOT, "deliverables", project, folder,
                                "selection.json")
        if not os.path.exists(sel_path):
            print(f"! {folder}: selection.json нет — часть пропущена",
                  file=sys.stderr)
            continue
        sel = read_json(sel_path)
        # deliver.py пишет объект с ключом frames; старый формат был списком.
        picks = sel.get("frames", sel) if isinstance(sel, dict) else sel

        # АНГЛИЙСКИЕ ПОЛЯ ДОБИРАЮТСЯ ИЗ РАСКАДРОВКИ, ЕСЛИ ИХ НЕТ В ЗАПИСИ.
        # selection.json части 1 снят в августе, когда function_en и alt ещё не
        # существовали, а пересдать её нечем: исходные PNG с диска исчезли, и
        # deliver.py честно отказывается сдавать кадр, которого нет в реестре.
        # Ждать перегенерации значит держать в отгружаемой деке русские подписи
        # ради чистоты механизма; читать недостающее из раскадровки по id
        # ячейки — дёшево и не выдумывает ничего, чего нет в проекте.
        shot_name = {"part1_profile": "shotlist.json",
                     "part2_story": "shotlist_story.json"}[folder]
        shot_path = os.path.join(project_dir, shot_name)
        by_cell = {}
        if os.path.exists(shot_path):
            by_cell = {c["id"]: c for c in read_json(shot_path).get("cells", [])}
        for p in picks:
            cell = by_cell.get(p.get("cell")) or {}
            for key in ("function_en", "alt"):
                if not p.get(key) and cell.get(key):
                    p[key] = cell[key]
        # Кадры, сданные вопреки воротам, в презентацию не попадают молча.
        if isinstance(sel, dict) and sel.get("blocked_by_gates"):
            forced += [f"{folder}: {c} ({v})"
                       for c, _f, v, _b in sel["blocked_by_gates"]]
        counts[folder] = len(picks)
        slides.append(("section", title, blurb, None))
        for i, p in enumerate(picks, 1):
            img = os.path.join(ROOT, p["delivered_as"])
            if not os.path.exists(img):
                print(f"! нет файла {img}", file=sys.stderr); continue
            uri, w, h = _img(img, max_width, quality)
            slides.append(("photo", f"{i:02d} · {p['label']}", p, (uri, w, h)))

    # Оформление: фотокнига, а не слайды. Бумажный фон, книжная антиква для
    # текста и моноширинный для замеров — потому что половина этой работы и
    # есть замеры. Акцент взят из кадра: винный шёлк платья в P5.
    css = """
:root{
  --paper:#efece6; --plate:#e6e2da; --ink:#191713; --muted:#6d685e;
  --rule:#d3cec3; --accent:#7a2233; --accent-ink:#7a2233;
  --measure:66ch;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",
    Georgia,"Times New Roman",serif;
  --mono:"SF Mono","Cascadia Mono","Roboto Mono",Menlo,Consolas,
    "Liberation Mono",monospace;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --paper:#15130f; --plate:#1e1b16; --ink:#eae5db; --muted:#948d80;
    --rule:#302b23; --accent:#c0475c; --accent-ink:#c0475c;
  }
}
:root[data-theme="dark"]{
  --paper:#15130f; --plate:#1e1b16; --ink:#eae5db; --muted:#948d80;
  --rule:#302b23; --accent:#c0475c; --accent-ink:#c0475c;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);
  font:400 17px/1.62 var(--serif);-webkit-font-smoothing:antialiased}
.sheet{max-width:1080px;margin:0 auto;padding:0 28px}
section{padding:96px 0;border-bottom:1px solid var(--rule)}
section:last-child{border-bottom:0}
h1{font:400 clamp(40px,7.5vw,76px)/1.02 var(--serif);margin:0 0 24px;
  letter-spacing:-.015em;text-wrap:balance}
h2{font:400 clamp(26px,4.4vw,42px)/1.12 var(--serif);margin:0 0 16px;
  letter-spacing:-.01em;text-wrap:balance}
p{margin:0 0 16px;max-width:var(--measure)}
.lede{font-size:clamp(19px,2.2vw,23px);line-height:1.5;color:var(--muted);
  max-width:54ch;font-style:italic}
.label{font:500 11px/1 var(--mono);letter-spacing:.16em;text-transform:uppercase;
  color:var(--accent-ink);margin:0 0 20px}
.muted{color:var(--muted)}

/* Плита: кадр во всю ширину, подпись под ним, номер на полях — логика
   контакт-листа, где у каждого кадра есть свой номер в серии. */
.plate{display:grid;grid-template-columns:4.5rem 1fr;gap:0 24px;align-items:start}
.plate .no{font:500 12px/1 var(--mono);color:var(--muted);letter-spacing:.1em;
  padding-top:6px;font-variant-numeric:tabular-nums}
.plate figure{margin:0;min-width:0}
.plate img{width:100%;height:auto;display:block;background:var(--plate)}
.plate figcaption{margin-top:20px;max-width:var(--measure)}
.say{font-size:clamp(20px,2.4vw,26px);line-height:1.42;margin:0}
.fn{margin:12px 0 0;color:var(--muted);font-size:16px;font-style:italic}
.meta{margin:14px 0 0;font:400 12px/1.7 var(--mono);color:var(--muted);
  letter-spacing:.04em}
.meta b{color:var(--accent-ink);font-weight:500}
@media (max-width:720px){.plate{grid-template-columns:1fr;gap:10px}
  .plate .no{padding-top:0}}

.notes{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
  gap:34px 40px;margin-top:38px}
.notes h3{font:500 12px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;
  color:var(--accent-ink);margin:0 0 10px;padding-top:14px;
  border-top:2px solid var(--accent)}
.notes p{font-size:15.5px;color:var(--muted);margin:0;max-width:42ch}

.tablewrap{overflow-x:auto;margin-top:28px}
table{width:100%;border-collapse:collapse;font-size:15.5px;min-width:520px}
th,td{text-align:left;padding:16px 14px 16px 0;border-bottom:1px solid var(--rule);
  vertical-align:top}
th{font:500 11px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;
  color:var(--accent-ink);padding-bottom:10px}
td:first-child{width:32%;padding-right:28px}
td:last-child{color:var(--muted)}

@media (prefers-reduced-motion:no-preference){
  .plate img{opacity:0;animation:fade .7s ease forwards}
  @keyframes fade{to{opacity:1}}
}
@page{size:A4;margin:12mm}
@media print{
  section{page-break-after:always;border:0;padding:26px 0}
  /* РИСУНОК НЕ РЕЖЕТСЯ ПОПОЛАМ. README сам советует «print to PDF and import
     into Google Slides», и на этом пути три фотографии из восьми уезжали на
     две страницы каждая: 20 страниц на 12 секций, причём страницы 10, 13 и 16
     несли только номер плашки. Причина — page-break-after на секции при
     height:auto у картинки без потолка. */
  .plate,.plate figure{break-inside:avoid;page-break-inside:avoid}
  .plate img{opacity:1;animation:none;max-height:76vh;object-fit:contain}
}
"""

    def esc(s):
        return html.escape(str(s or ""))

    shot = sum(counts.values())
    body = [f"""<section><div class="sheet">
<p class="label">Generative Designer — test task</p>
<h1>{esc(who)}</h1>
<p class="lede">A woman who does not exist, photographed on {shot} separate
occasions by people who do not exist either.</p>
<p>She is {esc(age)}. The brief asked for a set of profile pictures and a story
told at night — the work was to make them look like one person's actual
photographs rather than one afternoon in a studio.</p>
</div></section>"""]

    n = 0
    for kind, title, data, img in slides:
        if kind == "section":
            body.append(f'<section><div class="sheet"><h2>{esc(title)}</h2>'
                        f'<p class="lede">{esc(data)}</p></div></section>')
            continue
        n += 1
        p, (uri, w, h) = data, img
        marks = []
        if p.get("mirror_selfie"):
            marks.append("mirror selfie · <b>phone in frame</b>")
        # БЕЙДЖ ТАТУ СЛЕДУЕТ ЗАМЕРУ, А НЕ ЗАПРОСУ РАСКАДРОВКИ, И ЭТО БЫЛА
        # САМАЯ ДОРОГАЯ НЕПРАВДА ВО ВСЁМ ПАКЕТЕ. `tattoo_visible` — поле
        # ЯЧЕЙКИ, то есть «мы хотим здесь тату»; deliver.py копировал его в
        # selection.json как есть, и дека три раза подписывала «Manolo tattoo,
        # left wrist» на кадрах, где чернила нет ни одного пикселя. Четвёртый
        # критерий брифа называется «Attention to detail (tattoo, styling,
        # mood)» — то есть утверждение делалось ровно по тому пункту, на
        # который отвечает, и проверялось увеличением за десять секунд.
        # Настоящий ответ даёт metrics/wrist.py: на этой сдаче он отменил
        # вклейку на всех кадрах (ладонь, часы, перекрытие 9% и 11%).
        if p.get("tattoo_applied"):
            marks.append("Manolo tattoo, left wrist")
        marks.append(f"seed <b>{esc(p.get('seed'))}</b>")
        # ПОДПИСЬ БЕРЁТСЯ ПО-АНГЛИЙСКИ, И ЭТО НЕ ВКУС. Документ объявлен
        # <html lang="en">, заголовки и таблица критериев английские — а сюда
        # приезжала кириллица: при пустом caption код падал на `function`,
        # русское поле режиссёрской заметки, и у пяти профильных ячеек caption
        # пуст. То есть пять подписей из восьми ревьюер с английским брифом
        # прочитать не мог. Порядок: caption (реплика героини) → function_en →
        # и только потом русский function, чтобы отсутствие перевода было
        # видно, а не подменялось молчанием.
        cap = p.get("caption")
        fn = p.get("function_en") or p.get("function")
        said = (f'<p class="say">&ldquo;{esc(cap)}&rdquo;</p>'
                f'<p class="fn">{esc(fn)}</p>') if cap else \
               f'<p class="say">{esc(fn)}</p>'
        body.append(f"""<section><div class="sheet"><div class="plate">
<div class="no">{n:02d}</div>
<figure><img src="{uri}" width="{w}" height="{h}"
  alt="{esc(p.get('alt') or p.get('label'))}" loading="lazy">
<figcaption>{said}<p class="meta">{" &nbsp;·&nbsp; ".join(marks)}</p>
</figcaption></figure></div></div></section>""")

    rows = "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>"
                   for k, v in CRITERIA)
    body.append(f"""<section><div class="sheet">
<h2>Against the brief</h2>
<div class="tablewrap"><table>
<thead><tr><th>Criterion</th><th>How it is covered</th></tr></thead>
<tbody>{rows}</tbody></table></div></div></section>""")

    body.append("""<section><div class="sheet">
<h2>Four things worth knowing</h2>
<div class="notes">
<div><h3>Nothing is forbidden</h3><p>The base model runs at cfg 1.0, where the
negative prompt has no effect whatsoever. Every unwanted thing had to be
rewritten as a demand: not "no plastic skin" but "visible skin pores".</p></div>
<div><h3>Identity is won by choosing</h3><p>Four ways of forcing one face were
built and measured. The only one that worked destroyed the skin. So the face is
found instead: eight frames per scene, and the set whose worst pair is best.</p>
</div>
<div><h3>Age lives in the neck</h3><p>Models pull a woman toward twenty-seven
and they do not believe the words "51-year-old". They do believe thinner skin
over the tendons of the hand, and a throat that has been in the sun.</p></div>
<div><h3>The tattoo is lifted, not prompted</h3><p>Fine script on a wrist comes
out as a different mush of letters in every generation, and a name is either
right letter for letter or it belongs to somebody else. So the ink is separated
out of a reference photograph and composited — blurred to the focus of the arm
it sits on, grained to match. <b>It is on none of these frames.</b> The wrist
metric refused every one of them: two show the palm, one has no arm in shot,
and on the rest the model put a bracelet on the wrist the character card
reserves. That is the tool answering, not failing.</p></div></div>
<p class="meta" style="margin-top:44px">Photographs are delivered separately
under <b>deliverables/</b>. Character bible, both shotlists and the measured
numbers under <b>docs/</b>.</p>
</div></section>""")

    # КОММЕНТАРИИ CSS ВЫРЕЗАЮТСЯ ПРИ СБОРКЕ. Они написаны по-русски и для
    # автора: почему плита устроена так, почему картинка не режется на печати.
    # В отгружаемом файле, который открывает англоязычный ревьюер, это чужая
    # внутренняя речь в исходнике страницы — ровно та же болезнь, что и русские
    # подписи, только менее заметная. Вырезание здесь, а не отказ от
    # комментариев: объяснение нужно тому, кто правит генератор.
    clean_css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<title>{esc(who)} — Generative Designer test task</title>'
           f'<style>{clean_css}</style></head><body>{"".join(body)}</body></html>')

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"колода: {out}  ({len(doc)/1024/1024:.1f} МБ, "
          f"кадров {sum(counts.values())})")
    if forced:
        # Молчать об этом нельзя: презентация — то, что уходит наружу.
        print("ВНИМАНИЕ: в колоде есть кадры, сданные вопреки воротам:\n  "
              + "\n  ".join(forced), file=sys.stderr)
    return out


def main():
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__); raise SystemExit(1)

    def opt(k, d=None):
        return cli_opt(args, k, d)

    build(args[0], opt("--out"),
          int(opt("--max-width", 1400)), int(opt("--quality", 82)))


if __name__ == "__main__":
    main()
