// Match the generator's catalog labels, not ordinary discussion of a guard.
export function isTechnicalCatalogNote(note: string): boolean {
  return /^(?:운영 보정 신호 카탈로그|Operational calibration signal catalog|運用補正シグナルカタログ|運用調整信号カタログ)\s*[:：]/i.test(note.trim())
}
