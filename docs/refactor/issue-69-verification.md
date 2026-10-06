# #69 runtime bridge撤去とアプリ単位の依存・状態

基準: `975e63791f6bbc3b772b366afe4b560392721a9d`（#68 / PR #85取り込み後）。
分岐元・PR base: `refactor/step-12-structure`。Refs #69。

## 再現・変更

修正前の再現2件が失敗した。異なるDBの2番目のappに1番目の大会が出る問題と、
設定前にimportしたOAuthのclient IDがNoneへ固定される問題である。
再現テストを最初のcommit `4910fcb`へ保存した。

- 大会一覧cacheはactive app.extensionsのcontests_cacheへ移した。5秒TTL、時計の
  呼出回数、payload保存後の時計失敗、一覧分類・順序・SQLは保持する。
- 画像設定はapp.config、R2 clientはapp.extensionsへ移した。clientは最初の利用時だけ
  生成する。保存/削除の本体は_save_file/_delete_fileに保持し、例外補償も維持した。
- Cloud Tasks設定はapp.config、lazy clientはapp.extensionsへ移した。OIDC検証と
  署名task、予定時刻、再試行・例外境界は維持する。TESTINGによる認証迂回はない。
- OAuthはfactoryで読み込んだconfigから資格情報を解決する。frontend URLも各appから
  読み、OAuthプロトコルやsession/機密ログの契約は保持する。
- 文字数・結果は担当serviceへ直接依存する。request/CLIのloggerはcurrent_app.logger。
  SQL計測のmodule loggerは保持する。
- app/runtime_dependencies.py、app/routes/dependencies.py、legacy_route_helpersと
  namespaceを参照するhelper callback、不要になった14のroot再公開名を撤去した。
  管理外calc_result.pyの結果helperもcanonical serviceへ移行し、
  [適用パッチ](issue-69-local-scripts.patch)を記録した（集計処理は実行していない）。
  他checkoutではgit apply --unidiff-zero --checkで確認して適用する。
  root app/factoryの最終的なnamespace・遅延初期化・起動入口の撤去は#70で行う。

## fake・テスト移行

画像保存/削除はapp.integrations.imagesの実際の呼出先へfakeを接続し、clientだけを
差し替える場合はactive app.extensionsのr2_client/cloud_tasks_clientを使う。
設定はapp.configへ変更し、結果・文字数は担当serviceを使う。通信拒否fixtureは保持。
旧aliasだけを要求するshared-helper 15ケースをcanonicalな6ケースへ置換した。
業務・補償・所有権・認証ケースの期待値は保持した。cache共有を要求するケースは
DBを各appで初期化してcache分離を検証する契約へ置換した。
新規4件でDB分離、OAuth cold import、R2 lazy client、Cloud Tasks lazy clientの分離を確認。
画像設定・frontend・fakeは生成順と呼出順を変えて確認する。

## 検証・運用

[比較script](verify_issue_69_structure.py)で、依存名・cache状態参照の許可した置換後に
業務関数のASTを照合する。HTTP/DB/計算式/副作用/commit/rollbackの順序は変更しない。
Python 3.11.16で全体pytest 844件成功（123.38秒）。URL/method、起動/CLI、
全10モデルとAlembic差分ゼロを含む。#68の849件から互換15件を6件へ置換し、
回帰4件を追加した結果844件となった。skipはない。CIはPR #86で確認する。
#68取り込み後11件・開発ブランチCIは成功した。

やってないこと: DB schema、業務仕様、factoryの通常公開とWSGIの最終切替(#70)、
本番設定・本番データ・外部サービスの操作、master/devへのマージ。
呼出元のmonkeypatch先と設定の切替を一緒に戻す場合は本PRをrevertする。
Issueのcloseは計画どおりmaster統合まで保留する。
