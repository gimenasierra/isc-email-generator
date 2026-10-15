import { describe, expect, it } from 'vitest'
import { formatApiErrorDetail } from './api'

describe('errores de API', () => {
  it('convierte el detail de validación de FastAPI en texto legible', () => {
    const message = formatApiErrorDetail([
      { type: 'value_error', loc: ['body', 'base_url'], msg: 'La URL base local debe comenzar con http:// o https:// e incluir un host.' },
      { type: 'missing', loc: ['body', 'model'], msg: 'Field required' },
    ], 'Error de validación')

    expect(message).toBe('base_url: La URL base local debe comenzar con http:// o https:// e incluir un host. model: Field required')
    expect(message).not.toContain('[object Object]')
  })

  it('conserva mensajes simples del backend', () => {
    expect(formatApiErrorDetail('La preparación quedó desactualizada.', 'Error')).toBe('La preparación quedó desactualizada.')
  })
})
