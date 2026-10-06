# #26 画像保存・DB更新の補償

基準: `e8887c31833db991e0742c0524dcad097f3268d0`。baseは`fix/step-11-bugs`。
初回の再現5件は修正前すべて失敗した。

作成/編集では成功した新規uploadと途中失敗した生成URLを追跡し、DBをrollbackして
不要画像を補償削除する。編集/削除の既存画像はDB commit後だけ削除する。
削除前に全Postの参照を再確認し、commit結果が不明な場合も使用中画像を消さない。
参照確認不能・storage削除失敗の場合は削除を保留し、署名付きtokenを
`IMAGE_CLEANUP_PENDING`ログに記録する。低レベルstorage例外は握り潰さない。
編集/削除の対象Postに行lockを要求する（SQLiteのテストはPostgreSQLのlockを証明しない）。

## 運用・再試行

ログを永続保存し、`IMAGE_CLEANUP_PENDING`を監視対象とする。
同じSECRET_KEYを使う対象環境で、ログのtokenを指定して
`flask --app app retry-image-cleanup --token '<token>'`を実行する。
tokenの署名が不正なら拒否し、DBが参照している画像は保留する。
storage障害が続く場合も非ゼロ終了する。既に消えている画像の再削除は成功扱い。
tokenは運用者に限定して扱い、SECRET_KEY更新前に保留分を処理する。

これはDBとstorageの分散transactionではない。補償失敗時は一時的な不要画像が
残り、上記の再試行が必要。upload直後のプロセス強制終了等、例外処理を実行できない
障害はログtokenだけでは回収できない。既存不整合と同様、upload履歴/オブジェクト一覧を
DBの参照と照合し、#71の監査scriptで混入/未検証参照を洗い出す。
欠損参照はbackupから復元するか投稿者と確認して参照を修復し、未参照objectは
upload記録で所有根拠を確認してから個別に削除する。prefixだけで一括削除しない。
本番データ/ストレージ操作や自動retry schedulerの導入はしていない。

## 検証・影響

APIでDB commit失敗、複数uploadの途中失敗、部分書込URL、rollback後の行/カウンタを検証。
R2とローカルfakeで部分失敗と再削除を検証。cleanup失敗の署名ログ、CLI再試行、
偽造token拒否、現在参照の保護を確認。通信は拒否し、全体pytest/CIをPRに記録する。
正常なレスポンスと画像URL形式、schemaを維持する。DB確定後の画像削除失敗は
API成功として記録/再試行へ回す。戻す際は本PRをrevertできるが、旧版はDB失敗で
欠損参照を再発させるため、投稿操作を停止してから戻す。#71のmanifest互換手順も守る。
文字数/枚数と大会画像ルールは#21、構成整理は順12。masterへマージしない。
