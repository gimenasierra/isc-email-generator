import { FormEvent, useEffect, useState } from 'react'
import { api, setProjectVersion } from './api'
import type { AuthUser } from './types'

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [serverMode, setServerMode] = useState<boolean | null>(null)
  const [user, setUser] = useState<AuthUser | null>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [showUsers, setShowUsers] = useState(false)
  const [users, setUsers] = useState<AuthUser[]>([])
  const [newUsername, setNewUsername] = useState('')
  const [temporaryPassword, setTemporaryPassword] = useState('')
  const [newRole, setNewRole] = useState<'admin' | 'user'>('user')

  useEffect(() => {
    void api.health().then(async (health) => {
      const enabled = Boolean(health.server_mode)
      setServerMode(enabled)
      if (!enabled) return
      try { setUser((await api.me()).user) } catch { setUser(null) }
    }).catch((error) => { setMessage((error as Error).message); setServerMode(true) })
  }, [])
  useEffect(() => { const reset = () => { setProjectVersion(null); setUser(null) }; window.addEventListener('isc-auth-required', reset); return () => window.removeEventListener('isc-auth-required', reset) }, [])

  if (serverMode === false) return <>{children}</>
  if (serverMode === null) return <main className="auth-shell"><section className="auth-card"><h1>ISC · Email Generator</h1><p>Comprobando el servidor…</p></section></main>

  const login = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setMessage('')
    try { const result = await api.login(username, password); setUser(result.user); setPassword('') } catch (error) { setMessage((error as Error).message) } finally { setBusy(false) }
  }
  const changePassword = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setMessage('')
    try { await api.changePassword(password, newPassword); setProjectVersion(null); setUser(null); setPassword(''); setNewPassword(''); setMessage('Contraseña actualizada. Iniciá sesión nuevamente.') } catch (error) { setMessage((error as Error).message) } finally { setBusy(false) }
  }
  if (!user) return <main className="auth-shell"><form className="auth-card" onSubmit={login}><p className="eyebrow">ACCESO SEGURO</p><h1>ISC · Email Generator</h1><label>Usuario<input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></label><label>Contraseña<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>{message && <p className="auth-message">{message}</p>}<button className="primary" disabled={busy}>Ingresar</button></form></main>
  if (user.must_change_password) return <main className="auth-shell"><form className="auth-card" onSubmit={changePassword}><p className="eyebrow">CAMBIO OBLIGATORIO</p><h1>Definí una contraseña nueva</h1><label>Contraseña temporal<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label><label>Nueva contraseña<input type="password" autoComplete="new-password" minLength={12} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required /></label><small>Mínimo 12 caracteres.</small>{message && <p className="auth-message">{message}</p>}<button className="primary" disabled={busy}>Cambiar contraseña</button><button type="button" onClick={() => void api.logout().finally(() => setUser(null))}>Cerrar sesión</button></form></main>
  const openUsers = async () => { setMessage(''); try { setUsers((await api.users()).users); setShowUsers(true) } catch (error) { setMessage((error as Error).message) } }
  const addUser = async (event: FormEvent) => { event.preventDefault(); setBusy(true); try { await api.createUser(newUsername, temporaryPassword, newRole); setUsers((await api.users()).users); setNewUsername(''); setTemporaryPassword('') } catch (error) { setMessage((error as Error).message) } finally { setBusy(false) } }
  const toggleUser = async (target: AuthUser) => { try { await api.setUserActive(target.id, !target.active); setUsers((await api.users()).users) } catch (error) { setMessage((error as Error).message) } }
  const resetPassword = async (target: AuthUser) => { const value = window.prompt(`Contraseña temporal nueva para ${target.username} (mínimo 12 caracteres):`); if (!value) return; try { await api.resetUserPassword(target.id, value); setMessage(`Se restableció la contraseña de ${target.username} y se cerraron todas sus sesiones.`) } catch (error) { setMessage((error as Error).message) } }
  return <div className="authenticated-app"><div className="session-bar"><span>{user.username} · {user.role === 'admin' ? 'Administrador' : 'Usuario'}</span>{user.role === 'admin' && <button type="button" onClick={() => void openUsers()}>Usuarios</button>}<button type="button" onClick={() => void api.logout().finally(() => { setProjectVersion(null); setUser(null) })}>Cerrar sesión</button></div>{message && <div className="server-notice">{message}</div>}{children}{showUsers && <div className="config-backdrop"><section className="auth-users-dialog" role="dialog" aria-modal="true" aria-label="Administrar usuarios"><header><div><p className="eyebrow">ADMINISTRACIÓN</p><h2>Usuarios</h2></div><button type="button" onClick={() => setShowUsers(false)}>×</button></header><form onSubmit={addUser}><input placeholder="Usuario" value={newUsername} onChange={(e) => setNewUsername(e.target.value)} required/><input type="password" placeholder="Contraseña temporal" minLength={12} value={temporaryPassword} onChange={(e) => setTemporaryPassword(e.target.value)} required/><select value={newRole} onChange={(e) => setNewRole(e.target.value as 'admin' | 'user')}><option value="user">Usuario</option><option value="admin">Administrador</option></select><button className="primary" disabled={busy}>Crear usuario</button></form><div className="auth-user-list">{users.map((target) => <div key={target.id}><span><strong>{target.username}</strong><small>{target.role} · {target.active ? 'activo' : 'desactivado'}{target.must_change_password ? ' · cambio pendiente' : ''}</small></span><button onClick={() => void resetPassword(target)}>Restablecer</button><button disabled={target.id === user.id} onClick={() => void toggleUser(target)}>{target.active ? 'Desactivar' : 'Activar'}</button></div>)}</div></section></div>}</div>
}
