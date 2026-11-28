// Inputs accept Eastern Arabic (٠-٩) and Persian (۰-۹) digits, as staff type them on an Arabic keyboard
// (docs/decisions/0015). The server normalises too; doing it here lets the form check a code before sending.

const EASTERN = '٠١٢٣٤٥٦٧٨٩'
const PERSIAN = '۰۱۲۳۴۵۶۷۸۹'

export function toWesternDigits(text: string): string {
  return text.replace(/[٠-٩۰-۹]/g, (digit) => {
    const eastern = EASTERN.indexOf(digit)
    return String(eastern >= 0 ? eastern : PERSIAN.indexOf(digit))
  })
}

/** A 6-digit authenticator code from what was typed (spaces and either digit style allowed), or null. */
export function normaliseCode(text: string): string | null {
  const digits = toWesternDigits(text).replace(/\s+/g, '')
  return /^\d{6}$/.test(digits) ? digits : null
}
