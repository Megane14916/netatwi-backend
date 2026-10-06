# #27 投稿・大会削除の参照整合性

基準: `e967f6d93b7c27b22b0c961affbf5927578734fe`。base: `fix/step-11-bugs`。

大会削除はVote・Comment・Notification・Bookmark・ContestResultを先に削除し、
Post、親子大会参照、Contestを同じcommitで確定する。
対象大会の参照だけでなく、対象投稿を参照する過去の大会不一致行も削除する。
親大会を消しても子大会は残し、parent_contest_idをnullにする既存契約を維持。
ORM cascadeに頼らず、bulk deleteで全外部キー参照を処理する。
投稿削除の既存関連行処理も同じ検証で確認した。

## 検証

Python 3.11.16、一時SQLiteでPRAGMA foreign_keys=ONを確認してから実行。
投稿/大会 × relationship未読込/読込済み × 成功/commit失敗/途中DELETE失敗。
最初の8ケースは修正前に大会正常削除2件がFK違反で失敗し、他6件成功。
修正後は孤児なし、無関係な大会・投稿・関連行を保持する。
失敗注入が実際に到達したこと、件数と親子参照が全復元することを確認する。
最後にPRAGMA foreign_key_checkの差分ゼロを確認。
旧特性テストの孤児Bookmark/Commentの期待値とDELETE順序を新契約へ変更。
全体pytest/Actions/レビューの結果は個別PRに記録する。

## 影響・戻し方

大会削除で以前残った関連行も削除する。成功API、子大会の保持、schemaは維持。
migration/設定/frontend変更不要。DB操作は1つのcommitで、routeのrollbackを維持。
本番の既存孤児行は自動掃除しない。各post_id/contest_idをLEFT JOINして
不存在参照を読み取り監査し、対象を確認して別の修復手順で処理する。
コードはrevert可能だが、実際の大会削除は元データのバックアップからの復元が必要。

やってないこと: schema変更、既存孤児修復、画像の削除/補償（#26・#71）、
統計全体の再計算、構成整理。masterにはマージしない。
