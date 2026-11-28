import { createContext, useContext, useState, useEffect } from 'react'

export const DataRevision = createContext<string | undefined>(undefined)

interface FetchState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

export function useFetch<T>(url: string | null, cache: RequestCache = 'no-cache', revision = 0): FetchState<T> {
  const dataRevision = useContext(DataRevision)
  const [state, setState] = useState<FetchState<T> & { url: string | null }>({
    url,
    data: null,
    loading: !!url,
    error: null,
  })

  useEffect(() => {
    if (!url) {
      setState({ url, data: null, loading: false, error: null })
      return
    }
    const controller = new AbortController()
    setState(prev => prev.url === url && prev.data ? prev : { url, data: null, loading: true, error: null })

    fetch(url, { cache, signal: controller.signal })
      .then(res => {
        if (res.status === 404) return null
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json() as Promise<T>
      })
      .then(data => {
        if (!controller.signal.aborted) setState({ url, data, loading: false, error: null })
      })
      .catch(err => {
        if (!controller.signal.aborted) setState(prev => ({ url, data: prev.url === url ? prev.data : null, loading: false, error: String(err.message) }))
      })

    return () => controller.abort()
  }, [url, cache, revision, dataRevision])

  return state.url === url ? state : { data: null, loading: !!url, error: null }
}
