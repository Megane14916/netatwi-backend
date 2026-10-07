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
