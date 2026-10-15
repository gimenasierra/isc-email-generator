// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { isSafeEditableLink, protectVisualHtml, restoreVisualHtml, visualSafetyIssues } from './visualProtection'

function editableDocument(html: string) {
  return new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html')
}

describe('protector del editor visual', () => {
  it('bloquea y restaura literalmente variables, directivas y bloques deterministas', () => {
    const dateBlock = '#set($fechaExpiracionEs = $expires.replace("Monday", "lunes"))${fechaExpiracionEs}'
    const source = `<p>Hola ${'${user.name}'}</p>#if($expires)<p>${dateBlock}</p>#end`
    const protectedValue = protectVisualHtml(source, [dateBlock])
    const document = editableDocument(protectedValue.html)

    expect(document.querySelectorAll('[data-isc-velocity-id]').length).toBeGreaterThanOrEqual(4)
    const restored = restoreVisualHtml(document, protectedValue.fragments)
    expect(restored.valid).toBe(true)
    expect(restored.html).toContain('${user.name}')
    expect(restored.html).toContain('#if($expires)')
    expect(restored.html).toContain(dateBlock)
    expect(restored.html).toContain('#end')
  })

  it('detecta la eliminación de un elemento bloqueado', () => {
    const protectedValue = protectVisualHtml('<p>Hola ${user.name}</p>', [])
    const document = editableDocument(protectedValue.html)
    document.querySelector('[data-isc-velocity-id]')?.remove()

    expect(restoreVisualHtml(document, protectedValue.fragments).valid).toBe(false)
  })

  it('rechaza contenido activo y destinos inseguros', () => {
    expect(visualSafetyIssues('<script>alert(1)</script><p onclick="x()">Texto</p>')).toHaveLength(2)
    expect(visualSafetyIssues('<a href="javascript:alert(1)">Abrir</a>')).toHaveLength(1)
    expect(isSafeEditableLink('javascript:alert(1)')).toBe(false)
    expect(isSafeEditableLink('data:text/html,test')).toBe(false)
    expect(isSafeEditableLink('${registrationUrl}')).toBe(true)
    expect(isSafeEditableLink('https://tenant.example/path')).toBe(true)
  })
})
