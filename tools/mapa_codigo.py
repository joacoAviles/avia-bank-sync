#!/usr/bin/env python3
"""Genera MAPA-CODIGO.md: una línea de contexto por módulo, clase, función y endpoint.

Uso (desde la raíz del repo):  python3 tools/mapa_codigo.py
Vuelve a correrlo después de cambiar código; las pruebas verifican que el mapa esté al día.
Solo usa la biblioteca estándar.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SVC = RAIZ / "avia-bank-sync"
INTEG = RAIZ / "actual-avia-integration"
SALIDA = RAIZ / "MAPA-CODIGO.md"
METODOS_HTTP = {"get", "post", "put", "patch", "delete"}


def primera_linea(doc: str | None) -> str:
    if not doc:
        return ""
    return " ".join(doc.strip().split("\n\n")[0].split())


def firma(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    a = fn.args
    nombres = [x.arg for x in a.posonlyargs + a.args if x.arg not in ("self", "cls")]
    if a.vararg:
        nombres.append("*" + a.vararg.arg)
    nombres += [x.arg for x in a.kwonlyargs]
    if a.kwarg:
        nombres.append("**" + a.kwarg.arg)
    return f"{'async ' if isinstance(fn, ast.AsyncFunctionDef) else ''}{fn.name}({', '.join(nombres)})"


def comentario_previo(lineas: list[str], n: int) -> str:
    """Comentario `# ...` inmediatamente encima (o al final) de la línea n (1-based)."""
    linea = lineas[n - 1]
    if "#" in linea and not linea.strip().startswith("#"):
        c = linea.split("#", 1)[1].strip()
        if not c.startswith("noqa"):
            return c
    i, partes = n - 2, []
    while i >= 0 and lineas[i].strip().startswith("#"):
        t = lineas[i].strip().lstrip("#").strip()
        if t and not set(t) <= set("-=_ "):
            partes.insert(0, t)
        i -= 1
    return " ".join(partes)


def rutas(fn) -> list[str]:
    out = []
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in METODOS_HTTP:
            if d.args and isinstance(d.args[0], ast.Constant):
                out.append(f"{d.func.attr.upper()} {d.args[0].value}")
    return out


def mapa_python(ruta: Path, endpoints: list[str]) -> list[str]:
    fuente = ruta.read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    lineas = fuente.splitlines()
    rel = ruta.relative_to(RAIZ)
    out = [f"\n### `{rel}`", f"{primera_linea(ast.get_docstring(arbol)) or '_(sin docstring de módulo)_'}"]

    def nodo(n, prefijo=""):
        doc = primera_linea(ast.get_docstring(n)) or comentario_previo(lineas, n.lineno)
        if not doc and n.name.startswith("test_"):
            doc = "prueba: " + n.name[5:].replace("_", " ")
        if isinstance(n, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in n.bases)
            out.append(f"- **clase `{n.name}`**{f'({bases})' if bases else ''} · L{n.lineno}" + (f" — {doc}" if doc else ""))
            for h in n.body:
                if isinstance(h, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nodo(h, "  ")
        else:
            rs = rutas(n)
            for r in rs:
                endpoints.append(f"| `{r}` | `{rel}` L{n.lineno} `{n.name}` | {doc} |")
            marca = f" **[{'; '.join(rs)}]**" if rs else ""
            out.append(f"{prefijo}- `{firma(n)}` · L{n.lineno}{marca}" + (f" — {doc}" if doc else ""))

    for n in arbol.body:
        if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            nodo(n)
    return out


def mapa_otro(ruta: Path) -> str:
    """Archivos no Python: primera línea de comentario como contexto."""
    rel = ruta.relative_to(RAIZ)
    desc = ""
    for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines()[:15]:
        t = linea.strip()
        if t.startswith("#!") or not t:
            continue
        m = re.match(r"^(?:#|//|/\*+|\*|--)\s*(.+?)\s*(?:\*/)?$", t)
        if m and m.group(1) and not set(m.group(1)) <= set("-=*_ "):
            desc = m.group(1)
            break
        if not t.startswith(("#", "//", "/*", "*", "--")):
            break
    return f"- `{rel}`" + (f" — {desc}" if desc else "")


def generar() -> str:
    endpoints: list[str] = []
    cuerpo: list[str] = []
    for carpeta, titulo in ((SVC / "avia", "Servicio AVIA (`avia-bank-sync/avia`)"),
                            (SVC / "tests", "Pruebas del servicio (`avia-bank-sync/tests`)")):
        cuerpo.append(f"\n## {titulo}")
        for p in sorted(carpeta.rglob("*.py")):
            if "__pycache__" in p.parts or (p.name == "__init__.py" and p.stat().st_size < 40):
                continue
            cuerpo += mapa_python(p, endpoints)

    otros = [p for p in sorted(RAIZ.rglob("*"))
             if p.is_file() and p.suffix in {".sh", ".sql", ".mjs", ".js", ".ts", ".tsx", ".patch", ".yaml", ".yml"}
             and not any(x in p.parts for x in (".venv", "node_modules", "build", "__pycache__", ".git"))]
    cuerpo.append("\n## Scripts, SQL, parche de Actual y runner")
    cuerpo += [mapa_otro(p) for p in otros]

    cab = [
        "# Mapa del código — AVIA Bank Sync",
        "",
        "Generado por `python3 tools/mapa_codigo.py`. No editar a mano: corre el script tras cambiar código.",
        "Cada línea: nombre, línea del archivo (`L`) y su propósito (docstring o comentario).",
        "",
        "## Endpoints HTTP",
        "| Ruta | Dónde | Qué hace |",
        "| --- | --- | --- |",
        *endpoints,
    ]
    return "\n".join(cab + cuerpo) + "\n"


if __name__ == "__main__":
    texto = generar()
    if "--check" in sys.argv:
        actual = SALIDA.read_text(encoding="utf-8") if SALIDA.exists() else ""
        sys.exit(0 if actual == texto else "MAPA-CODIGO.md desactualizado: corre python3 tools/mapa_codigo.py")
    SALIDA.write_text(texto, encoding="utf-8")
    print(f"{SALIDA.relative_to(RAIZ)}: {texto.count(chr(10))} líneas")
