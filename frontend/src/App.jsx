import React, { useEffect, useState } from 'react'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8080'

export default function App() {
  const [tgData, setTgData] = useState(null)
  const [userId, setUserId] = useState('12345') // локально шлём в X-Debug-Tg-Id
  const [lang, setLang] = useState('ru')
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(false)
  const [storyCode] = useState('office_flirt')
  const [grantMsg, setGrantMsg] = useState('')

  useEffect(() => {
    // Telegram initData (когда будем открывать из бота)
    if (window.Telegram?.WebApp) {
      try {
        setTgData(window.Telegram.WebApp.initData || null)
        window.Telegram.WebApp?.expand?.()
      } catch (e) {}
    }
  }, [])

  const headers = tgData
    ? { 'X-Telegram-Init-Data': tgData }
    : { 'X-Debug-Tg-Id': userId }

  const loadState = async () => {
    setLoading(true)
    try {
      const url = `${API_BASE}/api/state?story=${storyCode}&lang=${lang}`
      const { data } = await axios.get(url, { headers })
      setState(data)
    } catch (e) {
      alert('Ошибка загрузки: ' + (e?.response?.data?.detail || e.message))
    } finally {
      setLoading(false)
    }
  }

  const choose = async (choiceCode) => {
    setLoading(true)
    try {
      const { data } = await axios.post(`${API_BASE}/api/choose`, {
        story_code: storyCode,
        choice_code: choiceCode,
        lang
      }, { headers })
      setState(data)
    } catch (e) {
      const detail = e?.response?.data?.detail
      if (detail === 'gems_required') {
        alert('Нужно больше 💎')
      } else if (detail === 'energy_required') {
        alert('Не хватает энергии ⚡')
      } else if (detail === 'premium_required') {
        alert('Нужен Премиум 🔒')
      } else if (detail === 'item_required') {
        alert('Нужен предмет 🧩')
      } else {
        alert('Ошибка выбора: ' + (detail || e.message))
      }
    } finally {
      setLoading(false)
    }
  }

  const devGrant = async () => {
    setLoading(true)
    try {
      await axios.post(`${API_BASE}/api/dev/grant`, {
        energy: 50, gems: 100, premium: false
      }, { headers })
      setGrantMsg('Выдано: +50 энергии, +100 💎')
      await loadState()
    } catch (e) {
      alert('Ошибка grant: ' + (e?.response?.data?.detail || e.message))
    } finally {
      setLoading(false)
      setTimeout(() => setGrantMsg(''), 2000)
    }
  }

  return (
    <div style={{ maxWidth: 820, margin: '16px auto', fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, Arial' }}>
      <h2>Romance MiniApp — demo</h2>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
        <label>Язык:
          <select value={lang} onChange={e => setLang(e.target.value)} style={{ marginLeft: 8 }}>
            <option value="ru">ru</option>
            <option value="en">en</option>
            <option value="es">es</option>
            <option value="de">de</option>
            <option value="fr">fr</option>
          </select>
        </label>

        <label>Test User ID:
          <input value={userId} onChange={e => setUserId(e.target.value)} style={{ marginLeft: 8, width: 120 }}/>
        </label>

        <button onClick={loadState} disabled={loading}>Загрузить сцену</button>
        <button onClick={devGrant} disabled={loading}>DEV: +энергия/+gems</button>
        {grantMsg && <span style={{ color: 'green' }}>{grantMsg}</span>}
      </div>

      {state && (
        <div style={{ border: '1px solid #e5e5e5', padding: 16, borderRadius: 8 }}>
          <div style={{ marginBottom: 8, opacity: 0.7 }}>
            <b>Сцена:</b> {state.scene.code} {state.scene.is_premium ? ' (Premium)' : ''} • ⚡ {state.scene.energy_cost}
          </div>

          {state.scene.image_url ? (
            <img src={state.scene.image_url} alt="scene" style={{ width: '100%', borderRadius: 8, marginBottom: 12 }}/>
          ) : null}

          <div style={{ whiteSpace: 'pre-wrap', marginBottom: 12 }}>{state.scene.text}</div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
            {state.choices.map(ch => (
              <button key={ch.code} onClick={() => choose(ch.code)} disabled={loading}
                style={{ padding: '10px 14px', borderRadius: 8, border: '1px solid #ddd', textAlign: 'left' }}>
                {ch.label}
                {!!ch.gem_cost && <span> • {ch.gem_cost}💎</span>}
                {ch.is_premium && <span> • Premium</span>}
                {!!ch.heat_points && <span> • +heat {ch.heat_points}</span>}
                {ch.requires_item && <span> • item: {ch.requires_item}</span>}
              </button>
            ))}
          </div>

          <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px dashed #ddd', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <div>⚡ Энергия: <b>{state.wallet?.energy ?? 0}</b></div>
            <div>💎 Gems: <b>{state.wallet?.gems ?? 0}</b></div>
            <div>⭐ Premium: <b>{state.wallet?.is_premium ? 'да' : 'нет'}</b></div>
          </div>
        </div>
      )}

      {!state && <div style={{ opacity: 0.7 }}>Нажми «Загрузить сцену», чтобы начать.</div>}
    </div>
  )
}
