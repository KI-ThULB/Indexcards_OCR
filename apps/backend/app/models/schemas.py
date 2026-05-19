from pydantic import BaseModel
from typing import List, Dict, Optional

class HealthCheck(BaseModel):
    status: str
    version: str

class FieldRule(BaseModel):
    preset_id: Optional[str] = None
    pattern: Optional[str] = None
    vocabulary: Optional[List[str]] = None
    fuzzy_distance: Optional[int] = None
    corrector_enabled: bool = False

class ReconciliationOutcome(BaseModel):
    authority: str
    uri: str
    label: str
    picked_by: str   # "auto" | "manual"
    picked_at: str   # ISO date string

class AuthorityBinding(BaseModel):
    type: Optional[str] = None  # AuthorityType string or null

class ValidationOutcome(BaseModel):
    status: str  # "valid" | "invalid" | "corrected" | "skipped" | "verified"
    rule_failed: Optional[str] = None
    original_value: Optional[str] = None
    rationale: Optional[str] = None
    corrector_proposal: Optional[str] = None
    reconciliation: Optional[ReconciliationOutcome] = None  # NEW — independent of status dimension

class BatchHistoryItem(BaseModel):
    batch_name: str
    custom_name: str
    created_at: str
    status: str
    files_count: int
    fields: List[str]
    has_errors: bool = False
    error_count: int = 0

class ExtractionResult(BaseModel):
    filename: str
    batch: str
    success: bool
    data: Optional[Dict[str, str]] = None
    error: Optional[str] = None
    duration: float
    validation: Optional[Dict[str, ValidationOutcome]] = None
    edited_data: Optional[Dict[str, str]] = None  # Phase 9 PATCH writes curator edits; Phase 12 adds round-trip read

class BatchConfig(BaseModel):
    fields: List[str]
    prompt_template: Optional[str] = None
    field_rules: Optional[Dict[str, FieldRule]] = None
    corrector_enabled: bool = False
    corrector_cap: Optional[int] = 100
    authority_bindings: Optional[Dict[str, AuthorityBinding]] = None  # Phase 11

class BatchCreate(BaseModel):
    custom_name: str
    session_id: str
    fields: Optional[List[str]] = None
    prompt_template: Optional[str] = None
    field_rules: Optional[Dict[str, FieldRule]] = None
    corrector_enabled: bool = False
    corrector_cap: Optional[int] = 100
    authority_bindings: Optional[Dict[str, AuthorityBinding]] = None  # Phase 11

class BatchResponse(BaseModel):
    batch_name: str
    status: str
    files_count: int

class BatchHistory(BaseModel):
    batch_name: str
    status: str
    created_at: str
    files_count: int
    fields: List[str]

class UploadResponse(BaseModel):
    session_id: str
    filenames: List[str]
    message: str

class Template(BaseModel):
    id: str
    name: str
    fields: List[str]
    prompt_template: Optional[str] = None
    field_rules: Optional[Dict[str, FieldRule]] = None
    authority_bindings: Optional[Dict[str, AuthorityBinding]] = None  # Phase 11

class TemplateCreate(BaseModel):
    name: str
    fields: List[str]
    prompt_template: Optional[str] = None
    field_rules: Optional[Dict[str, FieldRule]] = None
    authority_bindings: Optional[Dict[str, AuthorityBinding]] = None  # Phase 11

class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    fields: Optional[List[str]] = None
    prompt_template: Optional[str] = None
    field_rules: Optional[Dict[str, FieldRule]] = None
    authority_bindings: Optional[Dict[str, AuthorityBinding]] = None  # Phase 11

class BatchProgress(BaseModel):
    batch_name: str
    current: int
    total: int
    percentage: float
    eta_seconds: Optional[float] = None
    last_result: Optional[ExtractionResult] = None
    status: str # "running", "completed", "failed", "retrying"
    error: Optional[str] = None  # Human-readable error message for "failed" status

class BatchStartRequest(BaseModel):
    provider: str = "openrouter"  # "openrouter" | "ollama"
    model: Optional[str] = None   # None → provider default

class AuditEntry(BaseModel):
    id: str
    ts: str          # ISO timestamp string
    op: str          # 'bulk-transform' | 'cluster-merge'
    column: str
    label: str       # human-readable: "Upper on 42 rows"
    affected: int
    scope: str       # 'all' | 'faceted'
    facet_description: Optional[str] = None
    source: str      # 'bulk-transform' | 'cluster-merge'

class ResultPatch(BaseModel):
    field: str
    value: Optional[str] = None
    validation_status: Optional[str] = None  # 'verified' | 'valid' | 'invalid' | null
    reconciliation: Optional[dict] = None    # ReconciliationOutcome dict — set a new outcome
    clear_reconciliation: bool = False        # True → explicitly clear (set to null); takes priority over reconciliation
    # Convention (version-independent, agreed between frontend and backend):
    #   clear_reconciliation=True → set reconciliation to null (clear it)
    #   reconciliation=<dict>     → set a new ReconciliationOutcome
    #   neither                   → leave reconciliation unchanged
    audit_entry: Optional[dict] = None   # AuditEntry dict, appended to checkpoint["audit"] once
