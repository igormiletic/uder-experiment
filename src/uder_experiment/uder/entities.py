"""UDER: Uniform Data Entity Representation -- a linked entity graph, not an opaque blob.

Each UDEREntity carries entityId, entityType, representation, sourceStandard,
properties, and links (spec Section 8). A UDERGraph is the set of entities
describing one logical invoice, as they would be distributed across several
UCS instances and reassembled by the LDC.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UDERLink:
    predicate: str
    target_entity_id: str


@dataclass
class UDEREntity:
    entity_id: str
    entity_type: str
    representation: str  # e.g. "ubl", "cii", "source-c"
    source_standard: str  # e.g. "UBL-2.1", "UNCEFACT-CII", "OAGIS-9-JSON"
    properties: dict[str, Any] = field(default_factory=dict)
    links: list[UDERLink] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entityId": self.entity_id,
            "entityType": self.entity_type,
            "representation": self.representation,
            "sourceStandard": self.source_standard,
            "properties": self.properties,
            "links": [{"predicate": l.predicate, "targetEntityId": l.target_entity_id} for l in self.links],
        }

    @staticmethod
    def from_dict(d: dict) -> "UDEREntity":
        return UDEREntity(
            entity_id=d["entityId"], entity_type=d["entityType"], representation=d["representation"],
            source_standard=d["sourceStandard"], properties=d.get("properties", {}),
            links=[UDERLink(l["predicate"], l["targetEntityId"]) for l in d.get("links", [])],
        )


@dataclass
class UDERGraph:
    root_entity_id: str
    entities: dict[str, UDEREntity] = field(default_factory=dict)

    def add(self, entity: UDEREntity) -> None:
        self.entities[entity.entity_id] = entity

    def get(self, entity_id: str) -> UDEREntity | None:
        return self.entities.get(entity_id)

    def all(self) -> list[UDEREntity]:
        return list(self.entities.values())

    def linked_ids(self, entity_id: str) -> list[str]:
        e = self.entities.get(entity_id)
        return [l.target_entity_id for l in e.links] if e else []
