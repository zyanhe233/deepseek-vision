import { useEffect, useState, useRef } from 'react'
import { Select } from '@base-ui/react/select'
import { Switch } from '@base-ui/react/switch'

// ── Types ──────────────────────────────────────────────────────────────────

interface BackendInfo { name: string; models: string[] }
interface StatusData {
  status: string
  models: string[]
  backends: BackendInfo[]
  vision: { enabled: boolean; model?: string }
  web_search: { enabled: boolean; provider: string }
  web_fetch: { enabled: boolean }
}

// ── Helpers ────────────────────────────────────────────────────────────────

function randomKey(): string {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789'
  let s = 'sk-'
  for (let i = 0; i < 40; i++) s += chars[Math.floor(Math.random() * chars.length)]
  return s
}

// ── Sub-components ─────────────────────────────────────────────────────────

function SectionHeader({ title }: { title: string }) {
  return (
    <div className="section-header">
      <span className="section-title">{title}</span>
      <div className="section-line" />
    </div>
  )
}

function Pill({ ok, yes = '已启用', no = '未配置' }: { ok: boolean; yes?: string; no?: string }) {
  return <span className={`pill ${ok ? 'ok' : 'warn'}`}>{ok ? yes : no}</span>
}

function Field({
  label, hint, children, className = ''
}: { label: string; hint?: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`field ${className}`}>
      <label className="field-label">{label}</label>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </div>
  )
}

// ── Select wrapper ─────────────────────────────────────────────────────────

function SelectField({ label, value, onChange, options, className = '' }: {
  label: string
  value: string
  onChange: (v: string) => void
  options: { label: string; value: string }[]
  className?: string
}) {
  return (
    <Field label={label} className={className}>
      <Select.Root value={value} onValueChange={(v) => onChange(v as string)}>
        <Select.Trigger className="select-trigger">
          <Select.Value />
          <Select.Icon className="select-icon">▾</Select.Icon>
        </Select.Trigger>
        <Select.Portal>
          <Select.Positioner className="select-positioner" sideOffset={4}>
            <Select.Popup className="select-popup">
              <Select.List className="select-list">
                {options.map((o) => (
                  <Select.Item key={o.value} value={o.value} className="select-item">
                    <Select.ItemIndicator className="select-item-indicator">✓</Select.ItemIndicator>
                    <Select.ItemText>{o.label}</Select.ItemText>
                  </Select.Item>
                ))}
              </Select.List>
            </Select.Popup>
          </Select.Positioner>
        </Select.Portal>
      </Select.Root>
    </Field>
  )
}

// ── Switch wrapper ─────────────────────────────────────────────────────────

function SwitchRow({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="toggle-row">
      <span>{label}</span>
      <Switch.Root className="switch-root" checked={checked} onCheckedChange={onChange}>
        <Switch.Thumb className="switch-thumb" />
      </Switch.Root>
    </div>
  )
}

// ── API Key Manager ────────────────────────────────────────────────────────

function ApiKeyManager({ keys, onChange }: {
  keys: string[]
  onChange: (keys: string[]) => void
}) {
  const [visible, setVisible] = useState<boolean[]>(keys.map(() => false))

  function toggleVisible(i: number) {
    setVisible(v => { const n = [...v]; n[i] = !n[i]; return n })
  }

  function update(i: number, val: string) {
    const next = [...keys]; next[i] = val; onChange(next)
  }

  function remove(i: number) {
    const nextKeys = keys.filter((_, j) => j !== i)
    const nextVis = visible.filter((_, j) => j !== i)
    onChange(nextKeys)
    setVisible(nextVis)
  }

  function add() {
    onChange([...keys, ''])
    setVisible([...visible, false])
  }

  function generate(i: number) {
    update(i, randomKey())
  }

  function addGenerated() {
    const key = randomKey()
    onChange([...keys, key])
    setVisible([...visible, false])
  }

  return (
    <div>
      <div className="key-list">
        {keys.map((k, i) => (
          <div key={i} className="key-row">
            <div className="key-input-wrap">
              <input
                type={visible[i] ? 'text' : 'password'}
                value={k}
                onChange={e => update(i, e.target.value)}
                placeholder="sk-…"
                autoComplete="off"
                className={k ? 'filled' : ''}
              />
              <button className="btn-eye" onClick={() => toggleVisible(i)} title={visible[i] ? '隐藏' : '显示'}>
                {visible[i] ? '🙈' : '👁'}
              </button>
            </div>
            <button className="btn-icon" onClick={() => generate(i)} title="重新生成">🔄</button>
            <button className="btn-icon danger" onClick={() => remove(i)} title="删除" disabled={keys.length === 1}>✕</button>
          </div>
        ))}
      </div>
      <div className="key-actions">
        <button className="btn-sm" onClick={add}>＋ 手动添加</button>
        <button className="btn-sm accent" onClick={addGenerated}>⚡ 生成新 Key</button>
      </div>
    </div>
  )
}

