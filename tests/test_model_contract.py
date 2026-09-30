"""Schema and mapper contracts captured before splitting models.py."""

import json
from importlib import import_module
from pathlib import Path

import models
from sqlalchemy.dialects import sqlite
from sqlalchemy.schema import CreateIndex, CreateTable


FIXTURES = Path(__file__).parent / "fixtures"
MODEL_NAMES = {
    "User",
    "Contest",
    "Post",
    "Vote",
    "Bookmark",
    "Comment",
    "Notification",
    "ContestResult",
    "UserStats",
    "News",
}
MODEL_MODULES = {
    "User": "user",
    "Contest": "contest",
    "Post": "post",
    "Vote": "vote",
    "Bookmark": "bookmark",
    "Comment": "comment",
    "Notification": "notification",
    "ContestResult": "contest_result",
    "UserStats": "user_stats",
    "News": "news",
}


def schema_ddl():
    dialect = sqlite.dialect()
    statements = []
    for table in sorted(models.db.metadata.tables.values(), key=lambda table: table.name):
        statements.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda index: index.name):
            statements.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
    return "\n\n".join(statements) + "\n"


def relationship_contract():
    return {
        mapper.class_.__name__: {
            relation.key: {
                "target": relation.mapper.class_.__name__,
                "back_populates": relation.back_populates,
                "uselist": relation.uselist,
                "lazy": relation.lazy,
                "cascade": sorted(relation.cascade),
                "local_columns": sorted(column.name for column in relation.local_columns),
            }
            for relation in sorted(mapper.relationships, key=lambda relation: relation.key)
        }
        for mapper in sorted(
            models.db.Model.registry.mappers, key=lambda mapper: mapper.class_.__name__
        )
    }


def test_all_models_are_exported_and_registered():
    registered = {
        mapper.class_.__name__: mapper.class_
        for mapper in models.db.Model.registry.mappers
    }
    assert set(registered) == MODEL_NAMES
    assert set(models.db.metadata.tables) == {
        "user",
        "contest",
        "post",
        "vote",
        "bookmark",
        "comment",
        "notification",
        "contest_result",
        "user_stats",
        "news",
    }
    for name in MODEL_NAMES:
        assert getattr(models, name) is registered[name]


def test_each_model_module_uses_the_shared_db():
    for name, module_name in MODEL_MODULES.items():
        module = import_module(f"models.{module_name}")
        assert getattr(module, name) is getattr(models, name)
        assert module.db is models.db


def test_ddl_matches_pre_refactor_snapshot():
    assert schema_ddl() == (FIXTURES / "model_schema.sql").read_text(encoding="utf-8")


def test_relationships_match_pre_refactor_snapshot():
    expected = json.loads(
        (FIXTURES / "model_relationships.json").read_text(encoding="utf-8")
    )
    assert relationship_contract() == expected
