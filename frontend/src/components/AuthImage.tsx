import { useEffect, useState } from 'react'

import { fetchBlob } from '../api'

interface Props {
  path: string // API path, e.g. /images/3/thumbnail
  alt: string
  className?: string
}

type Loaded = { path: string; url: string | null } // url null = failed

/**
 * <img> that sends the JWT. A plain <img src="/api/..."> can't add an Authorization header,
 * so we fetch the bytes ourselves and show them through a temporary blob: URL, which is
 * revoked when the component unmounts or the path changes (otherwise memory leaks).
 */
export function AuthImage({ path, alt, className }: Props) {
  const [loaded, setLoaded] = useState<Loaded | null>(null)

  useEffect(() => {
    let cancelled = false
    let objectUrl: string | null = null
    fetchBlob(path)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setLoaded({ path, url: objectUrl })
      })
      .catch(() => {
        if (!cancelled) setLoaded({ path, url: null })
      })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [path])

  // Ignore a result that belongs to a previous path.
  const current = loaded?.path === path ? loaded : null
  const placeholder = `image-placeholder ${className ?? ''}`
  if (!current) return <div className={placeholder}>Loading…</div>
  if (!current.url) return <div className={placeholder}>Image unavailable</div>
  return <img src={current.url} alt={alt} className={className} />
}
