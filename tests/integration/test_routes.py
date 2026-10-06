"""The public URL map, including endpoint names used by url_for, is a contract."""


# Flask adds HEAD/OPTIONS automatically. Record the methods explicitly
# declared by the application, and exclude Flask's built-in static route.
EXPECTED_ROUTES = {
    ("/", ("GET",), "core.index"),
    ("/api/admin/contests", ("POST",), "admin.create_contest"),
    ("/api/admin/contests/<int:id>", ("DELETE",), "admin.delete_contest"),
    ("/api/admin/contests/<int:id>", ("PUT",), "admin.update_contest"),
    ("/api/admin/contests/management", ("GET",), "admin.get_management_contests"),
    ("/api/admin/news", ("GET",), "news.get_admin_news"),
    ("/api/admin/news", ("POST",), "news.add_news"),
    ("/api/admin/news/<int:id>", ("DELETE",), "news.delete_news"),
    ("/api/callback/twitter", ("GET",), "auth.twitter_callback"),
    ("/api/comments", ("GET",), "comments.get_multiple_comments"),
    ("/api/comments/<int:comment_id>", ("DELETE", "PUT"), "comments.modify_comment"),
    ("/api/contests", ("GET",), "contests.get_contests"),
    (
        "/api/contests/<int:contest_id>/posts/<int:post_id>",
        ("DELETE",),
        "posts.delete_post",
    ),
    (
        "/api/contests/<int:contest_id>/posts/<int:post_id>",
        ("PUT",),
        "posts.update_post",
    ),
    ("/api/contests/<int:id>", ("GET",), "contests.get_contest_details"),
    ("/api/contests/<int:id>/judge/login", ("POST",), "auth.judge_login"),
    ("/api/contests/<int:id>/posts", ("GET",), "posts.get_posts_for_contest"),
    ("/api/contests/<int:id>/posts", ("POST",), "posts.submit_post"),
    ("/api/contests/<int:id>/results", ("GET",), "results.get_contest_results"),
    ("/api/contests/<int:id>/vote", ("POST",), "voting.submit_votes"),
    ("/api/login/twitter", ("GET",), "auth.twitter_login"),
    ("/api/logout", ("GET",), "account.logout"),
    ("/api/me", ("GET",), "account.get_current_user"),
    ("/api/news", ("GET",), "news.get_news"),
    ("/api/notifications", ("GET",), "notifications.get_notifications"),
    ("/api/notifications/read", ("POST",), "notifications.mark_notifications_read"),
    ("/api/notifications/unread-count", ("GET",), "notifications.get_unread_notifications_count"),
    ("/api/posts/<int:post_id>/bookmark", ("DELETE", "PUT"), "interactions.set_bookmark"),
    ("/api/posts/<int:post_id>/comments", ("GET",), "comments.get_comments"),
    ("/api/posts/<int:post_id>/comments", ("POST",), "comments.add_comment"),
    ("/api/posts/<int:post_id>/like", ("DELETE", "PUT"), "interactions.set_like"),
    ("/api/profile/<string:screen_name>", ("GET",), "profile.get_user_profile_updated"),
    ("/api/tasks/contest/<int:id>/<event_type>", ("POST",), "tasks.handle_contest_task"),
    ("/api/users", ("GET",), "users.get_users_list"),
    ("/api/users/me", ("DELETE",), "account.withdraw_user"),
}


def test_route_contract(app):
    assert {
        "auth", "admin", "news", "contests", "posts", "profile",
        "voting", "results", "interactions", "comments", "notifications", "users",
        "tasks",
    } <= set(
        app.blueprints
    )
    actual = {
        (rule.rule, tuple(sorted(rule.methods - {"HEAD", "OPTIONS"})), rule.endpoint)
        for rule in app.url_map.iter_rules()
        if rule.endpoint != "static"
    }

    assert len(actual) == 35
    assert actual == EXPECTED_ROUTES


def test_issue_10_handlers_are_registered_from_blueprints(app):
    from app import create_app
    production_app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})

    groups = {
        "voting": ["voting.submit_votes"],
        "results": ["results.get_contest_results"],
        "interactions": ["interactions.set_bookmark", "interactions.set_like"],
        "comments": ["comments.get_comments", "comments.get_multiple_comments", "comments.add_comment", "comments.modify_comment"],
        "notifications": ["notifications.get_notifications", "notifications.get_unread_notifications_count", "notifications.mark_notifications_read"],
        "users": ["users.get_users_list"],
    }
    for application in (production_app, app):
        for module, endpoints in groups.items():
            for endpoint in endpoints:
                assert application.view_functions[endpoint].__module__ == f"app.routes.{module}"
