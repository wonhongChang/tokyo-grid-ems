import { useState, useEffect } from 'react'

interface FetchState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

export function useFetch<T>(url: string | null): FetchState<T> {
  const [state, setState] = useState<FetchState<T>>({
    data: null,
    loading: !!url,
    error: null,
  })

  useEffect(() => {
    if (!url) {
      setState({ data: null, loading: false, error: null })
      return
    }
    let cancelled = false
    setState({ data: null, loading: true, error: null })

    fetch(url)
      .then(res => {
        if (res.status === 404) return null
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json() as Promise<T>
      })
      .then(data => {
        if (!cancelled) setState({ data, loading: false, error: null })
      })
      .catch(err => {
        if (!cancelled) setState({ data: null, loading: false, error: String(err.message) })
      })

    return () => { cancelled = true }
  }, [url])

  return state
}
