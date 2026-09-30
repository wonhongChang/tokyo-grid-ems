# Review Bundle 検証概要

[構造と使い方](review-bundle-cli.md) | [English](../en/review-bundle-validation.md) | [한국어](../ko/review-bundle-validation.md)

対象は根拠の保持と選択照会であり、予測精度・候補昇格・token 削減の検証ではない。保存契約 `review-bundle/0.2.0-design`、表示契約 `review-bundle-batch/1.1.0` は production と独立している。

## 失敗と修正

| 段階 | 発見 | 修正の原則 |
|---|---|---|
| v0.1 offline | 初期 packet は小さいが followup/candidate の参照がなく、26境界検査中10件失敗 | サイズだけで根拠保持を判定しない |
| 欠落・境界入力 | 空/fallback-only actual、日付不一致、advance 不在、pointer/原本消失、overflow が不完全 | 0や最新値で補わず structured unavailable と locator を保持 |
| Q13 oracle 監査 | 最も近い発行本が意図した悪化反例とは別の行だった | 元の記録を残し、Q13-v02 で正確な issue/target を事前固定 |
| v0.2 | scope、全 date/run、候補の変更・悪化 pair、notice/chunk/source 索引を追加 | top-N 外の反例と unknown provenance を保持 |
| CLI | allowlist の不足、Windows CRLF による返却 byte 差 | 正しい namespace と UTF-8/LF。任意アクセスを開放しない |
| Batch/refinement | 単一照会の反復、長い provenance。一律 deferral は小さい一覧を増大 | registry 共有、複数時間、短い一覧 inline と明示的展開 |

Q13-v02 は2026-09-06 12:25:35 JST 発行/14時 target を指定し、近い13:30発行本に置き換えなかった。Q16 は変更4件・悪化3件を保持したが、悪化2件は負 lead の事後記録なので先行予測失敗ではない。これは過去の tooling fixture であり、Candidate A や9/30モデル研究ではない。

v0.2 では文字列型 model metadata の扱いと、テスト自身の pointer 数・キー名の誤りも記録した。修正後に再検証しており、初回から全件成功したとは説明しない。公開文書は教訓と最終構造を残し、session log を重複公開しない。

## 現在コードの再検証: 2026-09-30

| 検査 | 結果 |
|---|---:|
| 公開 synthetic core/CLI/security/batch/refinement pytest | **76 passed**、skip 0、21.67秒 |
| 固定した歴史的 fixture の CLI 復元質問 | **16/16** |
| 固定した境界・損失ケース | **33/33** |
| 保存 artifact の Draft 2020-12 | **46件、エラー0** |
| Batch schema/registry、compact/expanded、単一/複数時間の同等性 | pytest 通過 |
| 同一入力の bundle/details/index/access seal 再生成 | bytes/hash 一致 |
| 歴史的入力、元の v0.2 記録、query 前後の出力 | 変更なし |
| 今回の公開作業でのモデル API 呼び出し | 0 |

Windows、Python 3.14.4、pytest 9.0.3、ローカル開発用 jsonschema 4.26.0 で実行した。公開テストは private data なしで合成入力を作る。追加テストの最初の実行では小さい fixture に chunk manifest を期待した設定誤りと必須 date selector の不足があった。実際に overflow する入力と正しい selector に修正し、既存 assertion・計算規則・bounds は緩和していない。

