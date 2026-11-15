// AVIA · grabador de DATOS DESCIFRADOS (estructura enmascarada) — corre en TU computador.
// Ripley cifra sus respuestas, pero la propia página las descifra y las lee con JSON.parse.
// Esto engancha JSON.parse y anota SOLO la FORMA de lo que la página lee (nombres de campos,
// largos, fechas como "date", textos como str(n)). Valores enmascarados: no guarda montos,
// nombres, RUT ni números. Tú inicias sesión y navegas; al terminar escribe "fin" + ENTER.
import { chromium } from "playwright-core";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";

const bank = process.argv[2] || "ripley";
const START = { ripley: "https://web.bancoripley.cl/login", "banco-chile": "https://portalpersonas.bancochile.cl/persona/" }[bank];
if (!START) { console.error("Uso: node grabador-json.mjs ripley|banco-chile"); process.exit(1); }

const profile = fs.mkdtempSync(path.join(os.tmpdir(), "avia-json-"));
const ctx = await chromium.launchPersistentContext(profile, {
  channel: "chrome", headless: false, viewport: null, locale: "es-CL", timezoneId: "America/Santiago",
});
const found = new Map();
const t0 = Date.now();
await ctx.exposeBinding("__aviaShape", (src, key, shapeJson, url) => {
  const id = key + shapeJson;
  const prev = found.get(id);
  if (prev) { prev.veces++; return; }
  found.set(id, { t: Math.round((Date.now() - t0) / 1000), pantalla: url, veces: 1, forma: JSON.parse(shapeJson) });
});
await ctx.addInitScript(() => {
  const KEEP = /(tipo|type|moneda|currency|estado|status|signo|clase|indicador|sign|credit|debit|cargo|abono|code|codigo)/i;
  const shape = (v, key = "", d = 0) => {
    if (d > 7) return "…";
    if (Array.isArray(v)) return { _len: v.length, _item: v.length ? shape(v[0], key, d + 1) : null };
    if (v === null) return "null";
    if (typeof v === "object") return Object.fromEntries(Object.entries(v).slice(0, 60).map(([k, x]) => [k, shape(x, k, d + 1)]));
    if (typeof v === "boolean") return "bool";
    if (typeof v === "number") return "num";
    if (typeof v === "string") {
      if (/^\d{4}-\d{2}-\d{2}([T ].*)?$/.test(v) || /^\d{2}[-/]\d{2}[-/]\d{4}$/.test(v)) return "date";
      if (KEEP.test(key)) return v.replace(/\d/g, "9").slice(0, 30);
      return `str(${v.length})`;
    }
    return typeof v;
  };
  const orig = JSON.parse;
  JSON.parse = function (text, reviver) {
    const r = orig.call(this, text, reviver);
    try {
      if (r && typeof r === "object" && typeof text === "string" && text.length > 60) {
        const s = JSON.stringify(shape(r));
        if (s.length > 40 && s.length < 60000) {
          const keys = Array.isArray(r) ? "[]" : Object.keys(r).slice(0, 4).join(",");
          window.__aviaShape(keys, s, location.origin + location.pathname.replace(/\/\d{3,}/g, "/:n").replace(/;.*$/, ";…"));
        }
      }
    } catch {}
    return r;
  };
});
const page = ctx.pages()[0] ?? (await ctx.newPage());
await page.goto(START).catch(() => {});
console.log(`\nSe abrió Chrome en ${bank}. Inicia sesión y recorre: inicio, cuenta corriente (baja por la lista de movimientos),`);
console.log(`tarjeta de crédito (no facturados, facturados, abre un par de movimientos) y depósitos a plazo.`);
console.log(`Cuando termines, vuelve aquí y escribe: fin\n`);
const rl = readline.createInterface({ input: process.stdin });
for await (const line of rl) { if (line.trim().toLowerCase() === "fin") break; console.log(`(${found.size} estructuras capturadas)`); }
const file = path.join(os.homedir(), `datos-${bank}.json`);
fs.writeFileSync(file, JSON.stringify({ bank, estructuras: [...found.values()] }, null, 1));
console.log(`\nListo → ${file}  (adjúntalo en el chat)`);
await ctx.close();
process.exit(0);
