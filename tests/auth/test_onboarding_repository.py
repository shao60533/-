"""Unit tests for OnboardingRepository (onboarding v1.0).

7 cases per docs/design/onboarding.md §6.1:
  1. get_or_init for an unknown user returns defaults (welcome_pending=0)
  2. init_for_new_user flips welcome_pending=1
  3. mark_step writes the step into steps_completed
  4. mark_step with an unknown step_id is a no-op (returns False)
  5. mark_step on an already-true step is idempotent (returns False)
  6. reset clears flags + steps AND re-arms welcome_pending=1
  7. Cross-user isolation: alice's marks do not show up on bob
"""

from __future__ import annotations

import sqlite3

import pytest

from stock_trading_system.auth.onboarding_repository import OnboardingRepository
from stock_trading_system.migrations.add_user_onboarding import add_user_onboarding


@pytest.fixture
def onboarding_db(tmp_path):
    db = tmp_path / "ob.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT);"
        "INSERT INTO users (email) VALUES ('alice@x'),('bob@x');"
    )
    conn.commit()
    conn.close()
    add_user_onboarding(str(db))
    return str(db)


@pytest.fixture
def repo(onboarding_db):
    return OnboardingRepository(onboarding_db)


def test_get_or_init_defaults_for_unknown_user(repo):
    state = repo.get_or_init(1)
    assert state.user_id == 1
    assert state.welcome_pending is False
    assert state.welcomed is False
    assert state.tour_completed is False
    assert state.checklist_dismissed is False
    assert state.steps_completed == {}


def test_init_for_new_user_sets_welcome_pending(repo):
    repo.init_for_new_user(1)
    state = repo.get_or_init(1)
    assert state.welcome_pending is True
    assert state.welcomed is False


def test_mark_step_writes_into_steps_completed(repo):
    assert repo.mark_step(1, "add-holding") is True
    state = repo.get_or_init(1)
    assert state.steps_completed.get("add-holding") is True
    assert state.steps_completed.get("first-analysis") in (None, False)


def test_mark_step_unknown_step_id_is_noop(repo):
    assert repo.mark_step(1, "not-a-real-step") is False
    state = repo.get_or_init(1)
    assert state.steps_completed == {}


def test_mark_step_idempotent_returns_false_second_time(repo):
    assert repo.mark_step(1, "first-screen") is True
    assert repo.mark_step(1, "first-screen") is False
    state = repo.get_or_init(1)
    assert state.steps_completed == {"first-screen": True}


def test_reset_clears_flags_and_rearms_welcome_pending(repo):
    repo.init_for_new_user(1)
    repo.mark_step(1, "add-holding")
    repo.mark_welcomed(1, tour_completed=True)
    repo.dismiss_checklist(1)

    repo.reset(1)

    state = repo.get_or_init(1)
    assert state.welcome_pending is True
    assert state.welcomed is False
    assert state.tour_completed is False
    assert state.checklist_dismissed is False
    assert state.steps_completed == {}


def test_cross_user_isolation_alice_does_not_leak_to_bob(repo):
    repo.init_for_new_user(1)
    repo.mark_step(1, "add-holding")
    repo.mark_step(1, "first-analysis")

    bob = repo.get_or_init(2)
    assert bob.welcome_pending is False
    assert bob.steps_completed == {}

    alice = repo.get_or_init(1)
    assert alice.steps_completed == {"add-holding": True, "first-analysis": True}
