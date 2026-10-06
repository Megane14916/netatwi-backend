# 順11の実装・検証記録（2026-10-06）

各作業は最新のfix/step-11-bugsから分岐し、再現テスト→定期commit→修正→
全体pytest/CI成功→自己レビュー→個別PRを同branchへmerge→取り込み後テストを
順番に実施した。第三者レビューは未実施。masterは変更していない。

| Issue/範囲 | 取り込みPR | 全体pytest成功件数 | 取り込み後関連検証 | 記録 |
| --- | --- | ---: | ---: | --- |
| #22 結果保存・通知・flagのrollback/再試行 | [#74](https://github.com/Megane14916/netatwi-backend/pull/74) | 651 | 38 | [先行分](issue-22-step11-verification.md) |
| #24 OAuth機密ログ | [#75](https://github.com/Megane14916/netatwi-backend/pull/75) | 658 | 29 | [検証](issue-24-verification.md) |
| #25 投票・審査員賞の大会/存在/所有/型 | [#76](https://github.com/Megane14916/netatwi-backend/pull/76) | 676（最終CI） | 61 | [検証](issue-25-verification.md) |
| #72 退会済/不存在userのsession破棄 | [#77](https://github.com/Megane14916/netatwi-backend/pull/77) | 723 | 130 | [検証](issue-72-verification.md) |
| #27 投稿/大会削除の参照整合性 | [#78](https://github.com/Megane14916/netatwi-backend/pull/78) | 735 | 34 | [検証](issue-27-verification.md) |
| #71 保持画像の所有関係と旧混入参照 | [#79](https://github.com/Megane14916/netatwi-backend/pull/79) | 749 | 52 | [検証/監査](issue-71-verification.md) |
| #26 DB/storage失敗の補償・署名retry | [#80](https://github.com/Megane14916/netatwi-backend/pull/80) | 760 | 54 | [検証/復旧](issue-26-verification.md) |
| #21 投稿文字数/実画像/最終枚数 | [#81](https://github.com/Megane14916/netatwi-backend/pull/81) | 774 | 68 | [先行分](issue-21-step11-verification.md) |
| #23 OIDC署名・audience・呼出SA | [#82](https://github.com/Megane14916/netatwi-backend/pull/82) | 804 | 統合全体804件 | [検証/切替](issue-23-verification.md) |

統合コード基準: `914a3f3feb2dbac9241aabaf23779e094a469c25`。
Python 3.11.16、一時SQLite、socket通信拒否、外部境界fakeを使用。
URL map/起動/CLI/モデルmetadata/Alembic schema diffゼロを含む既存契約を検証する。
DB schema/migrationは変更せず、修正前に失敗する再現を追加し、バグを許容する
特性だけを意図した契約へ置換した。テスト削除/skipで通していない。

## レビュー指摘の修正（2026-10-06）

上記は初回取り込み時の記録。後続レビューで発見した3件を、
`3b69da95a18488124694e561b16b4c7a0240ebea`を基準に同じ開発ブランチで修正する。

- 不正なfalsy値の審査員賞をDELETE前に400で拒否し、既存票・賞・コメント・
  両カウンタを維持する。未指定・nullの賞は有効な票の置換・取り消しを許可する。
- 編集本文の欠損・nullを空文字にし、画像だけの編集を200で受け入れる。
  本文と画像の両方が空の場合は400で拒否し、DB/storageを変更しない。
- 投稿IDは通常票・賞で共通に`1〜2147483647`へ制限し、範囲外は対象投稿の
  DB検索前に400で拒否する。上限の有効IDは受け入れる。

再現・境界・副作用・互換性を確認する40ケースを追加した。
そのうち最初の36ケースを修正前に実行し、24失敗・12成功を確認した。
修正後の関連2ファイルは、互換性4ケースの追加前に107件成功した。
最終コードの全体pytestは844件成功（Python 3.11.16、一時SQLite、通信拒否）。
DB schema/migration、採点式、通常投票者の賞無視、master、本番環境は変更しない。

## 保留・残件

- master向け統合PR [#73](https://github.com/Megane14916/netatwi-backend/pull/73)はdraft・未マージ。
  個別Issueは計画どおりopenのまま、fix/step-11-bugs取り込み済みと記録する。
- #23の本番project/service/IAM/Ingress/queue OIDC override/retryConfig照合と実task試験は
  ユーザーの「一旦この本番照合の工程はスキップしてください」により今回除外した。
  認証コード/隔離試験の完了を本番確認の完了と混同しない。展開前に実施する。
- #21は管理/コメント等の一般入力検証、#22は他DB更新のtransaction整理が順13に残る。
- 画像manifestは旧readerと並行運用しない。旧不検証画像は監査でupload履歴を照合し、
  根拠がない画像は削除保留。cleanup失敗はログ保存/監視と署名tokenのCLI再試行を行う。
  強制終了で補償が走らない不要画像はstorage履歴とDBを照合して個別復旧する。
- 本番DB/ストレージ/GCP設定の変更、デプロイ、順12/13の作業は行っていない。

master基準は引き続き`beca003aaf881e03c8b7e4acb40ba0f410d6c2c3`。
全PRのCIリンクと各修正の影響・戻し方はPR本文と上記個別記録にある。
