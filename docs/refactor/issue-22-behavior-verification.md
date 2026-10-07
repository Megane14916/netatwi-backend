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
