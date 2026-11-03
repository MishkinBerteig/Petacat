import { ApiError, describeApiError } from '@/api/client'

/**
 * What a refusal said, in one sentence.
 *
 * The Database tab's refusals carry a code (`session_managed`, `episodic_memory_protected`,
 * `journal_read_only`, ...) and a message, either as FastAPI's `detail` object or as the change
 * API's `{ error, message }` body. Both are shown, so the reader sees which guard stopped them.
 */
export function describeDbError(err: unknown, action: string): string {
  if (err instanceof ApiError) {
    try {
      const body = JSON.parse(err.body)
      const detail = body?.detail
      if (detail && typeof detail === 'object' && !Array.isArray(detail) && detail.message) {
        return `Could not ${action} (${detail.error ?? err.status}): ${detail.message}`
      }
      if (body && typeof body === 'object' && body.ok === false && body.message) {
        const first = Array.isArray(body.problems) && body.problems[0]?.message
        return `Could not ${action} (${body.error}): ${body.message}${first && first !== body.message ? ` ${first}` : ''}`
      }
    } catch {
      // not JSON: fall through to the general sentence
    }
  }
  return describeApiError(err, action)
}
