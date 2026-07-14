from fastapi import APIRouter, HTTPException, Request, status
from typing import List
from app.services.template_service import template_service
from app.models.schemas import Template, TemplateCreate, TemplateUpdate
from app.core.security import validate_template_id
from app.core.audit import log_event

router = APIRouter()


def _ensure_template_id(template_id: str) -> str:
    """Validate a user-supplied template id at the endpoint boundary, 400 on failure (K-3)."""
    try:
        return validate_template_id(template_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid template id")

@router.get("/", response_model=List[Template])
async def list_templates():
    """
    List all field configuration templates.
    """
    return template_service.list_templates()

@router.get("/{template_id}", response_model=Template)
async def get_template(template_id: str):
    """
    Get a specific template by ID.
    """
    _ensure_template_id(template_id)
    template = template_service.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template

@router.post("/", response_model=Template, status_code=status.HTTP_201_CREATED)
async def create_template(template_in: TemplateCreate, request: Request):
    """
    Create a new field configuration template.
    """
    template = template_service.create_template(template_in)
    log_event("config.template.create", target=template.id, request=request)
    return template

@router.put("/{template_id}", response_model=Template)
async def update_template(template_id: str, template_in: TemplateUpdate, request: Request):
    """
    Update an existing template.
    """
    _ensure_template_id(template_id)
    template = template_service.update_template(template_id, template_in)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    log_event("config.template.update", target=template_id, request=request)
    return template

@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(template_id: str, request: Request):
    """
    Delete a template.
    """
    _ensure_template_id(template_id)
    success = template_service.delete_template(template_id)
    if not success:
        raise HTTPException(status_code=404, detail="Template not found")
    log_event("config.template.delete", target=template_id, request=request)
    return
