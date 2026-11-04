"""Load the six Digital Green JSON Schemas and validate documents against them.

- Schemas are read as-is from the participant pack; they are never modified.
- Cross-schema ``$ref`` values (e.g. ``survey.schema.json#/$defs/ist_time``)
  resolve through a local ``referencing.Registry`` keyed by each schema's
  ``$id``. Nothing is fetched over the network; an unknown reference fails.
- ``format`` is enforced (date-time, uuid, ...), not just annotated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource
from referencing.jsonschema import DRAFT202012

DRAFT_2020_12_URI = "https://json-schema.org/draft/2020-12/schema"


class SchemaName(StrEnum):
    INSIGHT = "insight"
    SURVEY = "survey"
    SCHEDULE_HANDOFF = "schedule_handoff"
    RESPONSE = "response"
    NO_SURVEY = "no_survey"
    BOTTOM_SHEET = "bottom_sheet"

    @property
    def filename(self) -> str:
        return f"{self.value}.schema.json"


class SchemaLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class ValidationIssue:
    path: str  # JSON pointer-ish location in the instance, e.g. "/items/0/prompt"
    message: str
    validator: str  # the failing keyword, e.g. "pattern", "format", "required"


def _no_remote_retrieval(uri: str) -> Resource:
    raise NoSuchResource(ref=uri)


class SchemaRegistry:
    """Holds the six schemas and one compiled validator per schema."""

    def __init__(self, schemas_dir: Path) -> None:
        self.schemas_dir = Path(schemas_dir)
        self.schemas: dict[SchemaName, dict[str, Any]] = {}
        self._validators: dict[SchemaName, Draft202012Validator] = {}
        self._load()

    def _load(self) -> None:
        if not self.schemas_dir.is_dir():
            raise SchemaLoadError(f"Schema directory not found: {self.schemas_dir}")

        resources: list[tuple[str, Resource]] = []
        for name in SchemaName:
            path = self.schemas_dir / name.filename
            if not path.is_file():
                raise SchemaLoadError(f"Missing schema file: {path}")
            schema = json.loads(path.read_text(encoding="utf-8"))
            if schema.get("$schema") != DRAFT_2020_12_URI:
                raise SchemaLoadError(f"{name.filename} is not declared as Draft 2020-12")
            if "$id" not in schema:
                raise SchemaLoadError(f"{name.filename} has no $id; cross-refs cannot resolve")
            # Raises SchemaError if the schema itself is not valid 2020-12.
            Draft202012Validator.check_schema(schema)
            self.schemas[name] = schema
            resources.append((schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012)))

        registry: Registry = Registry(retrieve=_no_remote_retrieval).with_resources(resources)
        # Resolve every $ref now, so a broken reference fails at startup rather
        # than on the first document that happens to reach it.
        for name, schema in self.schemas.items():
            resolver = registry.resolver(base_uri=schema["$id"])
            for ref in _iter_refs(schema):
                try:
                    resolver.lookup(ref)
                except Exception as exc:
                    raise SchemaLoadError(f"{name.filename}: cannot resolve $ref {ref!r}") from exc
        format_checker = FormatChecker()
        for name, schema in self.schemas.items():
            self._validators[name] = Draft202012Validator(
                schema, registry=registry, format_checker=format_checker
            )

    def validator(self, name: SchemaName | str) -> Draft202012Validator:
        return self._validators[SchemaName(name)]

    def errors(self, name: SchemaName | str, instance: Any) -> list[ValidationIssue]:
        """All validation problems, sorted by location. Empty list means valid."""
        found = sorted(self.validator(name).iter_errors(instance), key=lambda e: list(e.absolute_path))
        return [_to_issue(e) for e in found]

    def is_valid(self, name: SchemaName | str, instance: Any) -> bool:
        return self.validator(name).is_valid(instance)

    def validate(self, name: SchemaName | str, instance: Any) -> None:
        """Raise ``jsonschema.ValidationError`` (the most relevant one) if invalid."""
        self.validator(name).validate(instance)


def _iter_refs(node: Any):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield value
            else:
                yield from _iter_refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_refs(value)


def _to_issue(err: ValidationError) -> ValidationIssue:
    path = "/" + "/".join(str(p) for p in err.absolute_path)
    return ValidationIssue(path=path, message=err.message, validator=str(err.validator))
