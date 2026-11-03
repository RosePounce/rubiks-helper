// Démarrage du build GitHub Pages.
//
// Pages ne sert que des fichiers statiques : il n'y a pas de serveur Python.
// On charge donc Pyodide (CPython compilé en WebAssembly), numpy, puis le
// paquet `rubik_helper` (zippé à côté), et on expose `window.RHAPI` qui imite
// l'API HTTP attendue par app.js. app.js n'est importé qu'une fois le pont
// prêt, pour que son premier appel réseau passe déjà par Pyodide.
//
// La version de Pyodide doit correspondre à celle du script chargé dans la
// page (voir index.html). Pour changer de version, modifier les deux endroits.
const PYODIDE_VERSION = "0.26.4";
const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

function setStatus(text) {
  const el = document.getElementById("status");
  if (el) el.textContent = text;
}

function makeApi(pyodide, wg) {
  // webglue renvoie une chaîne JSON { ok, data } ou { ok:false, error, ... }.
  function unwrap(jsonStr) {
    const r = JSON.parse(jsonStr);
    if (!r.ok) {
      const err = new Error(r.error || `Erreur ${r.status || ""}`.trim());
      err.stickers = r.stickers || [];
      err.repairs = r.repairs || [];
      throw err;
    }
    return r.data;
  }
  const toPy = (x) => (x == null ? null : pyodide.toPy(x));
  const withPy = (x, fn) => {
    const proxy = toPy(x);
    try {
      return fn(proxy);
    } finally {
      if (proxy && proxy.destroy) proxy.destroy();
    }
  };

  return {
    // imite fetch(path, body) : renvoie les données, lève une erreur portant
    // stickers/repairs en cas d'échec — même contrat que la couche HTTP.
    async call(path, body) {
      if (path === "/api/puzzles") {
        // pas de préparation en arrière-plan ici : les bibliothèques se
        // construisent à la première résolution. On annonce tout « prêt ».
        return unwrap(wg.catalog()).map((p) => ({ ...p, ready: true }));
      }
      let m;
      if ((m = path.match(/^\/api\/puzzles\/(.+)$/))) return unwrap(wg.info(m[1]));
      if ((m = path.match(/^\/api\/cheatsheet\/(.+)$/))) return unwrap(wg.cheatsheet(m[1]));
      if (path === "/api/scramble") return unwrap(wg.scramble(body.puzzle, body.seed ?? null));
      if (path === "/api/formula")
        return withPy(body.colors ?? null, (c) => unwrap(wg.formula(body.puzzle, body.formula, c)));
      if (path === "/api/solve")
        return withPy(body.colors, (c) => unwrap(wg.solve(body.puzzle, c)));
      throw new Error("Route inconnue : " + path);
    },
  };
}

async function boot() {
  setStatus("Chargement de l'environnement Python (quelques secondes, une seule fois)…");
  const pyodide = await loadPyodide({ indexURL: PYODIDE_CDN });
  await pyodide.loadPackage("numpy");
  const buf = await (await fetch("./rubik_helper.zip")).arrayBuffer();
  pyodide.unpackArchive(buf, "zip", { extractDir: "/home/pyodide/site" });
  pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide/site')");
  const wg = pyodide.pyimport("rubik_helper.webglue");
  window.RHAPI = makeApi(pyodide, wg);
  setStatus("");
  await import("./app.js");
}

boot().catch((err) => {
  console.error(err);
  setStatus("Échec du chargement : " + (err && err.message ? err.message : err));
});
