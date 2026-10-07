# 順13 behavior系改善の完了記録（2026-10-07）

`050037e368b07959b9a8f67e43ddd0ba0fa3d628`のmasterから作られた
`refactor/step-13-behavior`を起点・baseとし、各Issueの個別PRを順に取り込んだ。
実装完了時点の開発ブランチは`1d3923200e35d4d14fb34e33a336d0ab2809c58f`。
ユーザー指定に従い、5件を開発ブランチで完了としてcloseした。
**masterにはマージせず、本番へデプロイしていない。** 既存のmaster向けdraft
[PR #91](https://github.com/Megane14916/netatwi-backend/pull/91)は未マージで保持する。

## Issueと取り込み結果

| Issue | 完了範囲 | 個別PR | 検証記録 |
| --- | --- | --- | --- |
| #18 | ログイン・管理者・審査員・所有者と期間/到達判定の共通化 | [#92](https://github.com/Megane14916/netatwi-backend/pull/92) | [#18](issue-18-behavior-verification.md) |
| #21 | コメント・大会・投票/審査員賞・投稿編集JSON・ニュース・審査員ログイン・予選名の入力検証 | [#93](https://github.com/Megane14916/netatwi-backend/pull/93)、[#94](https://github.com/Megane14916/netatwi-backend/pull/94)、[#95](https://github.com/Megane14916/netatwi-backend/pull/95)、[#96](https://github.com/Megane14916/netatwi-backend/pull/96)、[#97](https://github.com/Megane14916/netatwi-backend/pull/97)、[#98](https://github.com/Megane14916/netatwi-backend/pull/98)、[#99](https://github.com/Megane14916/netatwi-backend/pull/99) | [#21](issue-21-behavior-verification.md) |
| #22 | 一般mutationのrollback/再試行、行と件数の同時確定、結果・通知・フラグの並行生成防止 | [#100](https://github.com/Megane14916/netatwi-backend/pull/100)、[#101](https://github.com/Megane14916/netatwi-backend/pull/101) | [#22](issue-22-behavior-verification.md) |
| #20 | HTTP例外のstatus/headers保持とJSON化、未処理障害のrollback、機密情報を含めない障害診断 | [#102](https://github.com/Megane14916/netatwi-backend/pull/102) | [#20](issue-20-behavior-verification.md) |
| #19 | 大会・投稿・公開ユーザーとJST日時の整形共通化、正常JSON/公開条件の保持 | [#103](https://github.com/Megane14916/netatwi-backend/pull/103) | [#19](issue-19-behavior-verification.md) |

入力不正はDB/外部処理の前に400へ変更。HTTPExceptionの404等を500として
握りつぶさず、大会詳細のDB障害は404から500へ変更した。大会入力のenum表記揺れ
（general→both、forbidden→none）と時差付き日時のUTC正規化も#21の意図した変更である。
レスポンスのキー/型・採点式・順位・
進出条件・権限・期間・DB schema・外部サービス契約は保持した。
順11の画像所有/補償・退会session・OAuth機密ログ・Tasks OIDCも回帰テストで確認した。
ファイル移動、互換alias復活、lint/型の導入、無関係なquery最適化を混ぜていない。

## 検証

- 各入力/更新/例外修正は、修正前に失敗する再現テストをコミットしてから修正した。
  #18/#19の共通化は既存契約と境界/完全payloadテストを根拠にした。
- 各PRで差分・`git diff --check`と関連テストを確認し、全体Actions成功後に
  head SHAを指定して開発ブランチへmergeした。取り込み後も関連テストを実行した。
- 最終コード`dd7b34c`の[Actions run 37612481397](https://github.com/Megane14916/netatwi-backend/actions/runs/37612481397)
  は通常ジョブ**1024 passed / PostgreSQL専用9 skipped**、PostgreSQLジョブ**9 passed**。
  合計1033ケースを2つのジョブで検証する。#19取り込み後の関連92件も成功。
- ローカルはPython 3.11.16、隔離SQLite、X/R2/Tasks fakeと外部通信拒否で検証する。
  最終コードの全体も**1024 passed / PostgreSQL専用9 skipped**で成功（200.96秒）。
  実行手順は[tests/README.md](../../tests/README.md)。
- PostgreSQLの並行実行はCIの使い捨てPostgreSQL 16で検証。修正前の
  `16f3a5b`では5件すべて重複生成で失敗し、修正後はTasks/CLI混在・空大会を含む
  9件成功。`pg_stat_activity`で実際のlock待ちを確認する。
- URL map・metadata/Alembic差分・起動/factory/WSGI/CLIと状態分離の既存テストも
  全体に含む。スキーマmigrationは不要。

## 運用と戻し方

本番DB、R2、X、Cloud Tasks、設定やデプロイ元`dev`には操作していない。
masterのremote SHAは上記の開始時SHAと同じであることを確認した。
frontendは変更していない。正常API契約のための同時リリースやmigrationは不要。

PostgreSQLの標準READ COMMITTEDで大会行ロックを使う。SQLiteは同時実行の行ロック
保証の対象外。ロック待ち/DB障害はrollbackしてretryし、採点結果と通知を同時確定する。
DB確定後のCloud Tasks予定作成は従来のbest effortであり、DBと外部API/レスポンスを
原子的に確定する保証は含まない。画像の署名付きcleanup再試行記録とCLI fallbackを保持する。

本番反映前のTasks OIDC設定・既存task切替、画像manifest reader切替とcleanup監視等は
[順11](step-11-verification.md)・[順12](step-12-verification.md)の運用記録を引き継ぐ。
今回、本番設定の照合や切替は実施していない。
戻す場合は依存する後続PRから順にrevertし、関連/全体テストと運用条件を再確認する。

## レビュー後の修正（2026-10-08）

### ① ブックマークの並行更新

対象Postを変更前にFOR UPDATEでロックし、先行読込の状態も再取得する。
ブックマーク行の変更・再集計・保存は従来の1 transactionのまま確定する。
PUT/PUT、PUT/DELETE、DELETE/PUTの並行実行で保存件数と実件数の一致を検証する
PostgreSQLテストを3件追加し、既存の結果生成9件と同じCIジョブで実行する。
専用DB fixtureはintegration/conftest.pyに集約した。
ローカルの交流・rollback関連61件成功、PostgreSQL専用12件skip。
ローカルDocker engineは停止中のため、実DBの行ロック検証はCIで行う。

### ③ generalの採点方式

ユーザー指定によりgeneralはbothへ正規化し、元の審査員点＋一般票を保持する。
通常大会・予選作成と既存general大会更新の再現3件は修正前失敗、修正後成功。
審査員2点・一般票1票・重み50の結果52点を実際の結果保存まで検証した。
既存DBのgeneralも集計時は従来どおり両方の点を使う（migration不要）。
管理入力・大会更新・採点・結果関連116件成功。

### ⑨ 未使用の予選設定

予選なしの作成（hasQualifier省略/false）と単一大会更新では、使わない
qualifier項目と期間を検証しない。予選ペア作成では検証を維持し、更新で使用する
qualifierJudgeAwardAdvancementの互換入力もbooleanとして検証する。
追加50件は修正前34失敗/16成功、修正後の管理入力・大会関連140件成功。

### ⑥ 期間0の許容

ユーザー指定により通常大会・予選とも投稿開始≦投稿終了≦投票終了へ変更した。
作成・全体更新・部分更新で投稿期間0、投票期間0、両方0を許容し、逆順は拒否する。
投稿/投票の半開区間は維持するため、0期間には操作できる瞬間がなく、投票終了の
境界から結果を取得できる。追加16件は修正前14失敗/2成功、修正後関連183件成功。

②（分子0の保存値）はユーザー指定どおり変更していない。
①の[CI run 37642783197](https://github.com/Megane14916/netatwi-backend/actions/runs/37642783197)
では通常1024件成功・専用12件skip、PostgreSQL専用12件成功（新規3件を含む）。

4件の修正を反映したローカル全体は1088件成功・PostgreSQL専用12件skip
（Python 3.11.16、隔離SQLite、外部通信拒否/fake）。各修正は個別コミットとし、
開発ブランチrefactor/step-13-behaviorへ反映する。masterへのマージは行わない。
