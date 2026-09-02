import type { InputHTMLAttributes, ReactNode } from 'react'

interface FormFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  right?: ReactNode
  wrapperClassName?: string
  error?: string
}

export default function FormField({ label, right, wrapperClassName = '', error, ...inputProps }: FormFieldProps) {
  return (
    <div className={`field ${wrapperClassName}`}>
      <label htmlFor={inputProps.id}>{label}</label>
      {right ? (
        <div className="input-wrap">
          <input {...inputProps} />
          {right}
        </div>
      ) : (
        <input {...inputProps} />
      )}
      {error && <span className="field-error">{error}</span>}
    </div>
  )
}
