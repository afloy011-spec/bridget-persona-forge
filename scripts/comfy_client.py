#!/usr/bin/env python3
"""Клиент ComfyUI для persona-forge. Политика: сервер не мусорим.

CLI:
  py -3 comfy_client.py status
  py -3 comfy_client.py run <api_graph.json> --out <dir> [--set 7.seed=101 ...]
  py -3 comfy_client.py upload <file> [--subfolder persona-forge]
  py -3 comfy_client.py uploads            # что мы залили на сервер (реестр)

Как модуль:
  from comfy_client import run_graph, upload, manifest
  files = run_graph(graph, out_dir, sets={"7.seed": 101})

--set принимает точечные пути в API-граф: "97.inputs.text=..." или короткое
"97.text=...". Значение парсится как JSON, иначе остаётся строкой.
"@file.txt" читает значение из UTF-8 файла.

ПОЛИТИКА ЭФЕМЕРНОСТИ. Прогоны по умолчанию не пишут в output/ сервера:
SaveImage подменяется на PreviewImage, кадр падает в temp/ и забирается по
/view. Причина — машина общая, а удалить из output/ по API нечем: /userdata
работает только внутри user/, /internal/files умеет лишь листинг, ноды
удаления нет. Единственный надёжный способ не мусорить — не писать туда.
Проверено на живой машине после ~250 генераций: output/persona-forge не
появился ни разу.

TEMP/ САМ НЕ ЧИСТИТСЯ. Он очищается только при рестарте ComfyUI, а сервер
живёт неделями между рестартами — на проверке там накопилось 4.8 ГБ с
конца июля. Свой прогон надо убирать за собой руками: по API этого нет, но по
SSH есть (см. docs/environment.md). Отличить свои файлы от чужих можно только
по времени изменения — имя ComfyUI_temp_xxxxx владельца не несёт.

ЧТО ПИСАТЬ НА СЕРВЕР ВСЁ-ТАКИ НАДО. Банк лиц ReActor
(ReActorSaveFaceModel → models/reactor/faces/*.safetensors) обязан пережить
прогон, иначе ReActorLoadFaceModel не увидит якорь. Это ~2 МБ на персонажа и
единственное исключение — ephemeral() его намеренно не трогает.

Залитые входные картинки (/upload/image) попадают в input/<subfolder>/ и там
остаются. Каждая заливка пишется в локальный реестр .uploads.json, чтобы список
залитого был известен; автоматической уборки пока НЕТ — из input/<subfolder>/
удаляется руками (`py -3 comfy_client.py uploads` печатает список).
"""
import json, sys, time, uuid, os, urllib.request, urllib.parse, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import cli_opt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MANIFEST = None


def manifest():
    """assets.json — единственное место правды про сервер и модели."""
    global _MANIFEST
    if _MANIFEST is None:
        with open(os.path.join(ROOT, "assets.json"), encoding="utf-8") as fh:
            _MANIFEST = json.load(fh)
    return _MANIFEST


def _default_host():
    """Адрес воркера: COMFY_HOST → assets.local.json → внятная ошибка.

    В ОТСЛЕЖИВАЕМОМ МАНИФЕСТЕ АДРЕСА НЕТ, и это не педантизм. Раньше в
    assets.json лежал адрес рабочей машины вместе с картой её сервисов
    — в репозитории, который задуман публичным портфолио. При этом соседний
    комментарий уверял, что «адресов в коде нет намеренно»: утверждение и файл
    противоречили друг другу.

    assets.local.json не отслеживается (см. .gitignore) и хранит настройки
    конкретной машины. Формат: {"host": "http://…:8188"}.
    """
    env = os.environ.get("COMFY_HOST")
    if env:
        return env.rstrip("/")
    local = os.path.join(ROOT, "assets.local.json")
    if os.path.exists(local):
        try:
            with open(local, encoding="utf-8") as fh:
                h = json.load(fh).get("host")
            if h:
                return h.rstrip("/")
        except Exception as e:
            print(f"assets.local.json не разобран ({e})", file=sys.stderr)
    h = manifest().get("host_default")
    if h:
        return h.rstrip("/")
    raise SystemExit(
        "адрес ComfyUI не задан. Любое из двух:\n"
        "  set COMFY_HOST=http://<хост>:8188\n"
        '  echo {"host": "http://<хост>:8188"} > assets.local.json\n'
        "См. .env.example и docs/environment.md.")


