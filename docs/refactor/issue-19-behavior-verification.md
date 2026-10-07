# #19 APIレスポンス整形の共通化

分岐元/base: refactor/step-13-behavior、基準503ffbd。

大会ルール/3日時、投稿の本文・画像・作成日時/投稿応答のIDとuser_id、公開ユーザーの
3項目（必要な経路だけid追加）をapp/services/serialization.pyへ集約した。
明示したフィールドだけを返し、model全体や__dict__をserializeしない。

利用経路: 大会一覧/詳細/管理、投稿一覧/作成/編集、結果/審査員賞、プロフィール、
ユーザー一覧、単件/複数投稿コメント、通知sender。
期間・権限・並び順・閲覧者投票/コメント/ブックマーク判定は各serviceに保持。
judgePasswordは管理callerだけに残し、ユーザー一覧の既存twitter_idは明示して保持。
結果/プロフィールのpost_idと投稿応答のid/user_idを区別し、余分なキーを足さない。
投票者の最小表示情報や各API固有の集計・コメント・テーマ公開条件は共通化しない。

UTCをreplaceしてJST ISO8601へ変換する既存の日時表現を維持。
大会一覧の欠損日時Noneと、詳細/管理の必須日時の違いも維持する。
通知・コメントの日時/関連者None、空結果、非公開期間、匿名/一般/審査員/自己/管理、
画像配列・数値・None・query/transaction順を既存の完全payload特性テストで確認する。

変更前/共通化後に同じ関連275件が成功。機能のバグ修正ではなく重複除去なので、
既存正常/異常契約の期待値を変更せず、追加の仕様変更・テスト置換は行わない。
全体pytestとPostgreSQL9件はPRの最終CIで確認する。

やってないこと: JSONキー/型/公開条件、権限/期間/入力/例外/transactionの変更、
DB schema・採点式/順位/進出条件、無関係なquery最適化、ファイル移動や互換alias復活。
外部API・フロント変更・migration・本番設定変更・デプロイなし。
PR単位のrevertで戻せる。masterへマージしない。

## 最終結果

PR #103のdd7b34cで全1024件・専用9件skip、PostgreSQL9件成功。取り込み後の関連92件も成功し、開発ブランチへmerge済み。
ユーザー指定に従い開発ブランチでの完了としてIssueをcloseし、masterへのマージは行っていない。
現在の全体結果は[順13検証記録](step-13-verification.md)を参照する。
