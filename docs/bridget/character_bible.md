# Bridget — character bible

**Bridget, age 51.** A fictional person. Every image in this project is generated; no real individual is depicted.

*Generated from `character.json` by `scripts/export_docs.py` — edit the JSON, not this file.*

---

## How this card is used

The blocks below go into every prompt of the set verbatim. Identity holds by repetition, not by luck — rewriting a description by hand a sixth time produces a synonym, and a synonym produces a different woman. Once the batch is running the wording is frozen: changing it would move every frame that has already passed the gates.

## What the model is told it is making

> a candid photograph of a real woman, shot on film-like digital, not a render, not an illustration, not a 3D character

**Why.** The medium is the first block of every prompt. A model that is not told it is taking a photograph makes a portrait — and a portrait is exactly what an AI detector flags.

## The face

> a 51-year-old woman, long layered warm mid-brown hair with multi-tonal salon balayage lightening through the lengths to sun-blonde ends, green-hazel eyes, high cheekbones with mild volume loss beneath them, a straight nose with a slightly rounded tip, thin upper lip and fuller lower lip, one eyebrow set marginally higher than the other

**Why.** The asymmetry is not decoration, it is the anti-AI-look device. A generically symmetric face reads as generated to both a viewer and a detector; one specific irregularity turns a type into a person. The styling lives in the hair rules rather than here, because in the candid frame her hair is tied back and two contradictory instructions would fight inside one prompt.

## Age, in detail

> deep crow's feet fanning from both outer eye corners even at rest, pronounced nasolabial folds, clearly visible vertical lines above the upper lip, crepey texture on the lower eyelids, thinner vermilion of the upper lip, scattered grey strands at the temples and along the parting, loose skin on the neck with horizontal lines, prominent tendons and thinner skin on the backs of her hands, a sun-freckled décolleté, natural skin with visible pores across the nose and cheeks

**Why.** This is the automatic failure of the whole task: base models pull any woman back toward twenty-seven. Age lives here, not in the words '51-year-old' — a model does not believe a number, it believes detail. The neck and the backs of the hands are mandatory: diffusion hides them, and they are precisely what proves maturity to a viewer.

## Build

> fit but not gym-built — the build of someone who does yoga and paddle tennis four times a week: defined shoulders and forearms, a long neck, upright posture, strong legs

## Hair

> hair long enough to reach mid-back when loose, an even warm mid-brown from the parting down through the lengths, lightening to sun-blonde only in the last third and at the ends, never platinum and never one flat tone

**Why.** Length and grown-out roots are per-person markers, so they ride in every prompt rather than being left to whichever frame happens to get them right.

## Wardrobe

| element | rule |
|---|---|
| materials | silk, cashmere, fine wool, soft leather — fabrics that fall heavily and crease honestly |
| palette | camel, ivory, deep navy, warm grey, one recurring wine-red |
| jewelry | the same jewellery in every frame: a narrow gold bangle and a slim gold watch on her right wrist, small thin gold hoop earrings |
| nails | short almond-shaped nails, warm nude polish |
| shoes | when shoes are in frame they are pointed-toe stiletto pumps |

**Why.** Wardrobe is characterisation. The Manolo Blahnik tattoo dates her: she was around thirty in 2005, her taste was formed by the luxury of that decade and has grown up with her. Expensive cloth, never a loud logo.

**Why the same jewellery every time.** The same jewellery in every frame is the cheapest and most visible proof that this is one person in one period of her life, rather than ten separate generations.

**And how the frames broke it.** And it was broken — not in the rule but in the frames. In both delivered frames that show the back of the wrist (the dog and the restaurant), the watch and bangle ended up on the LEFT arm, right on the landing area. The rule was stated in the jewellery block, which reads 'on her right wrist', and at cfg 1.0 that was not enough: the model repeated the object, not the side. So the requirement is restated in tattoo.prompt_clause, where the wrist itself is asked for, and backed by a measurement of the frame rather than by trust in the prompt.

**Left and right.** Laterality is split once and hard: the tattoo is on the BACK of the LEFT wrist, the metal on the RIGHT. Otherwise the bangle and the watch sit on top of the landing area for the composite, and the paste-in either does not fit or lands on metal.

## The tattoo

> the words «Manolo Blahnik» tattooed in a fine handwritten script, single-needle work, a capital M and a capital B with the rest in a light sloping cursive, the strokes thin and slightly broken where the ink has spread, faded to a warm grey-brown the way a fifteen-year-old tattoo fades

| field | value |
|---|---|
| placement | back of the left wrist |
| size | 75 mm |
| length / forearm width | 1.2 |
| from wrist, in forearm widths | 0.88 |
| graphic asset | `assets/tattoo_manolo_blahnik.png` |
| source photograph | `references/tattoo_photo_wrist.png` |
| asked for in | P3, P5, S2, W01, W02, W03 |

**Why it is composited, not generated.** The model does not draw this, and neither do we. The tattoo exists on the character reference, and it is LETTERING rather than a graphic: the name either matches letter for letter or it is somebody else's tattoo — there is no drawing one in the spirit of the original — while diffusion turns fine script on a wrist into a different mush of letters in every frame. So the ink is lifted out of the reference photograph (scripts/tattoo_from_photo.py: separated from skin by darkness relative to the local background, straightened along its principal axis) and composited in — identical letter for letter in every frame. The ink colour is sampled from the photograph (RGB 75,60,65) rather than set to black: a fifteen-year-old tattoo has faded to a warm grey-brown, and substituting crisp black would lend the frame a freshness the character does not have.

