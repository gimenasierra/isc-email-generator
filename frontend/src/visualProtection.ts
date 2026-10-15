export type ProtectedFragment = { id: string; raw: string; kind: 'block' | 'velocity' }

const ACTIVE_ELEMENTS = 'script,iframe,object,embed,form,meta[http-equiv]'
const UNSAFE_URL = /^\s*(?:javascript|vbscript|data):/i

function velocityTokenAt(text: string, start: number): string | null {
  const rest = text.slice(start)
  if (rest[0] === '$') {
    const braced = rest.match(/^\$!?\{[^}\r\n]+\}/)?.[0]
    if (braced) return braced
    return rest.match(/^\$!?[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*(?:\([^\r\n)]*\))?|\[[^\r\n\]]+\])*/)?.[0] ?? null
  }
  if (rest[0] !== '#') return null
  const simple = rest.match(/^#(?:\{)?(?:else|end|break|continue)(?:\})?\b/i)?.[0]
  if (simple) return simple
  const opening = rest.match(/^#(?:\{)?(?:if|elseif|foreach|set|macro|parse|include|evaluate|define|stop)(?:\})?\s*\(/i)?.[0]
  if (!opening) return null
  let depth = 1
  let quote = ''
  for (let index = opening.length; index < rest.length; index += 1) {
    const character = rest[index]
    if (quote) {
      if (character === quote && rest[index - 1] !== '\\') quote = ''
      continue
    }
    if (character === '"' || character === "'") { quote = character; continue }
    if (character === '(') depth += 1
    if (character === ')') {
      depth -= 1
      if (depth === 0) return rest.slice(0, index + 1)
    }
  }
  return null
}

export function visualSafetyIssues(html: string): string[] {
  const document = new DOMParser().parseFromString(html, 'text/html')
  const issues: string[] = []
  if (document.querySelector(ACTIVE_ELEMENTS)) issues.push('contiene scripts, iframes, formularios u otro contenido activo')
  for (const element of [...document.querySelectorAll('*')]) {
    for (const attribute of [...element.attributes]) {
      if (attribute.name.toLowerCase().startsWith('on')) issues.push('contiene manejadores de eventos HTML')
      if (['href', 'src', 'action', 'formaction'].includes(attribute.name.toLowerCase()) && UNSAFE_URL.test(attribute.value)) issues.push('contiene una URL activa no segura')
    }
  }
  return [...new Set(issues)]
}

export function isSafeEditableLink(value: string): boolean {
  const candidate = value.trim()
  return Boolean(candidate) && !UNSAFE_URL.test(candidate) && !/[\u0000-\u001f\u007f]/.test(candidate)
}

export function protectVisualHtml(html: string, protectedBlocks: string[]): { html: string; fragments: ProtectedFragment[] } {
  const fragments: ProtectedFragment[] = []
  const markerPrefix = `ISCGENLOCK${Math.random().toString(36).slice(2)}_`
  let prepared = html
  for (const block of [...protectedBlocks].filter(Boolean).sort((left, right) => right.length - left.length)) {
    const id = `p${fragments.length}`
    fragments.push({ id, raw: block, kind: 'block' })
    prepared = prepared.split(block).join(`${markerPrefix}${id}__`)
  }
  const document = new DOMParser().parseFromString(prepared, 'text/html')
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  const nodes: Text[] = []
  while (walker.nextNode()) nodes.push(walker.currentNode as Text)
  for (const node of nodes) {
    const text = node.data
    const pieces: Array<{ raw: string; kind?: 'block' | 'velocity'; id?: string }> = []
    let plainStart = 0
    let cursor = 0
    while (cursor < text.length) {
      const marker = text.startsWith(markerPrefix, cursor)
        ? text.slice(cursor).match(new RegExp(`^${markerPrefix}(p\\d+)__`))
        : null
      const token = !marker && (text[cursor] === '$' || text[cursor] === '#') ? velocityTokenAt(text, cursor) : null
      if (!marker && !token) { cursor += 1; continue }
      if (plainStart < cursor) pieces.push({ raw: text.slice(plainStart, cursor) })
      if (marker) {
        const existing = fragments.find((fragment) => fragment.id === marker[1])!
        pieces.push({ raw: existing.raw, kind: 'block', id: existing.id })
        cursor += marker[0].length
      } else {
        const id = `v${fragments.length}`
        fragments.push({ id, raw: token!, kind: 'velocity' })
        pieces.push({ raw: token!, kind: 'velocity', id })
        cursor += token!.length
      }
      plainStart = cursor
    }
    if (!pieces.length) continue
    if (plainStart < text.length) pieces.push({ raw: text.slice(plainStart) })
    const replacement = document.createDocumentFragment()
    for (const piece of pieces) {
      if (!piece.kind) { replacement.append(document.createTextNode(piece.raw)); continue }
      const span = document.createElement('span')
      span.dataset.iscVelocityId = piece.id
      span.dataset.iscVelocityKind = piece.kind
      span.contentEditable = 'false'
      span.spellcheck = false
      span.textContent = piece.raw
      replacement.append(span)
    }
    node.replaceWith(replacement)
  }
  return { html: document.body.innerHTML, fragments }
}

export function restoreVisualHtml(document: Document, fragments: ProtectedFragment[]): { html: string; valid: boolean } {
  const clone = document.body.cloneNode(true) as HTMLElement
  let valid = true
  for (const fragment of fragments) {
    const matches = clone.querySelectorAll(`[data-isc-velocity-id="${fragment.id}"]`)
    if (matches.length !== 1) valid = false
    matches.forEach((node) => node.replaceWith(clone.ownerDocument.createTextNode(fragment.raw)))
  }
  if (clone.querySelector('[data-isc-velocity-id]')) valid = false
  return { html: clone.innerHTML, valid }
}
