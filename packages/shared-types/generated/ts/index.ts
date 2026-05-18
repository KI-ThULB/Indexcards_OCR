// AUTO-GENERATED from JSON Schema — do not edit manually
// Regenerate with: turbo generate (or npm run generate in packages/shared-types)
export interface FieldRule {
  preset_id?: string | null
  pattern?: string | null
  vocabulary?: string[] | null
  fuzzy_distance?: number | null
  corrector_enabled?: boolean
}

export interface ValidationOutcome {
  status: string
  rule_failed?: string | null
  original_value?: string | null
  rationale?: string | null
  corrector_proposal?: string | null
}

export interface BatchConfig {
  fields: string[]
  prompt_template?: string | null
  field_rules?: { [k: string]: FieldRule } | null
  corrector_enabled?: boolean
  corrector_cap?: number | null
}

export interface BatchCreate {
  custom_name: string
  session_id: string
  fields?: string[] | null
  prompt_template?: string | null
  field_rules?: { [k: string]: FieldRule } | null
  corrector_enabled?: boolean
  corrector_cap?: number | null
}

export interface BatchResponse {
  batch_name: string
  status: string
  files_count: number
}

export interface BatchHistory {
  batch_name: string
  status: string
  created_at: string
  files_count: number
  fields: string[]
}

export interface ExtractionResult {
  filename: string
  batch: string
  success: boolean
  data?: { [k: string]: string } | null
  error?: string | null
  duration: number
  validation?: { [k: string]: ValidationOutcome } | null
}

export interface HealthCheck {
  status: string
  version: string
}

export interface BatchProgress {
  batch_name: string
  current: number
  total: number
  percentage: number
  eta_seconds?: number | null
  last_result?: ExtractionResult | null
  status: string
}

export interface Template {
  id: string
  name: string
  fields: string[]
  prompt_template?: string | null
  field_rules?: { [k: string]: FieldRule } | null
}

export interface TemplateCreate {
  name: string
  fields: string[]
  prompt_template?: string | null
  field_rules?: { [k: string]: FieldRule } | null
}

export interface TemplateUpdate {
  name?: string | null
  fields?: string[] | null
  prompt_template?: string | null
  field_rules?: { [k: string]: FieldRule } | null
}

export interface UploadResponse {
  session_id: string
  filenames: string[]
  message: string
}