**Asked for is not the same as delivered.** The list of cells where the wrist is ASKED for. It does not decide whether the tattoo appears: that is decided by measuring the frame (metrics/wrist.py). A request and a result are different things, and on the delivery they diverged on all five frames.

**Which side of the wrist, and how we know.** The side changed with the second reference photograph, and this is a different place rather than a refinement. It used to read 'inner left wrist'. In the photograph all four fingernails face the camera, so the hand is seen from the BACK — and so is the wrist the lettering sits on. The hand is the left one: seen from the back with the fingers to the left, a left thumb points up, and it does. From this follows the whole rule the client set: composite the tattoo only where that surface is visible, and where it is not, do not composite it at all.

**Where the three numbers come from.** Three numbers measured off the photograph rather than chosen. The lettering is 679 px long where the forearm is 551 and 576 px wide at two points along it — hence 1.20. From the wrist to the centre of the line is 0.88 forearm widths, and the line sits on the arm's midline to within 0.07 of its width. Everything is measured against WIDTH rather than the length of the arm: the elbow is rarely in frame, while the width of the wrist is always visible when the wrist itself is. size_mm is derived and informational: 1.20 x 63 mm. The first photograph gave 0.74 and 45 mm for the same measurements; the second reference shows a larger tattoo, and its number is now the working one.

**Which way the line runs.** The direction of the line is not a choice, it follows from anatomy: the lettering is inked along the skin from wrist to elbow, so the rotation of the composite is fixed by that vector, and it never needs mirroring — the back of the wrist is one surface, and from whichever side you look at it the letters read the same way. While the composite went anywhere at all, both questions were open; the client's rule closed both.

**What changed when the reference arrived.** The asset has been replaced twice. First there was a drawn stiletto silhouette, assets/tattoo_stiletto.png — an invented tattoo, set down before any reference existed; the reference turned out to be lettering. Then the client sent a second photograph of the same lettering, larger and cleaner, and the asset was rebuilt from it: 689x165 px instead of 484x91, ink RGB 75,60,65. The source crop is kept in the repository so that the asset can be rebuilt rather than held as a single surviving copy.

**The clause in the prompt.** The composite needs somewhere to land, and that somewhere has to be the right surface AND empty. The first half follows the placement. The second was added by measurement: in both delivered frames that show the back of the wrist, the model put the watch and bangle on the LEFT arm — against the wardrobe rule that separates metal from ink by arm. The rule was stated in the jewellery block and broken there; at cfg 1.0 an instruction acts where it stands, and it stood next to the word 'right'. So the ban is repeated here, in the clause that asks for the wrist, and phrased as a requirement rather than a prohibition. A gate backs it: metrics/wrist.py cancels the composite when an object covers more than 2% of the lettering's footprint, and on the delivery it cancelled both (9% and 11%).

> her left arm turned so the back of her left wrist faces the lens, unobstructed and in focus, her left sleeve pushed up above the elbow and the skin of her left wrist and forearm completely bare, every piece of jewellery she wears — the bangle and the watch — on her right wrist only

## Personality, as something visible

| trait | what it looks like in the frame |
|---|---|
| independent | she occupies the centre of her own frame; nothing in the composition suggests she is waiting for anyone |
| flirtatious | eye contact held a beat too long, chin slightly down, a half-smile rather than a full one |
| sensitive | hands near the throat, collarbone or opposite forearm — a self-touch that reads as self-comfort |
| guarded | her attention is elsewhere, caught mid-thought rather than posing |

**Why.** The personality traits from the brief are translated into what is physically visible in a frame. Anything that stays an adjective never reaches the image at all.

**One frame at a time.** Each trait describes ONE frame. How many frames in the set look away is a decision for the shotlist, not for the character card — a note to the director written into a prompt only acts as noise.

## Camera and realism

> shot on a full-frame camera with a fast prime lens, shallow but not extreme depth of field, natural perspective at eye level

> visible skin pores and fine facial texture, uneven natural skin tone with faint redness around the nose and chin, a few flyaway hairs catching the light, fabric with real creases and pressure folds, slight optical softness toward the frame corners, natural unretouched skin

**Why.** This tail is attached to every prompt, and it is phrased as a demand on purpose. Krea 2 Turbo runs at cfg = 1.0, where the negative conditioning has no effect on the result at all. 'No plastic skin' does nothing; 'visible skin pores' works.

## Prohibitions rewritten as requirements

| prohibition | how it is asked for instead |
|---|---|
| no monochrome | full natural colour, warm skin tones against cooler ambient light |
| no young face | a woman clearly in her early fifties, mature and unaltered |

**Why.** The same rule applied to the prohibitions in the brief: each one is restated as a requirement, because at cfg = 1.0 there is nothing to prohibit with.

**No overlap.** These items deliberately do not overlap with the identity block or the realism tail, where asymmetry and untouched skin are already required. At cfg = 1.0 a repeated requirement is a doubled weight, and the frame drifts into exaggerated texture.

## Identity anchor

| field | value |
|---|---|
| anchor image | `D:/Cursor/persona-forge-work/bridget/ref/ref_face.png` |
| ArcFace embedding | recorded |

**Why.** Filled in by the casting stage. The anchor image is the single chosen frame the whole project is measured against; the embedding is the ArcFace vector every later frame is compared to for drift.
