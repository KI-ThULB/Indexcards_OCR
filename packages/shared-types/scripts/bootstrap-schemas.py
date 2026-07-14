#!/usr/bin/env python3
"""
One-time bootstrap: extract JSON Schema from existing Pydantic models.
Run from repo root: python packages/shared-types/scripts/bootstrap-schemas.py

After running, the generated .schema.json files become the source of truth.
Edit them directly for future changes, NOT the Pydantic models.
"""
import json
import re
import sys
import os

# Add backend to path so we can import models
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'apps', 'backend'))

from app.models.schemas import (
    HealthCheck, ExtractionResult, BatchConfig, BatchCreate,
    BatchResponse, BatchHistory, UploadResponse,
    Template, TemplateCreate, TemplateUpdate, BatchProgress
)

SCHEMAS_DIR = os.path.join(os.path.dirname(__file__), '..', 'schemas')
os.makedirs(SCHEMAS_DIR, exist_ok=True)

def fix_refs(obj):
    """Recursively rewrite Pydantic v2 $defs refs to draft-07 definitions refs."""
    if isinstance(obj, dict):
        return {
            k: re.sub(r'^#/\$defs/', '#/definitions/', v) if k == '$ref' and isinstance(v, str) else fix_refs(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [fix_refs(item) for item in obj]
    return obj

# Group models by domain
groups = {
    'health': [HealthCheck],
    'batch': [BatchConfig, BatchCreate, BatchResponse, BatchHistory, ExtractionResult],
    'upload': [UploadResponse],
    'template': [Template, TemplateCreate, TemplateUpdate],
    'progress': [BatchProgress],
}

for group_name, models in groups.items():
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"{group_name.capitalize()} API Types",
        "definitions": {}
    }
    for model in models:
        model_schema = model.model_json_schema()
        # Remove the top-level $defs if present (Pydantic v2 puts refs there)
        defs = model_schema.pop('$defs', {})
        schema['definitions'][model.__name__] = model_schema
        # Merge any nested $defs
        for def_name, def_schema in defs.items():
            schema['definitions'][def_name] = def_schema

    # Fix Pydantic v2 $defs refs to draft-07 definitions refs throughout
    schema = fix_refs(schema)

    outpath = os.path.join(SCHEMAS_DIR, f'{group_name}.schema.json')
    with open(outpath, 'w') as f:
        json.dump(schema, f, indent=2)
    print(f'  Written: {outpath}')

print(f'\nBootstrap complete. {len(groups)} schema files created.')
print('These are now the source of truth. Edit .schema.json files for future changes.')
