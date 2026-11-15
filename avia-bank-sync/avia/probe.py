"""Prueba de extracción con tu sesión real. Salida ENMASCARADA.

Uso:  python -m avia.probe banco-chile
Muestra cuentas, saldos y movimientos leídos, sin textos ni montos exactos.
"""

from __future__ import annotations

import math
import re
import sys
from datetime import date, timedelta

from .connectors import REGISTRY
from .recon import load_state


def mag(x) -> str:
    if x is None:
        return "—"
    v = abs(float(x))
    return ("-" if float(x) < 0 else "+") + f"~1e{int(math.log10(v)) if v >= 1 else 0}"


def mask_txt(s: str) -> str:
    return re.sub(r"[A-Za-zÁÉÍÓÚáéíóúñÑ]", "x", re.sub(r"\d", "9", s or ""))[:40]


def main(bank: str) -> None:
    key = bank.replace("-", "_")
    cls = REGISTRY[key]
    creds = load_state(bank, full=True)
    c = cls(creds)
    since = date.today() - timedelta(days=45)
    try:
        c.authenticate()
        accts = c.get_accounts()
        bals = {b.external_account_id: b for b in c.get_balances(accts)}
        print(f"{bank}: {len(accts)} cuentas/tarjetas")
        for a in accts:
            b = bals.get(a.external_id)
            try:
                txs = c.get_transactions(a, since)
                err = ""
            except Exception as exc:  # noqa: BLE001
                txs, err = [], f"  ERROR: {type(exc).__name__}: {str(exc)[:120]}"
            print(f" - {a.account_type:11} {a.masked_number or '':10} moneda={a.currency} "
                  f"saldo={mag(b.booked) if b else 'sin saldo'} disp={mag(b.available) if b else '—'} "
                  f"movs(45d)={len(txs)}{err}")
            for t in txs[:3]:
                print(f"     {t.value_date} {mag(t.amount):8} {mask_txt(t.description)}"
                      f"{' cuota ' + str(t.installment_number) + '/' + str(t.installment_total) if t.installment_total else ''}")
        rec = getattr(c, "_data", {}) or {}
        for k, r in rec.items():
            if r.get("error"):
                print(f" ! {r['acct'].masked_number}: {r['error']}")
            print("   claves del producto:", sorted((r.get("p") or {}).keys()))
        print("llamadas:", [(m, p, s) for m, p, s in getattr(c, "diagnostics", [])])
    except Exception as exc:  # noqa: BLE001
        print(f"FALLÓ: {type(exc).__name__}: {str(exc)[:300]}")
        print("llamadas:", getattr(c, "diagnostics", []))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "banco-chile")
