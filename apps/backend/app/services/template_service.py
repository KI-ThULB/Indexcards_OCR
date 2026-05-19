import json
import uuid
from pathlib import Path
from typing import List, Optional
from app.core.config import settings
from app.models.schemas import Template, TemplateCreate, TemplateUpdate

class TemplateService:
    def __init__(self, templates_file: str = settings.TEMPLATES_FILE):
        self.templates_file = Path(templates_file)
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not self.templates_file.exists():
            self.templates_file.parent.mkdir(parents=True, exist_ok=True)
            with self.templates_file.open("w") as f:
                json.dump([], f)

    def _read_templates(self) -> List[dict]:
        with self.templates_file.open("r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []

    def _save_templates(self, templates: List[dict]):
        with self.templates_file.open("w") as f:
            json.dump(templates, f, indent=2)

    def list_templates(self) -> List[Template]:
        templates_data = self._read_templates()
        return [Template(**t) for t in templates_data]

    def get_template(self, template_id: str) -> Optional[Template]:
        templates = self._read_templates()
        for t in templates:
            if t["id"] == template_id:
                return Template(**t)
        return None

    def create_template(self, template_in: TemplateCreate) -> Template:
        templates = self._read_templates()
        new_template = Template(
            id=str(uuid.uuid4()),
            name=template_in.name,
            fields=template_in.fields,
            prompt_template=template_in.prompt_template,
            field_rules=template_in.field_rules,
            authority_bindings=template_in.authority_bindings,  # Phase 12 Fix 1
        )
        templates.append(new_template.dict())
        self._save_templates(templates)
        return new_template

    def update_template(self, template_id: str, template_in: TemplateUpdate) -> Optional[Template]:
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
                self._save_templates(templates)
                return Template(**templates[i])
        return None

    def delete_template(self, template_id: str) -> bool:
        templates = self._read_templates()
        initial_count = len(templates)
        templates = [t for t in templates if t["id"] != template_id]
        if len(templates) < initial_count:
            self._save_templates(templates)
            return True
        return False

template_service = TemplateService()
