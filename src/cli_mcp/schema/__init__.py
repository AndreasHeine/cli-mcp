"""Schema layer: JSON Schema generation, argument validation, docs and OpenAPI."""

from __future__ import annotations

from cli_mcp.schema.docgen import command_section, parameter_summary, render_docs
from cli_mcp.schema.jsonschema import (
    argument_name,
    cli_hint,
    coerce_choices,
    execution_result_schema,
    input_schema,
    parameter_schema,
)
from cli_mcp.schema.openapi import OPENAPI_VERSION, build_openapi, tool_endpoint
from cli_mcp.schema.validate import validate_arguments

__all__ = [
    "OPENAPI_VERSION",
    "argument_name",
    "build_openapi",
    "cli_hint",
    "coerce_choices",
    "command_section",
    "execution_result_schema",
    "input_schema",
    "parameter_schema",
    "parameter_summary",
    "render_docs",
    "tool_endpoint",
    "validate_arguments",
]
