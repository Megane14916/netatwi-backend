# #22 順11: 結果保存失敗と再試行

基準: `126d20304e2b3d124a0311e549955df610852324` (`fix/step-11-bugs`)。

結果生成の単独呼出しは従来どおりcommitする。task/CLIでは`commit=False`で
結果を保存・flushし、通知・処理済みフラグと同じcommitで確定する。
保存例外を握りつぶさず、ライフサイクルの例外境界でもrollbackして呼出元へ返す。
CLIで同一大会の投稿開始・投票開始通知が未確定なら、それらも同時にrollbackする。
他大会で既にcommitした処理は維持する。

## 再現と検証

- Python 3.11.16、`.venv/issue53-env/Scripts/python.exe`、一時SQLite、外部通信拒否。
- 修正前の全体: 645 passed / 369 warnings。
- 追加6ケース: task/CLI × bulk保存・commit・通知保存失敗。
  修正前は4 failed / 2 passed。通知の残存、結果だけの確定を確認した。
- 失敗後の結果0件・通知0件・フラグfalse、再試行2回後の結果1件・通知1件を確認。
- 既存の不具合を記録した4ケースを失敗伝播・rollbackの契約に変更。
  task/CLIの結果処理commit回数は2回から1回へ変更した。
- 全体テストとGitHub Actionsの結果は個別PRに記録する。

## 影響と残件

URL・成功JSON・採点式・順位・進出条件・DBスキーマは維持する。
結果保存失敗はtaskで500、CLIで非ゼロ終了し、task再試行が可能になる。
schema migration・フロントエンド変更・本番設定変更は不要。
既に結果なしで処理済みになった大会は、運用で結果行と通知を確認し、
対象の`notified_result_announce`を戻して再実行する。自動データ修復は実施しない。
戻す場合は本PRをrevertする。既存データの変更は行っていない。

やってないこと: #22の他APIのトランザクション改善、画像整合性、
Cloud Tasks認証、構成整理。#22は順13の残件があるためcloseしない。
取り込み先は`fix/step-11-bugs`。`master`にはマージしない。
