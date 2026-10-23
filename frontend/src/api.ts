import type { AIConfig, AuthUser, BrandingConfig, ISCConnection, ISCConnectionInput, ISCImportResult, ISCQueryResult, ISCTemplateType, LocalImportResult, Project, ProviderStatus, PublicationBatchPrepareItem, PublicationRecord, StyleGuide, TemplateDetail, TemplateSummary } from './types'

type ApiOptions = RequestInit & { timeoutMs?: number }
let projectVersion: number | null = null
let styleGuideVersion: number | null = null

export function setProjectVersion(version: number | null) { projectVersion = version }

function cookie(name: string): string {
  return document.cookie.split(';').map((part) => part.trim()).find((part) => part.startsWith(`${name}=`))?.slice(name.length + 1) ?? ''
}

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
      credentials: 'same-origin',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(fetchOptions.method && !['GET', 'HEAD'].includes(fetchOptions.method) ? { 'X-CSRF-Token': decodeURIComponent(cookie('isc_email_generator_csrf')) } : {}),
        ...(projectVersion !== null && fetchOptions.method && !['GET', 'HEAD'].includes(fetchOptions.method) ? { 'X-Project-Version': String(projectVersion) } : {}),
        ...(fetchOptions.headers ?? {}),
      },
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
    if (response.status === 401) window.dispatchEvent(new Event('isc-auth-required'))
    throw new Error(formatApiErrorDetail(payload.detail, response.statusText || 'Ocurrió un error inesperado.'))
  }
  const nextVersion = response.headers.get('X-Project-Version')
  if (nextVersion !== null && /^\d+$/.test(nextVersion)) projectVersion = Number(nextVersion)
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
  health: () => request<{ status: string; server_mode?: boolean }>('/api/health'),
  me: () => request<{ user: AuthUser }>('/api/auth/me'),
  login: (username: string, password: string) => request<{ user: AuthUser; csrf_token: string }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  logout: () => request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }),
  changePassword: (currentPassword: string, newPassword: string) => request<{ ok: boolean; reauthenticate: boolean }>('/api/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) }),
  users: () => request<{ users: AuthUser[] }>('/api/admin/users'),
  createUser: (username: string, temporaryPassword: string, role: 'admin' | 'user') => request<{ user: AuthUser }>('/api/admin/users', { method: 'POST', body: JSON.stringify({ username, temporary_password: temporaryPassword, role }) }),
  resetUserPassword: (userId: string, temporaryPassword: string) => request<{ ok: boolean }>(`/api/admin/users/${userId}/reset-password`, { method: 'POST', body: JSON.stringify({ temporary_password: temporaryPassword }) }),
  setUserActive: (userId: string, active: boolean) => request<{ ok: boolean }>(`/api/admin/users/${userId}/active`, { method: 'PUT', body: JSON.stringify({ active }) }),
  project: async (projectId: string) => { const project = await request<Project>(`/api/projects/${projectId}`); setProjectVersion(project.project_version); return project },
  import: (projectId: string, filename: string, data: unknown) =>
    request<LocalImportResult>(`/api/projects/${projectId}/import`, {
      method: 'POST',
      body: JSON.stringify({ filename, data }),
    }),
  importFiles: (projectId: string, files: { filename: string; data: unknown }[], duplicateStrategy: 'skip' | 'copy') =>
    request<LocalImportResult>(`/api/projects/${projectId}/import`, {
      method: 'POST',
      body: JSON.stringify({ files, duplicate_strategy: duplicateStrategy }),
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
  styleGuide: async (projectId: string) => { const guide = await request<StyleGuide>(`/api/projects/${projectId}/style-guide`); styleGuideVersion = guide.version ?? 0; return guide },
  saveStyleGuide: (projectId: string, content: string, filename: string) =>
    request<StyleGuide>(`/api/projects/${projectId}/style-guide`, { method: 'PUT', headers: styleGuideVersion === null ? {} : { 'X-Style-Guide-Version': String(styleGuideVersion) }, body: JSON.stringify({ content, filename }) }).then((guide) => { styleGuideVersion = guide.version ?? null; return guide }),
  deleteStyleGuide: (projectId: string) =>
    request<StyleGuide>(`/api/projects/${projectId}/style-guide`, { method: 'DELETE', headers: styleGuideVersion === null ? {} : { 'X-Style-Guide-Version': String(styleGuideVersion) } }).then((guide) => { styleGuideVersion = guide.version ?? null; return guide }),
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
  updateDateTranslation: (projectId: string, internalId: string, enabled: boolean) =>
    request<TemplateDetail>(`/api/projects/${projectId}/templates/${internalId}/date-translation`, {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
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
