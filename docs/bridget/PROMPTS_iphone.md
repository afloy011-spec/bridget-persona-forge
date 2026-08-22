# Промпты под телефонный вид — для ручной прогонки

Под воркфлоу `templates/comfy/PERSONA_CHARACTER_FROM_REFERENCE.json`.
Персонаж приезжает картинкой в группу **1. CHARACTER**, лицо промптом не
описывается вовсе — иначе описание начинает спорить с референсом и тянет кадр
к типажу.

## Три правила, без которых остальное не работает

**Никаких запретов.** Krea 2 Turbo идёт на `cfg = 1.0`, где негативный
обусловливатель мёртв. «no watch» приносит watch, «not visible» приносит
visible. Замерено трижды: клауза запястья в трёх редакциях, 18 кадров, браслет
каждый раз на месте. Всё нежелательное пишется положительно: не «без часов», а
«запястье голое, кожа открыта до середины предплечья».

**Камера — телефонная, а не съёмочная.** Это единственное, чем часть 2 в старой
сдаче отличалась от части 1 и почему она читалась айфоном. Строки вида «85mm at
f/2» дают журнальный портрет; телефон описывается через «front camera, 26mm
equivalent, слегка бочкообразные края, автоэкспозиция».

**Одно длинное предложение работает лучше перечисления.** Так пишет автор
`krea2_realism_lora`, и наши промпты собираются иначе — блоками через запятую
до 2500 знаков. Ниже блоки склеены в связный текст намеренно.

---

## Общий хвост: приклеивать к каждому промпту

```
shot on a phone, the kind of picture that lives in someone's camera roll,
visible skin pores and fine facial texture, uneven natural skin tone with faint
redness around the nose and chin, a few flyaway hairs catching the light, fabric
with real creases and pressure folds, natural unretouched skin, full colour,
warm skin against cooler ambient light, a woman clearly in her early fifties,
mature and unaltered
```

---

# ЧАСТЬ 1 — профильные фото

### P1 · Геройский портрет
```
a candid phone photograph of her at home by a large window, chest up, she fills
the frame, looking straight into the lens with her chin a little down and a
half-smile, wearing an ivory silk blouse with one button open, a narrow gold
bangle and a slim gold watch on her right wrist and small thin gold hoops,
the room behind her thrown into soft warm blur, north window light from camera
left falling off into deep unlifted shadow on her right, taken by a friend on a
rear phone camera at 26mm equivalent held a touch too close at eye level, mild
barrel distortion at the edges, autofocus locked on her near eye
```

### P2 · В полный рост
```
a candid phone photograph of her walking on a wide city pavement in the late
afternoon, the whole standing figure small in a tall frame with room above her
head, photographed from far across the road, looking off to camera right caught
mid-thought, wearing a camel wool coat over a fine navy knit, slim trousers and
pointed-toe pumps, a limestone facade behind her and one parked car far out of
focus, low warm sun raking from behind camera right laying a long soft shadow
across the pavement, taken on a rear phone camera at 26mm equivalent held at
chest height with a slight handheld tilt, everything sharp the way a phone
renders it
```

### P3 · Падл-теннис, кэндид
```
a candid phone photograph of her mid-rally on a paddle tennis court in the
morning, three-quarter body slightly off-centre, her eyes tracking the ball
above and past the lens, wearing a fitted charcoal top and leggings with her
hair tied back in a low ponytail and strands escaping, bare ears and bare neck,
her right hand swinging the racket with the bangle and watch on that right
wrist, her left arm extended toward the lens with the back of her left wrist
facing the camera and the skin of that wrist and forearm completely bare and in
focus, green windscreen fencing behind her, flat bright overcast light with no
hard shadows, taken on a phone from across the court with a hint of motion
softness in the racket hand
```

