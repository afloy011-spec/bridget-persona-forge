# Bridget — Part 1 shotlist

*P — profile set*

5 cells · 1152 × 1440 px · 8 seeds per cell

*Generated from the project JSON by `scripts/export_docs.py`. The prompt under each cell is the exact string sent to the model.*

---

## How the set is built

Five frames, and the rule that matters is that they are five different FUNCTIONS rather than five poses. A real set of photographs of a person consists of frames taken on different occasions by different people — that is exactly what separates a set of photographs from an hour in a studio.

**Selection, not generation.** Forty frames generated, five delivered. Generation is cheap; the craft is in the selection.

**The trait field.** Each cell names which personality trait from the character card goes into its prompt. It is assigned here rather than inferred from the text of the frame, and "none" is a deliberate refusal — a second behavioural instruction would fight the one the frame already has. Across the set of five, each of the four traits from the brief is used at least once.

**The body-in-frame field.** Whether the build block — posture, shoulders, legs — belongs in this prompt. In a chest-up portrait a description of legs is noise that takes weight away from the face.

**The scene-class field.** The scene class (day / indoor / night / flash) selects the strength of the disposable-camera LoRA and the grain profile of the last-mile pass. Under daylight that LoRA casts the frame green, so it is only raised for night and flash.

---

## P1 · Hero portrait

**Function.** This is her face — the frame she is recognised by in all the others.

| field | value |
|---|---|
| framing | chest-up portrait, she fills the frame |
| gaze | direct eye contact with the lens, chin slightly lowered, a half-smile |
| wardrobe | an ivory silk blouse, one button open |
| personality trait in this prompt | flirtatious |
| scene class | indoor |
| body in frame | no |
| tattoo visible | no |

**Light.** soft north-facing window light from camera left, a gentle falloff into deep shadow on the right side of her face, the shadow side left dark and unlifted

**Camera.** 85mm at f/2, eye level, focus locked on the near eye

**Director's note.** Window light with no fill is mandatory: an even studio scheme erases age and texture together. The shadow across the right half of her face is what does the work of 'emotional depth' in the brief.

**Prompt**

```text
brdgt_w, a candid photograph of a real woman, shot on film-like digital, not a render, not an illustration, not a 3D character, chest-up portrait, she fills the frame, direct eye contact with the lens, chin slightly lowered, a half-smile, a 51-year-old woman, long layered warm mid-brown hair with multi-tonal salon balayage lightening through the lengths to sun-blonde ends, green-hazel eyes, high cheekbones with mild volume loss beneath them, a straight nose with a slightly rounded tip, thin upper lip and fuller lower lip, one eyebrow set marginally higher than the other, deep crow's feet fanning from both outer eye corners even at rest, pronounced nasolabial folds, clearly visible vertical lines above the upper lip, crepey texture on the lower eyelids, thinner vermilion of the upper lip, scattered grey strands at the temples and along the parting, loose skin on the neck with horizontal lines, prominent tendons and thinner skin on the backs of her hands, a sun-freckled décolleté, natural skin with visible pores across the nose and cheeks, hair long enough to reach mid-back when loose, an even warm mid-brown from the parting down through the lengths, lightening to sun-blonde only in the last third and at the ends, never platinum and never one flat tone, an ivory silk blouse, one button open, the same jewellery in every frame: a narrow gold bangle and a slim gold watch on her right wrist, small thin gold hoop earrings, at home by a large window, the room behind her thrown out of focus into warm neutral tones, soft north-facing window light from camera left, a gentle falloff into deep shadow on the right side of her face, the shadow side left dark and unlifted, 85mm at f/2, eye level, focus locked on the near eye, eye contact held a beat too long, chin slightly down, visible skin pores and fine facial texture, uneven natural skin tone with faint redness around the nose and chin, a few flyaway hairs catching the light, fabric with real creases and pressure folds, slight optical softness toward the frame corners, natural unretouched skin, full natural colour, warm skin tones against cooler ambient light, a woman clearly in her early fifties, mature and unaltered
```

## P2 · Full length

**Function.** Proves the build and the age at the same time — body, posture and hands all in frame.

