// AVIA · grabador de estructura (se ejecuta en TU computador, con tu Chrome).
// Tú inicias sesión y navegas; esto solo anota ESTRUCTURA enmascarada:
//   - etiquetas de lo que clicas (texto de botones/enlaces, dígitos → 9)
//   - URLs de las llamadas JSON del banco (sin valores) y la FORMA de sus respuestas
// NO guarda: contraseñas, teclas, cookies, cabeceras, montos, nombres, RUT ni números.
import { chromium } from "playwright-core";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";

const URLS = {
  "banco-chile": "https://portalpersonas.bancochile.cl/persona/",
  ripley: "https://web.bancoripley.cl/login",
};
const bank = process.argv[2];
if (!URLS[bank]) { console.error("Uso: node grabador.mjs banco-chile|ripley"); process.exit(1); }

const KEEP_KEY = /(tipo|type|moneda|currency|estado|status|producto|product|categoria|signo|clase)/i;
function shape(v, key = "", d = 0) {
  if (d > 6) return "…";
  if (Array.isArray(v)) return { _len: v.length, _item: v.length ? shape(v[0], key, d + 1) : null };
  if (v === null) return "null";
  if (typeof v === "object") return Object.fromEntries(Object.entries(v).slice(0, 40).map(([k, x]) => [k, shape(x, k, d + 1)]));
  if (typeof v === "boolean") return "bool";
  if (typeof v === "number") return "num";
  if (typeof v === "string") {
    if (/^\d{4}-\d{2}-\d{2}([T ].*)?$/.test(v) || /^\d{2}[-/]\d{2}[-/]\d{4}$/.test(v)) return "date";
    if (KEEP_KEY.test(key)) return v.replace(/\d/g, "9").slice(0, 30);
    return `str(${v.length})`;
  }
  return typeof v;
}
function normUrl(u) {
  try {
    const x = new URL(u);
    let p = x.pathname.replace(/\/\d{3,}/g, "/:n").replace(/\/[0-9a-fA-F-]{16,}/g, "/:id");
    const q = [...new Set([...x.searchParams.keys()])].sort();
    return `${x.origin}${p}${q.length ? "?" + q.join("&") : ""}`;
  } catch { return "(url)"; }
}
const mask = (t) => t.replace(/\d/g, "9").slice(0, 50);

const profile = fs.mkdtempSync(path.join(os.tmpdir(), "avia-grabador-"));
const ctx = await chromium.launchPersistentContext(profile, {
  channel: "chrome", headless: false, viewport: null, locale: "es-CL", timezoneId: "America/Santiago",
});
const page = ctx.pages()[0] ?? (await ctx.newPage());

const steps = [];
const calls = new Map();
const t0 = Date.now();
const stamp = () => Math.round((Date.now() - t0) / 1000);

await ctx.exposeBinding("__aviaClick", (_s, label) => {
  steps.push({ t: stamp(), clic: mask(String(label)) });
});
await ctx.addInitScript(() => {
  document.addEventListener("click", (e) => {
    const el = e.target.closest && e.target.closest("a,button,[role=menuitem],[role=tab],[role=button],li,td,tr");
    if (!el || el.matches("input,textarea")) return;
    const txt = (el.innerText || el.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ");
    if (txt && txt.length <= 60) window.__aviaClick(txt);
  }, true);
});
page.on("framenavigated", (f) => { if (f === page.mainFrame()) steps.push({ t: stamp(), url: normUrl(f.url()) }); });

ctx.on("response", async (resp) => {
  try {
    const req = resp.request();
    if (!["xhr", "fetch"].includes(req.resourceType()) || calls.size >= 80) return;
    if (!(resp.headers()["content-type"] || "").includes("json")) return;
    const key = req.method() + " " + normUrl(resp.url());
    if (calls.has(key)) return;
    let body = null;
    const pd = req.postData();
    if (pd) { try { body = shape(JSON.parse(pd)); } catch { body = "(sin JSON)"; } }
    const json = await resp.json();
    calls.set(key, { method: req.method(), url: normUrl(resp.url()), status: resp.status(), t: stamp(),
      request_body: body, response: JSON.stringify(shape(json)).slice(0, 2000) });
  } catch { /* ignorar */ }
});

await page.goto(URLS[bank]);
console.log(`
Se abrió Chrome en ${bank}.
 1) Inicia sesión TÚ (la clave no se guarda).
 2) Entra a "últimos movimientos" de la CUENTA CORRIENTE y desplázate un poco.
 3) Entra a los movimientos de la TARJETA DE CRÉDITO (facturados y no facturados si los hay).
 4) Vuelve a esta ventana y presiona ENTER para terminar.
`);
await new Promise((r) => readline.createInterface({ input: process.stdin }).once("line", r));

const out = { bank, pasos: steps, llamadas_api: [...calls.values()] };
const file = path.join(os.homedir(), `reporte-${bank}.json`);
fs.writeFileSync(file, JSON.stringify(out, null, 1));
console.log(`\nReporte guardado en ${file}\n`);
console.log(JSON.stringify(out, null, 1));
await ctx.close();
fs.rmSync(profile, { recursive: true, force: true });
process.exit(0);
