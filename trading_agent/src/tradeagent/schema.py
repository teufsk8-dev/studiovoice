"""Typed decision schema and strict validation of model output.

A response that fails validation is treated as HOLD, never repaired or guessed.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class Judgment:
    value: object  # str for choice, bool for noul, int for score
    probs: dict  # option -> probability (sums to ~1)

    @property
    def confidence(self) -> float:
        return float(self.probs[self.value]) if self.value in self.probs else 0.0


@dataclass(frozen=True)
class DecisionSchema:
    version: int
    fields: dict

    @classmethod
    def load(cls, path: str | Path) -> "DecisionSchema":
        raw = json.loads(Path(path).read_text())
        return cls(version=int(raw["version"]), fields=raw["fields"])

    def options(self, name: str) -> list:
        spec = self.fields[name]
        if spec["type"] == "choice":
            return list(spec["options"])
        if spec["type"] == "noul":
            return [True, False]
        if spec["type"] == "score":
            return list(range(int(spec["min"]), int(spec["max"]) + 1))
        raise SchemaError(f"unknown type {spec['type']}")


def _coerce_key(k, opts):
    if k in opts:
        return k
    for o in opts:  # JSON keys are strings: map "2" -> 2, "true" -> True
        if str(o).lower() == str(k).lower():
            return o
    raise SchemaError(f"unexpected option {k!r}; allowed {opts}")


def parse_decision(schema: DecisionSchema, raw: dict) -> dict[str, Judgment]:
    """raw: {field: {"probs": {option: p}}}. The chosen value is the argmax, computed here."""
    out: dict[str, Judgment] = {}
    for name in schema.fields:
        if name not in raw:
            raise SchemaError(f"missing field {name}")
        opts = schema.options(name)
        probs_in = raw[name].get("probs")
        if not isinstance(probs_in, dict) or not probs_in:
            raise SchemaError(f"{name}: probs missing")
        probs = {}
        for k, p in probs_in.items():
            p = float(p)
            if not (0.0 <= p <= 1.0) or math.isnan(p):
                raise SchemaError(f"{name}: prob out of range {p}")
            probs[_coerce_key(k, opts)] = p
        total = sum(probs.values())
        if abs(total - 1.0) > 0.02:
            raise SchemaError(f"{name}: probs sum to {total:.3f}")
        value = max(probs, key=probs.get)
        out[name] = Judgment(value=value, probs=probs)
    return out
