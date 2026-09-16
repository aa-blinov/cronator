"""TDD tests for F9: OpenAPI examples in Pydantic schemas.

Every public schema in /api/scripts should have at least one `example` so the
Swagger UI renders useful request/response samples instead of empty schemas.
"""

import pytest


@pytest.mark.asyncio
async def test_openapi_spec_available(test_client):
    r = await test_client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert "paths" in spec
    assert "components" in spec


@pytest.mark.asyncio
async def test_script_create_schema_has_example(test_client):
    """The POST /api/scripts request body schema (or its $ref target) must have an example."""
    spec = (await test_client.get("/openapi.json")).json()
    # Walk: paths → /api/scripts → post → requestBody → content → application/json → schema
    schema = spec["paths"]["/api/scripts"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    # Resolve $ref if needed (FastAPI emits $ref + inline schema_extra at component level)
    if "$ref" in schema:
        ref_name = schema["$ref"].rsplit("/", 1)[-1]
        resolved = spec["components"]["schemas"].get(ref_name, {})
        assert "example" in resolved or "examples" in resolved, (
            f"referenced schema {ref_name} has no example: {resolved}"
        )
    else:
        assert "example" in schema or "examples" in schema, f"script create schema has no example: {schema}"


@pytest.mark.asyncio
async def test_all_post_schemas_have_examples(test_client):
    """Every POST/PUT/PATCH endpoint WITH a JSON request body must expose an example.

    Examples may be present at either of these levels:
      - schema.example / schema.examples (in components after $ref resolution)
      - content-level example / examples (set via openapi_extra)
    """
    spec = (await test_client.get("/openapi.json")).json()
    missing = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            if method.upper() not in ("POST", "PUT", "PATCH"):
                continue
            rb = op.get("requestBody", {})
            content = rb.get("content", {}).get("application/json", {})
            schema = content.get("schema", {})
            # Skip endpoints that legitimately don't have a body (action endpoints)
            if not schema:
                continue
            # Check 1: example at the content level (openapi_extra style)
            if "example" in content or "examples" in content:
                continue
            # Check 2: example on the schema (component-level resolution)
            resolved_schema = schema
            if "$ref" in schema:
                ref = schema["$ref"].rsplit("/", 1)[-1]
                resolved_schema = spec["components"]["schemas"].get(ref, {})
            if "example" in resolved_schema or "examples" in resolved_schema:
                continue
            missing.append(f"{method.upper()} {path}")
    assert not missing, f"endpoints with body missing examples: {missing}"
