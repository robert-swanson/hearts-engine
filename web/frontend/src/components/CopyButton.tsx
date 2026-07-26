import { useState } from 'react'

/** A button that copies `text` to the clipboard and briefly shows a "copied" label. */
export function CopyButton({
  text,
  label = 'Copy',
  copiedLabel = 'Copied!',
  className,
}: {
  text: string
  label?: string
  copiedLabel?: string
  className?: string
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
    <button type="button" className={className} onClick={onClick}>
      {copied ? copiedLabel : label}
    </button>
  )
}
