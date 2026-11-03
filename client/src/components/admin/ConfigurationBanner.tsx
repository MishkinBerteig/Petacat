import { useEffect, useState } from 'react'
import { getConfigurationStatus, GLOBAL_CONFIGURATION_ID } from '@/api/client'
import type { ConfigurationStatus } from '@/types/configuration'

/**
 * Information only: how far the configuration differs from the Metacat Standard Configuration.
 *
 * It offers no action and is never an error. A failed or malformed reply shows nothing,
 * because the banner is a convenience beside the editors, not a gate on them.
 * `refreshKey` changes whenever the person moves to another tab or acts on the
 * configuration, which is when the count may have changed.
 */
export function ConfigurationBanner({
  refreshKey,
  configuration = GLOBAL_CONFIGURATION_ID,
}: {
  refreshKey?: unknown
  configuration?: number
}) {
  const [status, setStatus] = useState<ConfigurationStatus | null>(null)

  useEffect(() => {
    let live = true
    getConfigurationStatus(configuration)
      .then(s => { if (live) setStatus(s) })
      .catch(() => { if (live) setStatus(null) })
    return () => { live = false }
  }, [refreshKey, configuration])

  if (!status || typeof status.differs_rows !== 'number' || status.differs_rows === 0) return null

  const n = status.differs_rows
  return (
    <div
      role="note"
      aria-label="Difference from the Metacat Standard Configuration"
      style={{
        padding: '3px 8px', fontSize: 11, marginBottom: 2, borderRadius: 3,
        background: 'rgba(33,150,243,0.15)', color: 'var(--text-secondary)',
      }}
    >
      This configuration differs from the Metacat Standard Configuration in {n} {n === 1 ? 'row' : 'rows'}.
    </div>
  )
}
