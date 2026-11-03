"""JSON Schema validation against the SUPPLIED participant-pack schemas.

The schemas are the authoritative delivery contract. We load them read-only and
resolve cross-file ``$ref``s (e.g. schedule_handoff -> survey) via a local
registry so no network access is needed.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from . import config

_SCHEMA_FILES = {
    "insight": "insight.schema.json",
    "survey": "survey.schema.json",
    "no_survey": "no_survey.schema.json",
    "schedule_handoff": "schedule_handoff.schema.json",
    "response": "response.schema.json",
    "bottom_sheet": "bottom_sheet.schema.json",
}


@lru_cache(maxsize=1)
def _registry() -> Registry:
    """Build a referencing registry keyed by each schema's $id and filename."""
    resources: list[tuple[str, Resource]] = []
    for fname in _SCHEMA_FILES.values():
        with (config.SCHEMA_DIR / fname).open(encoding="utf-8") as fh:
            schema = json.load(fh)
        resource = Resource.from_contents(schema)
        # Register under the plain filename (how sibling schemas $ref each other)
        # and under the $id if present.
        resources.append((fname, resource))
        if "$id" in schema:
            resources.append((schema["$id"], resource))
    return Registry().with_resources(resources)


@lru_cache(maxsize=None)
def _validator(name: str) -> Draft202012Validator:
    fname = _SCHEMA_FILES[name]
    with (config.SCHEMA_DIR / fname).open(encoding="utf-8") as fh:
        schema = json.load(fh)
    return Draft202012Validator(schema, registry=_registry())


def validate(name: str, instance: Any) -> list[str]:
    """Validate an instance against a named schema.

    Returns a list of human-readable error messages; empty means valid.
    """
    if name not in _SCHEMA_FILES:
        raise KeyError(f"unknown schema {name!r}; known: {sorted(_SCHEMA_FILES)}")
    validator = _validator(name)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    out: list[str] = []
    for e in errors:
        loc = "/".join(str(p) for p in e.path) or "<root>"
        out.append(f"{loc}: {e.message}")
    return out


def is_valid(name: str, instance: Any) -> bool:
    return not validate(name, instance)