// ── Status section ─────────────────────────────────────────────────────────

function StatusSection({ data, offline }: { data: StatusData | null; offline: boolean }) {
  if (offline || !data) {
    return (
      <div className="status-grid">
        <div className="status-card">
          <div className="sc-label">代理服务</div>
          <div><span className="pill err">离线</span></div>
        </div>
      </div>
    )
  }
  const backends = data.backends.map(b => b.name).join(', ') || '—'
  return (
    <div className="status-grid">
      <div className="status-card">
        <div className="sc-label">代理服务</div>
        <div><Pill ok yes="运行中" /></div>
      </div>
      <div className="status-card">
        <div className="sc-label">后端</div>
        <div className="sc-value">{backends}</div>
        <div className="sc-sub">{data.models.length} 个模型</div>
      </div>
      <div className="status-card">
        <div className="sc-label">视觉中间件</div>
        <div><Pill ok={data.vision.enabled} /></div>
        {data.vision.enabled && <div className="sc-sub">{data.vision.model}</div>}
      </div>
      <div className="status-card">
        <div className="sc-label">联网搜索</div>
        <div><Pill ok={data.web_search.enabled} /></div>
        {data.web_search.enabled && <div className="sc-sub">{data.web_search.provider}</div>}
      </div>
      <div className="status-card">
        <div className="sc-label">网页抓取</div>
        <div><Pill ok yes="就绪" /></div>
      </div>
    </div>
  )
}

// ── .env generator ─────────────────────────────────────────────────────────

interface FormState {
  masterKeys: string[]
  dsKey: string
  dsUrl: string
  dsModels: string
  visUrl: string
  visKey: string
  visModel: string
  searchProvider: string
  searchKey: string
  visMaxImages: string
  webSearch: boolean
  webFetch: boolean
  port: string
  logLevel: string
}

const DEFAULTS: FormState = {
  masterKeys: [''],
  dsKey: '',
  dsUrl: 'https://api.deepseek.com/anthropic',
  dsModels: 'deepseek-v4-pro,deepseek-v4-flash',
  visUrl: '',
  visKey: '',
  visModel: '',
  searchProvider: 'tavily',
  searchKey: '',
  visMaxImages: '5',
  webSearch: false,
  webFetch: false,
  port: '8000',
  logLevel: 'INFO',
}

function envLine(key: string, val: string): string {
  return val ? `${key}=${val}` : `# ${key}=`
}

