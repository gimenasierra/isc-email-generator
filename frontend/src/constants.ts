import type { ISCEnvironment } from './types'

export const PROJECT_ID = 'default'
export const ENVIRONMENT_LABELS: Record<ISCEnvironment, string> = {
  sandbox: 'Sandbox',
  production: 'Producción',
  demo: 'Demo',
}
