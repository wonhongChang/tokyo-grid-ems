import type { Locale } from './i18n'

const LOCALE_TAGS: Record<Locale, string> = {
  ko: 'ko-KR',
  en: 'en-US',
  ja: 'ja-JP',
}

function divisor(locale: Locale): number {
  return locale === 'en' ? 1000 : 10
}

export function powerUnit(locale: Locale): string {
  if (locale === 'ko') return '만 kW'
  if (locale === 'en') return 'GW'
  return '万kW'
}

export function powerAxisStep(locale: Locale): number {
  return locale === 'en' ? 2 : 200
}

export function powerDisplayValue(mw: number, locale: Locale): number {
  return mw / divisor(locale)
}

export function formatPowerDisplayValue(value: number, locale: Locale): string {
  if (locale === 'en') {
    return value.toLocaleString(LOCALE_TAGS[locale], {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    })
  }
  return Math.round(value).toLocaleString(LOCALE_TAGS[locale])
}

export function formatPowerParts(mw: number, locale: Locale): { value: string; unit: string } {
  return {
    value: formatPowerDisplayValue(powerDisplayValue(mw, locale), locale),
    unit: powerUnit(locale),
  }
}

export function formatPower(mw: number, locale: Locale): string {
  const parts = formatPowerParts(mw, locale)
  return `${parts.value} ${parts.unit}`
}
