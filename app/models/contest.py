from app.extensions import db


class Contest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    theme = db.Column(db.Text, nullable=True) # お題なしを許可
    status = db.Column(db.String(20), nullable=False, default='upcoming')

    # 既存の時間は「決勝」または「通常」の時間とする
    start_time = db.Column(db.DateTime, nullable=False) # 通常:投稿開始 / 予選あり: 決勝投稿開始
    end_time = db.Column(db.DateTime, nullable=False) # 通常:投稿終了 / 予選あり: 決勝投稿終了
    voting_end_time = db.Column(db.DateTime, nullable=False) # 通常:投票終了 / 予選あり: 決勝投票終了

    general_vote_weight = db.Column(db.Integer, nullable=False, default=50) # 一般票の重み係数 (デフォルト50)
    judge_max_score = db.Column(db.Integer, nullable=False, default=10)

    judge_password = db.Column(db.String(120), nullable=True)
    has_theme = db.Column(db.Boolean, nullable=False, default=True)
    has_qualifier = db.Column(db.Boolean, nullable=False, default=False)
    allow_images = db.Column(db.Boolean, nullable=False, default=True)

    # --- ▼▼▼ 新規追加カラム (Phase 1) ▼▼▼ ---
    type = db.Column(db.String(20), nullable=False, default='grandprix')
    scoring_method = db.Column(db.String(20), nullable=False, default='both')
    image_rule = db.Column(db.String(20), nullable=False, default='optional')
    advancement_numerator = db.Column(db.Integer, nullable=True) # 予選通過率 (分子)
    advancement_denominator = db.Column(db.Integer, nullable=True) # 予選通過率 (分母)
    judge_award_advancement = db.Column(db.Boolean, nullable=False, default=False)
    parent_contest_id = db.Column(db.Integer, db.ForeignKey('contest.id'), index=True, nullable=True)
    is_voting_visible = db.Column(db.Boolean, nullable=False, default=True)

    result_comment_top = db.Column(db.Text, nullable=True)
    result_comment_bottom = db.Column(db.Text, nullable=True)

    # バッチ処理用の通知完了フラグ
    notified_post_start = db.Column(db.Boolean, nullable=False, default=False)
    notified_voting_start = db.Column(db.Boolean, nullable=False, default=False)
    notified_result_announce = db.Column(db.Boolean, nullable=False, default=False)

    # --- キャッシュスタンピード対策用カウンタ ---
    post_count = db.Column(db.Integer, nullable=False, default=0)
    total_voters = db.Column(db.Integer, nullable=False, default=0)
    total_judges = db.Column(db.Integer, nullable=False, default=0)

    children = db.relationship('Contest', backref=db.backref('parent', remote_side=[id]), lazy=True)
    # --- ▲▲▲ ここまで ▲▲▲ ---

    posts = db.relationship('Post', back_populates='contest', lazy=True)
    votes = db.relationship('Vote', back_populates='contest', lazy=True)
