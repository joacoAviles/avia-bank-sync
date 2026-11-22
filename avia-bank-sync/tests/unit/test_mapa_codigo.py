"""El mapa del código (MAPA-CODIGO.md) debe estar al día y cada función del servicio con su línea de contexto."""
import ast
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]


def test_mapa_al_dia():
    r = subprocess.run([sys.executable, str(RAIZ / "tools" / "mapa_codigo.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr or r.stdout


def test_toda_funcion_del_servicio_tiene_docstring():
    faltan = []
    for p in sorted((RAIZ / "avia-bank-sync" / "avia").rglob("*.py")):
        arbol = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(arbol):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not ast.get_docstring(n):
                if not (n.name.startswith("__") and n.name.endswith("__") and n.name != "__init__"):
                    faltan.append(f"{p.relative_to(RAIZ)}:{n.lineno} {n.name}")
    assert not faltan, "Agrega una línea de contexto (docstring) a:\n" + "\n".join(faltan)
