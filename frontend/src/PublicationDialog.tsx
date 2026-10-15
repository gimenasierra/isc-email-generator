import { useMemo, useState } from 'react'
import { api } from './api'
import type { ISCConnection, PublicationBatchPrepareItem, PublicationRecord, TemplateSummary } from './types'
import { ENVIRONMENT_LABELS, PROJECT_ID } from './constants'

type PublishState = { kind: PublicationRecord['status'] | 'publishing' | 'failed' | 'modified'; text: string; publicationId?: string }

const LOCKED_STATES = new Set<PublishState['kind']>([
  'published_pending_verification',
  'published_verified',
  'published_with_differences',
  'result_unconfirmed',
  'publishing',
])

function isLocked(kind?: PublishState['kind']) { return Boolean(kind && LOCKED_STATES.has(kind)) }

function publicationLabel(record: Pick<PublicationRecord, 'status' | 'message' | 'differences'>) {
  if (record.status === 'published_verified') return 'Publicada y verificada'
  if (record.status === 'published_with_differences') return `Publicada con diferencias: ${record.differences.join(', ')}`
  if (record.status === 'published_pending_verification') return `Publicada · verificación pendiente${record.message ? `: ${record.message}` : ''}`
  return `Resultado no confirmado${record.message ? `: ${record.message}` : ''}`
}

function statesForConnection(templates: TemplateSummary[], connectionId: string): Record<string, PublishState> {
  const entries: Array<[string, PublishState]> = []
  for (const template of templates) {
    const record = template.publication_states?.find((candidate) => candidate.connection.id === connectionId)
    if (!record) continue
    if (!record.applies_to_current_result) {
      entries.push([template.internal_id, { kind: 'modified', text: 'Modificada después de publicar · prepará nuevamente.' }])
      continue
    }
    entries.push([template.internal_id, {
      kind: record.status,
      text: publicationLabel(record),
      publicationId: record.publication_id,
    }])
  }
  return Object.fromEntries(entries)
}

function text(value: unknown) { return typeof value === 'string' ? value : '' }