function buildEnvText(f: FormState): string {
  const masterKey = f.masterKeys.filter(Boolean).join(',')
  const isTavily = f.searchProvider === 'tavily'
  return [
    '# 必填',
    envLine('MASTER_API_KEY', masterKey),
    envLine('DEEPSEEK_API_KEY', f.dsKey),
    `DEEPSEEK_BASE_URL=${f.dsUrl}`,
    `DEEPSEEK_MODELS=${f.dsModels}`,
    '',
    '# 视觉中间件（可选）',
    envLine('VISION_BASE_URL', f.visUrl),
    envLine('VISION_API_KEY', f.visKey),
    envLine('VISION_MODEL', f.visModel),
    envLine('VISION_MAX_IMAGES', f.visMaxImages),
    '',
    '# 联网搜索（可选）',
    `WEB_SEARCH_PROVIDER=${f.searchProvider}`,
    isTavily ? envLine('TAVILY_API_KEY', f.searchKey) : envLine('BRAVE_API_KEY', f.searchKey),
    '',
    '# 服务',
    `PORT=${f.port}`,
    `LOG_LEVEL=${f.logLevel}`,
  ].join('\n')
}

type TokenType = 'key' | 'val' | 'comment' | 'plain'

function tokenizeLine(line: string): { type: TokenType; text: string }[] {
  if (line.startsWith('#')) return [{ type: 'comment', text: line }]
  if (!line.includes('=')) return [{ type: 'plain', text: line }]
  const eq = line.indexOf('=')
  const key = line.slice(0, eq)
  const rest = line.slice(eq + 1)
  return [
    { type: 'key', text: key },
    { type: 'plain', text: '=' },
    { type: 'val', text: rest },
  ]
}

function EnvPreview({ text }: { text: string }) {
  return (
    <div className="env-block">
      {text.split('\n').map((line, i) => (
        <div key={i}>
          {tokenizeLine(line).map((t, j) => (
            <span key={j} className={t.type === 'plain' ? undefined : t.type === 'key' ? 'ek' : t.type === 'val' ? 'ev' : 'ec'}>
              {t.text}
            </span>
          ))}
        </div>
      ))}
    </div>
  )
}

