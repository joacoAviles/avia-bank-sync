// AVIA Actual Runner
//
// Importa en Actual los movimientos que AVIA ya sincronizó, usando el mecanismo
// interno de Actual (api.runBankSync -> accounts-bank-sync -> reconcileTransactions).
// No escribe en SQLite. Se ejecuta cuando AVIA lo pide (POST /run) y como respaldo
// una vez al día. Luego informa a AVIA el saldo conciliado de Actual para la
// reconciliación de saldos.
import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';

import * as api from '@actual-app/api';

const env = name => {
  const file = process.env[`${name}_FILE`];
  if (file) return fs.readFileSync(file, 'utf8').trim();
  return process.env[name];
};

const CFG = {
  port: Number(process.env.RUNNER_PORT ?? 8090),
  dataDir: process.env.RUNNER_DATA_DIR ?? '/data',
  actualUrl: process.env.ACTUAL_SERVER_URL ?? 'http://actual-budget:5006',
  actualPassword: env('ACTUAL_PASSWORD'),
  budgetSyncId: process.env.ACTUAL_BUDGET_SYNC_ID,
  budgetE2EPassword: env('ACTUAL_BUDGET_E2E_PASSWORD'),
  aviaUrl: (process.env.AVIA_SERVER_URL ?? 'http://avia-api:8000').replace(/\/+$/, ''),
  aviaToken: env('AVIA_API_TOKEN'),
  fallbackHours: Number(process.env.RUNNER_FALLBACK_HOURS ?? 24),
};

const log = (level, msg, extra = {}) =>
  console.log(JSON.stringify({ ts: new Date().toISOString(), level, logger: 'avia.runner', msg, ...extra }));

for (const k of ['actualPassword', 'budgetSyncId', 'aviaToken']) {
  if (!CFG[k]) {
    log('error', `falta configuración: ${k}`);
    process.exit(2);
  }
}

let running = null;
let lastResult = null;

export async function runOnce(reason) {
  if (running) return running;
  running = (async () => {
    const started = Date.now();
    fs.mkdirSync(CFG.dataDir, { recursive: true });
    const internal = await api.init({ dataDir: CFG.dataDir, serverURL: CFG.actualUrl, password: CFG.actualPassword });
    try {
      await api.downloadBudget(
        CFG.budgetSyncId,
        CFG.budgetE2EPassword ? { password: CFG.budgetE2EPassword } : undefined,
      );
      const accounts = (await internal.send('accounts-get')).filter(
        a => a.account_sync_source === 'avia' && !a.closed && !a.tombstone,
      );
      const summary = { reason, accounts: accounts.length, newTransactions: 0, matched: 0, errors: [] };
      for (const acct of accounts) {
        try {
          const res = await api.runBankSync({ accountId: acct.id });
          summary.newTransactions += res?.newTransactions?.length ?? 0;
          summary.matched += res?.matchedTransactions?.length ?? 0;
        } catch (err) {
          summary.errors.push({ account: acct.name, message: String(err?.message ?? err).slice(0, 300) });
        }
        await reportBalance(acct).catch(err =>
          log('warning', 'no se pudo informar saldo a AVIA', { account: acct.name, error: String(err) }),
        );
      }
      await api.sync();
      lastResult = { ...summary, ok: summary.errors.length === 0, ms: Date.now() - started, at: new Date().toISOString() };
      log(lastResult.ok ? 'info' : 'warning', 'importación a Actual terminada', lastResult);
      return lastResult;
    } finally {
      await api.shutdown();
    }
  })().finally(() => {
    running = null;
  });
  return running;
}

async function reportBalance(acct) {
  const { data } = await api.aqlQuery(
    api.q('transactions').filter({ account: acct.id, cleared: true }).calculate({ $sum: '$amount' }),
  );
  const res = await fetch(`${CFG.aviaUrl}/v1/accounts/${encodeURIComponent(acct.account_id)}/actual-balance`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${CFG.aviaToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ clearedBalance: data ?? 0 }),
    signal: AbortSignal.timeout(15000),
  });
  if (!res.ok && res.status !== 404) throw new Error(`HTTP ${res.status}`);
}

function authorized(req) {
  const h = req.headers.authorization ?? '';
  const a = Buffer.from(h);
  const b = Buffer.from(`Bearer ${CFG.aviaToken}`);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}


const server = http.createServer(async (req, res) => {
  const send = (code, body) => {
    res.writeHead(code, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(body));
  };
  if (req.method === 'GET' && req.url === '/health') return send(200, { status: 'ok', running: !!running, lastResult });
  if (req.method === 'POST' && req.url === '/run') {
    if (!authorized(req)) return send(401, { error: 'unauthorized' });
    const already = !!running;
    runOnce('avia').catch(err => log('error', 'importación falló', { error: String(err?.stack ?? err) }));
    return send(202, { started: !already, alreadyRunning: already });
  }
  if (req.method === 'POST' && req.url === '/run-sync') {
    // Variante síncrona (diagnóstico/pruebas)
    if (!authorized(req)) return send(401, { error: 'unauthorized' });
    try {
      return send(200, await runOnce('manual'));
    } catch (err) {
      return send(500, { error: String(err?.message ?? err) });
    }
  }
  send(404, { error: 'not found' });
});

if (process.env.RUNNER_NO_LISTEN !== '1') {
  server.listen(CFG.port, () => log('info', 'runner escuchando', { port: CFG.port }));
  // Respaldo: si AVIA no avisó, importar al menos cada RUNNER_FALLBACK_HOURS
  setInterval(() => {
    if (!lastResult || Date.now() - Date.parse(lastResult.at) > CFG.fallbackHours * 3600_000) {
      runOnce('fallback').catch(err => log('error', 'importación de respaldo falló', { error: String(err) }));
    }
  }, 15 * 60_000).unref();
}