export function PublicationDialog({ connections, templates, initialId, intent, onClose, onPublished }: { connections: ISCConnection[]; templates: TemplateSummary[]; initialId: string; intent: 'download' | 'publish'; onClose: () => void; onPublished: () => void }) {
  const eligible = useMemo(() => templates.filter((template) => template.has_result && !template.unsafe_result && !template.config_outdated), [templates])
  const initialConnectionId = connections[0]?.id ?? ''
  const persistedInitialStates = statesForConnection(templates, initialConnectionId)
  const requestedInitial = eligible.find((template) => template.internal_id === initialId)
  const initialSelection = requestedInitial
    ? (isLocked(persistedInitialStates[requestedInitial.internal_id]?.kind) ? '' : requestedInitial.internal_id)
    : eligible.find((template) => !isLocked(persistedInitialStates[template.internal_id]?.kind))?.internal_id ?? ''
  const [connectionId, setConnectionId] = useState(initialConnectionId)
  const [selected, setSelected] = useState<Set<string>>(new Set(initialSelection ? [initialSelection] : []))
  const [prepared, setPrepared] = useState<PublicationBatchPrepareItem[]>([])
  const [reviewId, setReviewId] = useState(initialSelection)
  const [states, setStates] = useState<Record<string, PublishState>>(persistedInitialStates)
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const connection = connections.find((candidate) => candidate.id === connectionId)
  const ready = prepared.filter((entry) => entry.status === 'ready' && entry.preparation)
  const review = ready.find((entry) => entry.internal_id === reviewId) ?? ready[0]
  const failed = ready.filter((entry) => states[entry.internal_id]?.kind === 'failed')
  const publishable = ready.filter((entry) => {
    const kind = states[entry.internal_id]?.kind
    return !kind || kind === 'modified'
  })
  const verifiable = eligible.filter((entry) => {
    const state = states[entry.internal_id]
    return ['published_pending_verification', 'result_unconfirmed'].includes(state?.kind ?? '') && state?.publicationId
  })

  const invalidate = () => { setPrepared([]); setStates(statesForConnection(templates, connectionId)); setNotice(null) }
  const toggle = (id: string) => { setSelected((current) => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next }); invalidate() }
  const prepare = async () => {
    if (!connectionId || !selected.size) return
    setBusy('prepare'); setNotice(null); setStates(statesForConnection(templates, connectionId))
    try {
      const response = await api.preparePublicationBatch(PROJECT_ID, connectionId, [...selected])
      setPrepared(response.items)
      const firstReady = response.items.find((entry) => entry.status === 'ready')
      if (firstReady) setReviewId(firstReady.internal_id)
      const blocked = response.items.filter((entry) => entry.status === 'blocked').length
      setNotice({ kind: blocked ? 'error' : 'ok', text: `${response.items.length - blocked} lista(s) para revisión. ${blocked ? `${blocked} bloqueada(s); revisá el detalle.` : 'La preparación no escribió nada en ISC.'}` })
    } catch (error) { setNotice({ kind: 'error', text: (error as Error).message }) } finally { setBusy('') }
  }
  const publish = async (retryOnly = false) => {
    if (!connection) return
    const candidates = retryOnly ? failed : publishable
    if (!candidates.length) return
    const confirmation = `Destino: ${connection.name}\nAmbiente: ${ENVIRONMENT_LABELS[connection.environment]}\nURL: ${connection.api_base_url}\n\nSe publicarán ${candidates.length} plantilla(s), una por una. El lote no es una transacción y puede quedar parcialmente completado. ¿Continuar?`
    if (!window.confirm(confirmation)) return
    setBusy('publish'); setNotice(null)
    setStates((current) => Object.fromEntries(Object.entries(current).concat(candidates.map((entry, index) => [entry.internal_id, { kind: 'publishing', text: `Publicando ${index + 1} de ${candidates.length}…` } as PublishState]))))
    let failedCount = 0
    try {
      const response = await api.publishPreparedBatch(PROJECT_ID, connectionId, candidates.map((entry) => ({ internal_id: entry.internal_id, preparation_id: entry.preparation!.preparation_id })))
      for (const entry of candidates) {
        const outcome = response.items.find((item) => item.internal_id === entry.internal_id)
        if (outcome?.publication) {
          const record = outcome.publication
          setStates((current) => ({ ...current, [entry.internal_id]: { kind: record.status, text: publicationLabel(record), publicationId: record.publication_id } }))
          setSelected((current) => { const next = new Set(current); next.delete(entry.internal_id); return next })
        } else {
          failedCount += 1
          setStates((current) => ({ ...current, [entry.internal_id]: { kind: 'failed', text: outcome?.error ?? 'ISC no devolvió un resultado para esta plantilla.' } }))
        }
      }
    } catch (error) {
      failedCount = candidates.length
      setStates((current) => ({ ...current, ...Object.fromEntries(candidates.map((entry) => [entry.internal_id, { kind: 'failed', text: (error as Error).message } as PublishState])) }))
    } finally {
      setBusy(''); onPublished()
    }
    setNotice({ kind: failedCount ? 'error' : 'ok', text: failedCount ? `El lote terminó con ${failedCount} falla(s). Las exitosas no se volverán a publicar al reintentar.` : 'Publicación terminada. Revisá el estado individual de cada plantilla.' })
  }
  const verifyUnconfirmed = async () => {
    if (!connection || !verifiable.length) return
    setBusy('verify'); setNotice(null)
    let stillUnconfirmed = 0
    for (const entry of verifiable) {
      const publicationId = states[entry.internal_id].publicationId!
      try {
        const record = await api.verifyPublication(PROJECT_ID, entry.internal_id, connectionId, publicationId)
        if (['published_pending_verification', 'result_unconfirmed'].includes(record.status)) stillUnconfirmed += 1
        setStates((current) => ({ ...current, [entry.internal_id]: { kind: record.status, text: publicationLabel(record), publicationId } }))
      } catch (error) {
        stillUnconfirmed += 1
        setStates((current) => ({ ...current, [entry.internal_id]: { ...current[entry.internal_id], text: (error as Error).message } }))
      }
    }
    setBusy(''); onPublished()
    setNotice({ kind: stillUnconfirmed ? 'error' : 'ok', text: stillUnconfirmed ? `${stillUnconfirmed} resultado(s) siguen pendientes de confirmación. No se volvió a publicar nada.` : 'La publicación quedó confirmada mediante una nueva consulta de solo lectura.' })
  }
  const downloadPrepared = async () => {
    if (!review?.preparation) return
    setBusy('download'); setNotice(null)
    try {
      await api.downloadPublication(PROJECT_ID, review.internal_id, review.preparation.identity.key)
    } catch (error) {
      setNotice({ kind: 'error', text: (error as Error).message })
    } finally {
      setBusy('')
    }
  }

  return <div className="config-backdrop"><section className="config-dialog publication-dialog" role="dialog" aria-modal="true" aria-label="Publicar en ISC">
    <header className="config-header"><div><span className="eyebrow">{intent === 'download' ? 'Preparación para destino' : 'Escritura controlada'}</span><h2>{intent === 'download' ? 'Descargar JSON para ISC' : 'Publicar en ISC'}</h2><p>{intent === 'download' ? 'Elegí el tenant destino. Se buscará primero su personalización y, si no existe, su plantilla estándar para construir los metadatos.' : 'Prepará y revisá el payload antes de confirmar. La IA no participa de esta operación.'}</p></div><button className="icon-button close-button" aria-label="Cerrar publicación" disabled={Boolean(busy)} title={busy ? 'Esperá a que termine la operación en curso.' : ''} onClick={onClose}>×</button></header>
    {connections.length === 0 ? <div className="empty publication-empty"><h3>No hay conexiones ISC</h3><p>Creá una conexión con permisos de lectura y <code>idn:notification-templates:create</code>.</p></div> : <div className="publication-scroll">
      <section className="publication-destination"><label className="field"><span>Conexión destino</span><select value={connectionId} onChange={(event) => { const nextConnectionId = event.target.value; const nextStates = statesForConnection(templates, nextConnectionId); setConnectionId(nextConnectionId); setPrepared([]); setStates(nextStates); setNotice(null); setSelected((current) => new Set([...current].filter((id) => !isLocked(nextStates[id]?.kind)))) }}>{connections.map((item) => <option value={item.id} key={item.id}>{item.name} · {ENVIRONMENT_LABELS[item.environment]}</option>)}</select></label>{connection && <div><strong>{connection.name}</strong><span>{ENVIRONMENT_LABELS[connection.environment]} · {connection.api_base_url}</span></div>}</section>
      <div className="publication-layout"><aside className="publication-list"><div className="publication-list-heading"><strong>Adaptaciones revisadas</strong><span>{selected.size} seleccionada(s)</span></div>{eligible.map((template) => { const preparedItem = prepared.find((entry) => entry.internal_id === template.internal_id); const state = states[template.internal_id]; return <label className={`publication-item ${review?.internal_id === template.internal_id ? 'active' : ''}`} key={template.internal_id}><input type="checkbox" checked={selected.has(template.internal_id)} disabled={Boolean(busy) || isLocked(state?.kind)} onChange={() => toggle(template.internal_id)} /><button type="button" onClick={() => setReviewId(template.internal_id)}><strong>{template.name}{template.local_copy ? ' · Copia local' : ''}</strong><code>{template.key} · {template.locale}</code><span className={`publication-status ${state?.kind ?? preparedItem?.status ?? ''}`}>{state?.text ?? (preparedItem?.status === 'ready' ? 'Lista para revisar' : preparedItem?.error ?? 'Sin preparar')}</span></button></label> })}{eligible.length === 0 && <p className="muted">No hay adaptaciones vigentes y sin cambios estructurales.</p>}</aside>
        <section className="publication-review">{review?.preparation ? <><div className="publication-review-header"><div><span className="eyebrow">Payload preparado</span><h3>{review.preparation.name}</h3><p><code>{review.preparation.identity.key}</code> · {review.preparation.identity.medium} · {review.preparation.identity.locale}</p></div><span className="mode-badge">{review.preparation.mode === 'replace_custom' ? 'Reemplazará personalización' : 'Creará sobre el default'}</span></div><div className="target-card"><strong>Destino confirmado</strong><span>{review.preparation.connection.name} · {ENVIRONMENT_LABELS[review.preparation.connection.environment]}</span><code>{review.preparation.connection.api_base_url}</code></div><div className="payload-metadata"><strong>Metadatos del payload</strong><span>ID: {text(review.preparation.payload.id) || 'omitido porque se creará sobre el default'}</span><span><code>key</code>, <code>medium</code> y <code>locale</code>: tomados del destino</span><span><code>from</code> y <code>replyTo</code>: conservados del destino</span><span><code>created</code>, <code>modified</code>, <code>header</code> y <code>footer</code>: omitidos</span></div>{review.preparation.warnings.length > 0 && <div className="publication-warnings"><strong>Referencias para revisar</strong><ul>{review.preparation.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}<div className="publication-comparison"><section><strong>Contenido actual del destino</strong><span>{text(review.preparation.target_current.subject) || 'Sin asunto'}</span><pre>{text(review.preparation.target_current.body)}</pre></section><section><strong>Adaptación a publicar</strong><span>{text(review.preparation.payload.subject) || 'Sin asunto'}</span><pre>{text(review.preparation.payload.body)}</pre></section></div><div className="publication-download"><button className="button secondary" disabled={Boolean(busy)} onClick={() => void downloadPrepared()}>{busy === 'download' ? 'Descargando…' : 'Descargar JSON para ISC'}</button><small>Este sí es el payload preparado para el tenant destino; no contiene los metadatos del origen.</small></div></> : <div className="empty"><h3>Prepará la selección</h3><p>Se resolverá cada plantilla por la combinación exacta key + medium + locale, sin escribir en ISC.</p></div>}</section>
      </div>
    </div>}
    {notice && <div className={`dialog-notice publication-notice ${notice.kind}`}>{notice.text}</div>}
    <footer className="config-footer publication-footer"><div><strong>Scopes requeridos</strong><span>{intent === 'download' ? 'defaults:read · templates:read' : 'defaults:read · templates:read · templates:create'}</span></div><button className="button secondary" disabled={!connectionId || !selected.size || Boolean(busy)} onClick={() => void prepare()}>{busy === 'prepare' ? 'Consultando destino…' : intent === 'download' ? 'Buscar destino y preparar JSON' : 'Preparar y comparar'}</button>{intent === 'publish' && verifiable.length > 0 && <button className="button secondary" disabled={Boolean(busy)} onClick={() => void verifyUnconfirmed()}>{busy === 'verify' ? 'Comprobando…' : `Volver a comprobar (${verifiable.length})`}</button>}{intent === 'publish' && failed.length > 0 && <button className="button secondary" disabled={Boolean(busy)} onClick={() => void publish(true)}>Reintentar fallidas ({failed.length})</button>}{intent === 'publish' && <button className="button primary publish-confirm" disabled={!publishable.length || Boolean(busy)} onClick={() => void publish(false)}>{busy === 'publish' ? 'Publicando secuencialmente…' : `Publicar ${publishable.length || ''} en ISC`}</button>}</footer>
  </section></div>
}