### P4 · С собакой
```
a candid phone photograph of her sitting on her living room floor crouched
toward an old grey greyhound leaning into her, her face turned down to the dog
with a real unguarded smile and visible eye creases, wearing an oversized grey
cashmere sweater slipping off one shoulder, bare feet, hair loose, a worn
terracotta and blue kilim rug under them and a stack of books and a green glass
vase behind, warm lamplight from a floor lamp behind camera left and cool blue
evening daylight from a window on the right holding the shadows, taken on a
phone held low almost at floor level with one hand steadying it, warm auto white
balance and a little motion softness
```

### P5 · Ресторан вечером
```
a candid phone photograph of her at a restaurant table in the evening, upper
body, raising a glass of red wine toward the lens with her left hand and talking
mid-sentence with her mouth slightly open, wearing a wine-red silk dress with
her hair down, the bangle and watch on her right wrist, other tables softly out
of focus behind her, a candle on the table and a deep teal banquette behind her
shoulder, candle warmth from below and a small cool source spilling in from a
window behind her rimming her hair, taken on a phone across the table in low
light with visible sensor noise in the shadows, slight handshake and the candle
blowing out into a small bloom
```

---

# ЧАСТЬ 2 — история одного вечера

Бриф просит **пять кадров: три эротических, два ню**, с эскалацией от полностью
одетой до душа, и хотя бы одно селфи в зеркале с телефоном в кадре.

### S1 · Халат, спальня — одета
```
a phone selfie of her sitting on the edge of her bed at night in a champagne
silk robe tied at the waist, winking at the lens with a mischievous smile,
bedside lamp warm behind her and a city window dark beyond, taken on the front
phone camera at 24mm equivalent held at arm's length with slight barrel
distortion at the edges and the focus on her eyes
```
Подпись: *"Told you I'd have an early night."*

### S2 · Селфи в зеркале — ОБЯЗАТЕЛЬНЫЙ КАДР
```
a phone mirror selfie of her standing in front of a bedroom mirror in the same
champagne silk robe now loosely open at the throat, holding the phone up so the
handset is clearly visible in the reflection covering part of her cheek, her
other hand at the tie of the robe, warm bedside lamp and an unmade bed behind
her, taken on the rear phone camera at 26mm equivalent with a soft smudge on the
mirror glass and a slight handheld tilt
```
Подпись: *"Fine. One more, then I'm putting the phone down."*

### S3 · Кровать, ближе — эротический
```
a phone photograph of her lying on white bedlinen on her front, head resting on
one hand, the champagne robe fallen open off one shoulder and the sheet gathered
at her waist, looking up into the lens with a quiet direct expression, one lamp
low and warm at the edge of frame, taken on a phone held low and close at 26mm
equivalent with one soft lens flare from the lamp and slight motion softness
```
Подпись: *"It's very quiet here without you."*

### S4 · Ванная, пар — ню со спины
```
a phone photograph of her standing at a bathroom counter seen from behind, bare
back and shoulders down to the small of her back, the champagne robe fallen and
pooled on the counter beside her, hair pinned up with loose strands stuck to her
neck, a mirror in front of her fogged over except one wiped streak where her
face reads only as a soft blurred shape, brass taps and a folded towel, the room
thick with steam, taken on a phone propped on the counter at 26mm equivalent
with condensation haze over the whole frame
```
Подпись: *"Going in. Don't wait up."*

### S5 · Душ, силуэт — ню
```
a phone photograph taken from outside a shower through a glass panel that is
completely white with condensation, the glass opaque and milky across the whole
frame, the warm shape of her body behind it dissolved into a soft amber blur
with edges that melt into the fog, the lower third of the frame filled by one
hand pressed flat on the near side of the glass with its fingers and wet
handprint in sharp focus, one warm light deep inside the shower turning the
shape into a flat silhouette, cool bathroom light on the near side, taken on a
phone held right against the glass at 26mm equivalent with the focus locked on
the water droplets and the near hand
```
Подпись: *"Now you're just going to have to imagine the rest."*

