# Character brief — Imani

Написан в **той же форме, в какой бриф приходит от заказчика** — по образцу
Character Bio из тестового задания (Name / Age / Occupation / Background /
Appearance / Personality / Goal). Это не стилизация ради стилизации: смысл
второго персонажа в том, что конвейер съедает бриф ТОГО ЖЕ ВИДА, какой
присылает клиент, и превращает его в набор кадров без правки кода.

---

## Character Bio

**Name:** Imani
**Age:** 34
**Occupation:** Tattoo artist; owns a two-chair studio she took over from her
former master

**Background:** Daughter of a seamstress, apprenticed at nineteen instead of
finishing college. Bought out the studio at thirty and has run it alone since.
Precise to the point of stubbornness about her own work, generous with everyone
else's. Financially steady and permanently tired. Not looking for rescue.

**Appearance:**
- Deep brown skin, warm undertones
- Natural coils, cropped close at the sides, fuller on top — never straightened
- A small raised scar through the outer end of her right eyebrow
- A narrow gold nose hoop, left nostril, in every frame
- Built by work: broad shoulders, forearms and grip, no gym sculpting
- Fine-line needle-and-feather tattoo on the inner right forearm, faded

**Personality:**
- Exacting at the bench, warm with people, guarded with cameras
- Says little, notices everything
- Carries the tiredness of someone who is the only one who can do her job

**Goal:** The pictures should read as a working life, not a styled one: hands
that do something, light that comes from real fixtures, and the same woman
under a tungsten lamp, a fluorescent tube and a street at dusk.

---

## Чем этот бриф отличается от первого, и зачем

Второй персонаж существует, чтобы доказать: здесь **инструмент**, а не одна
выполненная работа. Доказательство состоится только если разведение идёт по
тем осям, которые конвейер **меряет числами**. Вторая пятидесятилетняя
блондинка не доказала бы ничего.

| ось | Bridget | Imani | что это нагружает |
|---|---|---|---|
| возраст | 51 | 34 | полосу ворот возраста; задача обратная — не состарить, а не дать омолодить |
| тон кожи | светлый | глубокий тёмный | ворота цвета и микрорельефа считаются на другом материале |
| сложение | «fit and chic», йога и падел | работающие плечи и предплечья | блок `build`, который у поясных кадров выключается |
| свет | мягкий дневной, окно без заполнения | вольфрам, люминесцент, улица, кухонная лампа | `scene_class` и силу зерна последней мили |
| вторая часть | эротика и нагота | ночь без наготы | что договор полей общий, а содержание — решение автора |

**Одно место, где договор полей одинаковый, а содержание обязано быть
разным** — `realism_clause`. У Бриджит пластик выдаёт себя заглаженными порами,
и хвост реализма требует пор и неровного тона. На тёмной коже пластик выглядит
иначе: **ровным матовым тоном без бликов**. Поэтому здесь потребованы блики на
лбу и скулах, которых в её редакции нет. Скопировать хвост дословно значило бы
получить 3D-рендер и не понять почему.

## Состояние

**NOT_MEASURED.** Заведены бриф и обе раскадровки; GPU не запускался. Нет
кадров, реестра, вердикта ворот, якоря, сдачи, ассета тату и подобранных
координат вклейки — координаты стоят в умолчаниях и помечены
`"_state": "NOT_MEASURED"`, чтобы их нельзя было принять за подобранные.

Что **проверено** и чем:

```
py -3 scripts/prompts.py  projects/imani                          # промпты обеих частей
py -3 scripts/generate.py projects/imani --dry                    # план части 1
py -3 scripts/generate.py projects/imani --shotlist shotlist_story.json --dry
```

Все три отработали нулём, ни одного файла в рабочем корне не создано, **ни
одной правки кода не потребовалось**. Договор «конвейер работает на любом
проекте» держат тесты, параметризованные по всем папкам в `projects/` —
третий персонаж покроется сам собой.
