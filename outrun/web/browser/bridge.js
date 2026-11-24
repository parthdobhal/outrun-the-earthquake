// Web version only (added by scripts/build_web.py). Replaces the Flask server:
// the same /api/... requests app.js makes are answered by the project's Python
// code running inside the browser, in Web Workers, using Pyodide.
(() => {
  function makeWorker() {
    const worker = new Worker("static/worker.js");
    const pending = new Map();
    let next = 0;
    worker.onmessage = (e) => {
      const p = pending.get(e.data.id);
      if (!p) return;
      pending.delete(e.data.id);
      if (e.data.error === undefined) p.resolve(e.data.data); else p.reject(new Error(e.data.error));
    };
    worker.onerror = (e) => {
      for (const p of pending.values()) p.reject(new Error(e.message || "worker failed"));
      pending.clear();
    };
    return (op, data) => new Promise((resolve, reject) => {
      const id = next++;
      pending.set(id, { resolve, reject });
      worker.postMessage({ id, op, data });
    });
  }

  const main = makeWorker();
  let falseAlarms = null;  // null = not started yet

  function startFalseAlarms() {
    if (falseAlarms) return;
    falseAlarms = { status: "measuring", hours: 6 };
    // A second worker, so measuring hours of noise never delays a quake run.
    makeWorker()("false", {})
      .then((r) => { falseAlarms = r; })
      .catch((err) => { falseAlarms = { status: "error", error: err.message }; });
  }

  window.OutrunPy = {
    async call(path, body) {
      const url = new URL(path, "http://local/");
      switch (url.pathname) {
        case "/api/world": {
          const world = await main("world", { seed: Number(url.searchParams.get("seed") ?? 7) });
          startFalseAlarms();
          return world;
        }
        case "/api/run": return main("run", body);
        case "/api/hidden-test": return main("hidden", body);
        case "/api/false-alarms": startFalseAlarms(); return falseAlarms;
        default: throw new Error("unknown request " + path);
      }
    },
  };
})();
