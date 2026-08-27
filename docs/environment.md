# Environment

What has to exist on the ComfyUI side for this repo to run.

Everything below was read from the live worker on **2026-08-10, 13:34 UTC**,
re-read at **13:46 UTC**, and re-read again on **2026-08-18** with read-only
`GET /system_stats` and `GET /object_info`. Nothing was queued: the project
never posts to `/prompt` just to inspect a machine, and the machine is shared.

Reproduce the check against your own worker:

```
curl $COMFY_HOST/system_stats
curl $COMFY_HOST/object_info      # ~4200 node classes, large
```

The host is not hard-coded anywhere — not in the code and not in this document.
`assets.json → host_default` is `null` on purpose; the address comes from the
`COMFY_HOST` environment variable or from `assets.local.json`, which git does
not track. An earlier revision of this file printed a private
address in three places while `assets.json` claimed there were no machine
addresses in the repository; that claim was true of `assets.json` only.

---

## The worker

| | |
|---|---|
| endpoint | `$COMFY_HOST` — a private worker, `main.py --port <порт>` |
| ComfyUI | 0.33.1, `deploy_environment: local-git` |
| frontend | `comfyui-frontend-package` 1.48.7 (installed = required) |
| workflow templates | `comfyui-workflow-templates` 0.11.41 |
| Python | 3.10.9 (CPython, MSVC x64), not the embedded build |
| PyTorch | 2.11.0+cu128 |
| OS | Windows (`win32`) |
| GPU | NVIDIA GeForce RTX 5090, 32 GB VRAM, `cudaMallocAsync` |
| system RAM | 32 GB |

Version floors that matter: `CLIPLoader` must offer `krea2` in its `type` list.
It does from 0.26.0 onward; anything older has no Krea 2 text encoder path and
the base template will not load at all. The row above records 0.33.1 because
that is what the worker answered on the re-read date — the floor is 0.26.0, the
reading is 0.33.1, and those are different numbers.

## Models

Roles are those used by this project. Every filename below was confirmed
present in the corresponding loader's combo list on the live server on the date
above.

