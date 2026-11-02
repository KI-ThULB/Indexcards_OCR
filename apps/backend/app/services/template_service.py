from functools import wraps
import uuid
from pathlib import Path
from typing import List, Optional
from app.core.config import settings
from app.core.registry import RegistryError, read_registry, write_registry
from app.core.security import validate_template_id
from app.core.transactions import Resource
from app.services.batch_manager import batch_manager
from app.models.schemas import Template, TemplateCreate, TemplateUpdate

def _mutation(operation):
    @wraps(operation)
    def coordinated(self, *args, **kwargs):
        return batch_manager._registry_coordinator().run_sync(
            [Resource.templates()], lambda: operation(self, *args, **kwargs)
        )
    return coordinated


class TemplateService:
    def __init__(self, templates_file: str = settings.TEMPLATES_FILE):
        self.templates_file = Path(templates_file)

    @staticmethod
    def _validate(templates):
        if not isinstance(templates, list):
            raise RegistryError()
        identifiers = set()
        for item in templates:
            try:
                if not isinstance(item, dict):
                    raise ValueError()
                template = Template(**item)
                validate_template_id(template.id)
                if template.id in identifiers:
                    raise ValueError()
                identifiers.add(template.id)
            except Exception:
                raise RegistryError() from None

    def _read_templates(self) -> List[dict]:
        return read_registry(self.templates_file, self._validate)

    def _save_templates(self, templates: List[dict]):
        write_registry(self.templates_file, templates, self._validate)

    def list_templates(self) -> List[Template]:
        templates_data = self._read_templates()
        return [Template(**t) for t in templates_data]

    def get_template(self, template_id: str) -> Optional[Template]:
        validate_template_id(template_id)
        templates = self._read_templates()
        for t in templates:
            if t["id"] == template_id:
                return Template(**t)
        return None

    @_mutation
    def create_template(self, template_in: TemplateCreate) -> Template:
        return self._create_template(template_in)

    @_mutation
    def ensure_named(self, template_in: TemplateCreate) -> bool:
        if any(t["name"] == template_in.name for t in self._read_templates()):
            return False
        self._create_template(template_in)
        return True

    def _create_template(self, template_in: TemplateCreate) -> Template:
        templates = self._read_templates()
        new_template = Template(
            id=str(uuid.uuid4()),
            name=template_in.name,
            fields=template_in.fields,
            prompt_template=template_in.prompt_template,
            field_rules=template_in.field_rules,
            authority_bindings=template_in.authority_bindings,  # Phase 12 Fix 1
            field_groups=template_in.field_groups,               # repeatable groups
            describe_pictures=template_in.describe_pictures,
        )
        templates.append(new_template.dict())
        self._save_templates(templates)
        return new_template

    @_mutation
    def update_template(self, template_id: str, template_in: TemplateUpdate) -> Optional[Template]:
        validate_template_id(template_id)
        templates = self._read_templates()
        for i, t in enumerate(templates):
            if t["id"] == template_id:
                if template_in.name is not None:
                    templates[i]["name"] = template_in.name
                if template_in.fields is not None:
                    templates[i]["fields"] = template_in.fields
                if template_in.prompt_template is not None:
                    templates[i]["prompt_template"] = template_in.prompt_template
                if template_in.field_rules is not None:
                    templates[i]["field_rules"] = template_in.field_rules
                if template_in.authority_bindings is not None:  # Phase 12 Fix 1
                    templates[i]["authority_bindings"] = {
                        k: (v.dict() if hasattr(v, "dict") else v)
                        for k, v in template_in.authority_bindings.items()
                    }
                if template_in.field_groups is not None:
                    templates[i]["field_groups"] = {
                        k: (v.dict() if hasattr(v, "dict") else v)
                        for k, v in template_in.field_groups.items()
                    }
                if template_in.describe_pictures is not None:
                    templates[i]["describe_pictures"] = template_in.describe_pictures
                self._save_templates(templates)
                return Template(**templates[i])
        return None

    @_mutation
    def delete_template(self, template_id: str) -> bool:
        validate_template_id(template_id)
        templates = self._read_templates()
        initial_count = len(templates)
        templates = [t for t in templates if t["id"] != template_id]
        if len(templates) < initial_count:
            self._save_templates(templates)
            return True
        return False

template_service = TemplateService()
