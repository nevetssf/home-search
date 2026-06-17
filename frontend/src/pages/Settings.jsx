// Account settings: change your own password + manage household users
// (list / add / delete). Backed by /auth/me/password and /auth/users.
import { useEffect, useState } from 'react'
import { changePassword, createUser, deleteUser, listUsers } from '../api'
import { useAuth } from '../auth'

export default function Settings() {
  const { user } = useAuth()
  return (
    <div className="settings">
      <h2>Settings</h2>
      <PasswordCard />
      <UsersCard me={user} />
    </div>
  )
}

function PasswordCard() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [msg, setMsg] = useState(null) // {ok, text}

  const submit = async (e) => {
    e.preventDefault()
    setMsg(null)
    if (next.length < 6) return setMsg({ ok: false, text: 'New password must be at least 6 characters.' })
    if (next !== confirm) return setMsg({ ok: false, text: 'New passwords do not match.' })
    try {
      await changePassword(current, next)
      setCurrent(''); setNext(''); setConfirm('')
      setMsg({ ok: true, text: 'Password changed.' })
    } catch (err) {
      setMsg({ ok: false, text: err.response?.data?.detail || 'Could not change password.' })
    }
  }

  return (
    <section className="card">
      <h3>Change my password</h3>
      <form className="stack" onSubmit={submit}>
        <input type="password" placeholder="Current password" value={current}
          onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
        <input type="password" placeholder="New password" value={next}
          onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
        <input type="password" placeholder="Confirm new password" value={confirm}
          onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
        <button type="submit">Update password</button>
        {msg && <span className={msg.ok ? 'ok-msg' : 'error'}>{msg.text}</span>}
      </form>
    </section>
  )
}

function UsersCard({ me }) {
  const [users, setUsers] = useState([])
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [error, setError] = useState('')

  const load = () => listUsers().then(setUsers).catch(() => {})
  useEffect(() => { load() }, [])

  const add = async (e) => {
    e.preventDefault()
    setError('')
    try {
      await createUser(form)
      setForm({ name: '', email: '', password: '' })
      load()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not add user.')
    }
  }

  const remove = async (u) => {
    if (!confirm(`Remove ${u.name} (${u.email})?`)) return
    try {
      await deleteUser(u.id)
      load()
    } catch (err) {
      alert(err.response?.data?.detail || 'Could not remove user.')
    }
  }

  return (
    <section className="card">
      <h3>Household users</h3>
      <table className="grid">
        <thead><tr><th>Name</th><th>Email</th><th></th></tr></thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.name}{u.id === me?.id && <span className="muted"> (you)</span>}</td>
              <td>{u.email}</td>
              <td>
                {u.id !== me?.id && (
                  <button className="link-btn danger" onClick={() => remove(u)}>remove</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h4>Add a user</h4>
      <form className="crit-form" onSubmit={add}>
        <input placeholder="Name" value={form.name} required
          onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <input type="email" placeholder="Email" value={form.email} required
          onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <input type="password" placeholder="Password (min 6)" value={form.password} required
          onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" />
        <button type="submit">Add user</button>
        {error && <span className="error">{error}</span>}
      </form>
    </section>
  )
}
