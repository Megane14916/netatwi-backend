# #70 明示的なApplication Factoryと起動入口

基準: `2c57f8008f38d7e38671b5ca833f45e823f49447`（#69 / PR #86取り込み後）。
分岐元・PR base: `refactor/step-12-structure`。Refs #70。

## 再現・実装

修正前の2件で、factoryのimport自体によるapp生成と、完全なconfigを渡す前の
必須環境変数検証失敗を確認。commit `2ff5844`に再現テストを保存した。
factory.pyにトップレベルcreate_appを置き、packageは通常の再公開だけにした。
RLock、runtime exports、__getattr__/__dir__、namespace injection、nested factory、
packageへの入口注入を撤去した。factoryはDB接続・create_all・migrationを実行しない。

未初期化の単一app.extensions.dbを全モデル・service・routeが直接参照する。
app.models.dbとmodels/base.pyの再公開を撤去。全10モデルの定義自体は変更しない。
root/static/open_resource/instance/uploadsの基準はリポジトリルートを保持した。
プロセス共通SQL hookはextensionsの通常module importで一度だけ登録する。
HTTPと業務の契約は保持し、factoryごとにroute/CLI/hook/extensionsを登録する。

## 入口の切替一覧

| 利用者 | 旧 | 新 |
| --- | --- | --- |
| Dockerfile/Gunicorn | app:app | wsgi:app |
| Flask CLI | app:app または旧package探索 | flask --app app:create_app ... |
| python app.py | namespace生成・packageへ公開 | main内でcreate_app、直接起動だけcreate_all |
| sync_comment_counts.py | from app import app, db | create_appとextensions.db、関数内でapp context |
| generate_dummy_data.py / generate_dummy_gp_result.py | appと旧models/root公開 | create_appとcanonical models/db |
| scripts/sync_comment_count.py / recalculate_contest_stats.py | app/root公開 | create_appとcanonical models/db |
| calc_result.py | app/root公開結果helper | create_appとservices.results |
| scripts/audit_image_ownership.py | create_app | 継続（既に明示factory対応済み） |

管理外5本はローカルで適用し、[適用パッチ](issue-70-local-scripts.patch)に記録した。
他checkoutでは#67・#69のパッチを先に適用し、本パッチを
`git apply --unidiff-zero --check`で照合してから同じオプションで適用する。
AST/構文を確認し、データ更新本体は実行していない。
リポジトリ外のWSGI設定・ジョブが残る場合は、本番リリース時に上表で照合する。
現在の本番設定を未確認のまま「切替済み」とは扱わない。

## テストと戻し方

互換export/既定app生成を要求するテストをcold factory/明示的WSGI/直接起動へ置換。
factoryの同じroute・CLI・hookの件数/identity、異なるconfig、config不足後の再試行、
並行するexport取得がappを生成しないことを検証する。component cold importに
package自体を追加し、全体fixtureもdefault appを生成せずfactoryを使う。
HTTP/業務のテストと期待値は保持。テストのdb参照とhandler参照だけを移す。

[比較script](verify_issue_70_structure.py)はfactory/公開/入口を除くアプリ全体の
import以外のASTが一致することを確認する。全体pytest/CI結果は最終確認後追記する。
#69取り込み後40件と開発ブランチCIは成功した。

やってないこと: 業務処理/HTTP URL/method/応答/DB schema/migration、devへの反映、
本番デプロイ・設定変更・データ更新、masterへのマージ。
戻す場合は本PRとDocker/WSGI/CLI/scriptの入口を同時に戻す。旧root helperの復元は
#69/#67の差分も含めて判断する。Issueのcloseはmaster統合まで保留する。
