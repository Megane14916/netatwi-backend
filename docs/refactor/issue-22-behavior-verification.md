# #22 DB更新のtransaction境界

分岐元・PR base: 最新の`refactor/step-13-behavior`。基準`099bc66`。

## 一般mutation

追加7件は修正前すべて失敗。serviceのcommit失敗後、テストからrollbackせずに
元の行・本文・カウンタ・既読・退会状態を読み取り、そのまま成功再試行できることを検証。
ブックマークの再集計失敗で行だけが保存される問題もPUT/DELETEで再現した。

ブックマークはflush→再集計→カウンタ更新→1回commitへ変更。いいね件数もcommit前に
取得し、再集計障害で更新/通知だけが残らないようにする。コメント・通知既読・退会・
統計はserviceがrollbackして失敗を呼出元へ伝播する。HTTP専用の他mutationはrouteが
rollbackを担い、画像補償とTasks/CLIの既存rollback責務は維持する。
ニュース/コメントの生成IDはflush後に確保し、commit後の不要な再取得を避ける。

正常API契約・DB schema・採点式/順位/進出条件・画像補償に変更なし。
やってないこと: 一般的なHTTP例外/ログ改善（#20）、整形共通化（#19）。
結果集計の並行実行は別PRで範囲・PostgreSQL再現を記録する。
Cloud Tasksのスケジュールは従来どおりDB確定後で、外部APIとDBの原子的な確定を
保証しない。レスポンス/通信失敗もDB確定後を巻き戻す保証の対象外。既存CLI経路を
保持し、本番設定や外部タスクを変更せず、各mutationのDB単位を確認する。

Python 3.11.16、隔離SQLite、外部通信拒否/fakeで検証。結果はPRへ追記。
migration/本番設定変更なし。本番反映なし。PR単位のrevertで戻せる。

一般mutation関連246件成功。全体CIの結果はPRに記録する。

## 結果処理の同時実行

一般mutationのPR #100は全体1009件（ローカル/CI）、マージ後7件成功。
並行処理の基準はそのmerge `f4e1ce2`。再現テストだけの`16f3a5b`を
[CI run 37609955001](https://github.com/Megane14916/netatwi-backend/actions/runs/37609955001)
で実行し、PostgreSQLの5件すべてで結果行または通知が2件になる失敗を確認した。

大会行をSELECT FOR UPDATEで取得し、待機後にORMの既存オブジェクトを再読込する。
結果存在判定とTasks/CLIの通知フラグ判定の前に同じロックを取り、結果・通知・フラグは
従来の1 transactionで確定する。CLIはID順に処理してロック順を揃える。
結果serviceの取得/集計失敗もrollbackする。採点式・順位・空大会の正常契約は保持。

PostgreSQL専用テストは本番URIを受け付けず、CI service containerの固定URIだけを許可。
実際のlock待ちをpg_stat_activityで確認し、TasksとCLIの混在も追加した計9件を検証する。
通常のSQLiteジョブでは9件をskipし、PostgreSQLジョブで実行する。ローカルはDocker
engineが起動していないため、SQLite関連60件成功とCIの実DB検証を組み合わせる。

schema/migrationの変更なし。SQLiteはFOR UPDATEを提供しないため同時実行保証の対象外。
PostgreSQLの標準READ COMMITTEDを前提とし、待機/lock timeoutは例外をrollbackして再試行する。
スキップ時のロックは呼出元のtransaction終了/context teardownで解放される。
本番設定変更・外部task操作・デプロイなし。PR単位でrevert可能。

## 最終結果

PR #100は全1009件（ローカル/CI）、取り込み後7件成功。PR #101は全1009件・専用9件skip、PostgreSQL9件成功、取り込み後の結果/Tasks/CLI38件成功。両PRを開発ブランチへmerge済み。
ユーザー指定に従い開発ブランチでの完了としてIssueをcloseし、masterへのマージは行っていない。
現在の全体結果は[順13検証記録](step-13-verification.md)を参照する。
