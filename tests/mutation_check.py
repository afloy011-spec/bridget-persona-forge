#!/usr/bin/env python3
"""Проверка того, что тесты умеют краснеть.

  py -3 tests/mutation_check.py            все мутации
  py -3 tests/mutation_check.py registry   только совпадающие по имени

ЗАЧЕМ ЭТО ОТДЕЛЬНЫЙ ФАЙЛ, А НЕ ЧАСТЬ СЬЮТА. Четыре раунда ревью подряд
находили одно и то же: починка есть, тест на неё есть, тест зелёный — и
остаётся зелёным, если починку убрать. Такой тест не проверяет ничего, он
описывает намерение. Единственный способ отличить один от другого —
сломать код нарочно и посмотреть, заметит ли сьют.

Каждая строка таблицы ниже — это НАЗВАННЫЙ ДЕФЕКТ: точный текст починки,
чем он подменяется, и какой тест обязан на это отреагировать. Прогон правит
файл на диске и возвращает его назад в finally, поэтому в сьют он не входит
(параллельный pytest увидел бы сломанный исходник) и в CI не запускается.

Запускать руками — после каждой новой починки, вместе с новым тестом.

ПОЧЕМУ НА ОДНУ СТРОКУ ТАБЛИЦЫ ПРИХОДИТСЯ ТРИ ПРОГОНА PYTEST. «Ловится»
значит ровно одно: выбранные тесты были ЗЕЛЁНЫМИ, а после внесения дефекта
покраснели. Раунд 6 показал, чем это оборачивается, если проверять только
последний прогон: `-k`, не выбравший ни одного теста, возвращает код 5, и
проверка вида `if r.returncode:` печатала «ловится» там, где не запустился
ни один тест — обычное переименование теста превращало строку в штамп.
Поэтому сначала считаются собранные тесты, потом проверяется зелёный фон, и
только потом вносится дефект.
"""
import io
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Коды возврата pytest, которые ОБЯЗАНЫ читаться по-разному. Доказательством
# служит только RC_FAILED: тесты собрались, запустились и упали. RC_NOTHING —
# это не «дефект пойман», а протухшая строка таблицы: имя теста уехало, и
# проверять дефект больше нечем. Любой другой код (сборка обвалилась на
# импорте, внутренняя ошибка, неверные аргументы) тоже ничего не доказывает:
# сьют не дошёл до проверки поведения.
RC_OK = 0
RC_FAILED = 1
RC_NOTHING = 5

