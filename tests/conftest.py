"""Shared test fixtures."""

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def jira_fixture():
    with open(FIXTURES_DIR / "jira_issues.json") as f:
        return json.load(f)


@pytest.fixture
def notion_db_fixture():
    with open(FIXTURES_DIR / "notion_database.json") as f:
        return json.load(f)


@pytest.fixture
def notion_pages_fixture():
    with open(FIXTURES_DIR / "notion_pages.json") as f:
        return json.load(f)


@pytest.fixture
def mstodo_lists_fixture():
    with open(FIXTURES_DIR / "mstodo_lists.json") as f:
        return json.load(f)


@pytest.fixture
def mstodo_tasks_fixture():
    with open(FIXTURES_DIR / "mstodo_tasks.json") as f:
        return json.load(f)