| field | value |
|---|---|
| framing | a full-length street photograph of her walking, the whole standing figure small in a wide frame, photographed from far across the road |
| gaze | looking off to camera right, caught mid-thought, not posing |
| wardrobe | a camel wool coat over a fine navy knit, slim trousers, pointed-toe stiletto pumps |
| personality trait in this prompt | independent |
| scene class | day |
| body in frame | yes |
| tattoo visible | no |

**Light.** low warm afternoon sun raking from behind camera right, long soft shadow across the pavement

**Camera.** 35mm at f/4 from slightly below eye level, full body in frame with headroom

**Director's note.** The off-camera gaze already reads as guarded, so the trait assigned to this cell is independent: she occupies the centre of her own frame and is waiting for no one. 35mm from slightly below eye level gives height without the distortion a wider lens would add.

**Prompt**

```text
brdgt_w, a candid photograph of a real woman, shot on film-like digital, not a render, not an illustration, not a 3D character, a full-length street photograph of her walking, the whole standing figure small in a wide frame, photographed from far across the road, looking off to camera right, caught mid-thought, not posing, a 51-year-old woman, long layered warm mid-brown hair with multi-tonal salon balayage lightening through the lengths to sun-blonde ends, green-hazel eyes, high cheekbones with mild volume loss beneath them, a straight nose with a slightly rounded tip, thin upper lip and fuller lower lip, one eyebrow set marginally higher than the other, deep crow's feet fanning from both outer eye corners even at rest, pronounced nasolabial folds, clearly visible vertical lines above the upper lip, crepey texture on the lower eyelids, thinner vermilion of the upper lip, scattered grey strands at the temples and along the parting, loose skin on the neck with horizontal lines, prominent tendons and thinner skin on the backs of her hands, a sun-freckled décolleté, natural skin with visible pores across the nose and cheeks, hair long enough to reach mid-back when loose, an even warm mid-brown from the parting down through the lengths, lightening to sun-blonde only in the last third and at the ends, never platinum and never one flat tone, fit but not gym-built — the build of someone who does yoga and paddle tennis four times a week: defined shoulders and forearms, a long neck, upright posture, strong legs, a camel wool coat over a fine navy knit, slim trousers, pointed-toe stiletto pumps, the same jewellery in every frame: a narrow gold bangle and a slim gold watch on her right wrist, small thin gold hoop earrings, on a wide city sidewalk in the late afternoon, a limestone building facade behind her, one parked car far out of focus, low warm afternoon sun raking from behind camera right, long soft shadow across the pavement, 35mm at f/4 from slightly below eye level, full body in frame with headroom, she occupies the centre of her own frame; nothing in the composition suggests she is waiting for anyone, visible skin pores and fine facial texture, uneven natural skin tone with faint redness around the nose and chin, a few flyaway hairs catching the light, fabric with real creases and pressure folds, slight optical softness toward the frame corners, natural unretouched skin, full natural colour, warm skin tones against cooler ambient light, a woman clearly in her early fifties, mature and unaltered
```

## P3 · Candid, in motion

**Function.** Authenticity. The one frame in which she does not know she is being photographed.

| field | value |
|---|---|
| framing | caught mid-rally, standing, her left arm extended forward toward the lens for balance while her right arm swings a paddle racket back behind her, three-quarter body, slightly off-centre in the frame |
| gaze | not at the camera at all — her eyes tracking the ball above and past the lens |
| wardrobe | a fitted charcoal yoga top and leggings, hair tied back in a low ponytail with strands escaping |
| jewellery (overrides the bible) | bare ears and bare neck, only the narrow gold bangle left on her right wrist |
| personality trait in this prompt | guarded |
| scene class | day |
| body in frame | yes |
| tattoo visible | yes |

**Light.** flat bright overcast morning light, no hard shadows

**Camera.** 135mm at f/2.8 from across the court, a hint of motion blur in the racket hand

**Director's note.** This is where the tattoo composite goes: the left wrist is open and close to the lens. The motion blur in the racket hand is mandatory — a perfectly sharp frame in mid-movement reads as a render. The flat overcast light is deliberate: it shows the skin as it is.

**Prompt**

