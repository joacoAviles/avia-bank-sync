// AVIA · grabador de PANTALLAS (DOM enmascarado) — se ejecuta en TU computador, con tu Chrome.
// Tú inicias sesión en el banco y navegas; en cada pantalla que quieras que yo conozca,
// vuelves a esta terminal y presionas ENTER. Al terminar escribes "fin" + ENTER.
// Guarda SOLO estructura: etiquetas fijas (títulos, encabezados, botones) tal cual;
// todo lo demás (montos, nombres, comercios, fechas, números) se enmascara: letras→x, dígitos→9.
// NO guarda contraseñas, cookies, cabeceras ni valores de formularios.
import { chromium } from "playwright-core";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";

const bank = process.argv[2] || "ripley";
const START = { ripley: "https://web.bancoripley.cl/login", "banco-chile": "https://portalpersonas.bancochile.cl/persona/" }[bank];
if (!START) { console.error("Uso: node grabador-dom.mjs ripley|banco-chile"); process.exit(1); }

const profile = fs.mkdtempSync(path.join(os.tmpdir(), "avia-dom-"));
const ctx = await chromium.launchPersistentContext(profile, {
  channel: "chrome", headless: false, viewport: null, locale: "es-CL", timezoneId: "America/Santiago",
});
const page = ctx.pages()[0] ?? (await ctx.newPage());
await page.goto(START).catch(() => {});

const snaps = [];
async function snapshot(note) {
  const pg = ctx.pages().at(-1) ?? page;
  const data = await pg.evaluate(() => {
    const LABEL = new Set(["H1","H2","H3","H4","H5","H6","TH","LABEL","BUTTON","A","LEGEND","DT","OPTION","SUMMARY"]);
    const mask = (t) => t.replace(/[A-Za-zÁÉÍÓÚÑáéíóúñÜü]/g, "x").replace(/\d/g, "9");
    const cssPart = (el) => {
      let s = el.tagName.toLowerCase();
      const id = el.getAttribute("id"); if (id && !/\d{3,}/.test(id)) s += "#" + id;
      const cls = [...el.classList].filter((c) => !/\d{3,}/.test(c)).slice(0, 3); if (cls.length) s += "." + cls.join(".");
      const tid = el.getAttribute("data-testid") || el.getAttribute("data-test") || el.getAttribute("formcontrolname");
      if (tid) s += `[${tid.replace(/\d/g, "9")}]`;
      const role = el.getAttribute("role"); if (role) s += `{${role}}`;
      return s;
    };
    const pathOf = (el) => { const p = []; for (let e = el, i = 0; e && e !== document.body && i < 7; e = e.parentElement, i++) p.unshift(cssPart(e)); return p.join(" > "); };
    const out = [];
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n; while ((n = w.nextNode()) && out.length < 700) {
      const raw = n.nodeValue.replace(/\s+/g, " ").trim(); if (!raw) continue;
      const el = n.parentElement; if (!el || ["SCRIPT","STYLE","NOSCRIPT"].includes(el.tagName)) continue;
      const st = getComputedStyle(el); if (st.display === "none" || st.visibility === "hidden") continue;
      const keep = LABEL.has(el.tagName) && !/\d/.test(raw) && raw.length <= 40;
      out.push({ path: pathOf(el), text: (keep ? raw : mask(raw)).slice(0, 60), fixed: keep });
    }
    const loc = new URL(location.href);
    return { url: loc.origin + loc.pathname.replace(/\/\d{3,}/g, "/:n").replace(/;.*$/, ";…"), title: mask(document.title).slice(0, 40), nodes: out };
  });
  snaps.push({ note: note || "", ...data });
  console.log(`✔ pantalla ${snaps.length} guardada: ${data.url} (${data.nodes.length} textos)`);
}

console.log(`\nSe abrió Chrome en ${bank}. Inicia sesión, ve a la pantalla que quieras, y aquí presiona ENTER.`);
console.log(`Opcional: escribe una nota (ej: "cuenta corriente movimientos") y ENTER. Para terminar escribe: fin\n`);
const rl = readline.createInterface({ input: process.stdin });
for await (const line of rl) {
  if (line.trim().toLowerCase() === "fin") break;
  try { await snapshot(line.trim()); } catch (e) { console.log("no pude capturar:", e.message); }
}
const file = path.join(os.homedir(), `pantallas-${bank}.json`);
fs.writeFileSync(file, JSON.stringify({ bank, snaps }, null, 1));
console.log(`\nListo → ${file}  (adjúntalo en el chat)`);
await ctx.close();
process.exit(0);
