import React, { useEffect, useState } from 'react'
import axios from 'axios'

// В проде (в туннеле/на сервере) используем текущий origin, локально — переменную окружения
const API_BASE = import.meta.env.VITE_API_URL || window.location.origin

export default function App() {
  const [tgData, setTgData] = useState(null)
  const [userId, setUserId] = useState('12345') // локально шлём в X-Debug-Tg-Id
  const [lang, setLang] = useState('ru')
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(false)
  const [storyCode] = useState('office_flirt')
  const [grantMsg, setGrantMsg] = useState('')
  const [ageAgree, setAgeAgree] = useState(false)
  const [showMenu, setShowMenu] = useState(false)

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
    ? { 'X-Telegram-Init-Data': tgData, 'bypass-tunnel-reminder': '1' }
    : { 'X-Debug-Tg-Id': userId, 'bypass-tunnel-reminder': '1' }

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
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Love Paths</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {state && (
            <>
              <span>⚡ {state.wallet?.energy ?? 0}</span>
              <span>💎 {state.wallet?.gems ?? 0}</span>
              <span>⭐ {state.wallet?.is_premium ? 'Premium' : 'Free'}</span>
              <button onClick={() => setShowMenu(true)} disabled={loading}>Меню</button>
            </>
          )}
          {!state && (
            <button onClick={() => setShowMenu(true)} disabled={loading}>Меню</button>
          )}
        </div>
        {!tgData && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ opacity: .7 }}>DEBUG</span>
            <input value={userId} onChange={e => setUserId(e.target.value)} style={{ width: 120 }} />
            <button onClick={devGrant} disabled={loading}>DEV: +энергия/+gems</button>
            {grantMsg && <span style={{ color: 'green' }}>{grantMsg}</span>}
          </div>
        )}
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
            {state.choices.map(ch => {
              const needsItem = !!ch.requires_item && !(state.items||[]).includes(ch.requires_item)
              return (
                <div key={ch.code} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <button onClick={() => choose(ch.code)} disabled={loading || needsItem}
                    style={{ padding: '10px 14px', borderRadius: 8, border: '1px solid #ddd', textAlign: 'left', opacity: needsItem ? .6 : 1 }}>
                    {ch.label}
                    {!!ch.gem_cost && <span> • {ch.gem_cost}💎</span>}
                    {ch.is_premium && <span> • Premium</span>}
                    {!!ch.heat_points && <span> • +heat {ch.heat_points}</span>}
                    {ch.requires_item && <span> • item: {ch.requires_item}</span>}
                  </button>
                  {needsItem && (
                    <button onClick={async () => {
                      setLoading(true)
                      try {
                        const price = 10 // клиентский дефолт; сервер вернёт точную ошибку с ценой, но для UX показываем быстро
                        await axios.post(`${API_BASE}/api/item/buy`, { story_code: storyCode, item_code: ch.requires_item, price_gems: price, lang }, { headers })
                        await loadState()
                      } catch (e) {
                        const d = e?.response?.data?.detail
                        if (d === 'gems_required') alert('Нужно больше 💎 для покупки предмета')
                        else alert('Покупка предмета: ' + (typeof d === 'string' ? d : e.message))
                      } finally { setLoading(false) }
                    }}>Купить предмет</button>
                  )}
                </div>
              )
            })}
          </div>

          <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px dashed #ddd', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <div>⚡ Энергия: <b>{state.wallet?.energy ?? 0}</b></div>
            <div>💎 Gems: <b>{state.wallet?.gems ?? 0}</b></div>
            <div>⭐ Premium: <b>{state.wallet?.is_premium ? 'да' : 'нет'}</b></div>
            <button onClick={() => setShowMenu(true)} disabled={loading}>Вернуться в меню</button>
          </div>
        </div>
      )}

      {!state && (
        <div style={{ border: '1px solid #e5e5e5', padding: 16, borderRadius: 8 }}>
          <h3 style={{ marginTop: 0 }}>Добро пожаловать!</h3>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 12 }}>
            <label>Язык:
              <select value={lang} onChange={e => setLang(e.target.value)} style={{ marginLeft: 8 }}>
                <option value="ru">ru</option>
                <option value="en">en</option>
                <option value="es">es</option>
                <option value="de">de</option>
                <option value="fr">fr</option>
              </select>
            </label>
          </div>
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
            <input type="checkbox" checked={ageAgree} onChange={e => setAgeAgree(e.target.checked)} />
            <span>Мне 18 лет и старше</span>
          </label>
          <button
            onClick={async () => {
              setLoading(true)
              try {
                if (ageAgree) {
                  await axios.post(`${API_BASE}/api/age/confirm`, { agree: true }, { headers })
                }
                await loadState()
              } catch (e) {
                alert('Ошибка: ' + (e?.response?.data?.detail || e.message))
              } finally {
                setLoading(false)
              }
            }}
            disabled={loading || !ageAgree}
            style={{ padding: '10px 14px', borderRadius: 8, border: '1px solid #ddd' }}
          >
            Начать
          </button>
        </div>
      )}

      {showMenu && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }} onClick={() => setShowMenu(false)}>
          <div onClick={e => e.stopPropagation()} style={{ width: 'min(92vw, 720px)', maxHeight: '86vh', overflow: 'auto', background: '#fff', borderRadius: 12, padding: 16, boxShadow: '0 10px 30px rgba(0,0,0,0.25)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h3 style={{ margin: 0 }}>Меню</h3>
              <button onClick={() => setShowMenu(false)}>К истории</button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 16 }}>
              <section style={{ border: '1px solid #eee', borderRadius: 8, padding: 12 }}>
                <h4 style={{ marginTop: 0 }}>Профиль</h4>
                <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                  <div>⚡ Энергия: <b>{state?.wallet?.energy ?? 0}</b></div>
                  <div>💎 Gems: <b>{state?.wallet?.gems ?? 0}</b></div>
                  <div>⭐ Статус: <b>{state?.wallet?.is_premium ? 'Premium' : 'Free'}</b></div>
                  {typeof state?.next_energy_in === 'number' && state?.next_energy_in > 0 && (
                    <div style={{ opacity: .8 }}>⏱️ +1⚡ через ~{Math.ceil((state.next_energy_in||0)/60)} мин</div>
                  )}
                </div>
              </section>
              <section style={{ border: '1px solid #eee', borderRadius: 8, padding: 12 }}>
                <h4 style={{ marginTop: 0 }}>Инвентарь</h4>
                <div style={{ display: 'grid', gap: 8 }}>
                  {(state?.shop || []).map(si => (
                    <div key={si.code} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', border: '1px solid #eee', borderRadius: 8, padding: '8px 10px' }}>
                      <div>
                        <div style={{ fontWeight: 600 }}>{si.code}</div>
                        <div style={{ opacity: .7, fontSize: 12 }}>{si.owned ? 'Куплено' : `Цена: ${si.price_gems}💎`}</div>
                      </div>
                      {!si.owned && (
                        <button onClick={async () => {
                          setLoading(true)
                          try {
                            await axios.post(`${API_BASE}/api/item/buy`, { story_code: storyCode, item_code: si.code, price_gems: si.price_gems, lang }, { headers })
                            await loadState()
                          } catch (e) {
                            const d = e?.response?.data?.detail
                            if (d === 'gems_required') alert('Нужно больше 💎')
                            else alert('Покупка: ' + (typeof d === 'string' ? d : e.message))
                          } finally { setLoading(false) }
                        }}>Купить</button>
                      )}
                    </div>
                  ))}
                </div>
              </section>
              <section style={{ border: '1px solid #eee', borderRadius: 8, padding: 12 }}>
                <h4 style={{ marginTop: 0 }}>Покупки</h4>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button onClick={async () => { setLoading(true); try { await axios.post(`${API_BASE}/api/purchase/mock`, { gems: 100 }, { headers }); await loadState(); } finally { setLoading(false); } }}>Купить 100💎</button>
                  <button onClick={async () => { setLoading(true); try { await axios.post(`${API_BASE}/api/dev/grant`, { energy: 10 }, { headers }); await loadState(); } finally { setLoading(false); } }}>Купить 10⚡ (врем.)</button>
                  <button onClick={async () => { setLoading(true); try { await axios.post(`${API_BASE}/api/purchase/mock`, { premium_days: 30 }, { headers }); await loadState(); } finally { setLoading(false); } }}>Купить Premium 30д</button>
                </div>
                <div style={{ opacity: .6, marginTop: 8, fontSize: 12 }}>Покупки сейчас – мок; позже заменим на Telegram Stars.</div>
              </section>
              <section style={{ border: '1px solid #eee', borderRadius: 8, padding: 12 }}>
                <h4 style={{ marginTop: 0 }}>Настройки</h4>
                <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                  <label>Язык:
                    <select value={lang} onChange={e => setLang(e.target.value)} style={{ marginLeft: 8 }}>
                      <option value="ru">ru</option>
                      <option value="en">en</option>
                      <option value="es">es</option>
                      <option value="de">de</option>
                      <option value="fr">fr</option>
                    </select>
                  </label>
                  <button onClick={async () => { await loadState(); setShowMenu(false); }}>Применить</button>
                  <button onClick={async () => { setLoading(true); try { await axios.post(`${API_BASE}/api/restart`, { story_code: storyCode, lang }, { headers }); await loadState(); } finally { setLoading(false); setShowMenu(false); } }}>Начать заново</button>
                </div>
              </section>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
