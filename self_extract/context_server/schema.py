"""JSON schema definitions for the personal context server."""

from __future__ import annotations

PROFILE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "PersonalContextProfile",
    "type": "object",
    "required": ["facts"],
    "properties": {
        "facts": {
            "type": "array",
            "items": {"$ref": "#/definitions/fact"},
        },
        "metadata": {
            "type": "object",
            "additionalProperties": True,
        },
    },
    "additionalProperties": False,
    "definitions": {
        "fact": {
            "type": "object",
            "required": [
                "id",
                "title",
                "summary",
                "domain",
                "tags",
                "embedding",
            ],
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "details": {"type": "string"},
                "domain": {"type": "string"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "sensitivity": {
                    "type": "object",
                    "properties": {
                        "level": {
                            "type": "string",
                            "enum": ["public", "personal", "sensitive"],
                        },
                        "reasons": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["level"],
                    "additionalProperties": False,
                },
                "source": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "bucket": {"type": "string"},
                        "mentions": {"type": "integer"},
                    },
                    "additionalProperties": True,
                },
                "last_updated": {"type": "string", "format": "date"},
                "embedding": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 4,
                },
                "attributes": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
            "additionalProperties": False,
        }
    },
}


def get_profile_schema() -> dict:
    """Return the JSON schema for profile validation."""

    return PROFILE_SCHEMA
