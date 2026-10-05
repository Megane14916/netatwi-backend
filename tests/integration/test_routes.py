"""The public URL map, including endpoint names used by url_for, is a contract."""


# Flask adds HEAD/OPTIONS automatically. Record the methods explicitly
# declared by the application, and exclude Flask's built-in static route.
EXPECTED_ROUTES = {
    ("/", ("GET",), "index"),
    ("/api/admin/contests", ("POST",), "create_contest"),
    ("/api/admin/contests/<int:id>", ("DELETE",), "delete_contest"),
    ("/api/admin/contests/<int:id>", ("PUT",), "update_contest"),
    ("/api/admin/contests/management", ("GET",), "get_management_contests"),
    ("/api/admin/news", ("GET",), "get_admin_news"),
    ("/api/admin/news", ("POST",), "add_news"),
    ("/api/admin/news/<int:id>", ("DELETE",), "delete_news"),
    ("/api/callback/twitter", ("GET",), "twitter_callback"),
    ("/api/comments", ("GET",), "get_multiple_comments"),
    ("/api/comments/<int:comment_id>", ("DELETE", "PUT"), "modify_comment"),
    ("/api/contests", ("GET",), "get_contests"),
    (
        "/api/contests/<int:contest_id>/posts/<int:post_id>",
        ("DELETE",),
        "delete_post",
    ),
    (
        "/api/contests/<int:contest_id>/posts/<int:post_id>",
        ("PUT",),
        "update_post",
    ),
    ("/api/contests/<int:id>", ("GET",), "get_contest_details"),
    ("/api/contests/<int:id>/judge/login", ("POST",), "judge_login"),
    ("/api/contests/<int:id>/posts", ("GET",), "get_posts_for_contest"),
    ("/api/contests/<int:id>/posts", ("POST",), "submit_post"),
    ("/api/contests/<int:id>/results", ("GET",), "get_contest_results"),
    ("/api/contests/<int:id>/vote", ("POST",), "submit_votes"),
    ("/api/login/twitter", ("GET",), "twitter_login"),
    ("/api/logout", ("GET",), "logout"),
    ("/api/me", ("GET",), "get_current_user"),
    ("/api/news", ("GET",), "get_news"),
    ("/api/notifications", ("GET",), "get_notifications"),
    ("/api/notifications/read", ("POST",), "mark_notifications_read"),
    ("/api/notifications/unread-count", ("GET",), "get_unread_notifications_count"),
    ("/api/posts/<int:post_id>/bookmark", ("DELETE", "PUT"), "set_bookmark"),
    ("/api/posts/<int:post_id>/comments", ("GET",), "get_comments"),
    ("/api/posts/<int:post_id>/comments", ("POST",), "add_comment"),
    ("/api/posts/<int:post_id>/like", ("DELETE", "PUT"), "set_like"),
    ("/api/profile/<string:screen_name>", ("GET",), "get_user_profile_updated"),
    ("/api/tasks/contest/<int:id>/<event_type>", ("POST",), "handle_contest_task"),
    ("/api/users", ("GET",), "get_users_list"),
    ("/api/users/me", ("DELETE",), "withdraw_user"),
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
    from app import app as production_app

    groups = {
        "voting": ["submit_votes"],
        "results": ["get_contest_results"],
        "interactions": ["set_bookmark", "set_like"],
        "comments": ["get_comments", "get_multiple_comments", "add_comment", "modify_comment"],
        "notifications": ["get_notifications", "get_unread_notifications_count", "mark_notifications_read"],
        "users": ["get_users_list"],
    }
    for application in (production_app, app):
        for module, endpoints in groups.items():
            for endpoint in endpoints:
                assert application.view_functions[endpoint].__module__ == f"app.routes.{module}"
