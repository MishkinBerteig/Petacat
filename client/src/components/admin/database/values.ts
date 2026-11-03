import type { DbColumn } from './types'

/** The text a cell or an edit box shows for a stored value. */
export function showValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

const isJson = (c: DbColumn) => /json/i.test(c.type)
const isNumber = (c: DbColumn) => /int|float|double|numeric|real/i.test(c.type)
const isBool = (c: DbColumn) => /bool/i.test(c.type)

/** Read an edit box back into the value the server stores; throws a sentence on a bad value. */
export function parseValue(column: DbColumn, text: string): unknown {
  if (text === '' && column.nullable) return null
  if (isJson(column)) {
    try {
      return JSON.parse(text)
    } catch {
      throw new Error(`${column.name} is not valid JSON.`)
    }
  }
  if (isNumber(column)) {
    const n = Number(text)
    if (text.trim() === '' || Number.isNaN(n)) throw new Error(`${column.name} is not a number.`)
    return n
  }
  if (isBool(column)) {
    if (text === 'true') return true
    if (text === 'false') return false
    throw new Error(`${column.name} is true or false.`)
  }
  return text
}
