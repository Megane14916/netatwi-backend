# #23 Cloud Tasks OIDC認証

基準: `b4402d9a91ce16fceba955338db1c527c0a2c323`。base `fix/step-11-bugs`。
handlerは従来匿名で通知/結果/flagを変更できた。再現9件は修正前200で全件失敗。

AuthorizationのBearer ID tokenをgoogle-authのverify_oauth2_tokenで検証する。
Google公開鍵の署名、issuer、iat/exp、設定したaudienceを検証した後、email_verified=trueと
TASKS_SERVICE_ACCOUNT_EMAILへの完全一致を要求する。CloudTasks系ヘッダーやsessionは
認証の根拠にしない。未認証/不正tokenは401、不許可callerは403、設定欠損と
証明書取得障害は503で業務serviceへ到達しない。token/claimsをログへ出さない。
schedulerは同じaudience/SAのoidc_tokenを追加し、設定不十分なら署名なしtaskを作らない。
google-auth[requests]を直接依存として現在の検証版2.59.1に固定する。

## 設定・切替手順

以下を同じrevisionの環境へ設定する（.env.exampleに例）。

- TASKS_OIDC_AUDIENCE: Cloud Runの正規service URL（pathを含めず、発行/検証で完全一致）。
- TASKS_SERVICE_ACCOUNT_EMAIL: queueと同projectのtask呼出用SA。
- GCP_PROJECT_ID/GCP_LOCATION/GCP_QUEUE_NAME/TASK_HANDLER_URL: 従来のqueue/handler。

task作成主体はCloud Tasks Enqueuerと指定SAへのiam.serviceAccounts.actAsを持つ。
Cloud Tasks service agentのroles/cloudtasks.serviceAgentと指定SAへの利用権限を確認する。
Cloud RunがIAM認証を要求する構成では呼出SAに対象serviceのroles/run.invokerが必要。
ブラウザー向け公開APIと同じserviceを全面privateへ切り替えると一般APIを遮断するため、
今回その設定変更は行わない。公開serviceでもこのtask endpointはapplicationで検証する。
X-Serverless-Authorizationの署名除去済みtokenは信用しない。アプリに署名付き
Authorizationが届く経路を使う。queueのhttpTarget.oidcToken overrideはtask設定より
優先するので、存在する場合は上記SA/audienceと一致させる。

展開前にqueueをpauseし、未処理の旧taskへqueue-level OIDC overrideを設定するか、
対象eventを照合してOIDC付きtaskへ再作成する。task-level更新だけでは既存taskは直らない。
設定とrevisionを反映後、未認証taskの拒否、正規の試験taskと再試行を確認してresumeする。
retryConfigの回数/期間/backoffを記録し、503と業務失敗が再試行されること、成功2xxが
重複通知/結果を作らないことを確認する。本PRは本番変更/実task実行を行っていない。
戻す場合もqueueをpauseしてrevision/設定を一緒に戻す。旧handlerは匿名到達が再発するので、
安全な代替入口を確保せず旧公開handlerを再開しない。

参考: [Google Cloud Tasks認証](https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks)、
[Cloud Run認証](https://docs.cloud.google.com/run/docs/authenticating/service-to-service)、
[google-auth検証API](https://google-auth.readthedocs.io/en/latest/reference/google.oauth2.id_token.html)。

## 隔離検証と本番照合の区別

使い捨てRSA鍵で本物の署名tokenを生成し、Google公開鍵取得だけfake化する。
署名改ざん・wrong audience/issuer・期限切れ・他SA・email未検証/文字列trueを拒否し、
通知/結果/flagが不変であることを確認する。既存taskテストは署名付きtask_clientを
明示的に利用し、時刻境界・3event・正規再試行・DB失敗後の再試行を保持する。
匿名clientは既存どおり匿名で、TESTINGによる認証バイパスはない。
新しいoidc_token以外のURL・予定時刻・通知/結果・CLI契約は維持する。
全体pytest/CIの件数はPRへ記録する。schema変更なし。

本番のproject/service/IAM/Ingress/queue override/retryConfigはユーザー提供情報待ち。
ローカル.envに対象設定はなく、gcloud接続もない。サインイン済みコンソールの閲覧は
自動承認レビューで拒否され、ユーザーは設定情報を自分で提供する方針を選んだ。
提供情報との照合が済むまで、本Issueの本番確認を完了扱いにしない。
やってないこと: 本番設定変更、外部client/config分離(#69)、構成整理、masterマージ。
