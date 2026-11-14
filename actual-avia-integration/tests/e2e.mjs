// Prueba de punta a punta contra un stack real:
//   PostgreSQL + AVIA Bank Sync (sandbox) + sync-server de Actual con el parche AVIA
//   + @actual-app/api construido desde el mismo fork.
// Simula exactamente lo que hace la interfaz: Set up -> Link bank account -> sincronizar.
//
// Variables: ACTUAL_SERVER_URL, ACTUAL_PASSWORD, AVIA_SERVER_URL, AVIA_API_TOKEN, E2E_DATA_DIR
import assert from 'node:assert/strict';
import fs from 'node:fs';

import * as api from '@actual-app/api';

const ACTUAL = process.env.ACTUAL_SERVER_URL ?? 'http://127.0.0.1:5006';
const AVIA = process.env.AVIA_SERVER_URL ?? 'http://127.0.0.1:8000';
const TOKEN = process.env.AVIA_API_TOKEN;
const dataDir = process.env.E2E_DATA_DIR ?? '/tmp/e2e/client';
fs.rmSync(dataDir, { recursive: true, force: true });
fs.mkdirSync(dataDir, { recursive: true });

const step = (n, msg) => console.log(`\n[${n}] ${msg}`);
const aviaGet = async p =>
  (await fetch(AVIA + p, { headers: { Authorization: `Bearer ${TOKEN}` } })).json();
let internal;
const send = (name, args) => internal.send(name, args);
const money = n => (n / 100).toLocaleString('es-CL', { style: 'currency', currency: 'CLP' });

internal = await api.init({ dataDir, serverURL: ACTUAL, password: process.env.ACTUAL_PASSWORD });

step(1, 'Crear presupuesto de prueba y subirlo al servidor');
await send('create-budget', { budgetName: 'AVIA E2E' });
const prefs = await send('load-prefs');
assert.ok(prefs.groupId, 'el presupuesto debe tener Sync ID');
console.log('   Sync ID:', prefs.groupId);

step(2, 'Proveedor AVIA visible y sin configurar (estado inicial)');
let st = await send('avia-status');
assert.equal(st.reachable, true);
assert.equal(st.configured, false);
const blocked = st.institutions.filter(i => !i.available).map(i => i.id).sort();
assert.deepEqual(blocked, ['banco-chile', 'itau', 'ripley']);
console.log('   instituciones bloqueadas (documentado):', blocked.join(', '));

step(3, 'Set up: un banco bloqueado se rechaza; el sandbox se conecta');
const bad = await send('avia-connection-create', { institution: 'banco-chile' });
assert.equal(bad.error_code, 'INSTITUTION_BLOCKED');
const conn = await send('avia-connection-create', { institution: 'sandbox', label: 'Sandbox E2E' });
assert.ok(conn.id, JSON.stringify(conn));
for (let i = 0; i < 30 && (await send('avia-status')).state !== 'synchronized'; i++) {
  await new Promise(r => setTimeout(r, 500));
}
st = await send('avia-status');
assert.equal(st.state, 'synchronized');
console.log(`   ${st.importedTransactions} movimientos en AVIA`);

step(4, 'Link bank account: listar cuentas y vincular ambas como cuentas nuevas');
const { accounts } = await send('avia-accounts');
assert.equal(accounts.length, 2);
for (const a of accounts) {
  console.log(`   ${a.institution} · ${a.name} · ${a.type} · saldo ${money(a.balance)}`);
}
// tarjeta primero para que el pago desde la cuenta corriente encuentre su payee de transferencia
for (const a of [...accounts].sort(a => (a.type === 'credit_card' ? -1 : 1))) {
  await send('avia-accounts-link', {
    externalAccount: {
      account_id: a.account_id, name: a.name, institution: a.institution,
      orgDomain: null, orgId: a.institutionId, balance: a.balance,
    },
  });
}
const dup = await send('avia-accounts-link', {
  externalAccount: { account_id: accounts[0].account_id, name: 'dup', institution: 'x', orgId: 'sandbox', balance: 0 },
}).catch(e => e);
assert.ok(String(dup?.message ?? JSON.stringify(dup)).includes('ya está vinculada'), 'no debe duplicar cuentas');

const local = (await send('accounts-get')).filter(a => a.account_sync_source === 'avia');
assert.equal(local.length, 2);
const byType = Object.fromEntries(
  local.map(l => [accounts.find(a => a.account_id === l.account_id).type, l]),
);

step(5, 'Integridad: saldo contable de Actual = saldo contable del banco');
const cleared = async id =>
  (await api.aqlQuery(api.q('transactions').filter({ account: id, cleared: true }).calculate({ $sum: '$amount' })))
    .data;
for (const [type, l] of Object.entries(byType)) {
  const bank = accounts.find(a => a.account_id === l.account_id).balance;
  const act = await cleared(l.id);
  console.log(`   ${type}: banco ${money(bank)} · Actual conciliado ${money(act)}`);
  if (type === 'checking') assert.equal(act, bank, 'saldo de la cuenta corriente debe cuadrar exactamente');
}

step(6, 'Pagos de tarjeta como transferencias (no como gasto)');
const txCC = (await api.getTransactions(byType.checking.id, '2000-01-01', '2100-01-01')).filter(t =>
  (t.imported_payee ?? '').includes('TARJETA'),
);
assert.ok(txCC.length > 0);
const asTransfer = txCC.filter(t => t.transfer_id);
console.log(`   ${asTransfer.length}/${txCC.length} pagos de tarjeta registrados como transferencia`);
assert.equal(asTransfer.length, txCC.length);
const txTC = await api.getTransactions(byType.credit_card.id, '2000-01-01', '2100-01-01');
const payTC = txTC.filter(t => t.amount > 0 && !t.starting_balance_flag);
// cada abono de la tarjeta existe UNA vez (conciliado con la contrapartida de la transferencia)
const amounts = payTC.map(t => `${t.date}:${t.amount}`);
assert.equal(new Set(amounts).size, amounts.length, 'abonos duplicados en la tarjeta');

step(7, 'Re-sincronizar desde Actual (bank sync nativo): idempotente');
const countAll = async () =>
  (await api.aqlQuery(api.q('transactions').filter({ account: { $oneof: local.map(l => l.id) } }).calculate({ $count: '*' })))
    .data;
const before = await countAll();
const res = await api.runBankSync();
const after = await countAll();
console.log(`   antes ${before} · después ${after} · nuevos ${res?.newTransactions?.length ?? 0}`);
assert.equal(after, before);

step(8, 'Estado y conciliación registrados en AVIA');
st = await send('avia-status');
assert.equal(st.linkedAccounts, 2);
const rec = await aviaGet('/v1/reconciliation');
console.log('   snapshots de saldo:', rec.accounts.length);

console.log('\nSYNC_ID=' + prefs.groupId);
await api.shutdown();
console.log('\nE2E OK');
