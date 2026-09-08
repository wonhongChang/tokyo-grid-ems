# 2026-09-09 配信補正契約の整備

Languages: [English](../../en/model-improvements/model-improvement-2026-09-09-serving-calibration-contracts.md) · [한국어](../../ko/model-improvements/model-improvement-2026-09-09-serving-calibration-contracts.md)

## 背景と範囲

[9月8日のモデル点検](../model-reviews/model-review-2026-09-08.md)で確認した、リード不一致の区間推定、同一レジーム証跡の古さ、終段ガード変動量の不足を修正した。事前予測の誤差を保存政策のせいにしたり、TEPCO予測を補正入力に使ったりする変更ではない。

学習artifactは`v14-r2-source-robust-day-ahead`のまま。区間計算とログ追加はq50を変更しないが、D-1 priorをD0へ再利用しなくなるため、**配信中心線は変わり得る**。新モデルの昇格や全体MAE改善の証明とは区別する。

## 1. リード別予測区間

`build_lead_conformal_profile()`は`forecast_snapshots/`と`forecast_origins/`の実際の事前発行本を読み、上書き後の最終`forecast/`は使わない。

- 現行artifact SHAと`servingPolicyFingerprint`の一致を要求する。timezoneのない時刻は除外し、時刻をJSTへ変換する。
- 対象時間枠の開始前に発行された正のリードのみを使用する。区分は`(0,2]`、`(2,4]`、`(4,8]`、`(8,24]`、`(24,48]`時間。
- ETL `okDates`と24時間すべての真の実績が必要。TEPCO予測代替値は実績ではない。
- 直近28暦日のうち発行日DのD-2までを使用する。過去CSVの確定時刻が保存されていないため、朝の確定値が深夜にも存在したと仮定するreplayを避ける。
- 同一日・対象時刻・リード区分は最後の事前発行本にまとめ、実行回数による標本の偏りを防ぐ。

対象時間帯は従来の`overnight` 00-05、`morning` 06-10、`daytime` 11-15、`late_afternoon` 16-18、`evening` 19-23。区間誤差の集計単位であり、需要を強制的に上下させる条件ではない。

リード・時間帯ごとに同一レジームと全レジームを別集計し、**各集計24標本・4日以上**を要求する。有効な有限標本誤差q95の大きい方に1.05を掛ける。同一レジームが不足すれば有効な全レジームを使えるが、別リードの証跡で補充しない。

### 導入直後と証跡不足

証跡不足や範囲外リードは`native_fallback`としてnative区間の正規化・上限制御を維持する。必要半幅が3,750MWを超える場合は`native_fallback_cap_exceeded`と`requiredHalfWidthMw`を記録する。上限で切った結果を目標包含率達成と呼ばない。

旧スナップショットへ新しい政策fingerprintを遡及付与しない。点検資料には新契約と互換性のある標本が0件だったため、導入直後はtargetが無効で区間が広がる可能性がある。`availability: ok`は一部時刻でtargetを計算できた意味であり、各時刻の`detailsByHour`が実際の状態を示す。native代替やp95という名称は実測包含率95%の保証ではない。

標準保存モードでは観測済み時間の公開p95/p99も保持し、新政策で過去の成績を作り直さない。fingerprintはq50関連設定と`servingSemanticsVersion`を含み、区間幅設定は含まない。設定が変わらなくてもq50コードの意味が変われば、このversionを更新する必要がある。

## 2. 同一レジーム補正の出所と適用範囲

`SameRegimeDayLevelCalibrator`は`application: day_ahead_only`、`require_day_ahead_origin: true`で動作する。

- JST前日に発行するD-1予測だけに適用する。D0は`origin_horizon_mismatch`でこの層を迂回するが、通常のintraday補正は続く。
- 同一artifactの`immutable_day_ahead_origin`に結び付く確定実績残差だけを認める。D0 holdout seedと旧retained snapshotは除外する。
- 発行日以降の確定実績を除外し、全体の最新残差は発行日から2日以内を要求する。
- それとは別に、日本の営業日・休日暦から直近の同一レジーム3日を算出する。選択日がこの集合に属するか確認し、別レジームの新しい記録で古い平日証跡を通さない。通常の週末間隔は暦で扱う。
- 不足時は`insufficient_same_regime_history`、古い場合は`stale_same_regime_history`で補正0とし、`expectedHistoryDates`、`rejectedOriginEntries`を残す。

