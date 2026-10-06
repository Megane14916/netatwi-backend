# 順12 構成整理の検証

順12の実装は`refactor/step-12-structure`へIssueごとに取り込む。
ユーザー指示により、このブランチはmasterへマージしない。
統合PRはレビュー用draftとして残す。devへの反映・本番デプロイも行わない。

## 個別実装と基準

| Issue | 個別PR・記録 | 検証 |
| --- | --- | --- |
| #67 旧import alias | [PR #84](https://github.com/Megane14916/netatwi-backend/pull/84)・[記録](issue-67-verification.md) | 全844件＋追加を含む関連23件、CI成功、取り込み後15件 |
| #68 標準Blueprint | [PR #85](https://github.com/Megane14916/netatwi-backend/pull/85)・[記録](issue-68-verification.md) | 全849件、CI成功、取り込み後11件、35 endpoint接頭辞の照合 |
| #69 runtime bridge/状態 | [PR #86](https://github.com/Megane14916/netatwi-backend/pull/86)・[記録](issue-69-verification.md) | 修正前の失敗2件、全844件、CI成功、取り込み後40件、業務52関数の照合 |
| #70 explicit factory | [PR #87](https://github.com/Megane14916/netatwi-backend/pull/87)・[記録](issue-70-verification.md) | 修正前の失敗2件、全847件、関連44件、CI成功、53 moduleの非import AST保持 |

開始基準は`1de7adf25ec5123bd10cd6327004d250ff96676b`。
別のgit archive checkoutでも開始時の全844件成功（136.13秒）を確認した。
各Issueの実装前に最新開発ブランチから分岐し、実装・検証記録を定期的にcommitした。
各段階でskipを追加せず、特性テストの業務の期待値を保持した。

4件の最終取り込みコードは`d87c29f64bcace40142b21ace8301326d0e0d4c0`。
取り込み後の全体pytestは847件成功（125.94秒）。開発ブランチの
[CI](https://github.com/Megane14916/netatwi-backend/actions/runs/37450877167)も成功した。
リモートmasterは開始時の`5fee097d39888387afaa4d0ae53f6637c30b6375`のまま。
frontendには変更を行っていない。backendの追跡対象の作業ツリーに未commit差分は残さない。
4件のIssue本文も実装結果・検証・master保留へ更新済み。

最終847件は開始時844件の固定維持ではない。#67で1件追加、#68で4件追加、
#69で旧helper互換15件をcanonical6件へ置換して回帰4件追加、#70で3件追加。
既定app生成・旧endpoint・module global cache共有などの旧内部契約は新契約へ置換した。
順11の不正票・画像編集/ID・退会session・所有記録/補償/cleanup CLI・結果保存失敗と
再試行・Tasks OIDCを含む全体テストが成功した。477件の既存SQLAlchemy警告は開始時と同数。

## 起動と依存

- `app/__init__.py`はcreate_appを通常の再公開だけで公開する。
- dbはapp.extensionsで1個、モデルは10個。DDL/制約/relationshipとAlembic差分ゼロを維持。
- HTTP URL/method/応答は維持。内部endpointはBlueprint名付きにした。
- cache/画像/Tasks/OAuth設定とclient/fakeをappごとに分離した。文字数はcontextなしで動く。
- Gunicorn/Dockerはwsgi:app、Flask CLIはapp:create_app、直接起動はapp.pyのmain。
- root/static/open_resource/instance/uploadsの基準はリポジトリルートを維持。

## 本番反映前の残る確認と戻し方

Git管理外scriptは#67/#69/#70の適用パッチを同順で他checkoutへ反映する。
本checkoutの7本は構文と入口を確認済みで、データ更新処理は実行していない。
リポジトリ外の実WSGI・ジョブ設定を参照できていないため、本番切替済みとは扱わない。
実運用入口を[切替一覧](issue-70-verification.md)へ照合し、Docker・script・CLIと同時に切り替える。
順11で残したTasks本番設定照合、画像manifest reader/cleanup運用の確認も保持する。

本番DB/migration/外部サービスの操作は行っていない。構成変更を戻す際は個別PRを
依存の逆順でrevertし、entry/script/fakeの切替も一緒に戻す。結果処理の並行実行問題や
順13の一般改善はこの実装へ混ぜない。Issueは計画書の運用に従いmaster統合までopenを保持する。
