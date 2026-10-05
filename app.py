"""Application compatibility exports and direct server entry."""

from app.factory import initialize_application
from app import _publish_entry


initialize_application(globals())
_publish_entry(globals())


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        print("Database tables created (if not existed).")

    # 環境変数PORTを取得（Cloud Runでは必須）、なければローカル用の5001を使う
    port = int(os.environ.get("PORT", 5001))

    # host='0.0.0.0' を指定してコンテナ外からのアクセスを許可する
    # 本番環境では debug=False にする
    app.run(host="0.0.0.0", port=port, debug=False)
