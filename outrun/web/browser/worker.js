// Web version only (copied by scripts/build_web.py). Runs the project's own
// Python package (outrun/) inside the browser with Pyodide. Nothing here
// computes results: every number comes from the same Python functions the
// Flask server calls (outrun/web/api.py).
//
// build_web.py replaces the next line: "local" when Pyodide's files are hosted
// next to this file, or a CDN address such as
// "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/".
const PYODIDE_BASE = "local";

// Some hosts (for example claude.ai artifacts) cannot serve .zip/.whl files,
// so in "local" mode Python's standard library and the numpy wheel are stored
// as base64 text. This wrapper turns a request for the original file into the
// decoded original bytes, unchanged (numpy is still checked against its
// SHA-256 from pyodide-lock.json, below).
const realFetch = self.fetch.bind(self);
self.fetch = async (input, init) => {
  const url = input instanceof Request ? input.url : String(input);
  if (PYODIDE_BASE === "local" && /(python_stdlib\.zip|\.whl)$/.test(url)) {
    const res = await realFetch(url + ".b64.txt");
    if (!res.ok) return res;
    const text = (await res.text()).trim();
    const raw = atob(text);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    // Pyodide passes the expected hash (from pyodide-lock.json) as
    // "sha256-<base64>"; check the decoded bytes against it ourselves.
    const want = init && init.integrity;
    if (want) {
      const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
      const got = "sha256-" + btoa(String.fromCharCode(...digest));
      if (got !== want) throw new Error("integrity check failed for " + url);
    }
    return new Response(bytes, { status: 200, headers: { "Content-Type": "application/octet-stream" } });
  }
  return realFetch(input, init);
};

const PYODIDE_URL = PYODIDE_BASE === "local" ? new URL("pyodide/", self.location.href).href : PYODIDE_BASE;
importScripts(PYODIDE_URL + "pyodide.js");

const BRIDGE = `
import json, math
from outrun.web import api

def _clean(x):
    # JSON has no NaN/Infinity; send them as null, as the browser expects.
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x

def call(op, data_json):
    data = json.loads(data_json)
    try:
        if op == "world":
            seed = int(data.get("seed", 7))
            if not 0 <= seed <= api.MAX_SEED:
                raise ValueError(f"seed must be between 0 and {api.MAX_SEED}")
            result = api.world_payload(seed)
        elif op == "run":
            result = api.run_payload(data)
        elif op == "hidden":
            result = api.hidden_test_payload(data)
        elif op == "false":
            cache = api.FalseAlarmCache()
            cache._work()          # same measurement the server runs in a thread
            result = cache.payload()
        else:
            raise ValueError("unknown request " + op)
        return json.dumps({"ok": True, "data": _clean(result)})
    except (ValueError, TypeError, KeyError) as err:
        return json.dumps({"ok": False, "error": str(err)})
`;

let ready = null;

async function start() {
  const base = new URL("./", self.location.href).href;
  const py = await loadPyodide({ indexURL: PYODIDE_URL });
  await py.loadPackage("numpy");
  const files = await (await fetch(base + "outrun-python.json")).json();
  for (const [path, text] of Object.entries(files)) {
    const full = "/home/pyodide/app/" + path;
    py.FS.mkdirTree(full.slice(0, full.lastIndexOf("/")));
    py.FS.writeFile(full, text);
  }
  py.runPython("import sys; sys.path.insert(0, '/home/pyodide/app')");
  py.runPython(BRIDGE);
  return py.globals.get("call");
}

self.onmessage = async (event) => {
  const { id, op, data } = event.data;
  try {
    if (!ready) ready = start();
    const call = await ready;
    const out = JSON.parse(call(op, JSON.stringify(data || {})));
    self.postMessage(out.ok ? { id, data: out.data } : { id, error: out.error });
  } catch (err) {
    self.postMessage({ id, error: String(err && err.message || err) });
  }
};