class _LazyHost(str):
    """Адрес воркера резолвится при ПЕРВОМ обращении, а не при импорте.

    Раньше стояло HOST = _default_host() на уровне модуля, и с тех пор как
    _default_host стал падать при незаданном адресе, любой импорт
    comfy_client убивал скрипт — в том числе `generate.py --dry`, который
    задокументирован как «план без GPU» и к серверу не обращается вовсе.
    Чужой человек получал SystemExit на команде, которую README предлагает
    выполнить первой.
    """
    _resolved = None

    def _v(self):
        if _LazyHost._resolved is None:
            _LazyHost._resolved = _default_host()
        return _LazyHost._resolved

    def __str__(self):
        return self._v()

    def __repr__(self):
        return repr(self._v())

    def __add__(self, other):
        return self._v() + other

    def __eq__(self, other):
        return self._v() == other

    def __hash__(self):
        return hash(self._v())


HOST = _LazyHost()
CLIENT_ID = str(uuid.uuid4())
UPLOAD_LEDGER = os.path.join(ROOT, ".uploads.json")


def _req(path, data=None, method=None, timeout=60):
    url = HOST + path
    if data is not None and not isinstance(data, bytes):
        data = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    try:
        return json.loads(body)
    except Exception:
        return body


# ---------------------------------------------------------------- граф

def apply_sets(graph, sets):
    """sets — либо список строк "7.seed=101", либо dict {"7.seed": 101}."""
    items = sets.items() if isinstance(sets, dict) else (
        (s.partition("=")[0], s.partition("=")[2]) for s in sets)
    for path, raw in items:
        parts = str(path).split(".")
        if len(parts) == 2:                      # 7.seed → 7.inputs.seed
            parts = [parts[0], "inputs", parts[1]]
        val = raw
        if isinstance(raw, str):
            if raw.startswith("@"):
                val = open(raw[1:], encoding="utf-8").read()
            else:
                try:
                    val = json.loads(raw)
                except Exception:
                    val = raw
        node = graph
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = val
    return graph


SAVE_CLASSES = ("SaveImage", "Image Save", "SaveAnimatedPNG", "SaveAnimatedWEBP")


def ephemeral(graph):
    """SaveImage → PreviewImage. Возвращает {node_id: базовое имя}.

    Имена нужны, потому что temp-файлы приходят как ComfyUI_temp_xxxxx, а
    батчи различают кадры по осмысленному префиксу. ReActorSaveFaceModel
    сознательно не трогаем — банк лиц обязан жить на сервере.
    """
    names = {}
    for nid, node in graph.items():
        if node.get("class_type") not in SAVE_CLASSES:
            continue
        pref = node.get("inputs", {}).get("filename_prefix") or f"node{nid}"
        names[nid] = os.path.basename(pref)
        node["class_type"] = "PreviewImage"
        node["inputs"] = {"images": node["inputs"]["images"]}
    return names


def submit(graph):
    try:
        res = _req("/prompt", {"prompt": graph, "client_id": CLIENT_ID})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"ВАЛИДАЦИЯ НЕ ПРОШЛА ({e.code}) — в очередь ничего не встало:",
              file=sys.stderr)
        try:
            print(json.dumps(json.loads(body), indent=2, ensure_ascii=False),
                  file=sys.stderr)
        except Exception:
            print(body[:4000], file=sys.stderr)
        raise SystemExit(2)
    # ComfyUI отвечает 200 даже когда часть графа отбракована: невалидная нода
    # молча выбрасывается вместе с зависимыми выходами, а прогон рапортует
    # success. Без этой проверки пропажа половины результата выглядит загадкой.
    for nid, info in (res.get("node_errors") or {}).items():
        for err in info.get("errors", []):
            print(f"ВНИМАНИЕ: нода {nid} ({info.get('class_type')}) отбракована"
                  f" — {err.get('message')}: {err.get('details')}",
                  file=sys.stderr)
        dep = info.get("dependent_outputs") or []
        if dep:
            print(f"  → НЕ будут исполнены выходы: {', '.join(map(str, dep))}",
                  file=sys.stderr)
    return res["prompt_id"]