```text
brdgt_w, a candid photograph of a real woman, shot on film-like digital, not a render, not an illustration, not a 3D character, caught mid-rally, standing, her left arm extended forward toward the lens for balance while her right arm swings a paddle racket back behind her, three-quarter body, slightly off-centre in the frame, not at the camera at all — her eyes tracking the ball above and past the lens, a 51-year-old woman, long layered warm mid-brown hair with multi-tonal salon balayage lightening through the lengths to sun-blonde ends, green-hazel eyes, high cheekbones with mild volume loss beneath them, a straight nose with a slightly rounded tip, thin upper lip and fuller lower lip, one eyebrow set marginally higher than the other, deep crow's feet fanning from both outer eye corners even at rest, pronounced nasolabial folds, clearly visible vertical lines above the upper lip, crepey texture on the lower eyelids, thinner vermilion of the upper lip, scattered grey strands at the temples and along the parting, loose skin on the neck with horizontal lines, prominent tendons and thinner skin on the backs of her hands, a sun-freckled décolleté, natural skin with visible pores across the nose and cheeks, hair long enough to reach mid-back when loose, an even warm mid-brown from the parting down through the lengths, lightening to sun-blonde only in the last third and at the ends, never platinum and never one flat tone, fit but not gym-built — the build of someone who does yoga and paddle tennis four times a week: defined shoulders and forearms, a long neck, upright posture, strong legs, a fitted charcoal yoga top and leggings, hair tied back in a low ponytail with strands escaping, bare ears and bare neck, only the narrow gold bangle left on her right wrist, her left arm turned so the back of her left wrist faces the lens, unobstructed and in focus, her left sleeve pushed up above the elbow and the skin of her left wrist and forearm completely bare, every piece of jewellery she wears — the bangle and the watch — on her right wrist only, a paddle tennis court in the morning, green windscreen fencing behind her, racket in her right hand mid-swing, flat bright overcast morning light, no hard shadows, 135mm at f/2.8 from across the court, a hint of motion blur in the racket hand, her attention is elsewhere, caught mid-thought rather than posing, visible skin pores and fine facial texture, uneven natural skin tone with faint redness around the nose and chin, a few flyaway hairs catching the light, fabric with real creases and pressure folds, slight optical softness toward the frame corners, natural unretouched skin, full natural colour, warm skin tones against cooler ambient light, a woman clearly in her early fifties, mature and unaltered
```

## P4 · With the dog

**Function.** Warmth and vulnerability — the beat the brief calls emotional complexity.

| field | value |
|---|---|
| framing | seated on the floor, crouched toward a dog, her face turned down toward it |
| gaze | down at the dog, a real unguarded smile with visible eye creases |
| wardrobe | an oversized grey cashmere sweater slipping off one shoulder, bare feet, hair loose |
| personality trait in this prompt | none |
| scene class | indoor |
| body in frame | no |
| tattoo visible | no |

**Light.** warm low lamplight from a floor lamp behind camera left, cool blue evening daylight from a window on the right holding the shadows, the room falling into soft darkness beyond

**Camera.** 50mm at f/1.8, low, almost at floor level

**Director's note.** The only frame with a real smile rather than a half one. The creases at her eyes must be visible here; they prove age and aliveness in the same gesture. An old greyhound rather than a puppy: the dog's age supports hers.

**Prompt**

```text
brdgt_w, a candid photograph of a real woman, shot on film-like digital, not a render, not an illustration, not a 3D character, seated on the floor, crouched toward a dog, her face turned down toward it, down at the dog, a real unguarded smile with visible eye creases, a 51-year-old woman, long layered warm mid-brown hair with multi-tonal salon balayage lightening through the lengths to sun-blonde ends, green-hazel eyes, high cheekbones with mild volume loss beneath them, a straight nose with a slightly rounded tip, thin upper lip and fuller lower lip, one eyebrow set marginally higher than the other, deep crow's feet fanning from both outer eye corners even at rest, pronounced nasolabial folds, clearly visible vertical lines above the upper lip, crepey texture on the lower eyelids, thinner vermilion of the upper lip, scattered grey strands at the temples and along the parting, loose skin on the neck with horizontal lines, prominent tendons and thinner skin on the backs of her hands, a sun-freckled décolleté, natural skin with visible pores across the nose and cheeks, hair long enough to reach mid-back when loose, an even warm mid-brown from the parting down through the lengths, lightening to sun-blonde only in the last third and at the ends, never platinum and never one flat tone, an oversized grey cashmere sweater slipping off one shoulder, bare feet, hair loose, the same jewellery in every frame: a narrow gold bangle and a slim gold watch on her right wrist, small thin gold hoop earrings, her living room floor, a worn terracotta and blue kilim rug, an old grey greyhound leaning into her, a stack of books and a green glass vase behind, warm low lamplight from a floor lamp behind camera left, cool blue evening daylight from a window on the right holding the shadows, the room falling into soft darkness beyond, 50mm at f/1.8, low, almost at floor level, visible skin pores and fine facial texture, uneven natural skin tone with faint redness around the nose and chin, a few flyaway hairs catching the light, fabric with real creases and pressure folds, slight optical softness toward the frame corners, natural unretouched skin, full natural colour, warm skin tones against cooler ambient light, a woman clearly in her early fifties, mature and unaltered
```