# (дефект, файл, что стояло, чем подменяем, -k для pytest)
MUTATIONS = [
    ("сдача пишет файл до проверки вердикта", "scripts/deliver.py",
     "    if blocked and not force:", "    if False:",
     "refused_delivery_writes_nothing"),
    ("отбор не смотрит на вердикт ворот", "scripts/select_set.py",
     '        if v is not None and not v.get("ships"):', "        if False:",
     "selection_excludes_frames"),
    ("последняя миля пишет поверх исходника", "scripts/lastmile.py",
     "def _same_dir(a, b):",
     "def _same_dir(a, b):\n    return os.path.normcase(a) == os.path.normcase(b)\n"
     "def _dead(a, b):",
     "lastmile_refuses"),
    ("запрет снят в реестровом режиме", "scripts/lastmile.py",
     "    if any(_same_dir(out_dir, d) for d in src_dirs):", "    if False:",
     "registry_mode"),
    ("лист снова растягивает кадры", "scripts/contactsheet.py",
     "            w = min(cw, int(ch * im.width / im.height))\n"
     "            h = min(ch, int(cw * im.height / im.width))\n",
     "            w, h = cw, ch\n",
     "contact_sheet"),
    ("отчёты не сбрасываются между проектами", "scripts/export_docs.py",
     "def export(project_dir, out_dir):\n    _reset_reports()",
     "def export(project_dir, out_dir):",
     "export_docs_reports"),
    ("кастинг игнорирует --dry", "scripts/generate.py",
     '        if "--dry" in args:', '        if False:',
     "casting_dry_run"),
    ("ворота не считают обязательные", "scripts/gates.py",
     "    if not required:", "    if False:",
     "gates_refuse_to_run"),
    ("имя файла сдачи не приводится к латинице", "scripts/deliver.py",
     'slug = re.sub(r"[^a-z0-9]+", "_", str(raw).lower()).strip("_")',
     "slug = str(raw)",
     "delivery_name_cannot_escape"),
    ("вердикт от чужой настройки ворот принимается", "scripts/_util.py",
     "    if why and strict:", "    if False:",
     "verdict_from_another_gate_config"),
    ("настройка ворот проверяется после диска", "scripts/gates.py",
     "    if not required:", "    if False:",
     "before_touching_the_disk"),
    ("отбор не видит частичный вердикт", "scripts/select_set.py",
     "        if gap and not partial_ok:", "        if False:",
     "refuses_to_recommend_from_a_partial"),
    ("отпечаток снова без порогов", "scripts/_util.py",
     '            "thresholds": {k: v for k, v in sorted(g.items())',
     '            "_thresholds_off": {k: v for k, v in sorted(g.items())',
     "fingerprint_covers_thresholds"),
    ("сдача снова падает в середине записи", "scripts/deliver.py",
     "        if not os.path.isfile(src):", "        if False:",
     "all_or_nothing_when_a_source_vanishes"),
    ("--auto снова фантом", "scripts/deliver.py",
     '    if "--auto" in args:', '    if False:',
     "auto_ranks_on_a_number"),
    ("имя проекта убрали из пути отчёта", "scripts/qa_report.py",
     'return os.path.join(ROOT, "docs", project, "qa_report.md")',
     'return os.path.join(ROOT, "docs", "qa_report.md")',
     "outputs_are_namespaced"),
    ("имя проекта убрали из пути документов", "scripts/export_docs.py",
     'return os.path.join(ROOT, "docs", project)',
     'return os.path.join(ROOT, "docs")',
     "outputs_are_namespaced"),
    ("отчёт читает несуществующий ключ разброса", "scripts/qa_report.py",
     '    mn, mean = ident.get("min"), ident.get("mean")',
     '    mn, mean = ident.get("worst"), ident.get("average")',
     "numbers_the_verdict"),
    ("головное число вернули на весь пул", "scripts/qa_report.py",
     '    rows = sel.get("frames", sel) if isinstance(sel, dict) else sel',
     '    rows = [{"cell": r["cell"], "source": r["file"]} for r in read_json('
     'os.path.join(work_dir(project, "frames"), "gates.json"))["frames"] '
     'if r.get("ships")]',
     "headline_is_the_delivered_set"),
    ("сторож пути снова строковый (жёсткая ссылка)", "scripts/_util.py",
     "            return os.path.samefile(a, b)", "            pass",
     "inode_guard_beats_a_hard_link"),
    ("композит тату пишет поверх входа", "scripts/composite_tattoo.py",
     "    if _same_file(out, frame_path):", "    if False:",
     "refuses_to_write_over"),
    ("предпроверка разметки не видит умолчания", "scripts/composite_tattoo.py",
     '        dst = _expand(p["out"]) if p.get("out") else _auto_out(p["frame"], preview)',
     '        dst = _expand(p["out"]) if p.get("out") else os.devnull',
     "check_the_default_destination or writing_to_one_file"),
    ("отчёт калибровки спорит со своим флагом", "scripts/identity_calibration.py",
     '        if sc["separates_under_scene_control"]:', "        if k:",
     "minority_of_cells"),
    ("самотест кожи не считает дыру провалом", "scripts/metrics/skin.py",
     "    dead = [r for r in rows if r[1] != FAIL and r[2] != FAIL]",
     "    dead = []",
     "labour_split_calls_a_hole"),
    ("CI снова зовёт runner вне шага", ".github/workflows/ci.yml",
     "      COMFY_HOST: http://127.0.0.1:9",
     '      COMFY_HOST: http://127.0.0.1:9\n      X: ${{ runner.temp }}',
     "ci_file_uses_only_contexts"),
    # Строка обновлена вслед за починкой: слоты стали параметром (`slots`),
    # потому что у эдит-шаблона их нет вовсе и цепочка строится с нуля.
    ("цепочка лор снова обрезается по слотам", "scripts/generate.py",
     "        if i < len(slots):", "        if True:",
     "chain_grows_past"),
    ("персонажная лора больше не первая", "scripts/generate.py",
     '    stack += list(man["models"]["realism_loras"])',
     '    stack = list(man["models"]["realism_loras"]) + stack',
     "character_lora_goes_first"),
    ("сила света снова по номеру слота", "scripts/generate.py",
     '        if "disposable" in lora["name"].lower():', "        if False:",
     "disposable_camera_follows"),
    ("триггер лоры не подставляется в промпт", "scripts/prompts.py",
     "        _character_trigger(),", '        "",',
     "trigger_word_is_in_the_prompt"),
    ("ключ без значения снова падает трейсбеком", "scripts/generate.py",
     '        if i >= len(args) or args[i].startswith("--"):',
     "        if False:",
     "opt_rejects_a_key"),
    ("надпись снова выходит вверх ногами", "scripts/tattoo_from_photo.py",
     "        up, top, bot = is_upright(a)",
     "        up = True",
     "long_ascenders_do_not_flip"),
    ("соринка снова уводит ось выпрямления", "scripts/tattoo_from_photo.py",
     "            res = (deskew_angle(a > 0.02) + 90.0) % 180.0 - 90.0",
     "            res = 0.0",
     "speck_across_the_frame"),
    # ЭКВИВАЛЕНТНОГО МУТАНТА ЗДЕСЬ НЕТ НАМЕРЕННО. Приведение остатка угла к
    # (-90, 90] в tattoo_from_photo.build выглядит проверяемым, но им не
    # является: поворот на θ+180 оставляет строку такой же горизонтальной,
    # просто перевёрнутой, а следующий же шаг — определение направления по
    # выносным элементам — переворачивает её обратно. Ассет получается
    # побайтово тот же, отличается только НАПЕЧАТАННЫЙ угол. Мутация,
    # которую не может поймать ни один тест, потому что она ничего не меняет,
    # в списке не нужна: она превратила бы отчёт в вечную «слепоту».
    ("потолок размытия снова по ширине вклейки", "scripts/composite_tattoo.py",
     "               max(0.4, 0.35 * _stroke_px(ta[..., 3])))",
     "               0.018 * tw)",
     "thin_lettering_survives"),
    # РОДИНКИ В ЭТОМ СПИСКЕ БОЛЬШЕ НЕТ. Признак снят с карточки 14.08.2026, а
    # вместе с ним удалены composite_mole.py, metrics/mark.py и их тесты. Два
    # дефекта — «место берётся с умолчанием» и «незамеренная щека считается
    # браком» — ушли туда же: мутация в удалённом файле не дефект, а мусор,
    # который отчёт показывал бы вечной слепотой.
    ("направление надписи снова по центру тяжести чернила",
     "scripts/tattoo_from_photo.py",
     "    top, bot = _edge_scatter(a)\n    return bot <= top, top, bot",
     "    rows = a.sum(1)\n"
     "    up = (rows * np.arange(len(rows))).sum() / max(rows.sum(), 1e-9) \\\n"
     "        >= (len(rows) - 1) / 2.0\n"
     "    return up, 0.0, 0.0",
     "long_ascenders_do_not_flip"),
    ("разброс края снова меряется медианным отклонением",
     "scripts/tattoo_from_photo.py",
     "    spread = lambda v: float(np.quantile(v, 0.9)   # noqa: E731\n"
     "                             - np.quantile(v, 0.1))",
     "    spread = lambda v: float(np.median(np.abs(v - np.median(v))))  "
     "# noqa: E731",
     "long_ascenders_do_not_flip"),
    ("приёмник разметки снова может лечь в папку входа",
     "scripts/metrics/wrist.py",
     "        if os.path.normcase(os.path.abspath(out_dir)) == "
     "os.path.normcase(d):",
     "        if out_dir == d:",
     "generated_placements_never_land"),
    ("сторона запястья решается по всему предплечью, а не у кисти",
     "scripts/metrics/wrist.py",
     "    band = (d >= 0) & (d <= NEAR_W * width)",
     "    band = np.ones(d.shape, bool)",
     "side_is_decided_in_the_band_next_to_the_hand"),
    ("поворот надписи снова считается в сторону кисти, а не локтя",
     "scripts/metrics/wrist.py",
     '    out["rot"] = float(-np.degrees(np.arctan2(-ax[1], -ax[0])))',
     '    out["rot"] = float(-np.degrees(np.arctan2(ax[1], ax[0])))',
     "lettering_runs_from_the_wrist_towards_the_elbow"),
    ("чужая сторона руки снова годится под вклейку",
     "scripts/metrics/wrist.py",
     "    if want < BACK_MIN:",
     "    if False:",
     "the_palm_side_never_gets_the_tattoo"),
    ("нужная сторона подменена на «всегда тыльную»",
     "scripts/metrics/wrist.py",
     '    want = g["back_frac"] if surface == "back" else 1.0 - g["back_frac"]',
     '    want = g["back_frac"]',
     "the_wanted_surface_is_the_one_the_card_asks_for"),
    ("занятое запястье снова не отменяет вклейку",
     "scripts/metrics/wrist.py",
     "        if hit > OCCLUDE_MAX:",
     "        if False:",
     "an_object_on_the_wrist_cancels_the_composite"),
    ("нечитаемо мелкая надпись снова вклеивается",
     "scripts/metrics/wrist.py",
     '    if res["size"] * W < need:',
     "    if False:",
     "lettering_too_small_to_read"),
    ("кисть снова берётся самая крупная, а не ближайшая к предплечью",
     "scripts/metrics/wrist.py",
     "        d_j = float(dist[hlab == j].min())",
     "        d_j = -float(hst[j, cv2.CC_STAT_AREA])",
     "the_hand_must_belong_to_this_forearm"),
    ("кисть чужой руки снова сходит за свою",
     "scripts/metrics/wrist.py",
     "    if bd > HAND_GAP_W * width:",
     "    if False:",
     "the_hand_must_belong_to_this_forearm"),
    ("размер надписи снова считается по ширине руки",
     "scripts/metrics/wrist.py",
     "    size_px = LEN_OVER_IPD * ipd",
     '    size_px = LEN_OVER_W * g["arm_width_px"] * k',
     "the_scale_comes_from_the_face_not_from_the_arm"),
    ("перенос лица снова переписывает весь кадр, а не лицо",
     "scripts/face_transfer.py",
     "    return keep_outside(src, files[0],\n"
     "                        os.path.splitext(files[0])[0] + \"_face.png\")",
     "    return files[0]",
     "transfer_returns_the_glued_frame"),
    ("склейка возвращает исходник вместо перенесённого лица",
     "scripts/face_transfer.py",
     "    imwrite(out, np.clip(a * (1.0 - mm) + b * mm, 0, 255).astype(np.uint8))",
     "    imwrite(out, a.astype(np.uint8))",
     "the_face_itself_does_change"),
    ("стек лор снова цепочкой, а не коробкой", "scripts/generate.py",
     "    graph = _apply_lorabox(cc.load_template(TEMPLATE), loras)",
     "    graph = _apply_loras(cc.load_template(TEMPLATE), loras)",
     "stack_grows_with_the_character_lora"),
    ("CLIP идёт мимо коробки — лоры молча не действуют на текст",
     "scripts/generate.py",
     '    graph["4"]["inputs"]["clip"] = [LORABOX_NODE, 1]',
     '    graph["4"]["inputs"]["clip"] = ["2", 0]',
     "clip_goes_through_the_box_not_around_it"),
    ("апскейл выпал из доводки", "scripts/produce.py",
     "            if upscale_frames:", "            if False:",
     "upscale_is_part_of_the_pipeline"),
    ("проход фактуры снова стал умолчанием", "scripts/produce.py",
     "           graft_skin=False, upscale_frames=True, refine_frames=False):",
     "           graft_skin=False, upscale_frames=True, refine_frames=True):",
     "texture_pass_is_opt_in_not_default"),
    ("перенос лица вернулся в доводку безусловно", "scripts/produce.py",
     "            if face_ref:", "            if True:",
     "the_face_swap_is_not_part_of_finishing"),
    ("цепочка компенсаций вернулась", "scripts/produce.py",
     "                src = dfc.detail(src, tmp, prompt=it.get(\"prompt\", \"\"))",
     "                src = rf.refine(src, tmp)",
     "the_compensation_chain_is_gone"),
    ("лицо снова тонет в холсте детейлера", "scripts/detail_face.py",
     "SIZE = 1024", "SIZE = 512",
     "the_detailer_gives_the_face_its_own_canvas"),
    ("вклейка кропа без растушёвки", "scripts/detail_face.py",
     "FEATHER = 0.10", "FEATHER = 0.0",
     "the_paste_is_feathered"),
    ("детейлер пишет поверх своего исходника", "scripts/detail_face.py",
     '"_det.png")', '"")',
     "the_detailer_does_not_write_over_its_own_input"),
    ("возврат фактуры двигает низкие частоты", "scripts/refine.py",
     "    detail = R - cv2.GaussianBlur(R, (k, k), sigma)",
     "    detail = R - S",
     "texture_back_moves_detail_and_leaves_structure"),
    ("добавка стенда пришита к слоту шаблона, а не к концу цепочки",
     "scripts/lab_grid.py",
     '    last = graph["7"]["inputs"]["model"][0]',
     "    last = G.LORA_NODES[-1]",
     "the_stack_of_a_look_reaches_the_sampler"),
    ("прививка кожи снова включена по умолчанию", "scripts/produce.py",
     "           graft_skin=False, upscale_frames=True, refine_frames=True):",
     "           graft_skin=True, upscale_frames=True, refine_frames=True):",
     "graft_is_off_by_default"),
    ("надпись снова ложится на рукав",
     "scripts/metrics/wrist.py",
     "    if cloth is not None and cloth > CLOTH_MAX:",
     "    if False:",
     "a_sleeve_is_not_a_wrist"),
    ("квоты выбраковки снова складываются по осям",
     "scripts/produce.py",
     "            prev = rank.get(id(it))\n"
     "            if prev is None or q > prev[0]:\n"
     "                rank[id(it)] = (q, key, name, v)",
     "            cutv = vals[int(len(vals) * 0.8)]\n"
     "            if v > cutv and it[\"verdict\"] == \"ok\":\n"
     "                it[\"verdict\"] = \"reject\"\n"
     "                it[\"reason\"] = f\"{name} {v:.3f}\"",
     "one_quota_not_three"),
    ("починимое сходство снова режется относительной планкой",
     "scripts/produce.py",
     "        if repaired:",
     "        if False:",
     "a_repairable_face_is_not_thrown_away"),
    ("квадратный кусок предплечья снова сходит за руку",
     "scripts/metrics/wrist.py",
     '    if out["elongation"] < MIN_ELONGATION:',
     "    if False:",
     "a_blob_with_no_axis_is_refused"),
    ("расхождение масштабов снова не отменяет вклейку",
     "scripts/metrics/wrist.py",
     "    if not (IPD_VS_ARM[0] <= ratio <= IPD_VS_ARM[1]):",
     "    if False:",
     "a_face_and_an_arm_at_odds_cancel"),
    ("длина и ширина куска снова по крайним точкам",
     "scripts/metrics/wrist.py",
     "    span = lambda u: float(np.quantile(u, 1 - q)   # noqa: E731\n"
     "                           - np.quantile(u, q)) / 2.0",
     "    span = lambda u: float(np.ptp(u)) / 2.0  # noqa: E731",
     "geometry_follows_the_measured_reference_proportions"),
    ("главное лицо снова выбирается по площади бокса",
     "scripts/metrics/faces.py",
     "    return max(found, key=lambda f: (inter_pupillary_distance(f.kps),\n"
     "                                     float(f.det_score)))",
     "    return max(found, key=lambda f: (f.bbox[2] - f.bbox[0]) * "
     "(f.bbox[3] - f.bbox[1]))",
     "stretched_blurry_box"),
    ("старт задания снова не включает очередь карты", "scripts/lora_train.py",
     '        if cmd == "start":\n            qcode, qdata = start_queue(gpu)',
     '        if False:\n            qcode, qdata = start_queue(gpu)',
     "turns_on_the_gpu_queue"),
    ("очередь адресуется id строки, а не номером карты",
     "scripts/lora_train.py",
     '    return api(f"/api/queue/{gpu_ids}/start")',
     '    return api("/api/queue/1/start")',
     "addressed_by_gpu_not_by_row_id"),
]