**Замер по этой ячейке, чтобы не потерять время.** Прежняя редакция описывала
кадр отрицаниями («not visible», «nothing but water»), и **все восемь сидов**
отдали фронтальный портрет вместо силуэта. Редакция выше переписана
положительно — молочное стекло во весь кадр, спина в воде, одна ладонь на
ближней стороне, — и это сдвинуло кадр, но не решило до конца: под персонажной
лорой модель всё равно тянет к резкому портрету. Если силуэт не выходит и с
референса, снимайте ячейку **без персонажной лоры**: тяга к портрету уходит
вместе с ней.

---

## Что крутить, если не выходит

| симптом | ручка |
|---|---|
| лицо «поплыло», мелкое | не лора виновата: мало пикселей на лицо. Кадрировать теснее либо прогнать `upscale.py` |
| кадр повторяет позу и фон референса | `ref_boost` вниз, 8 → 4 |
| лицо уезжает от референса | больше сидов и отбор, а не `ref_boost` вверх |
| кадр кинематографичный, не телефонный | камера в промпте, и проверить, что риг в группе LOOK включён |
| днём зелёный оттенок | `k2_disposable_camera` в ноль, она только для ночи и вспышки |

---

# Три пробных промпта

Вставлять в ноду **Prompt** целиком, они уже с хвостом реализма.

### A · Кухня утром — ровный свет, крупно

*проверяет кожу: плоский белый свет ничего не прячет, поры и фактура видны или их нет*

```
a candid phone photograph of her standing at a kitchen counter in the morning, close in from the chest up, holding a mug in both hands near her collarbone and looking off past the lens with a small tired smile, wearing an oversized grey marl sweatshirt with the sleeves pushed up, an open window behind her giving flat white morning light, a kettle and a chopping board soft out of focus, taken on a rear phone camera at 26mm equivalent held at eye level with mild barrel distortion at the edges and autofocus on her near eye, shot on a phone, the kind of picture that lives in someone's camera roll, visible skin pores and fine facial texture, uneven natural skin tone with faint redness around the nose and chin, a few flyaway hairs catching the light, fabric with real creases and pressure folds, natural unretouched skin, full colour, a woman clearly in her early fifties, mature and unaltered
```

### B · Диван вечером — низкий свет

*проверяет шум и зерно: тёмная сцена, одна лампа. Тут же смотрите, не зеленит ли disposable camera*

```
a candid phone photograph of her curled sideways on a low sofa late in the evening, three-quarter body, one bare foot tucked under her and a paperback face down on the cushion beside her, laughing at something off camera with her head tipped back, wearing a soft black knit dress, one warm floor lamp behind her shoulder and the rest of the room falling away into darkness, taken on a phone from the armchair opposite in low light with visible sensor noise in the shadows and slight motion softness in her hair, shot on a phone, the kind of picture that lives in someone's camera roll, visible skin pores and fine facial texture, uneven natural skin tone with faint redness around the nose and chin, a few flyaway hairs catching the light, fabric with real creases and pressure folds, natural unretouched skin, full colour, a woman clearly in her early fifties, mature and unaltered
```

### C · Цветочный рынок — фигура целиком

*проверяет рост и лицо на расстоянии: тут лицо мелкое, и видно, держится ли оно*

```
a candid phone photograph of her at an outdoor flower market on a bright overcast morning, the whole standing figure in frame with room above her head, photographed from across the aisle as she leans in to smell a bunch of eucalyptus, wearing a long camel coat open over a white shirt and jeans with a canvas tote on one shoulder, buckets of cut flowers and a striped awning behind her, flat soft daylight with no hard shadows, taken on a rear phone camera at 26mm equivalent held at chest height with a slight handheld tilt, shot on a phone, the kind of picture that lives in someone's camera roll, visible skin pores and fine facial texture, uneven natural skin tone with faint redness around the nose and chin, a few flyaway hairs catching the light, fabric with real creases and pressure folds, natural unretouched skin, full colour, a woman clearly in her early fifties, mature and unaltered
```
