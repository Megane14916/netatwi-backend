# #67 旧import aliasの撤去

基準: `1de7adf25ec5123bd10cd6327004d250ff96676b`。分岐元・PR baseは
`refactor/step-12-structure`。Refs #67。

## 変更と利用者

旧rootのmodels/blueprints/services/integrations/cliとflat alias 5本、計28ファイルを削除。
対応先は順にapp.models/app.routes/app.services/app.integrations/app.cli、
app.config/app.extensions/app.factory/app.hooks/app.runtime_dependencies。
アプリ・追跡中scriptは既にcanonical importへ移行済みだった。
alias同一性のテスト2件をcanonical module・実際のclient差替えテストへ置換し、
12個のcold importケースをcanonical importへ移した。旧importを禁止した
隔離プロセスでfactory・HTTP・CLI・単一dbの動作を追加検証する。

Git管理外の利用者4本もローカルで移行済み:

- generate_dummy_data.py
- generate_dummy_gp_result.py
- scripts/sync_comment_count.py
- scripts/recalculate_contest_stats.py

差分は [適用パッチ](issue-67-local-scripts.patch)。他checkoutの同じscriptへは
`git apply --unidiff-zero --check docs/refactor/issue-67-local-scripts.patch`で照合してから
`git apply --unidiff-zero docs/refactor/issue-67-local-scripts.patch`を実行する。データ更新処理は
実行していない。root appの再公開を使うscriptは#70でfactoryへ移す。

Dockerfile、CI、migrations/env.py、workspace内の現在のbackend入口も調査した。
Dockerfileのapp:appは#70で変更する。workspaceのNetatwi/backendとdocsの比較資料は
別の過去実装であり、本backendの実行入口ではない。patch.pyとdocs/refactorの
歴史的な抽出scriptは過去ソース専用のため保持し、実行しない。
リポジトリ外の本番ジョブ設定にはアクセスしておらず、その切替は本番反映時の確認事項。

## 維持する契約・戻し方

app/__init__.pyのruntime再公開・遅延初期化、LegacyEndpointBlueprint、helper bridgeは保持。
HTTP URL/method/endpoint/応答、DB schema、認証、画像補償、Tasks OIDC、業務処理は変更なし。
本PRをrevertし、管理外scriptへ適用パッチを逆適用する。本番DB・外部サービスの操作なし。

## 検証

Python 3.11.16、既存`.venv/issue53-env`、一時SQLite、外部通信拒否を使用。
全体pytest 844件成功（145.37秒）。追加の旧import禁止ケースを含む関連23件成功。
最終収集数は845件。URL map、起動/CLI、全10モデル、Alembic差分ゼロも成功。
CIはPR #84で確認する。Issueは計画書の運用に従いmaster統合までopenを保持する。
