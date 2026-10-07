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

## 投稿編集JSON

追加7件が修正前すべて失敗し、修正後の投稿/画像関連78件成功。
JSON object以外と空/壊れたJSONはJSON 400へ変更。既存投稿本文/画像とストレージに
副作用がないことを確認。multipartのkept_imagesはJSONDecodeErrorだけを捕捉する。
既存の画像所有関係・補償・null/本文なしの画像編集条件は保持。

## ニュース入力

追加10件は修正前すべて失敗、JSON object・文字列のtweet_id・保存後80文字上限を検証。
ID/URLからの既存の抽出規則は保持。入力型/JSON不正は500からJSON 400へ変更し、
DB更新を伴わない。frontend正常入力・DB schemaと公開日時表現は維持。

## 審査員ログイン入力

追加10件は修正前8失敗/2成功、修正後認証・外部境界関連43件成功。
JSON object、文字列パスワード、DB上限120文字を検証し、不正入力はJSON 400。
認証失敗・一般投票大会・rate limit・既存の審査員sessionを維持する。
OAuthの機密ログ対策とTasks OIDCは変更していない。

## 予選/決勝の大会名境界

追加3件は修正前2失敗/1成功、修正後管理入力関連71件成功。
createでhasQualifier=trueの場合、予選/決勝の自動接尾辞3文字を含めてDB上限120文字
以内とする（入力名117文字まで）。118/120文字の入力はDB/Tasks更新前にJSON 400。
SQLiteでも受理前検証を確認し、PostgreSQL VARCHARへの依存を回避する。schema変更なし。
#21の一般入力検証と順11の先行投稿/投票/画像検証を併せて残件を完了した。

## 最終結果

PR #93〜#99を開発ブランチへ順にmerge。最後のPR #99で全1002件のCI成功を確認した。
ユーザー指定に従い開発ブランチでの完了としてIssueをcloseし、masterへのマージは行っていない。
現在の全体結果は[順13検証記録](step-13-verification.md)を参照する。
