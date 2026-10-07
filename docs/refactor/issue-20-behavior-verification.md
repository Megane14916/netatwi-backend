# #20 例外境界と障害ログ

分岐元/base: refactor/step-13-behavior、基準9ac39b2。順11のOAuth機密ログと
Tasks OIDC検証、順13の入力/transaction改善を維持する。

修正前は7経路の不存在応答とコメント未処理例外の計8件が失敗した。
HTTPExceptionを一般障害として捕捉しない。404/405/429等はJSONのerrorにHTTP名を
返し、元のstatus/Allow/Retry-Afterを保持する。413とInputError400は個別契約を保持。
大会詳細のDB/整形障害は404から500へ直す。その他の既存500のerror文字列は維持。
未処理例外は共通handlerでrollbackし、Internal server errorのJSON500を返す。
TESTINGでもHTTPで確認し、CLI/service単体は失敗を伝播する。

print/traceback.print_excによる障害出力を、処理名・例外型・ファイル名/行/関数名の
診断に変更。例外本文・source行・locals・request/session・OAuth code/tokenは出さない。
画像保存/削除・Tasks予定作成の外部障害にも同じ診断を適用する。
既存の画像補償URL属性とIMAGE_CLEANUP_PENDINGの署名付き再試行記録は保持する。
OAuth開始/コールバックの既存redirect/機密ログ対策は変更しない。
プロフィール計時、審査員認証、予定作成はloggerへ移し、審査員sessionの一覧出力を廃止。
CLIの開始/進行/完了メッセージは操作の結果として保持し、失敗は安全な診断を記録して
元の例外を伝播する。古い通知のcleanup失敗は従来どおりrollback後に後続処理を続ける。

異常経路の特性テストは今回の意図した応答/rollback/logだけを更新し、正常payload、
query順、画像補償、transaction失敗時の行/カウンタと再試行を保持する。
追加15件はHTTP headers、commit失敗再試行、外部サービスエラーの機密文字列非出力も検証。
関連572件の初回再検証で570件成功、旧print期待値1件とtest import不足1件を修正した。
最終関連結果と全体CIはPRへ記録する。Python3.11.16、隔離SQLite/外部fake。

やってないこと: JSON正常契約の変更、採点式/期間/権限/DB schema変更、整形共通化(#19)。
migration/本番設定変更・デプロイなし。必要なフロント更新なし（HTTPエラーのstatusとJSON化）。
DB確定後のレスポンス/通信障害はcommitを取り消す保証の対象外。
PR単位のrevertで戻せる。masterへのマージは行わない。

## 最終結果

PR #102の0c7a93cで全1024件・専用9件skip、PostgreSQL9件成功。取り込み後の追加15件も成功し、開発ブランチへmerge済み。
ユーザー指定に従い開発ブランチでの完了としてIssueをcloseし、masterへのマージは行っていない。
現在の全体結果は[順13検証記録](step-13-verification.md)を参照する。
