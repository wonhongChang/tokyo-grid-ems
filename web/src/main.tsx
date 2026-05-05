import { StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'
import { I18nContext, type Locale } from './i18n'

function Root() {
  const [locale, setLocale] = useState<Locale>('ja')
  return (
    <I18nContext.Provider value={locale}>
      <App locale={locale} setLocale={setLocale} />
    </I18nContext.Provider>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