有効な場合だけ日平均残差3個の中央値×0.25を+/-1,000MW以内で適用する。D0へのD-1 prior再利用中止は中心線に影響するため、以後の評価はD0/D-1を分離する。

## 3. 終段変動量とAI入力

Operational-calibrationの時間別行に`terminalAdjustments`、metadataに`terminalAdjustmentsByHour`を追加する。

| フィールド | 意味 |
|---|---|
| `preCalibrationMw` | intraday直前の値 |
| `preTerminalAdjustmentMw` | 終段shape/rampより前の総変動。純粋な残差だけではない |
| `shapeGuardDeltaMw` | 終段shape guardの変動 |
| `rampGuardDeltaMw` | 終段ramp guardの変動 |
| `postCalibrationMw` | 終段処理後の値 |
| `totalAdjustmentMw` | intraday直前からの総変動 |

```text
preCalibrationMw + preTerminalAdjustmentMw
  + shapeGuardDeltaMw + rampGuardDeltaMw = postCalibrationMw
```

既存の`residualCarryover.finalAdjustmentMw`の意味は変えない。9月8日13:32実行の14時行ではpre 42,870.1MW、残差-112.1MW、post 40,880MWだった。保存入力から終段を再構成すると、残り-1,878.0MWはramp guardの変動と確認できる。公開済み予測は書き換えない。

AIの上限付き`focusedRows`に4個の数値変動量だけを追加する。自然言語の結論、API呼び出し回数、モデル、全24時間の送信範囲は増やさない。既存AIリポートも自動再生成しない。

## 4. 検証と限界

- 外部ネットワークを遮断したテストプロセスで全609テスト通過。有料API呼び出しなし。
- リード分離、重複実行、未来/無timezone時刻、artifact・政策不一致、未確定/代替実績、UTC→JST索引、公開区間保存を検証。
- D0 seed排除、同一レジーム鮮度、通常の週末間隔、D-1/D0分離、終段の合計とAIパケット伝達を検証。
- 固定data revision `0e9a67dcb`から再構成できる**61実行・1,464行が既存終段結果と丸め許容0.2MW以内で一致**。旧ログで前段priorを分離できない8実行は除外し、非ゼロの終段変動は7行だった。

これは**終段の再構成検証であり、全パイプラインの反事実MAEバックテストではない**。新契約互換の証跡が0件だった点検資料では、新区間の包含率改善も証明していない。raw気象感度と午前anchor/残差guardの不要な追加補正は別の後続実験である。

## 5. 反映と次の点検

コード配信後、次のIntraday/ETLから政策・リード・終段ログが蓄積する。再学習や過去予測再計算オプションは不要。この検証ではライブ・ローカル公開JSONを上書きしていない。

1. `intervalCalibration.servedTarget.detailsByHour`のリード、native/target、標本数・日数を確認する。
2. D0でD-1 priorが停止し、D-1の使用履歴が`expectedHistoryDates`と一致することを確認する。
3. 終段デルタの合計、公開q50/区間の保存、artifact同一性を確認する。
4. 互換証跡が増えたら、同一発行時点でリード別包含率・幅・MAEを評価する。旧政策の履歴を新政策として再命名しない。
5. raw気象感度と個別guard on/offを別replayで比較し、昼休みdip、休日転換、夕方下降を含める。TEPCO予測は比較専用とする。

Rollbackでも最終公開線の誤差から全リードを狭める方式やD0 seed混合を復活させない。native状態をまず観察し、中心線guardの変更は別の証跡・変更として管理する。

コード: [`rolling_interval_calibration.py`](../../../python/forecast/rolling_interval_calibration.py)、[`same_regime_calibration.py`](../../../python/forecast/same_regime_calibration.py)、[`intraday_correction.py`](../../../python/forecast/intraday_correction.py)、[`run_batch.py`](../../../python/etl/run_batch.py)、[`ai_daily_report.py`](../../../python/eval/ai_daily_report.py)。