def _pytest(k, *extra):
    """Прогон сьюта по фильтру -k — так же, как его зовут руками и в CI."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *extra, "-k", k],
        cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace")


def _selected(k):
    """(код возврата, сколько тестов выбрал `-k k`) — до всякой мутации.

    `-o addopts=` гасит addopts из pytest.ini: там уже стоит -q, и второй -q
    складывается с ним в -qq, а на этом уровне сборка печатает не имена
    тестов, а «файл: 3» — считать было бы нечего. -p no:cacheprovider тогда
    приходится вернуть руками, иначе прогон заведёт .pytest_cache в
    рабочей копии, которого репозиторий избегает.
    """
    r = _pytest(k, "-o", "addopts=", "-p", "no:cacheprovider", "--collect-only")
    return r.returncode, sum(1 for ln in r.stdout.splitlines() if "::" in ln)


def run(mut, pattern=None):
    name, rel, old, new, k = mut
    if pattern and pattern not in name and pattern not in k:
        return None
    path = os.path.join(ROOT, rel)
    orig = io.open(path, encoding="utf-8").read()
    if old not in orig:
        print(f"  ПРОПУСК  {name}\n           фрагмент не найден в {rel} — "
              f"починку переписали, а строку мутации не обновили")
        return False

    # Два прогона ДО мутации. Первый ловит уехавшее имя теста: `-k`, не
    # выбравший ничего, отдаёт RC_NOTHING, и раньше это засчитывалось за
    # «ловится». Второй ловит фон: если выбранные тесты красные и без
    # дефекта, красный под мутацией не значит ничего.
    rc, n = _selected(k)
    if rc == RC_NOTHING or not n:
        print(f"  ОШИБКА   {name}\n           `-k {k}` не выбрал ни одного теста — "
              f"тест переименован или удалён, строка таблицы ничего не проверяет")
        return False
    if rc != RC_OK:
        print(f"  ОШИБКА   {name}\n           сборка тестов по `-k {k}` падает "
              f"(код {rc}) — мутацию проверять нечем, сначала чинить сьют")
        return False
    r = _pytest(k)
    if r.returncode != RC_OK:
        print(f"  ОШИБКА   {name}\n           `pytest -k {k}` красный (код "
              f"{r.returncode}) ещё ДО мутации, тестов: {n} — под мутацией он "
              f"покраснеет по той же причине, а не из-за дефекта")
        return False

    try:
        io.open(path, "w", encoding="utf-8").write(orig.replace(old, new, 1))
        r = _pytest(k)
    finally:
        io.open(path, "w", encoding="utf-8").write(orig)
    # Число выбранных тестов печатается в каждом исходе: `-k` из одной буквы
    # цепляет половину набора и выглядит как проверка ровно одной починки.
    if r.returncode == RC_FAILED:
        print(f"  ловится  {name} (тестов: {n})")
        return True
    if r.returncode == RC_OK:
        print(f"  СЛЕПОТА  {name}\n           дефект внесён, `pytest -k {k}` зелёный "
              f"(тестов: {n}) — тест описывает намерение, а не поведение")
        return False
    print(f"  ОШИБКА   {name}\n           `pytest -k {k}` вернул код {r.returncode} "
          f"вместо {RC_FAILED} (тестов: {n}) — сьют не дошёл до проверки поведения, "
          f"дефект не доказан")
    return False


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else None
    print(f"мутаций в таблице: {len(MUTATIONS)}"
          + (f", фильтр «{pattern}»" if pattern else ""))
    res = [x for x in (run(m, pattern) for m in MUTATIONS) if x is not None]
    bad = res.count(False)
    print(f"\n{len(res) - bad} из {len(res)} дефектов ловятся сьютом")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
