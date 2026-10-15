import { useEffect, useMemo, useRef, useState } from 'react'
import { isSafeEditableLink, protectVisualHtml, restoreVisualHtml, type ProtectedFragment } from './visualProtection'

type Props = {
  value: string
  protectedBlocks: string[]
  onChange: (value: string) => void
  onIntegrityChange: (valid: boolean) => void
}

const EDITOR_STYLE = `
html{background:#f3f6f8}body{box-sizing:border-box;min-height:520px;max-width:760px;margin:0 auto;padding:34px;background:#fff;color:#1c2635;font:14px/1.5 Arial,sans-serif;overflow-wrap:anywhere;outline:none}
img{max-width:100%;height:auto}table{max-width:100%}a{cursor:pointer}
[data-isc-velocity-id]{display:inline-block;max-width:100%;padding:1px 4px;border:1px solid #9fcfea;border-radius:4px;background:#eaf6fd;color:#005f99;font:600 12px/1.45 Consolas,monospace;white-space:pre-wrap;vertical-align:baseline;user-select:all;cursor:not-allowed}
[data-isc-velocity-kind="block"]{display:block;margin:5px 0;border-style:dashed;background:#f0f7fb}
::selection{background:#acd8f2}
`

export function SafeVisualEditor({ value, protectedBlocks, onChange, onIntegrityChange }: Props) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const fragmentsRef = useRef<ProtectedFragment[]>([])
  const lastEmitted = useRef('')
  const savedRange = useRef<Range | null>(null)
  const [selectedLink, setSelectedLink] = useState<HTMLAnchorElement | null>(null)
  const [linkValue, setLinkValue] = useState('')
  const [linkError, setLinkError] = useState('')
  const [ready, setReady] = useState(false)
  const protectedKey = useMemo(() => protectedBlocks.join('\u0000'), [protectedBlocks])

  const emit = () => {
    const document = iframeRef.current?.contentDocument
    if (!document) return
    const restored = restoreVisualHtml(document, fragmentsRef.current)
    onIntegrityChange(restored.valid)
    if (!restored.valid) return
    lastEmitted.current = restored.html
    onChange(restored.html)
  }

  const rememberSelection = () => {
    const document = iframeRef.current?.contentDocument
    const selection = document?.getSelection()
    if (selection?.rangeCount) savedRange.current = selection.getRangeAt(0).cloneRange()
    const element = selection?.anchorNode instanceof Element ? selection.anchorNode : selection?.anchorNode?.parentElement
    const anchor = element?.closest('a') as HTMLAnchorElement | null
    setSelectedLink(anchor)
    setLinkValue(anchor?.getAttribute('href') ?? '')
    setLinkError('')
  }

  const restoreSelection = () => {
    const selection = iframeRef.current?.contentDocument?.getSelection()
    if (!selection || !savedRange.current) return
    selection.removeAllRanges()
    selection.addRange(savedRange.current)
  }

  const command = (name: string, argument?: string) => {
    const document = iframeRef.current?.contentDocument
    if (!document) return
    restoreSelection()
    document.execCommand(name, false, argument)
    iframeRef.current?.contentWindow?.focus()
    emit()
  }

  const setFontSize = (size: string) => {
    const document = iframeRef.current?.contentDocument
    if (!document) return
    restoreSelection()
    document.execCommand('fontSize', false, '7')
    document.querySelectorAll('font[size="7"]').forEach((font) => {
      const span = document.createElement('span')
      span.style.fontSize = `${size}px`
      while (font.firstChild) span.append(font.firstChild)
      font.replaceWith(span)
    })
    emit()
  }

  useEffect(() => {
    if (value === lastEmitted.current && ready) return
    const frame = iframeRef.current
    if (!frame) return
    const protectedValue = protectVisualHtml(value, protectedBlocks)
    fragmentsRef.current = protectedValue.fragments
    onIntegrityChange(true)
    setReady(false)
    frame.srcdoc = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https: http: data:; style-src 'unsafe-inline'"><style>${EDITOR_STYLE}</style></head><body>${protectedValue.html}</body></html>`
  }, [value, protectedKey])

  const initialize = () => {
    const document = iframeRef.current?.contentDocument
    if (!document) return
    document.body.contentEditable = 'true'
    document.body.spellcheck = true
    document.execCommand('styleWithCSS', false, 'true')
    document.addEventListener('input', emit)
    document.addEventListener('selectionchange', rememberSelection)
    document.addEventListener('click', (event) => {
      const anchor = (event.target as Element | null)?.closest?.('a')
      if (anchor) event.preventDefault()
      rememberSelection()
    })
    document.addEventListener('drop', (event) => event.preventDefault())
    document.addEventListener('paste', (event) => {
      event.preventDefault()
      document.execCommand('insertText', false, event.clipboardData?.getData('text/plain') ?? '')
    })
    setReady(true)
  }

  const updateLink = () => {
    if (!selectedLink) return
    if (!isSafeEditableLink(linkValue)) { setLinkError('Ingresá una URL segura. No se admiten javascript:, data: ni destinos vacíos.'); return }
    selectedLink.setAttribute('href', linkValue.trim())
    setLinkError('')
    emit()
  }

  return <div className="visual-editor-shell">
    <div className="visual-toolbar" role="toolbar" aria-label="Formato visual">
      <button type="button" title="Negrita" aria-label="Negrita" onMouseDown={(event) => event.preventDefault()} onClick={() => command('bold')}><strong>B</strong></button>
      <button type="button" title="Cursiva" aria-label="Cursiva" onMouseDown={(event) => event.preventDefault()} onClick={() => command('italic')}><em>I</em></button>
      <button type="button" title="Subrayado" aria-label="Subrayado" onMouseDown={(event) => event.preventDefault()} onClick={() => command('underline')}><u>U</u></button>
      <label className="toolbar-select"><span className="sr-only">Tamaño</span><select defaultValue="14" onChange={(event) => setFontSize(event.target.value)}><option value="12">12 px</option><option value="14">14 px</option><option value="16">16 px</option><option value="18">18 px</option><option value="20">20 px</option><option value="24">24 px</option><option value="28">28 px</option><option value="32">32 px</option></select></label>
      <label className="color-tool" title="Color de texto">A<input type="color" defaultValue="#333333" onChange={(event) => command('foreColor', event.target.value)} /></label>
      <label className="color-tool highlight" title="Color de fondo">▰<input type="color" defaultValue="#fff2a8" onChange={(event) => command('hiliteColor', event.target.value)} /></label>
      <span className="toolbar-divider" />
      <button type="button" title="Alinear a la izquierda" aria-label="Alinear a la izquierda" onMouseDown={(event) => event.preventDefault()} onClick={() => command('justifyLeft')}>≡</button>
      <button type="button" title="Centrar" aria-label="Centrar" onMouseDown={(event) => event.preventDefault()} onClick={() => command('justifyCenter')}>≣</button>
      <button type="button" title="Alinear a la derecha" aria-label="Alinear a la derecha" onMouseDown={(event) => event.preventDefault()} onClick={() => command('justifyRight')}>≡</button>
      <span className="toolbar-divider" />
      <div className="link-editor"><input aria-label="URL del enlace seleccionado" value={linkValue} disabled={!selectedLink} placeholder={selectedLink ? 'URL del enlace' : 'Seleccioná un enlace existente'} onChange={(event) => setLinkValue(event.target.value)} /><button type="button" disabled={!selectedLink} onClick={updateLink}>Actualizar enlace</button></div>
    </div>
    {linkError && <p className="visual-editor-error">{linkError}</p>}
    <iframe ref={iframeRef} title="Editor visual aislado" sandbox="allow-same-origin" onLoad={initialize} />
    <p className="visual-editor-note">Las etiquetas azules son variables, directivas o bloques protegidos de Velocity y no se pueden editar. Pegado limitado a texto; no se insertan imágenes, tablas ni enlaces nuevos.</p>
  </div>
}
