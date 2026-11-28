import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { CheckCircle, Clock, Copy, WhatsappLogo, X } from '@phosphor-icons/react'
import { api } from '../services/api'
import { useAuth } from '../auth/useAuth'
import { Button } from '../components/ui/Button'
import { BankAccountSetupCard } from '../components/payments/BankAccountSetupCard'

interface WhatsAppStatus {
  linked: boolean
  phone_masked: string | null
}

interface LinkCodeResponse {
  code: string
  expires_at: string
  join_url: string | null
  link_url: string | null
}

interface SetupPreviewResponse {
  phone_masked: string
  expires_at: string
  already_linked_to_current_user: boolean
  already_linked_to_other_account: boolean
}

interface CompleteSetupResponse {
  ok: boolean
  phone_masked: string
  display_name: string
  notified_whatsapp: boolean
}

interface SettlementSettings {
  default_target: 'crypto' | 'fiat'
  is_explicit: boolean
}

function formatCountdown(seconds: number) {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, '0')
  const remainder = (seconds % 60).toString().padStart(2, '0')
  return `${minutes}:${remainder}`
}

function Settings() {
  const { user } = useAuth()
  const isWhatsAppOnlyAccount = Boolean(
    user?.hasWallet === false || user?.address?.startsWith('whatsapp:'),
  )
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const setupToken = searchParams.get('whatsapp_setup')?.trim() || null

  const [status, setStatus] = useState<WhatsAppStatus | null>(null)
  const [statusLoading, setStatusLoading] = useState(true)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [linkInfo, setLinkInfo] = useState<LinkCodeResponse | null>(null)
  const [linkDialogOpen, setLinkDialogOpen] = useState(false)
  const [linkStep, setLinkStep] = useState<'waiting' | 'success'>('waiting')
  const [linkLoading, setLinkLoading] = useState(false)
  const [unlinking, setUnlinking] = useState(false)
  const [linkError, setLinkError] = useState<string | null>(null)
  const [copiedCommand, setCopiedCommand] = useState(false)
  const [now, setNow] = useState(Date.now())
  const [settlement, setSettlement] = useState<SettlementSettings | null>(null)
  const [settlementLoading, setSettlementLoading] = useState(true)
  const [settlementSaving, setSettlementSaving] = useState(false)
  const [settlementError, setSettlementError] = useState<string | null>(null)

  const [setupLoading, setSetupLoading] = useState(false)
  const [setupPreview, setSetupPreview] = useState<SetupPreviewResponse | null>(null)
  const [setupError, setSetupError] = useState<string | null>(null)
  const [completingSetup, setCompletingSetup] = useState(false)
  const [setupSuccess, setSetupSuccess] = useState<CompleteSetupResponse | null>(null)

  const clearSetupParam = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.delete('whatsapp_setup')
      return next
    }, { replace: true })
  }, [setSearchParams])

  const refreshStatus = useCallback(async () => {
    try {
      const next = await api<WhatsAppStatus>('/v1/whatsapp/status')
      setStatus(next)
      setStatusError(null)
      if (next.linked && linkDialogOpen) setLinkStep('success')
      return next
    } catch (error) {
      setStatusError(error instanceof Error ? error.message : 'Could not load WhatsApp status.')
      return null
    } finally {
      setStatusLoading(false)
    }
  }, [linkDialogOpen])

  useEffect(() => {
    void refreshStatus()
  }, [refreshStatus])

  useEffect(() => {
    api<SettlementSettings>('/v1/settings/settlement')
      .then(setSettlement)
      .catch((error) => setSettlementError(error instanceof Error ? error.message : 'Could not load settlement settings.'))
      .finally(() => setSettlementLoading(false))
  }, [])

  useEffect(() => {
    if (!setupToken) {
      setSetupLoading(false)
      setSetupPreview(null)
      setSetupError(null)
      return
    }
    let cancelled = false
    setSetupLoading(true)
    setSetupPreview(null)
    setSetupError(null)
    setSetupSuccess(null)
    api<SetupPreviewResponse>(`/v1/whatsapp/setup/${encodeURIComponent(setupToken)}`)
      .then((preview) => {
        if (!cancelled) setSetupPreview(preview)
      })
      .catch((error) => {
        if (!cancelled) {
          setSetupError(error instanceof Error ? error.message : 'Could not load WhatsApp setup link.')
        }
      })
      .finally(() => {
        if (!cancelled) setSetupLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [setupToken])

  useEffect(() => {
    if (!linkDialogOpen) return
    void refreshStatus()
    const interval = window.setInterval(() => void refreshStatus(), 3000)
    return () => window.clearInterval(interval)
  }, [linkDialogOpen, refreshStatus])

  useEffect(() => {
    if (!linkDialogOpen || linkStep !== 'success') return
    const timeout = window.setTimeout(() => setLinkDialogOpen(false), 1800)
    return () => window.clearTimeout(timeout)
  }, [linkDialogOpen, linkStep])

  const expiresAt = linkInfo ? Date.parse(linkInfo.expires_at) : null
  const secondsRemaining = expiresAt === null
    ? 0
    : Math.max(0, Math.ceil((expiresAt - now) / 1000))

  useEffect(() => {
    if (!linkDialogOpen || expiresAt === null) return
    setNow(Date.now())
    const interval = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(interval)
  }, [expiresAt, linkDialogOpen])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (linkDialogOpen && !dialog.open) dialog.showModal()
    if (!linkDialogOpen && dialog.open) dialog.close()
  }, [linkDialogOpen])

  async function issueLinkCode() {
    setLinkLoading(true)
    setLinkError(null)
    setCopiedCommand(false)
    try {
      const response = await api<LinkCodeResponse>('/v1/whatsapp/link-code', { method: 'POST' })
      setLinkInfo(response)
      setLinkStep('waiting')
      setNow(Date.now())
      setLinkDialogOpen(true)
    } catch (error) {
      setLinkError(error instanceof Error ? error.message : 'Could not create a WhatsApp link code.')
    } finally {
      setLinkLoading(false)
    }
  }

  async function copyLinkCommand(code: string) {
    try {
      await navigator.clipboard.writeText(`link ${code}`)
      setCopiedCommand(true)
      window.setTimeout(() => setCopiedCommand(false), 1800)
    } catch {
      // Clipboard may be unavailable.
    }
  }

  async function completeSetup() {
    if (!setupToken) return
    setCompletingSetup(true)
    setSetupError(null)
    try {
      const response = await api<CompleteSetupResponse>('/v1/whatsapp/setup/complete', {
        method: 'POST',
        body: JSON.stringify({ token: setupToken }),
      })
      setSetupSuccess(response)
      setSetupPreview(null)
      clearSetupParam()
      await refreshStatus()
    } catch (error) {
      setSetupError(error instanceof Error ? error.message : 'Could not connect WhatsApp.')
    } finally {
      setCompletingSetup(false)
    }
  }

  async function unlinkWhatsApp() {
    setUnlinking(true)
    setLinkError(null)
    setSetupSuccess(null)
    try {
      await api<{ ok: boolean }>('/v1/whatsapp/link', { method: 'DELETE' })
      await refreshStatus()
    } catch (error) {
      setLinkError(error instanceof Error ? error.message : 'Could not unlink WhatsApp.')
    } finally {
      setUnlinking(false)
    }
  }

  async function saveSettlementTarget(defaultTarget: 'crypto' | 'fiat') {
    setSettlementSaving(true)
    setSettlementError(null)
    try {
      const next = await api<SettlementSettings>('/v1/settings/settlement', {
        method: 'PATCH',
        body: JSON.stringify({ default_target: defaultTarget }),
      })
      setSettlement(next)
    } catch (error) {
      setSettlementError(error instanceof Error ? error.message : 'Could not save settlement settings.')
    } finally {
      setSettlementSaving(false)
    }
  }

  return (
    <div className="w-full space-y-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-primary">Settings</h1>
        <p className="mt-1 text-sm text-foreground/60">Manage your account connections.</p>
      </header>

      <div className="grid gap-6 xl:grid-cols-2 xl:items-start">
        <section aria-labelledby="whatsapp-settings-title" className="rounded-panel border border-primary/10 bg-surface p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-card bg-primary/10 text-primary">
              <WhatsappLogo size={24} weight="fill" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <h2 id="whatsapp-settings-title" className="font-semibold text-primary">WhatsApp</h2>
              <p className="mt-1 text-sm text-foreground/60">
                {statusLoading
                  ? 'Checking connection…'
                  : status?.linked
                    ? `Connected · ${status.phone_masked ?? 'WhatsApp'}`
                    : 'Not connected'}
              </p>
            </div>
          </div>
          <div className="flex w-full flex-wrap gap-2 sm:w-auto">
            {status?.linked ? (
              isWhatsAppOnlyAccount ? (
                <span className="inline-flex items-center rounded-pill bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
                  Sign-in identity
                </span>
              ) : (
                <Button variant="secondary" size="sm" loading={unlinking} onClick={() => void unlinkWhatsApp()}>
                  Unlink
                </Button>
              )
            ) : (
              <Button size="sm" loading={linkLoading} disabled={statusLoading} onClick={() => void issueLinkCode()}>
                Connect WhatsApp
              </Button>
            )}
          </div>
        </div>

        {setupToken && (
          <div className="mt-4 rounded-card border border-primary/15 bg-background/60 p-4">
            {setupLoading ? (
              <p className="text-sm text-foreground/70">Checking your WhatsApp setup link…</p>
            ) : setupError ? (
              <div className="space-y-3">
                <p role="alert" className="text-sm text-red-700 dark:text-red-300">{setupError}</p>
                <Button size="sm" variant="secondary" onClick={clearSetupParam}>
                  Dismiss
                </Button>
              </div>
            ) : setupPreview ? (
              <div className="space-y-3">
                <div>
                  <p className="text-sm font-semibold text-primary">Confirm WhatsApp connection</p>
                  <p className="mt-1 text-sm text-foreground/70">
                    Link WhatsApp number{' '}
                    <span className="font-mono font-medium text-primary">{setupPreview.phone_masked}</span>{' '}
                    to this Veil account so messages from it create payment links for your wallet.
                  </p>
                  {setupPreview.already_linked_to_other_account && (
                    <p className="mt-2 text-xs text-foreground/60">
                      This number is currently linked to a different Veil account and will be moved here.
                    </p>
                  )}
                  {setupPreview.already_linked_to_current_user && (
                    <p className="mt-2 text-xs text-foreground/60">
                      This number is already linked to your account.
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" loading={completingSetup} onClick={() => void completeSetup()}>
                    Confirm &amp; link
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={completingSetup}
                    onClick={() => {
                      setSetupPreview(null)
                      clearSetupParam()
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            ) : null}
          </div>
        )}

        {setupSuccess && !setupToken && (
          <div className="mt-4 rounded-card bg-emerald-50 p-4 text-sm text-emerald-800 dark:bg-emerald-950/45 dark:text-emerald-300" role="status">
            <p className="flex items-center gap-2 font-medium">
              <CheckCircle size={18} weight="fill" aria-hidden="true" />
              WhatsApp connected · {setupSuccess.phone_masked}
            </p>
            <p className="mt-1 text-xs opacity-90">
              {setupSuccess.notified_whatsapp
                ? 'We sent a confirmation on WhatsApp — you can return to your chat now.'
                : 'You can return to your WhatsApp chat now.'}
            </p>
          </div>
        )}

        {statusError && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-card bg-red-50 px-4 py-3 dark:bg-red-950/45">
            <p role="alert" className="text-sm text-red-700 dark:text-red-300">{statusError}</p>
            <button type="button" className="text-sm font-medium text-red-700 underline dark:text-red-300" onClick={() => void refreshStatus()}>
              Try again
            </button>
          </div>
        )}
        {linkError && !linkDialogOpen && (
          <p role="alert" className="mt-3 text-sm text-red-700 dark:text-red-300">{linkError}</p>
        )}
        </section>

        <div id="fiat-account-settings">
          <BankAccountSetupCard />
        </div>
      </div>

      <section aria-labelledby="settlement-settings-title" className="rounded-panel border border-primary/10 bg-surface p-5 sm:p-6">
        <div>
          <h2 id="settlement-settings-title" className="font-semibold text-primary">Default settlement</h2>
          <p className="mt-1 max-w-2xl text-sm text-foreground/60">
            Choose where new WhatsApp payment links should settle. This applies to future links only.
          </p>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {([
            { value: 'crypto' as const, title: 'Crypto wallet', description: 'Keep crypto payments in your wallet.' },
            { value: 'fiat' as const, title: 'Nigerian bank account', description: 'Convert supported crypto payments to NGN.' },
          ]).map((option) => (
            <label
              key={option.value}
              className={`cursor-pointer rounded-card border p-4 transition-colors ${
                settlement?.default_target === option.value
                  ? 'border-primary-action bg-primary/5'
                  : 'border-primary/10 hover:border-primary/30'
              }`}
            >
              <input
                type="radio"
                name="default-settlement"
                value={option.value}
                checked={settlement?.default_target === option.value}
                disabled={settlementLoading || settlementSaving}
                onChange={() => void saveSettlementTarget(option.value)}
                className="sr-only"
              />
              <p className="text-sm font-semibold text-primary">{option.title}</p>
              <p className="mt-1 text-xs text-foreground/60">{option.description}</p>
            </label>
          ))}
        </div>
        {settlementError && <p role="alert" className="mt-3 text-sm text-red-700 dark:text-red-300">{settlementError}</p>}
      </section>

      <dialog
        ref={dialogRef}
        aria-labelledby="whatsapp-link-title"
        onCancel={(event) => {
          event.preventDefault()
          setLinkDialogOpen(false)
        }}
        onClose={() => setLinkDialogOpen(false)}
        onClick={(event) => {
          if (event.target === event.currentTarget) setLinkDialogOpen(false)
        }}
        className="m-auto max-h-[90dvh] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-panel border border-primary/10 bg-surface p-0 text-foreground shadow-veil-lg backdrop:bg-foreground/40 backdrop:backdrop-blur-sm max-sm:mb-0 max-sm:mt-auto max-sm:w-full max-sm:max-w-none max-sm:rounded-b-none max-sm:rounded-t-panel dark:backdrop:bg-black/65"
      >
        <div className="p-5 sm:p-7">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 id="whatsapp-link-title" className="text-xl font-semibold text-primary">
                {linkStep === 'success' ? 'WhatsApp connected' : 'Connect WhatsApp'}
              </h2>
              <p className="mt-1 text-sm text-foreground/60">
                {linkStep === 'success'
                  ? `Your account is connected${status?.phone_masked ? ` · ${status.phone_masked}` : ''}.`
                  : 'Follow these steps to link your WhatsApp number.'}
              </p>
            </div>
            <button
              type="button"
              aria-label="Close"
              onClick={() => setLinkDialogOpen(false)}
              className="flex size-9 shrink-0 items-center justify-center rounded-full text-foreground/50 hover:bg-primary/5 hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
            >
              <X size={20} />
            </button>
          </div>

          {linkStep === 'success' ? (
            <div className="mt-6 rounded-card bg-emerald-50 p-4 text-emerald-800 dark:bg-emerald-950/45 dark:text-emerald-300" role="status">
              <p className="flex items-center gap-2 font-medium"><CheckCircle size={20} weight="fill" /> Successfully linked</p>
              <Button className="mt-4" onClick={() => setLinkDialogOpen(false)}>Done</Button>
            </div>
          ) : linkInfo ? (
            <div className="mt-6 space-y-5">
              <div className="rounded-card border border-primary/10 p-4">
                {linkInfo.join_url ? (
                  <>
                    <p className="text-sm font-semibold text-primary">1. Open Veil on WhatsApp</p>
                    <p className="mt-1 text-sm leading-relaxed text-foreground/60">
                      Start a chat with Veil's WhatsApp business number.
                    </p>
                    <a
                      href={linkInfo.join_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-3 inline-flex h-10 items-center justify-center rounded-sm bg-primary-action px-4 text-sm font-medium text-white hover:bg-primary-action-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    >
                      Open WhatsApp
                    </a>
                  </>
                ) : (
                  <>
                    <p className="text-sm font-semibold text-primary">1. Open your Veil chat on WhatsApp</p>
                    <p className="mt-1 text-sm leading-relaxed text-foreground/60">
                      Open the chat where you messaged Veil on WhatsApp to send the code below.
                    </p>
                  </>
                )}
              </div>

              <div className="rounded-card border border-primary/10 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-primary">2. Send link code</p>
                  {secondsRemaining > 0 && (
                    <span className="inline-flex items-center gap-1.5 text-xs tabular-nums text-foreground/55">
                      <Clock size={15} aria-hidden="true" /> Expires in {formatCountdown(secondsRemaining)}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-sm text-foreground/60">
                  Send <span className="font-mono font-medium text-primary">link {linkInfo.code}</span> to the bot on WhatsApp.
                </p>
                {secondsRemaining > 0 ? (
                  <>
                    <p className="my-4 break-all text-center font-mono text-3xl font-semibold tracking-[0.18em] text-primary sm:text-4xl">
                      {linkInfo.code}
                    </p>
                    <div className="flex flex-col gap-2">
                      {linkInfo.link_url && (
                        <a
                          href={linkInfo.link_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex h-10 w-full items-center justify-center rounded-sm border border-primary/20 bg-surface px-4 text-sm font-medium text-primary hover:bg-primary/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                        >
                          Send link code
                        </a>
                      )}
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        fullWidth
                        leftIcon={copiedCommand ? <CheckCircle size={15} weight="fill" /> : <Copy size={15} />}
                        onClick={() => void copyLinkCommand(linkInfo.code)}
                      >
                        {copiedCommand ? 'Copied command' : `Copy "link ${linkInfo.code}"`}
                      </Button>
                    </div>
                  </>
                ) : (
                  <div className="mt-4">
                    <p role="alert" className="text-sm text-red-700 dark:text-red-300">This code has expired. Create a new code to continue.</p>
                    <Button className="mt-3" loading={linkLoading} onClick={() => void issueLinkCode()}>
                      Generate a new code
                    </Button>
                  </div>
                )}
              </div>
              {linkError && <p role="alert" className="text-sm text-red-700 dark:text-red-300">{linkError}</p>}
            </div>
          ) : (
            <div className="mt-6 space-y-3">
              <p className="text-sm text-foreground/60">Preparing your secure link code…</p>
              {linkError && <p role="alert" className="text-sm text-red-700 dark:text-red-300">{linkError}</p>}
              <Button loading={linkLoading} onClick={() => void issueLinkCode()}>Try again</Button>
            </div>
          )}
        </div>
      </dialog>
    </div>
  )
}

export default Settings
