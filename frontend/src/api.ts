import type { AIConfig, BrandingConfig, ISCConnection, ISCConnectionInput, ISCImportResult, ISCQueryResult, ISCTemplateType, Project, ProviderStatus, PublicationBatchPrepareItem, PublicationRecord, StyleGuide, TemplateDetail, TemplateSummary } from './types'

type ApiOptions = RequestInit & { timeoutMs?: number }

export class ApiRequestCancelled extends Error {
  constructor() { super('Solicitud cancelada.'); this.name = 'ApiRequestCancelled' }
}

export function formatApiErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail.map((entry) => {
      if (!entry || typeof entry !== 'object') return String(entry)
      const validation = entry as { loc?: unknown[]; msg?: unknown }
      const location = Array.isArray(validation.loc)
        ? validation.loc.filter((part) => part !== 'body').map(String).join(' → ')
        : ''
      const message = typeof validation.msg === 'string' ? validation.msg : 'Valor inválido'
      return location ? `${location}: ${message}` : message
    }).filter(Boolean)
    if (messages.length) return messages.map((message) => message.replace(/[.\s]+$/, '')).join('. ')
  }
  if (detail && typeof detail === 'object') {
    const object = detail as Record<string, unknown>
    if (typeof object.message === 'string') return object.message
    if (typeof object.detail === 'string') return object.detail
  }
  return fallback
}

async function fetchResponse(url: string, options: ApiOptions = {}): Promise<Response> {
  const { timeoutMs = 90_000, signal: externalSignal, ...fetchOptions } = options
  const controller = new AbortController()
  const externalAbort = () => controller.abort('external')
  if (externalSignal?.aborted) controller.abort('external')
  else externalSignal?.addEventListener('abort', externalAbort, { once: true })
  const timeout = window.setTimeout(() => controller.abort('timeout'), timeoutMs)
  let response: Response
  try {
    response = await fetch(url, {
      ...fetchOptions,
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...(fetchOptions.headers ?? {}) },
    })
  } catch (error) {
    if (controller.signal.aborted) {
      if (externalSignal?.aborted || controller.signal.reason === 'external') throw new ApiRequestCancelled()
      throw new Error('La operación superó el tiempo de espera. Verificá la conexión e intentá nuevamente.')
    }
    if (error instanceof TypeError) {
      throw new Error('No se pudo conectar con el backend. La aplicación local parece estar detenida; volvé a abrir “Iniciar app.cmd” y mantené su ventana abierta.')
    }
    throw error
  } finally {
    window.clearTimeout(timeout)
    externalSignal?.removeEventListener('abort', externalAbort)
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(formatApiErrorDetail(payload.detail, response.statusText || 'Ocurrió un error inesperado.'))
  }
  return response
}

async function request<T>(url: string, options?: ApiOptions): Promise<T> {
  const response = await fetchResponse(url, options)
  return response.json() as Promise<T>
}

async function download(url: string, filename: string): Promise<void> {
  const response = await fetchResponse(url)
  const blobUrl = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = blobUrl
  anchor.download = filename
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(blobUrl)
}