## P5 · Her world

**Function.** The context of a life. Shot by someone else across a table — the kind of frame that reads as a real life in a profile.

| field | value |
|---|---|
| framing | seated at a restaurant table, upper body, her left hand raising a glass of red wine toward the lens |
| gaze | at whoever is sitting across from her, mid-sentence, mouth slightly open |
| wardrobe | a wine-red silk dress, hair down and loose |
| personality trait in this prompt | sensitive |
| scene class | night |
| body in frame | no |
| tattoo visible | yes |

**Light.** candle warmth from below-front and a small cool blue-white source spilling in from a window behind her, rimming her hair

**Camera.** 50mm at f/1.4 across a table, slight camera shake, focus just barely on the near eye

**Director's note.** The raised glass is a natural reason to bring the left wrist close to the lens, and the second tattoo composite goes here. The slight shake and the near-miss focus are deliberate: a perfect frame by candlelight is physically impossible, and the eye knows it. Watch the colour gate on this one — a warm restaurant in the dark drifts toward near-monochrome and fails the brief's explicit requirement on colour.

**Prompt**

```text
brdgt_w, a candid photograph of a real woman, shot on film-like digital, not a render, not an illustration, not a 3D character, seated at a restaurant table, upper body, her left hand raising a glass of red wine toward the lens, at whoever is sitting across from her, mid-sentence, mouth slightly open, a 51-year-old woman, long layered warm mid-brown hair with multi-tonal salon balayage lightening through the lengths to sun-blonde ends, green-hazel eyes, high cheekbones with mild volume loss beneath them, a straight nose with a slightly rounded tip, thin upper lip and fuller lower lip, one eyebrow set marginally higher than the other, deep crow's feet fanning from both outer eye corners even at rest, pronounced nasolabial folds, clearly visible vertical lines above the upper lip, crepey texture on the lower eyelids, thinner vermilion of the upper lip, scattered grey strands at the temples and along the parting, loose skin on the neck with horizontal lines, prominent tendons and thinner skin on the backs of her hands, a sun-freckled décolleté, natural skin with visible pores across the nose and cheeks, hair long enough to reach mid-back when loose, an even warm mid-brown from the parting down through the lengths, lightening to sun-blonde only in the last third and at the ends, never platinum and never one flat tone, a wine-red silk dress, hair down and loose, the same jewellery in every frame: a narrow gold bangle and a slim gold watch on her right wrist, small thin gold hoop earrings, her left arm turned so the back of her left wrist faces the lens, unobstructed and in focus, her left sleeve pushed up above the elbow and the skin of her left wrist and forearm completely bare, every piece of jewellery she wears — the bangle and the watch — on her right wrist only, a warm dimly lit restaurant in the evening, other tables softly out of focus behind her, a candle on the table, a deep teal upholstered banquette behind her shoulder, candle warmth from below-front and a small cool blue-white source spilling in from a window behind her, rimming her hair, 50mm at f/1.4 across a table, slight camera shake, focus just barely on the near eye, hands near the throat, collarbone or opposite forearm — a self-touch that reads as self-comfort, visible skin pores and fine facial texture, uneven natural skin tone with faint redness around the nose and chin, a few flyaway hairs catching the light, fabric with real creases and pressure folds, slight optical softness toward the frame corners, natural unretouched skin, full natural colour, warm skin tones against cooler ambient light, a woman clearly in her early fifties, mature and unaltered
```
