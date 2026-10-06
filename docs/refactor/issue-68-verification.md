# #68 標準Blueprintへの置換

基準: `aa9ea148bfa15f105588610dd07690d806e19277`（#67 / PR #84取り込み後）。
分岐元・PR base: `refactor/step-12-structure`。Refs #68。

15 route moduleのBlueprintをflask.Blueprintに変更し、legacy.pyを削除した。
旧endpoint aliasを二重登録せず、35 routeに各Blueprint名の接頭辞を付けた。
全URL・methodと新旧endpointの対応は[対応表](issue-68-endpoints.json)に記録。
明示的なroute契約テスト・snapshot・url_for・view_functions利用者を更新した。
アプリ本体のurl_for/動的endpoint利用に変更は不要だった。ログのendpointは接頭辞付きになる。

[比較script](verify_issue_68_structure.py)で、全アプリソースについて
Blueprint import/生成の2箇所とlegacy.py撤去以外の一致を確認する。
HTTP/DB/認証/期間/副作用と業務関数本体に変更はない。

Python 3.11.16で関連61件と追加4件成功。新ケースはURL/methodの同等性、
request.blueprint、旧endpointの不在、CORS/preflight/hook、審査員認証5/min、
既定5000/hourの実際の連続リクエストを検証する。既存ケースをskipしていない。
全体pytestは849件成功（136.59秒）。URL map、起動/CLI、モデル契約、
Alembic差分ゼロを含む。CIはPR #85で確認する。

やってないこと: route再分類、URL prefix、HTTP応答、業務処理、DB schema、
runtime bridge/状態分離(#69)、factory/WSGI切替(#70)。
外部公開URLやフロントエンドの切替は不要。本PRをrevertすれば旧登録とsnapshotへ戻る。
masterやdev、本番DB・外部サービスは変更しない。Issueのcloseはmaster統合まで保留。

#67の取り込み後検証は15件成功、開発ブランチCIも成功。
順12開始時の独立checkout（git archive）でも全844件成功（136.13秒）を確認した。
