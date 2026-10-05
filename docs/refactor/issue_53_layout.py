"""Fixed mapping for the behavior-preserving #53 test relocation."""

BASELINE = "23dbc5bc8acbc070bbfdacc63626e45a55c0e184"
API = (
    "test_api_access.py",
    "test_api_activity.py",
    "test_auth_characterization.py",
    "test_blueprint_contract.py",
    "test_comment_service_contract.py",
    "test_contest_post_profile_contract.py",
    "test_contest_post_query_service_contract.py",
    "test_contest_query_service_contract.py",
    "test_interaction_service_contract.py",
    "test_news_service_contract.py",
    "test_post_service_contract.py",
    "test_profile_service_contract.py",
    "test_user_account_service_contract.py",
    "test_voting_results_interactions_contract.py",
    "test_voting_service_contract.py",
)
INTEGRATION = (
    "test_application_factory_contract.py",
    "test_bootstrap_contract.py",
    "test_contest_jobs.py",
    "test_contest_lifecycle_contract.py",
    "test_external_boundaries.py",
    "test_model_contract.py",
    "test_notification_stats_contract.py",
    "test_package_alias_contract.py",
    "test_package_entry_contract.py",
    "test_post_vote_effects.py",
    "test_results_service_contract.py",
    "test_routes.py",
    "test_scoring.py",
    "test_scoring_characterization.py",
    "test_shared_helper_contract.py",
    "test_tasks_cli_contract.py",
)
MAPPING = {
    **{f"tests/{name}": f"tests/api/{name}" for name in API},
    **{f"tests/{name}": f"tests/integration/{name}" for name in INTEGRATION},
}
UNIT_SOURCE = "tests/test_shared_helper_contract.py"
UNIT_TARGET = "tests/unit/test_text_contract.py"
UNIT_FUNCTIONS = ("test_weighted_text_contract", "test_truthy_non_string_keeps_original_exception")
SNAPSHOTS = ("url_map.json", "model_schema.sql", "model_relationships.json")