def wait(prompt_id, timeout=1800, poll=4.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = _req(f"/history/{prompt_id}")
        if prompt_id in h:
            item = h[prompt_id]
            st = item.get("status", {})
            if st.get("completed") or st.get("status_str") in ("success", "error"):
                return item
        time.sleep(poll)
    raise TimeoutError(f"prompt {prompt_id} не завершился за {timeout} с")


def fetch(item, out_dir, names=None):
    os.makedirs(out_dir, exist_ok=True)
    saved = []
    for node_id, out in (item.get("outputs") or {}).items():
        for key in ("images", "gifs"):
            for i, f in enumerate(out.get(key, []) or []):
                if f.get("type") not in ("output", "temp"):
                    continue
                q = urllib.parse.urlencode({
                    "filename": f["filename"],
                    "subfolder": f.get("subfolder", ""),
                    "type": f["type"]})
                data = _req(f"/view?{q}", timeout=600)
                name = f["filename"]
                if names and node_id in names:
                    name = "%s_%02d%s" % (names[node_id], i + 1,
                                          os.path.splitext(name)[1])
                dest = os.path.join(out_dir, name)
                with open(dest, "wb") as fh:
                    fh.write(data if isinstance(data, bytes)
                             else json.dumps(data).encode())
                saved.append(dest)
    return saved


def run_graph(graph, out_dir, sets=None, timeout=1800, keep_on_server=False):
    """Полный цикл: подстановка → эфемерность → очередь → ожидание → забор."""
    if sets:
        apply_sets(graph, sets)
    names = None if keep_on_server else ephemeral(graph)
    pid = submit(graph)
    item = wait(pid, timeout=timeout)
    if item.get("status", {}).get("status_str") == "error":
        msgs = [m for m in item.get("status", {}).get("messages", [])
                if m[0] == "execution_error"]
        print("ОШИБКА ИСПОЛНЕНИЯ:", json.dumps(msgs, indent=2,
              ensure_ascii=False)[:3000], file=sys.stderr)
        raise RuntimeError("граф упал на исполнении")
    return fetch(item, out_dir, names)


def load_template(name):
    """Шаблон графа из templates/comfy/ по имени без расширения.

    Ключи, начинающиеся с '_', выбрасываются: в шаблонах живут комментарии
    (и на верхнем уровне, и внутри узлов), а ComfyUI на них давится. Раньше
    первый же комментарий ронял ephemeral() с 'str' object has no attribute
    'get' — обход графа наткнулся на строку там, где ждал узел.
    """
    p = os.path.join(ROOT, "templates", "comfy", name)
    if not p.endswith(".json"):
        p += ".json"
    with open(p, encoding="utf-8") as fh:
        graph = json.load(fh)
    return {nid: {k: v for k, v in node.items() if not k.startswith("_")}
            for nid, node in graph.items() if not nid.startswith("_")}


# ---------------------------------------------------------------- сервер

_alive = None


def preflight(timeout=75):
    """Жив ли воркер — тривиальным графом без GPU.

    Без этой проверки каждая ячейка честно ждёт свой таймаут на уже мёртвом
    воркере. Зависший prompt worker лечится только рестартом ComfyUI на самой
    машине: /interrupt, /free и очистка очереди отвечают ok и не помогают.
    """
    global _alive
    if _alive is not None:
        return _alive
    g = {"1": {"class_type": "EmptyImage",
               "inputs": {"width": 64, "height": 64, "batch_size": 1,
                          "color": 0}},
         "2": {"class_type": "PreviewImage", "inputs": {"images": ["1", 0]}}}
    try:
        wait(submit(g), timeout=timeout, poll=3.0)
        _alive = True
    except (Exception, SystemExit):
        # SystemExit не наследник Exception: submit() бросает именно его на
        # провале валидации, и без этой ветки preflight умирал молча, не
        # напечатав подсказку про рестарт — ровно в том случае, ради которого
        # он и написан.
        _alive = False
    if not _alive:
        print("ВОРКЕР НЕ ИСПОЛНЯЕТ ЗАДАЧИ (тривиальный граф не прошёл).\n"
              "Лечится рестартом ComfyUI на самой машине: "
              "API этого не умеет.", file=sys.stderr)
    return _alive


def object_info(cls=None):
    return _req(f"/object_info/{cls}" if cls else "/object_info", timeout=120)


def _ledger_add(entry):
    """Реестр заливок — чтобы было известно, что за собой убирать руками."""
    try:
        data = json.load(open(UPLOAD_LEDGER, encoding="utf-8"))
    except Exception:
        data = []
    if entry not in data:
        data.append(entry)
    with open(UPLOAD_LEDGER, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def upload(path, subfolder=None):
    """Залить картинку в input/<subfolder>/ сервера и записать в реестр."""
    import mimetypes
    subfolder = subfolder or manifest().get("remote_subfolder", "persona-forge")
    boundary = uuid.uuid4().hex
    name = os.path.basename(path)
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"

    def part(k, v):
        return (f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="{k}"\r\n\r\n{v}\r\n').encode()

    body = part("subfolder", subfolder) + part("overwrite", "true")
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\";"
             f" filename=\"{name}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
    body += open(path, "rb").read() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(HOST + "/upload/image", data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=600) as r:
        res = json.loads(r.read())
    ref = f"{subfolder}/{res.get('name', name)}"
    _ledger_add(ref)
    return ref


def save_workflow(path, remote=None, folder=None):
    """Положить UI-воркфлоу в браузер воркфлоу СЕРВЕРА, а не только на диск.

    ЗАЧЕМ. Сборщики холстов писали файл в templates/comfy/ репозитория — и
    только туда. На сервере его не было, в списке Workflows он не появлялся, и
    человек, которому сказали «открой холст», не находил ничего. Ошибка не в
    сборщике: недоставало последнего шага, и делался он руками.

    ПИШЕТСЯ ПО HTTP, А НЕ КОПИРОВАНИЕМ ФАЙЛА. Путь к папке воркфлоу зависит от
    того, как поставлен ComfyUI, и зашивать его сюда значило бы привязать
    репозиторий к одной машине. У сервера для этого есть /api/userdata, и он
    знает свои пути сам.
    """
    folder = folder or manifest().get("remote_subfolder", "persona-forge")
    remote = remote or os.path.basename(path)
    key = urllib.parse.quote("workflows/%s/%s" % (folder, remote), safe="")
    body = open(path, "rb").read()
    req = urllib.request.Request(HOST + "/api/userdata/" + key, data=body,
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        if r.status not in (200, 201):
            raise RuntimeError("сервер ответил %s на запись воркфлоу" % r.status)
    return "%s/%s" % (folder, remote)


def main():
    # Единственный main без этого вызова: на русской Windows консоль cp1251,
    # и печать собственного __doc__ падала с UnicodeEncodeError на символе '→'.
    from _util import setup_console
    setup_console()
    args = sys.argv[1:]
    if not args:
        print(__doc__); raise SystemExit(1)
    cmd = args[0]

    def opt(k, d=None):
        return cli_opt(args, k, d)

    sets = [args[i + 1] for i, a in enumerate(args) if a == "--set"]

    if cmd == "status":
        q = _req("/queue")
        print(f"host: {HOST}")
        print("running:", len(q.get("queue_running", [])),
              "pending:", len(q.get("queue_pending", [])))
        print("worker alive:", preflight())
    elif cmd == "upload":
        print(upload(args[1], opt("--subfolder")))
    elif cmd == "uploads":
        try:
            print("\n".join(json.load(open(UPLOAD_LEDGER, encoding="utf-8"))))
        except Exception:
            print("(реестр пуст)")
    elif cmd == "run":
        graph = json.load(open(args[1], encoding="utf-8"))
        for p in run_graph(graph, opt("--out", "."), sets,
                           timeout=int(opt("--timeout", "1800")),
                           keep_on_server="--keep-on-server" in args):
            print("saved:", p)
    else:
        print(__doc__); raise SystemExit(1)


if __name__ == "__main__":
    main()
