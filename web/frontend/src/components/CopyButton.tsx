import { useState, type ReactNode } from 'react'

/** A button that copies `text` to the clipboard and briefly shows a "copied"
 *  state. `label`/`copiedLabel` may be text or an icon; `title` sets the tooltip
 *  (useful for icon-only buttons). */
export function CopyButton({
  text,
  label = 'Copy',
  copiedLabel = 'Copied!',
  className,
  title,
}: {
  text: string
  label?: ReactNode
  copiedLabel?: ReactNode
  className?: string
  title?: string
}) {
  const [copied, setCopied] = useState(false)
  const onClick = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard blocked (e.g. an insecure context) — leave the label unchanged;
      // the caller typically also shows the text so it can be selected manually.
      setCopied(false)
    }
  }
  return (
    <button type="button" className={className} onClick={onClick} title={copied ? undefined : title}>
      {copied ? copiedLabel : label}
    </button>
  )
}
