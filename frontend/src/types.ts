export type MappingEntry = { source: string; target: string }

export type AIProviderId = 'simulated' | 'gemini' | 'groq' | 'anthropic' | 'openai' | 'openai_compatible'
export type AIConfig = { provider: AIProviderId; model: string; base_url: string }
export type ProviderStatus = {
  id: AIProviderId
  name: string
  model: string
  base_url: string
  simulated: boolean
  key_configured: boolean
  connection: { status: 'not_tested' | 'connected' | 'error'; message: string }
}

export type BrandingConfig = {
  target_language: string
  generate_missing_title: boolean
  old_client_name: string
  new_client_name: string
  product_display_name: string
  old_logo_url: string
  new_logo_url: string
  color_instructions: string
  color_mappings: MappingEntry[]
  greeting: string
  treatment: string
  signature: string
  email_mappings: MappingEntry[]
  url_mappings: MappingEntry[]
  additional_instructions: string
  mode: 'preserve' | 'guide'
}

export type StyleGuide = {
  configured: boolean
  content: string
  filename: string
  updated_at: string | null
  hash: string
  warnings: string[]
}

export type TemplateSummary = {
  internal_id: string
  name: string
  key: string
  medium: string
  locale: string
  has_result: boolean
  config_outdated: boolean
  unsafe_result: boolean
  local_copy: boolean
  source_filename: string
  provenance?: ISCProvenance | null
  publication_states: PublicationStateSummary[]
}

export type LocalImportResult = {
  imported: number
  skipped: number
  copied: number
  internal_ids: string[]
  valid_files: { filename: string; templates: number }[]
  rejected_files: { filename: string; error: string }[]
  templates: TemplateSummary[]
}

export type ISCEnvironment = 'sandbox' | 'production' | 'demo'
export type ISCTemplateType = 'standard' | 'custom'
export type ISCConnectionStatus = 'not_tested' | 'connected' | 'limited' | 'error'
export type ISCConnection = {
  id: string
  name: string
  environment: ISCEnvironment
  api_base_url: string
  client_id_configured: boolean
  secret_configured: boolean
  status: ISCConnectionStatus
  status_message: string
}
export type ISCConnectionInput = {
  name: string
  environment: ISCEnvironment
  api_base_url: string
  client_id: string
  client_secret: string
}
export type ISCProvenance = {
  connection_id: string
  connection_name: string
  api_base_url: string
  environment: ISCEnvironment
  template_type: ISCTemplateType
  read_at: string
}
export type ISCTemplateCandidate = {
  selection_id: string
  name: string
  key: string
  medium: string
  locale: string
  template: Record<string, unknown>
}
export type ISCQueryResult = {
  connection: ISCConnection
  template_type: ISCTemplateType
  read_at: string
  templates: ISCTemplateCandidate[]
}
export type ISCImportResult = {
  imported: number
  skipped: number
  replaced: number
  copied: number
  adaptations_removed: number
  internal_ids: string[]
  templates: TemplateSummary[]
}

export type Validation = {
  missing_variables: string[]
  added_variables: string[]
  repeated_variables?: string[]
  original_directives: string[]
  result_directives: string[]
  missing_directives: string[]
  added_directives: string[]
  directive_order_changed?: boolean
  modified_protected_blocks?: string[]
  pending_old_client_references: string[]
  suspicious: boolean
  disclaimer: string
}

export type TemplateDetail = {
  internal_id: string
  original: Record<string, unknown>
  result: Record<string, unknown> | null
  original_subject: string
  original_body: string
  result_subject: string | null
  result_body: string | null
  validation: Validation | null
  protected_velocity_blocks: string[]
  date_translation: {
    applied: boolean
    removable: boolean
    variables: string[]
    available_variables: string[]
    language_supported: boolean
  }
  actions: string[]
  config_outdated: boolean
  provenance?: ISCProvenance | null
  publication_preparation?: PublicationPreparation | null
  publication_history: PublicationRecord[]
}

export type PublicationPreparation = {
  preparation_id: string
  prepared_at: string
  connection: Pick<ISCConnection, 'id' | 'name' | 'environment' | 'api_base_url'>
  identity: { key: string; medium: string; locale: string }
  name: string
  mode: 'replace_custom' | 'create_from_default'
  target_current: Record<string, unknown>
  payload: Record<string, unknown>
  warnings: string[]
  validation: Validation | null
}

export type PublicationRecord = {
  publication_id: string
  published_at: string
  status: 'published_pending_verification' | 'published_verified' | 'published_with_differences' | 'result_unconfirmed'
  connection: PublicationPreparation['connection']
  identity: PublicationPreparation['identity']
  preparation_id: string
  backup_id: string
  write_acknowledged: boolean
  local_signature?: string
  payload?: Record<string, unknown>
  response: Record<string, unknown> | null
  verification: Record<string, unknown> | null
  differences: string[]
  message: string
}

export type PublicationStateSummary = Pick<PublicationRecord, 'publication_id' | 'status' | 'connection' | 'message' | 'differences'> & {
  applies_to_current_result: boolean
}

export type PublicationBatchPrepareItem = {
  internal_id: string
  status: 'ready' | 'blocked'
  preparation?: PublicationPreparation
  error?: string
}

export type Project = {
  project_id: string
  filename: string
  config: BrandingConfig
  ai_config: AIConfig
  templates: TemplateSummary[]
  provider: ProviderStatus
}
