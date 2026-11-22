"""Cifrado de credenciales/tokens con Fernet (AES-128-CBC + HMAC-SHA256).

La primera llave de AVIA_ENCRYPTION_KEYS cifra; todas descifran (rotación sin downtime).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class SecretBox:
    """Cifra credenciales con MultiFernet; la primera llave es la activa."""
    def __init__(self, keys: list[str]):
        """Carga las llaves (la primera cifra, todas descifran)."""
        if not keys:
            raise ValueError("Se requiere al menos una llave")
        self._fernets = [Fernet(k.encode()) for k in keys]
        self._multi = MultiFernet(self._fernets)
        self.active_key_id = self.key_id(keys[0])

    @staticmethod
    def key_id(key: str) -> str:
        """Identificador corto de una llave (sin revelarla)."""
        return hashlib.sha256(key.encode()).hexdigest()[:12]

    def encrypt(self, payload: dict[str, Any]) -> bytes:
        """Cifra un dict como JSON."""
        return self._multi.encrypt(json.dumps(payload, separators=(",", ":")).encode())

    def decrypt(self, token: bytes) -> dict[str, Any]:
        """Descifra a dict; ante llave incorrecta falla sin mostrar el dato."""
        try:
            return json.loads(self._multi.decrypt(bytes(token)))
        except InvalidToken as exc:  # no filtrar contenido
            raise ValueError("No se pudo descifrar la credencial (llave incorrecta o dato alterado)") from exc

    def rotate(self, token: bytes) -> bytes:
        """Re-cifra un dato con la llave activa."""
        return self._multi.rotate(bytes(token))