export const api = {
  project: (projectId: string) => request<Project>(`/api/projects/${projectId}`),
  import: (projectId: string, filename: string, data: unknown) =>
    request<{ templates: TemplateSummary[] }>(`/api/projects/${projectId}/import`, {
      method: 'POST',
      body: JSON.stringify({ filename, data }),
    }),
  iscConnections: (projectId: string) =>
    request<{ connections: ISCConnection[] }>(`/api/projects/${projectId}/isc-connections`),
  createISCConnection: (projectId: string, input: ISCConnectionInput) =>
    request<ISCConnection>(`/api/projects/${projectId}/isc-connections`, { method: 'POST', body: JSON.stringify(input) }),
  updateISCConnection: (projectId: string, connectionId: string, input: ISCConnectionInput) =>
    request<ISCConnection>(`/api/projects/${projectId}/isc-connections/${connectionId}`, { method: 'PUT', body: JSON.stringify(input) }),
  deleteISCConnection: (projectId: string, connectionId: string) =>
    request<{ deleted_id: string; name: string }>(`/api/projects/${projectId}/isc-connections/${connectionId}`, { method: 'DELETE' }),
  testISCConnection: (projectId: string, connectionId: string) =>
    request<{ authenticated: boolean; permissions: Record<string, string>; message: string; connection: ISCConnection }>(`/api/projects/${projectId}/isc-connections/${connectionId}/test`, { method: 'POST' }),
  listISCTemplates: (projectId: string, connectionId: string, templateType: ISCTemplateType) =>
    request<ISCQueryResult>(`/api/projects/${projectId}/isc-connections/${connectionId}/templates?template_type=${encodeURIComponent(templateType)}`),
  importISCTemplates: (projectId: string, connectionId: string, templateType: ISCTemplateType, templates: Record<string, unknown>[], duplicateStrategy: 'skip' | 'replace' | 'copy') =>
    request<ISCImportResult>(`/api/projects/${projectId}/isc-connections/${connectionId}/import`, { method: 'POST', body: JSON.stringify({ template_type: templateType, templates, duplicate_strategy: duplicateStrategy }) }),
  saveConfig: (projectId: string, config: BrandingConfig) =>
    request<{ config: BrandingConfig }>(`/api/projects/${projectId}/config`, {
      method: 'PUT',
      body: JSON.stringify(config),
    }),
  styleGuide: (projectId: string) => request<StyleGuide>(`/api/projects/${projectId}/style-guide`),
  saveStyleGuide: (projectId: string, content: string, filename: string) =>
    request<StyleGuide>(`/api/projects/${projectId}/style-guide`, { method: 'PUT', body: JSON.stringify({ content, filename }) }),
  deleteStyleGuide: (projectId: string) =>
    request<StyleGuide>(`/api/projects/${projectId}/style-guide`, { method: 'DELETE' }),
  saveAIConfig: (projectId: string, config: AIConfig, apiKey: string) =>
    request<{ ai_config: AIConfig; provider: ProviderStatus }>(`/api/projects/${projectId}/ai-config`, {
      method: 'PUT',
      body: JSON.stringify({ ...config, api_key: apiKey }),
    }),
  testAIConnection: (projectId: string, config: AIConfig, apiKey: string) =>
    request<{ status: 'connected'; message: string; provider: ProviderStatus }>(`/api/projects/${projectId}/ai-config/test`, {
      method: 'POST',
      body: JSON.stringify({ ...config, api_key: apiKey }),
      timeoutMs: 360_000,
    }),
  detail: (projectId: string, internalId: string, signal?: AbortSignal) =>
    request<TemplateDetail>(`/api/projects/${projectId}/templates/${internalId}`, { signal }),
  deleteTemplate: (projectId: string, internalId: string) =>
    request<{ deleted_id: string; name: string; templates: TemplateSummary[] }>(`/api/projects/${projectId}/templates/${internalId}`, { method: 'DELETE' }),
  clearTemplates: (projectId: string) =>
    request<{ deleted: number; templates: TemplateSummary[] }>(`/api/projects/${projectId}/templates`, { method: 'DELETE' }),
  adapt: (projectId: string, internalId: string) =>
    request<TemplateDetail>(`/api/projects/${projectId}/adapt`, {
      method: 'POST',
      body: JSON.stringify({ internal_id: internalId }),
      timeoutMs: 360_000,
    }),
  edit: (projectId: string, internalId: string, subject: string, body: string, editorMode: 'visual' | 'html') =>
    request<TemplateDetail>(`/api/projects/${projectId}/templates/${internalId}/result`, {
      method: 'PUT',
      body: JSON.stringify({ subject, body, editor_mode: editorMode }),
    }),
  preparePublicationBatch: (projectId: string, connectionId: string, internalIds: string[]) =>
    request<{ connection: ISCConnection; items: PublicationBatchPrepareItem[] }>(`/api/projects/${projectId}/publication/batches/prepare`, { method: 'POST', body: JSON.stringify({ connection_id: connectionId, internal_ids: internalIds }) }),
  publishPreparedBatch: (projectId: string, connectionId: string, items: Array<{ internal_id: string; preparation_id: string }>) =>
    request<{ items: Array<{ internal_id: string; status: string; publication?: PublicationRecord; error?: string }> }>(`/api/projects/${projectId}/publication/batches/publish`, { method: 'POST', body: JSON.stringify({ connection_id: connectionId, items }), timeoutMs: 360_000 }),
  verifyPublication: (projectId: string, internalId: string, connectionId: string, publicationId: string) =>
    request<PublicationRecord>(`/api/projects/${projectId}/templates/${internalId}/publication/verify`, { method: 'POST', body: JSON.stringify({ connection_id: connectionId, publication_id: publicationId }) }),
  downloadPublication: (projectId: string, internalId: string, key: string) =>
    download(`/api/projects/${projectId}/templates/${internalId}/publication/download`, `${key || 'template'}-isc-publication-payload.json`),
}
