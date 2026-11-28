import svg from '../assets/kahraman-logo.svg?raw'

/**
 * Kahraman's logo, inline: the mark is always brand gold, the wordmark takes the text colour (white on the
 * green rail, charcoal or cream on the page). The file has no <style>, so the strict CSP allows it.
 */
export function Logo({ label, className }: { label: string; className?: string }) {
  return <span className={`logo ${className ?? ''}`} role="img" aria-label={label} dangerouslySetInnerHTML={{ __html: svg }} />
}