function ConfigSection() {
  const [form, setForm] = useState<FormState>(DEFAULTS)
  const [generated, setGenerated] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [applying, setApplying] = useState(false)
  const [applyMsg, setApplyMsg] = useState<string | null>(null)
  const envRef = useRef<HTMLDivElement>(null)

  const set = <K extends keyof FormState>(key: K, val: FormState[K]) =>
    setForm(f => ({ ...f, [key]: val }))

  const filledClass = (val: string) => val ? 'filled' : ''

  function generate() {
    setGenerated(buildEnvText(form))
    setTimeout(() => envRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }

  function copyEnv() {
    if (!generated) return
    navigator.clipboard.writeText(generated).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  async function applyAndRestart() {
    if (!generated) return
    setApplying(true)
    setApplyMsg('正在写入配置…')
    try {
      const r = await fetch('/admin/apply', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ env: generated }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setApplyMsg('服务重启中，请稍候…')
      // Poll /health until it comes back up (max 30s)
      const deadline = Date.now() + 30_000
      await new Promise<void>((resolve, reject) => {
        const tick = async () => {
          if (Date.now() > deadline) { reject(new Error('超时')); return }
          try {
            const h = await fetch('/health')
            if (h.ok) { resolve(); return }
          } catch { /* still restarting */ }
          setTimeout(tick, 800)
        }
        setTimeout(tick, 1500) // give process time to shut down first
      })
      setApplyMsg('✓ 配置已生效，服务已恢复')
      setTimeout(() => { setApplyMsg(null); setApplying(false) }, 3000)
    } catch (e) {
      setApplyMsg(`错误：${(e as Error).message}`)
      setApplying(false)
    }
  }

  const LOG_OPTIONS = ['INFO', 'DEBUG', 'WARNING', 'ERROR'].map(v => ({ label: v, value: v }))
  const PROVIDER_OPTIONS = [
    { label: 'Tavily', value: 'tavily' },
    { label: 'Brave', value: 'brave' },
  ]

  return (
    <>
      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>

        {/* DeepSeek */}
        <div className="form-group">
          <div className="form-group-title">DeepSeek 上游配置</div>
          <div className="form-grid">
            <Field label="DEEPSEEK_API_KEY" hint="必填，你的 DeepSeek API Key">
              <input
                type="password"
                value={form.dsKey}
                onChange={e => set('dsKey', e.target.value)}
                placeholder="sk-…"
                className={filledClass(form.dsKey)}
                autoComplete="off"
              />
            </Field>
            <Field label="DEEPSEEK_BASE_URL" hint="不使用镜像站则保持默认">
              <input
                type="text"
                value={form.dsUrl}
                onChange={e => set('dsUrl', e.target.value)}
                className={filledClass(form.dsUrl)}
              />
            </Field>
            <Field label="DEEPSEEK_MODELS" className="full"
              hint="逗号分隔，支持别名：客户端ID:上游ID，例如 fast:deepseek-chat">
              <input
                type="text"
                value={form.dsModels}
                onChange={e => set('dsModels', e.target.value)}
                className={filledClass(form.dsModels)}
              />
            </Field>
          </div>
        </div>

        <div className="divider" />

        {/* Auth */}
        <div className="form-group">
          <div className="form-group-title">代理鉴权 Key（MASTER_API_KEY）</div>
          <Field label="" hint="客户端使用这些 Key 访问本代理，可添加多个">
            <ApiKeyManager
              keys={form.masterKeys}
              onChange={v => set('masterKeys', v)}
            />
          </Field>
        </div>

        <div className="divider" />

        {/* Vision */}
        <div className="form-group">
          <div className="form-group-title">
            视觉中间件
            <span className="optional-tag">可选</span>
          </div>
          <div className="form-grid">
            <Field label="VISION_BASE_URL" hint="任何 OpenAI 兼容的视觉接口地址">
              <input
                type="text"
                value={form.visUrl}
                onChange={e => set('visUrl', e.target.value)}
                placeholder="https://api.openai.com/v1"
                className={filledClass(form.visUrl)}
              />
            </Field>
            <Field label="VISION_API_KEY">
              <input
                type="password"
                value={form.visKey}
                onChange={e => set('visKey', e.target.value)}
                placeholder="sk-…"
                className={filledClass(form.visKey)}
                autoComplete="off"
              />
            </Field>
            <Field label="VISION_MODEL" hint="例如：gpt-4o-mini、qwen-vl-max、glm-4v">
              <input
                type="text"
                value={form.visModel}
                onChange={e => set('visModel', e.target.value)}
                placeholder="gpt-4o-mini"
                className={filledClass(form.visModel)}
              />
            </Field>
            <Field label="VISION_MAX_IMAGES" hint="单次请求最多处理的图片数量（默认 5，超出部分直接透传）">
              <input
                type="text"
                value={form.visMaxImages}
                onChange={e => set('visMaxImages', e.target.value)}
              />
            </Field>
          </div>
        </div>

        <div className="divider" />

        {/* Web tools */}
        <div className="form-group">
          <div className="form-group-title">
            联网工具
            <span className="optional-tag">可选</span>
          </div>
          <div className="form-grid">
            <SelectField
              label="搜索服务商"
              value={form.searchProvider}
              onChange={v => set('searchProvider', v)}
              options={PROVIDER_OPTIONS}
            />
            <Field label={form.searchProvider === 'tavily' ? 'TAVILY_API_KEY' : 'BRAVE_API_KEY'}>
              <input
                type="password"
                value={form.searchKey}
                onChange={e => set('searchKey', e.target.value)}
                placeholder={form.searchProvider === 'tavily' ? 'tvly-…' : 'BSA-…'}
                className={filledClass(form.searchKey)}
                autoComplete="off"
              />
            </Field>
          </div>
          <div style={{ paddingTop: 4 }}>
            <SwitchRow label="启用联网搜索工具（web_search）" checked={form.webSearch} onChange={v => set('webSearch', v)} />
            <SwitchRow label="启用网页抓取工具（web_fetch）" checked={form.webFetch} onChange={v => set('webFetch', v)} />
          </div>
        </div>

        <div className="divider" />

        {/* Server */}
        <div className="form-group">
          <div className="form-group-title">服务器</div>
          <div className="form-grid">
            <Field label="PORT（端口）">
              <input type="text" value={form.port} onChange={e => set('port', e.target.value)} />
            </Field>
            <SelectField
              label="LOG_LEVEL（日志级别）"
              value={form.logLevel}
              onChange={v => set('logLevel', v)}
              options={LOG_OPTIONS}
            />
          </div>
        </div>

        <div className="btn-row">
          <button className="btn btn-ghost" onClick={() => { setForm(DEFAULTS); setGenerated(null) }}>
            重置
          </button>
          <button className="btn btn-primary" onClick={generate}>
            生成 .env 配置文件
          </button>
        </div>
      </div>

      {generated && (
        <div className="section" ref={envRef}>
          <div className="section-header">
            <span className="section-title">生成结果</span>
            <div className="section-line" />
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button className={`btn-copy ${copied ? 'copied' : ''}`} onClick={copyEnv} disabled={applying}>
                {copied ? '已复制 ✓' : '复制'}
              </button>
              <button className="btn btn-primary" onClick={applyAndRestart} disabled={applying}
                style={{ padding: '6px 16px', fontSize: 13 }}>
                {applying ? '重启中…' : '应用并重启'}
              </button>
            </div>
          </div>
          {applyMsg && (
            <div style={{
              padding: '10px 14px',
              borderRadius: 'var(--rsm)',
              background: applyMsg.startsWith('✓') ? 'rgba(23,169,114,.08)' : 'rgba(79,110,247,.07)',
              border: `1px solid ${applyMsg.startsWith('✓') ? 'rgba(23,169,114,.25)' : 'var(--border)'}`,
              color: applyMsg.startsWith('✓') ? 'var(--ok)' : 'var(--text2)',
              fontSize: 14,
            }}>
              {applyMsg}
            </div>
          )}
          <EnvPreview text={generated} />
          <div style={{ fontSize: 13, color: 'var(--text3)', lineHeight: 1.8 }}>
            也可以手动保存为项目根目录下的 <code>.env</code> 文件后重启服务：
          </div>
          <div className="run-cmd">
            {'docker build -t deepseek-vision . &&\ndocker run --env-file .env -p 8000:8000 deepseek-vision'}
          </div>
        </div>
      )}
    </>
  )
}

// ── App ────────────────────────────────────────────────────────────────────

export default function App() {
  const [status, setStatus] = useState<StatusData | null>(null)
  const [offline, setOffline] = useState(false)
  const [models, setModels] = useState<string[]>([])

  async function poll() {
    try {
      const r = await fetch('/status')
      if (!r.ok) throw new Error()
      const data: StatusData = await r.json()
      setStatus(data)
      setModels(data.models ?? [])
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }

  useEffect(() => {
    poll()
    const id = setInterval(poll, 15_000)
    return () => clearInterval(id)
  }, [])

  const liveClass = offline ? 'err' : status ? 'ok' : ''
  const liveLabel = offline ? '离线' : status ? '在线' : '检测中…'

  return (
    <div className="layout">
      <header>
        <img src="/icon.png" alt="logo" style={{width:32,height:32,borderRadius:8,objectFit:"cover"}} />
        <span className="header-title">deepseek-vision</span>
        <span className="header-badge">配置器</span>
        <div className="header-live">
          <div className={`live-dot ${liveClass}`} />
          <span>{liveLabel}</span>
        </div>
      </header>

      <main>
        <div className="section">
          <SectionHeader title="服务状态" />
          <StatusSection data={status} offline={offline} />
        </div>

        <div className="section">
          <SectionHeader title="可用模型" />
          <div className="card">
            {models.length > 0
              ? <div className="model-list">{models.map(m => <span key={m} className="model-tag">{m}</span>)}</div>
              : <span className="empty-text">暂无模型 — 请设置 DEEPSEEK_API_KEY 并重启服务</span>
            }
          </div>
        </div>

        <div className="section">
          <SectionHeader title="配置生成" />
          <ConfigSection />
        </div>
      </main>
    </div>
  )
}
