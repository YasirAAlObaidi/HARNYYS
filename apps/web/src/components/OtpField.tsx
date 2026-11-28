import { useState } from 'react'

import { toWesternDigits } from '../lib/digits'

interface OtpFieldProps {
  value: string
  onChange: (value: string) => void
  /** Called once the sixth digit is in (typed or pasted). */
  onComplete: (value: string) => void
  label: string
  describedBy?: string
  invalid?: boolean
  disabled?: boolean
}

/**
 * The authenticator code as six cells. It is one real input (numeric keyboard, one-time-code autofill, paste
 * fills every cell) drawn as cells. Eastern Arabic digits are accepted and shown as 0-9. Always left to right.
 */
export function OtpField({ value, onChange, onComplete, label, describedBy, invalid, disabled }: OtpFieldProps) {
  const [focused, setFocused] = useState(false)
  const active = Math.min(value.length, 5)
  return (
    <div className={`otp${invalid ? ' otp--error' : ''}`} dir="ltr">
      <input
        className="otp__input"
        aria-label={label}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        name="code"
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={12}
        value={value}
        disabled={disabled}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onChange={(event) => {
          const next = toWesternDigits(event.target.value).replace(/\D/g, '').slice(0, 6)
          onChange(next)
          if (next.length === 6 && value.length < 6) onComplete(next)
        }}
      />
      {Array.from({ length: 6 }, (_, index) => (
        <span
          key={index}
          aria-hidden="true"
          className={`otp__cell${focused && index === active ? ' otp__cell--active' : ''}${index === 3 ? ' otp__cell--group' : ''}`}
        >
          {value[index] ?? ''}
        </span>
      ))}
    </div>
  )
}
