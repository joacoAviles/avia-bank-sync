"""RUT chileno: limpieza, validación (módulo 11) y formatos."""

from __future__ import annotations

import re


def clean(rut: str) -> str:
    """RUT solo con dígitos y K mayúscula."""
    return re.sub(r"[^0-9kK]", "", rut or "").upper()


def check_digit(body: str) -> str:
    """Dígito verificador (módulo 11)."""
    total, factor = 0, 2
    for d in reversed(body):
        total += int(d) * factor
        factor = 2 if factor == 7 else factor + 1
    r = 11 - total % 11
    return {11: "0", 10: "K"}.get(r, str(r))


def is_valid(rut: str) -> bool:
    """Si el RUT tiene dígito verificador correcto."""
    c = clean(rut)
    if len(c) < 2 or not c[:-1].isdigit():
        return False
    return check_digit(c[:-1]) == c[-1]


def fmt(rut: str, style: str = "dotted") -> str:
    """dotted: 12.345.678-9 · dash: 12345678-9 · plain: 123456789"""
    c = clean(rut)
    body, dv = c[:-1], c[-1]
    if style == "plain":
        return body + dv
    if style == "dash":
        return f"{body}-{dv}"
    return f"{int(body):,}".replace(",", ".") + f"-{dv}"


def mask(rut: str) -> str:
    """RUT enmascarado para mostrar (**.***.123-4)."""
    c = clean(rut)
    return f"**.***.{c[-4:-1]}-{c[-1]}" if len(c) >= 4 else "***"