Schema 依存性は `requirements-dev.txt` のみ。欠落時に黙って skip しない。[公開テストコマンド](review-bundle-cli.md#テスト)で再現できる。公開整理のために検証済み CLI の計算・選択・アクセス制御や保存 schema を変更していない。

16問は completeness/finalization、published/advance 母集団、MAE/RMSE/WAPE/bias、逆方向・時間帯、同一 run stages、発行 vintage、interval/exclusion、control、issue-time weather 不在、昼の delta、followup 訂正、政策変更、候補反例・gate 不在・全変更 pair、governance を扱う。

33境界は空/fallback、0分母、NaN/Inf、重複 timestamp、timezone/date 不一致、provisional revision、TEPCO 不在、残差順序・小さい形状・gap・反対方向極値、top-N 外の悪化、policy mismatch、advance/control 不足、hash 改変、pointer/原本消失、overflow、標本下限変更、retained と pass の区別、secret exclusion、cache identity、代替 run、failed gates、unknown population、locator、schema mutant を検査する。

Null の正確な復元は不足 provenance を取得できたことを意味しない。Gate 不在も候補合格ではない。決定性は同じローカルパスで確認した。Source index に絶対 locator があるため、別マシン間の byte 一致までは保証しない。

## アクセス境界

Root/traversal、hash/size、原本消失、allowlist、query 無書き込み、build 範囲、`.env`/subprocess/socket 拒否、full-detail dump 拒否、Windows symlink/junction/hardlink を確認した。他の OS/権限で利用できない link 機能は明示的な skip 理由になる。

信頼された Python の command-body guard であり OS sandbox ではない。Import 前の実行、悪意あるコード、外部の同時変更、metadata を維持する cache 改変まで隔離を証明しない。Raw detail/followup 内部の全フィールドが完全な formal subtype schema の対象ではなく、復元・意味検査で補完する。

## 手動レビューの観測

| 計測 | 第1回手動レビュー | 第2回手動レビュー | 第2回の質問を refinement 後に再現 |
|---|---:|---:|---:|
| Evidence CLI コマンド | 83 | 13 | 11 |
| 返却 bytes | 328,849 | 255,913 | 218,477 |
| 内部 logical read bytes | 22,658,704 | 7,308,680 | 6,473,451 |
| File open events | 428 | 126 | 112 |
| 原本 read events | 2 | 3 | 3 |
| 原本 read bytes | 327,041 | 556,803 | 556,803 |
| Command-body 秒 | 44.739833 | 7.604760 | 5.921800 |

**83→13 は異なる手動試行、13→11 は同じ13質問の決定的な再現結果。** 統制された benchmark ではない。83回には pointer 失敗1回を含み、別の help 1回を含まない。

第2回の明示的な raw-source コマンドは0回だったが、hour-review が cutoff 検証で原本を3回読んだ。直接探索の減少を raw I/O 減少とは言わない。Refinement は総返却量と反復照会を減らした一方、最大単一応答は34,161→49,125 bytes に増えた。Membership 要約も選択 interval 確認で内部読み取りが増える場合がある。

別途実施した展開・同等性・決定性検査10回は追加返却658,787 bytes、内部読み取り6,325,261 bytes で、11回の通常経路に隠していない。OS cache は統制せず、command-body 計測は import/startup/ログ解析を含まない。

**Codex input/output/cached/reasoning tokens と model turns は unavailable/null。** Bytes や CLI 回数から換算しない。根拠取得 interaction と再構成作業が減った観測であり、token/cost 削減率や因果的な性能保証ではない。

## 再現と公開範囲

Code/schema と self-contained synthetic tests を公開する。保管した歴史的 corpus はローカルで再実行し、manifest hash `e944f9e9f6861d90fe575acedb0ff7c91413ae1c22ed704aff1a2496520c03bf`、bundle seal `f80d7c74b0c3e57ebd84b2b631db924b3cfde01decba2ce063859dedc8e40a27` を維持した。全 corpus は配布しないため、公開 checkout だけで歴史実行全体を再現できるとは主張しない。

日別 bundle、query dump、capture/replay intermediate、HANDOFF/AS_OF_SEAL、private notes、Jev 詳細実験、Candidate A、9/30研究結果は除外する。公開文書は構造/使用法と検証概要に統合した。独立した手動レビュー道具として利用し、欠落と反例の確認を続ける。予測や昇格の判断を代行しない。
