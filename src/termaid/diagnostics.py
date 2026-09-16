"""Versioned diagnostics for subprocess consumers such as editor plugins."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Literal, Mapping, TypedDict


class DiagnosticDocument(TypedDict):
    version: int
    severity: Literal["error", "warning"]
    code: str
    message: str
    details: dict[str, str | int]
    exit_code: int


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    exit_code: int = 1
    severity: Literal["error", "warning"] = "error"
    details: Mapping[str, str | int] = field(default_factory=dict)

    def to_dict(self) -> DiagnosticDocument:
        return {
            "version": 1,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
            "exit_code": self.exit_code,
        }

    def emit(self, output_format: str = "text") -> int:
        """Write one diagnostic to stderr and return its process exit code."""
        if output_format == "json":
            print(json.dumps(self.to_dict(), ensure_ascii=False), file=sys.stderr)
        else:
            print(f"{self.severity.capitalize()}: {self.message}", file=sys.stderr)
        return self.exit_code
