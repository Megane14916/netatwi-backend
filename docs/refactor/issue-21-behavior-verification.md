# #21 入力検証

分岐元・PR baseは最新の`refactor/step-13-behavior`。API単位でPRを分ける。

## コメント

基準`0ed5287`。追加27ケースのうち修正前26件失敗・1件成功。
POST/PUTの本文null・配列・数値・真偽値、contentの非文字列、空/不正JSONと
非JSONリクエストをJSON 400へ変更。既存の文字数・審査員例外・所有者判定は保持。
GET `/api/comments`のpostIdsは正の32bit整数へ限定する。
入力検証に失敗した際、コメント・カウンタ・通知が変化しないことを確認。
共通JSON object parserと専用InputError handlerは、この段階ではコメントだけで利用。

HTTP影響: 従来の未捕捉例外/HTML 400/415や範囲外IDの200をJSON 400へ変更。
正常JSON object/文字列を送るfrontendの呼出しに変更不要。
やってないこと: 他APIの検証、transaction/例外処理一般、schema変更。
Python 3.11.16、隔離SQLite、外部通信拒否。対象/全体/CI結果は個別PRに記録。
migration・本番設定変更なし。本番反映なし。PR単位のrevertで戻せる。

## 大会管理API

基準`dbeff1c`。追加68件は修正前67失敗/1成功、修正後の管理/認証関連114件成功。
create/updateの全フィールドを更新前に検証。name/passwordのDB上限、真偽値の型、
整数の型/32bit範囲・非負の重み・正の最大点/分母、enum、文字列/null、期間順序と
部分更新後の期間・進出率を確認する。数値文字列は従来どおり許容する。
日時はUTCへ正規化して保存し、オフセット消失を修正する。naive入力は従来どおりUTC。
旧enum general/forbiddenはuser/noneへ正規化し、一般票・画像禁止の条件を適用する。
不正JSONと検証失敗はJSON 400へ変更し、DB・Cloud Tasksに副作用を出さない。
frontendはISO日時、number/booleanと有効enumを送るため正常系の調整不要。
既存の不正値/ゼロ分母/forbiddenの特性テストは意図した契約のみ更新した。
他APIの入力検証は後続PR。DB schema/migration・本番設定変更なし。

## 投票API

追加17件は修正前11失敗/6成功、修正後関連108件成功。
JSON objectを要求し、真偽値を点数とする入力と非文字列の審査員賞commentを
既存投票の削除前に拒否する。点数の数値文字列・小数、nullコメント、0点審査、
投票対象と点数範囲の先行修正を保持。拒否時は既存投票/投票者・審査員数を保持。
HTTP: malformed JSON/型不正をJSON 400へ変更。frontendの有効入力は変更不要。
