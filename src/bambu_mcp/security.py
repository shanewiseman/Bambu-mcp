"""Credential encryption, redaction, approval hashing, and path confinement."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from bambu_mcp.errors import SafetyError, ValidationError

SENSITIVE_KEYS = re.compile(
    r"(access[_-]?code|api[_-]?key|authorization|credential|password|secret|token)",
    re.IGNORECASE,
)
SENSITIVE_VALUE = re.compile(
    r"(?i)\b(access[_ -]?code|password|token|api[_ -]?key)\s*[:=]\s*([^\s,;]+)"
)


class CredentialVault:
    """Encrypt printer credentials at rest with an operator-supplied Fernet key."""

    def __init__(self, key: str | bytes) -> None:
        try:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except (TypeError, ValueError) as exc:
            raise ValidationError("credential key must be a valid Fernet key") from exc

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            raise ValidationError("cannot encrypt an empty credential")
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise SafetyError("credential could not be decrypted") from exc


def compare_api_key(expected: str | None, supplied: str | None) -> bool:
    if expected is None:
        return True
    return supplied is not None and hmac.compare_digest(expected, supplied)


def redact(value: Any) -> Any:
    """Recursively redact secret-bearing keys and common inline credential forms."""
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if SENSITIVE_KEYS.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return SENSITIVE_VALUE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return value


def canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def issue_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def confined_path(root: Path, candidate: Path) -> Path:
    """Resolve a local import and require it to remain inside the allowlisted root."""
    resolved_root = root.resolve(strict=True)
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise SafetyError("path is outside the configured import root or is not a file")
    return resolved
