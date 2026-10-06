# #71 保持画像検証とアップロード所有記録

基準: `c9c6de4cdba3cac4217bd630ce480ba9a44c0e13`。base: `fix/step-11-bugs`。

kept_imagesは重複のない文字列listで、対象Postの既存画像だけを許可する。
他Postも参照するURL・任意URL・不正な型・壊れたform JSONは保存/削除/更新前に400。
URL prefixは所有権の根拠にしない。サーバーのsave_fileが返したURLだけを
対象Postの所有記録に追加し、削除はその記録と他投稿の参照の両方で確認する。
所有記録がない旧画像は削除せずwarningを残す。画像保持と表示は維持する。

## データ互換と展開

カラム・schemaは変えない。既存Textのimage_urlsに新画像の所有記録を保存する。
旧値のJSON listは引き続き読み、新値は以下のmanifest形式で保存する。
APIのimagesはどちらも従来のURL list、保存先とURL生成は変更しない。

```json
{"netatwi_image_manifest": 1, "urls": ["..."], "owned": ["..."]}
```

旧readerはmanifestを解釈しないため、本番切替時は旧revisionへの並行trafficを停止し、
全workerをこのreaderへ揃えてから投稿更新を再開する。DB schema migrationは不要。
旧バージョンへ戻す場合は、バックアップ後にmanifestのurlsを旧JSON listへ戻し、
workerのreaderも同時に戻す。所有記録が消えるため、旧版の画像削除を再開しない。

## 検証

Python 3.11.16、一時SQLite、画像save/delete fakeと通信拒否。
初回13ケースは修正前すべて失敗。保持型/foreign URL/任意URL/重複、
旧不正参照の編集と削除、新画像の追加→保持→削除、壊れたformを検証する。
正当なuploadを模す既存fixtureでは所有記録を明示し、正当な削除経路も維持する。
URL map・モデルDDL/Alembic差分ゼロを含む全体pytest/CIを確認してPRに記録する。

## 旧データの監査

読み取り専用の `python scripts/audit_image_ownership.py` が、未検証URL、
重複参照と該当post_idを報告する。本番ではDBの読取権限で実行する。
ストレージのupload記録と投稿作成履歴を照合して正当な元投稿を判断し、
混入URLを他投稿から除去する。単独参照や公開prefixだけでownedへ昇格しない。
根拠がない旧画像は保留し、DBから外した画像もストレージ削除を自動実行しない。
この作業中に本番データ・ストレージは操作していない。

他Postの参照照合は画像付きPostの読込が増える。正規APIからの共有URL取り込みは
拒否するため、新しい共有参照は発生させない。

やってないこと: DB失敗時の画像補償（#26）、文字数/画像枚数（#21）、
本番旧データ修復、構成整理。masterにはマージしない。