| file | role | loaded by | present | source |
|---|---|---|---|---|
| `krea2_turbo_fp8_scaled.safetensors` | base diffusion model, 8-step distilled | `UNETLoader` | yes | [`Comfy-Org/Krea-2`](https://huggingface.co/Comfy-Org/Krea-2) → `diffusion_models/krea2_turbo_fp8_scaled.safetensors` |
| `qwen3vl_4b_fp8_scaled.safetensors` | text encoder, loaded with `type: krea2` | `CLIPLoader` | yes | [`Comfy-Org/Krea-2`](https://huggingface.co/Comfy-Org/Krea-2) → `text_encoders/qwen3vl_4b_fp8_scaled.safetensors` |
| `qwen_image_vae.safetensors` | VAE | `VAELoader` | yes | [`Comfy-Org/Krea-2`](https://huggingface.co/Comfy-Org/Krea-2) → `vae/qwen_image_vae.safetensors` |
| `bridget_char_v2_000002500.safetensors` | **персонажная лора — держит лицо**, strength 1.0 | `LoraLoaderModelOnly` | yes | **нигде не скачивается: обучена этим проектом.** Рецепт — `scripts/lora_dataset.py --pool produce` → `scripts/lora_train.py`, срез выбран `scripts/lora_pick.py`; параметры в `assets.json → models.character_lora` |
| `krea2_realism_lora.safetensors` | realism base, strength 0.65 | `LoraLoaderModelOnly` | yes | не опознан |
| `RealisticSnapshotKrea2.safetensors` | amateur snapshot look, 0.45 | `LoraLoaderModelOnly` | yes | [Civitai 2268008](https://civitai.com/models/2268008/realistic-snapshot-z-image-turbo-krea-2), вариант Krea2 |
| `purelens_krea2.safetensors` | optics, 0.9 | `LoraLoaderModelOnly` | yes | не опознан |
| `k2_amateur_slider.safetensors` | amateur slider, 0.35 | `LoraLoaderModelOnly` | yes | не опознан |
| `k2_disposable_camera.safetensors` | night/flash only, 0.0 by day | `LoraLoaderModelOnly` | yes | не опознан |
| `codeformer-v0.1.0.pth` | alternative restorer — abandoned with the swap | — | yes | present on the shared machine; not used by this project |
| `4xFaceUpSharpDAT.safetensors` | face upscaler for the anchor and portrait finishing | `UpscaleModelLoader` | yes | не опознан |
| `4x-UltraSharp.pth` | general upscaler | `UpscaleModelLoader` | yes | не опознан |
| `krea2-depth-control-lora.safetensors` | depth control, optional (pose from a reference) | `Krea2ControlLoRALoader` | yes | не опознан |
| `krea2_raw_fp8_scaled.safetensors` | RAW base, needed only to *train* a character LoRA | `UNETLoader` | **yes (появился)** | [`Comfy-Org/Krea-2`](https://huggingface.co/Comfy-Org/Krea-2) → `diffusion_models/krea2_raw_fp8_scaled.safetensors` |

**Две строки этой таблицы были неверны, и обе поправлены переспросом живого
сервера, а не памятью.** `krea2_raw_fp8_scaled` стоял как отсутствующий — он
есть, значит переобучение персонажной лоры на этой машине возможно. А
`inswapper_128.onnx` и `GPEN-BFR-512.onnx` стояли как присутствующие — их в
списке моделей больше нет; закрытая ветка фейс-свопа осталась только в
описании, и это как раз хорошо.

**Хеши: по-прежнему НЕ ЗАПИСАНЫ, и вот чем это ограничено.** HTTP-API отдаёт
имена файлов, но не хеши и не происхождение, а посчитать sha256 можно только
имея оболочку на самом воркере. Из этого репозитория такой доступ не
предполагается. Тому, у кого он есть, достаточно одной команды на машине с
моделями:

```powershell
Get-ChildItem -Recurse -Include *.safetensors,*.pth,*.onnx |
  Get-FileHash -Algorithm SHA256 |
  Select-Object Hash, @{n='Name';e={Split-Path $_.Path -Leaf}} |
  ConvertTo-Json | Out-File models.sha256.json
```

Пока этого файла нет, таблицу выше надо читать как «эти имена обязаны
разрешаться на воркере», а строку «источник» — как «отсюда файл с таким именем
берут обычно», а не как доказательство, что на воркере лежит именно он.
Совпадение имени и совпадение весов — разные утверждения, и второе здесь не
проверено ни для одного файла.

**Чего эта таблица не чинит.** Даже с источниками репозиторий остаётся
непереносимым в одном месте, и оно главное: персонажная лора весит 109 МБ, в
гит не положена и нигде не опубликована. Без неё конвейер запустится и будет
считать, но лицо в кадрах будет чужое — идентичность живёт в этих весах, а не в
коде. Восстановить её можно только переобучением по рецепту из строки таблицы,
и это часы GPU, а не команда `pip install`.

**This section said the opposite until 2026-08-18, and the reversal is the
single most important change in this document.**

It used to read: `krea2_raw_fp8_scaled.safetensors` is absent, Krea's guidance
is to train on RAW and apply on Turbo, therefore the character-LoRA route is
closed on this machine and identity runs through selection alone.

The premise was correct and the conclusion expired. The LoRA was trained on
**Turbo directly**, through the ostris training adapter, which is what removed
the need for the RAW base. So:

- A character LoRA exists, is installed on the worker, and is switched on:
  `assets.json → models.character_lora.name` =
  `bridget_char_v2_000002500.safetensors`, trigger `brdgt_w`, strength 1.0. It
  loads first in the stack and its trigger is injected as the first token of
  every prompt. There is no `path` key in that object and never was — the old
  bullet here asserted that `models.character_lora.path` was `null`, which was
  not a state but a reference to a field that does not exist.
- Identity therefore has **two** mechanisms now, not one: the LoRA puts the
  person in the weights, and `select_set.py` still picks the set whose worst
  pair is best. `assets.json → identity.method` still reads `"selection"`; that
  string describes the second half only.
- The face-swap route was built, measured and taken out of the pipeline — see
  "The closed swap branch". `scripts/face_transfer.py` and
  `templates/comfy/face_transfer_api.json` are still in the tree as an
  off-by-default branch; "removed" means removed from the default path, not
  deleted from the repository.

## Custom node packs

Re-derived on **2026-08-18** by walking every graph in `templates/comfy/` and
asking the live server which module registered each class. The previous edition
of this table listed two packs and was wrong in both directions: it named
ReActor as a requirement of the current pipeline (the swap is not in it), and it
omitted every pack the tattoo step and the edit branch actually need — a reader
who provisioned a worker from it could not have run step 9 at all.

| pack | `python_module` | classes used here | needed for |
|---|---|---|---|
| controlnet_aux | `custom_nodes.comfyui_controlnet_aux` | `DensePosePreprocessor`, `DepthAnythingV2Preprocessor` | **step 9** — body-surface map that tells palm from back of wrist; depth for optional control |
| RMBG | `custom_nodes.ComfyUI-RMBG` | `SAM3Segment` | **step 9** — text-driven segmentation, checks a watch or bracelet is not sitting on the tattoo patch |
| Afloy Lora Box | `custom_nodes.ComfyUI-LoraBox` | `LoraBox` | `build_ui.py` only — the hand-check workflow packs the whole LoRA stack into one node |
| Krea 2 Edit | `custom_nodes.comfyui-krea2edit` | `Krea2EditGroundedEncode`, `Krea2EditModelPatch` | the edit branch (`krea2_identity_edit_api.json`) |
| Krea 2 ControlNet | `custom_nodes.comfyui-krea2-controlnet` | `Krea2ControlApply`, `Krea2ControlImageEncode`, `Krea2ControlLoRALoader` | optional depth control |
| KJNodes | `custom_nodes.ComfyUI-KJNodes` | `ColorMatchV2` | the `nd_*` refine templates |
| ReActor | `custom_nodes.comfyui-reactor` | `ReActorFaceBoost`, `ReActorFaceSwap` | **not the pipeline** — `face_transfer_api.json` only, an off-by-default branch (see below) |

Upstream repository URLs are **not recorded** — the server reports the module
path it imported, not where that directory came from.

**The batch that produces the delivery needs none of these.** `UNETLoader`,
`CLIPLoader`, `VAELoader`, `CLIPTextEncode`, `ConditioningZeroOut`,
`EmptyLatentImage`, `KSampler`, `VAEDecode`, `LoraLoaderModelOnly`,
`ImageScaleBy`, `UpscaleModelLoader`, `ImageUpscaleWithModel`,
`SaveImage`/`PreviewImage` are all core. Steps 1-8 and 10-12 run on a stock
ComfyUI; the packs above buy step 9 and the two side branches.

### The closed swap branch

**Nothing below is part of the current pipeline.** It is kept because the branch
was built and measured, and the measurement is the reason the pipeline looks the
way it does — a reader who does not know the swap was tried will propose it.

What was measured: the swap gave the best pairwise cosine of the four identity
routes, and it did so by rendering the face at 128×128 into a 1152×1440 frame.
The restorer then had to invent everything between those two resolutions, which
is exactly the plastic skin the task forbids; the second img2img pass that tried
to bring texture back painted fibrous ripple onto flat walls. Identity bought
with skin is not identity bought.

`templates/comfy/krea2_swap_api.json` was deleted with the branch, so the table
below no longer matches anything in the repository; it records what the nodes
were, not what to run.

| class | used as | notes |
|---|---|---|
| `ReActorLoadFaceModel` | loads the anchor face bank entry | node 30; combo of `models/reactor/faces/*.safetensors` |
| `ReActorOptions` | detection and ordering options | node 31; `large-small`, `detect_gender_input: female`, index `0` |
| `ReActorFaceBoost` | boost pass, `GPEN-BFR-512.onnx` | node 32 |
| `ReActorFaceSwapOpt` | the swap itself | node 33; `retinaface_resnet50`, `inswapper_128.onnx` |
| `ReActorBuildFaceModel` | builds the bank entry from the casting frames | needed once, at casting |
| `ReActorSaveFaceModel` | wrote it to `models/reactor/faces/` | removed from the shared machine when the branch closed |

**The face bank was the branch's one persistent artefact**, and it is gone.
`ReActorSaveFaceModel` wrote `persona_anchor.safetensors` into
`models/reactor/faces/` on the shared machine — the single deliberate exception
this project ever made to "leave nothing behind". When the branch closed the
entry was deleted, and the exception went with it: today the policy in
`scripts/comfy_client.py` has none.

Kept as a finding, because it survives the branch: the restorers had to be held
at `face_restore_visibility` 0.35 / `codeformer_weight` 0.4, and above roughly
0.5 the restorer irons skin into plastic and takes the visible age with it. That
is the main source of AI-look on a mature face, and it is why the current
pipeline has a `skin` gate on micro-relief rather than a restoration step.

### Krea 2 ControlNet classes

`Krea2ControlLoRALoader`, `Krea2ControlImageEncode`, `Krea2ControlApply`. Not
used by the current templates; present so a pose can be driven from a depth map
if a frame needs it.

## Krea 2 is its own architecture

This is the constraint that catches people out: **SD 1.5, SDXL and Flux
ControlNets do not apply to Krea 2.** Not "work worse" — they are a different
conditioning interface and there is no adapter. Concretely:

- Control goes through the pack above, which applies a *control LoRA* to the
  model and encodes the control image into a latent. It is not a
  `ControlNetLoader` / `ControlNetApplyAdvanced` chain, and those core nodes have
  nothing to accept a Krea 2 model.
- The only publicly available Krea 2 control LoRA is depth
  (`krea2-depth-control-lora.safetensors`). No canny, no openpose, no depth+pose
  stack. Pose is expressed as a depth map rendered from a reference.
- LoRAs must be trained for Krea 2. The Krea LoRAs listed above are not
  interchangeable with SD or Flux LoRAs of the same name pattern, and the
  `LoraLoaderModelOnly` combo on this machine is one 35-entry alphabetical list
  that mixes Flux, Z-Image, LTX and Krea 2 files — `amelie-flux.safetensors`
  sits four rows above `k2_amateur_slider.safetensors`. Picking by eye is how a
  run silently produces noise.
- Text conditioning is a Qwen3-VL encoder loaded with `CLIPLoader type: krea2`.
  A CLIP-L/T5 pair from an SD or Flux workflow is not a substitute.

What *was* architecture-independent: ReActor. `inswapper_128.onnx` operates on
decoded pixels after `VAEDecode`, so it neither knows nor cares which model drew
the frame — which is why it looked like the way around the blocked LoRA route.
It was, and the frame paid for it in skin. The route that survived costs nothing
architecturally: generate well, then choose.

## Sampler settings, and why the negative prompt is missing

`assets.json → models.base`: `euler` / `simple`, 8 steps, **cfg 1.0**.

At cfg 1.0 the negative conditioning has no effect on the output whatsoever. The
templates reflect this literally: node 5 is a `ConditioningZeroOut` fed from the
same `CLIPTextEncode` as the positive, and there is no negative text field
anywhere in the project. Everything unwanted is expressed as a positive
requirement instead — see `character.json → forbidden_as_positive`. A reviewer
looking for the negative prompt will not find one, and its absence is the design.

## Server-side write policy

`SaveImage` is swapped for `PreviewImage` at submit time. Frames land in the
server's `temp/`, are pulled back over `/view`, and the local copy under
`work_root` is the only product. The API has no way to delete from `output/`, so
the project does not write there. In the UI twin
(`templates/comfy/PERSONA_MANUAL_CHECK.json`) the `SaveImage` node is present but
muted (`mode = 2`).

There is no exception. The ReActor face bank used to be one; it was deleted
from the shared machine when the swap branch closed, and `temp/` is left as
found — see "The closed swap branch".

## Local Python side

The scripts that talk to ComfyUI (`comfy_client.py`, `prompts.py`,
`generate.py`, `build_ui.py`, `casting.py`, `export_docs.py`) run on the
standard library alone — no `requests`, no SDK.

The quality gates under `scripts/metrics/` and the last-mile pass are the part
with dependencies:

| package | version in this environment | required for |
|---|---|---|
| numpy | 2.4.3 | every metric, and `lastmile.py` |
| opencv-python | 4.13.0 | colour, sharpness, skin metrics |
| Pillow | 12.1.1 | image I/O and EXIF in `lastmile.py`, `contactsheet.py` |
| insightface | 1.0.1 | face detection, ArcFace identity, age |
| onnxruntime | 1.28.0 | runs the insightface models |
| pytest | 9.0.3 | the metric tests |
| piexif | **not installed** | nothing — EXIF is written through Pillow |

A gate whose dependency is missing must report `NOT_MEASURED`, never `PASS`, and
a frame with a `NOT_MEASURED` required gate does not ship. A gate that switches
itself off silently manufactures a green verdict, which is worse than no gate.

On Windows, run scripts with `py -3` and set `PYTHONIOENCODING=utf-8` first —
or rely on `setup_console()`, which every `main()` calls as its first line for
exactly this reason.
