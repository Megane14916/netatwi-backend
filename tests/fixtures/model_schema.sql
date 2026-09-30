CREATE TABLE bookmark (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	post_id INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_user_post_bookmark UNIQUE (user_id, post_id),
	FOREIGN KEY(user_id) REFERENCES user (id),
	FOREIGN KEY(post_id) REFERENCES post (id)
);

CREATE INDEX ix_bookmark_post_id ON bookmark (post_id);

CREATE INDEX ix_bookmark_user_id ON bookmark (user_id);

CREATE TABLE comment (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	post_id INTEGER NOT NULL,
	content TEXT NOT NULL,
	is_judge BOOLEAN NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_user_post_comment UNIQUE (user_id, post_id),
	FOREIGN KEY(user_id) REFERENCES user (id),
	FOREIGN KEY(post_id) REFERENCES post (id)
);

CREATE INDEX ix_comment_post_id ON comment (post_id);

CREATE INDEX ix_comment_user_id ON comment (user_id);

CREATE TABLE contest (
	id INTEGER NOT NULL,
	name VARCHAR(120) NOT NULL,
	theme TEXT,
	status VARCHAR(20) NOT NULL,
	start_time DATETIME NOT NULL,
	end_time DATETIME NOT NULL,
	voting_end_time DATETIME NOT NULL,
	general_vote_weight INTEGER NOT NULL,
	judge_max_score INTEGER NOT NULL,
	judge_password VARCHAR(120),
	has_theme BOOLEAN NOT NULL,
	has_qualifier BOOLEAN NOT NULL,
	allow_images BOOLEAN NOT NULL,
	type VARCHAR(20) NOT NULL,
	scoring_method VARCHAR(20) NOT NULL,
	image_rule VARCHAR(20) NOT NULL,
	advancement_numerator INTEGER,
	advancement_denominator INTEGER,
	judge_award_advancement BOOLEAN NOT NULL,
	parent_contest_id INTEGER,
	is_voting_visible BOOLEAN NOT NULL,
	result_comment_top TEXT,
	result_comment_bottom TEXT,
	notified_post_start BOOLEAN NOT NULL,
	notified_voting_start BOOLEAN NOT NULL,
	notified_result_announce BOOLEAN NOT NULL,
	post_count INTEGER NOT NULL,
	total_voters INTEGER NOT NULL,
	total_judges INTEGER NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(parent_contest_id) REFERENCES contest (id)
);

CREATE INDEX ix_contest_parent_contest_id ON contest (parent_contest_id);

CREATE TABLE contest_result (
	id INTEGER NOT NULL,
	contest_id INTEGER NOT NULL,
	post_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	score FLOAT NOT NULL,
	rank INTEGER NOT NULL,
	is_advanced BOOLEAN NOT NULL,
	is_judge_award BOOLEAN NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(contest_id) REFERENCES contest (id),
	FOREIGN KEY(post_id) REFERENCES post (id),
	FOREIGN KEY(user_id) REFERENCES user (id)
);

CREATE INDEX ix_contest_result_contest_id ON contest_result (contest_id);

CREATE INDEX ix_contest_result_post_id ON contest_result (post_id);

CREATE INDEX ix_contest_result_user_id ON contest_result (user_id);

CREATE TABLE news (
	id INTEGER NOT NULL,
	tweet_id VARCHAR(80) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE notification (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	sender_id INTEGER,
	type VARCHAR(50) NOT NULL,
	post_id INTEGER,
	contest_id INTEGER,
	is_read BOOLEAN NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES user (id),
	FOREIGN KEY(sender_id) REFERENCES user (id),
	FOREIGN KEY(post_id) REFERENCES post (id),
	FOREIGN KEY(contest_id) REFERENCES contest (id)
);

CREATE INDEX idx_user_is_read ON notification (user_id, is_read);

CREATE INDEX ix_notification_contest_id ON notification (contest_id);

CREATE INDEX ix_notification_post_id ON notification (post_id);

CREATE INDEX ix_notification_sender_id ON notification (sender_id);

CREATE INDEX ix_notification_user_id ON notification (user_id);

CREATE TABLE post (
	id INTEGER NOT NULL,
	content TEXT NOT NULL,
	image_urls TEXT,
	comment_count INTEGER NOT NULL,
	bookmark_count INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	contest_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(contest_id) REFERENCES contest (id),
	FOREIGN KEY(user_id) REFERENCES user (id)
);

CREATE INDEX ix_post_contest_id ON post (contest_id);

CREATE INDEX ix_post_user_id ON post (user_id);

CREATE TABLE user (
	id INTEGER NOT NULL,
	twitter_id VARCHAR(80) NOT NULL,
	name VARCHAR(255) NOT NULL,
	screen_name VARCHAR(80) NOT NULL,
	profile_image_url VARCHAR(255),
	created_at DATETIME NOT NULL,
	deleted_at DATETIME,
	PRIMARY KEY (id),
	UNIQUE (twitter_id)
);

CREATE UNIQUE INDEX ix_user_screen_name ON user (screen_name);

CREATE TABLE user_stats (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	rank INTEGER NOT NULL,
	gp_1st INTEGER NOT NULL,
	gp_2nd INTEGER NOT NULL,
	gp_3rd INTEGER NOT NULL,
	daily_1st INTEGER NOT NULL,
	daily_2nd INTEGER NOT NULL,
	daily_3rd INTEGER NOT NULL,
	judge_awards INTEGER NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (user_id),
	FOREIGN KEY(user_id) REFERENCES user (id)
);

CREATE TABLE vote (
	id INTEGER NOT NULL,
	count FLOAT NOT NULL,
	is_judge_vote BOOLEAN NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	user_id INTEGER NOT NULL,
	post_id INTEGER NOT NULL,
	contest_id INTEGER NOT NULL,
	is_judge_award BOOLEAN NOT NULL,
	judge_comment TEXT,
	PRIMARY KEY (id),
	CONSTRAINT uq_user_post_vote UNIQUE (user_id, post_id),
	FOREIGN KEY(user_id) REFERENCES user (id),
	FOREIGN KEY(post_id) REFERENCES post (id),
	FOREIGN KEY(contest_id) REFERENCES contest (id)
);

CREATE INDEX ix_vote_contest_id ON vote (contest_id);

CREATE INDEX ix_vote_post_id ON vote (post_id);

CREATE INDEX ix_vote_user_id ON vote (user_id);
