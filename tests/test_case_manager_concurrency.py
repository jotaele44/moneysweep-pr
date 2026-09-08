"""Shared-connection request isolation, interruption, and lazy initialization."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from moneysweep.case_manager.models import Case
from moneysweep.case_manager.repository import CaseManagerConflict, SQLiteCaseManagerRepository
from server.backend import case_manager_api as api


@pytest.fixture
def repository():
    repo = SQLiteCaseManagerRepository(":memory:")
    try:
        repo.apply_migration(api.MIGRATION_PATH)
        yield repo
    finally:
        repo.close()


def case(number):
    return Case(
        case_id=f"case_{number}",
        title=f"Case {number}",
        case_type="audit",
        status="open",
        scope="test",
    )


@pytest.mark.parametrize("second_fails", [False, True])
def test_overlapping_writers_cannot_rollback_each_other(repository, second_fails):
    entered = Event()
    release = Event()
    attempted = Event()
    finished = Event()

    def first():
        with repository.transaction() as connection:
            repository.insert_case(case(1), connection)
            entered.set()
            assert release.wait(20)

    def second():
        attempted.set()
        try:
            with repository.transaction() as connection:
                repository.insert_case(case(2), connection)
                if second_fails:
                    raise ValueError("second request rejected")
        finally:
            finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(first)
        try:
            assert entered.wait(20)
            second_result = pool.submit(second)
            assert attempted.wait(20)
            assert not finished.wait(0.2), "second request entered another request's transaction"
        finally:
            release.set()
        first_result.result(timeout=20)
        if second_fails:
            with pytest.raises(ValueError, match="second request rejected"):
                second_result.result(timeout=20)
        else:
            second_result.result(timeout=20)
    expected = ["case_1"] if second_fails else ["case_1", "case_2"]
    assert [row["case_id"] for row in repository.list_cases()] == expected


@pytest.mark.parametrize("rollback", [False, True])
def test_reads_wait_for_committed_state(repository, rollback):
    inserted = Event()
    release = Event()
    reading = Event()
    finished = Event()

    def writer():
        with repository.transaction() as connection:
            repository.insert_case(case(1), connection)
            inserted.set()
            assert release.wait(20)
            if rollback:
                raise ValueError("rejected")

    def reader():
        reading.set()
        try:
            return repository.list_cases()
        finally:
            finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        write_result = pool.submit(writer)
        try:
            assert inserted.wait(20)
            read_result = pool.submit(reader)
            assert reading.wait(20)
            assert not finished.wait(0.2), "read exposed uncommitted data"
        finally:
            release.set()
        if rollback:
            with pytest.raises(ValueError, match="rejected"):
                write_result.result(timeout=20)
        else:
            write_result.result(timeout=20)
        assert len(read_result.result(timeout=20)) == (0 if rollback else 1)


def test_rejected_nested_begin_does_not_rollback_outer_transaction(repository):
    with repository.transaction() as connection:
        repository.insert_case(case(1), connection)
        with pytest.raises(sqlite3.OperationalError):
            with repository.transaction():
                pytest.fail("nested BEGIN unexpectedly succeeded")
        repository.insert_case(case(2), connection)
    assert len(repository.list_cases()) == 2


def test_interruption_rolls_back_before_releasing_connection(repository):
    with pytest.raises(KeyboardInterrupt):
        with repository.transaction() as connection:
            repository.insert_case(case(1), connection)
            raise KeyboardInterrupt()
    assert not repository.connection.in_transaction
    assert repository.list_cases() == []


def test_closing_repository_does_not_close_borrowed_connection():
    connection = sqlite3.connect(":memory:")
    try:
        repository = SQLiteCaseManagerRepository(connection)
        repository.close()
        assert connection.execute("SELECT 1").fetchone()[0] == 1
    finally:
        connection.close()


@pytest.fixture
def isolated_api(tmp_path, monkeypatch):
    previous = api._repository
    api.configure_repository(None)
    monkeypatch.setattr(api, "DATABASE_PATH", tmp_path / "cases.sqlite3")
    try:
        yield
    finally:
        current = api._repository
        if current is not None and current is not previous:
            current.close()
        api.configure_repository(previous)


def test_failed_migration_is_closed_and_next_request_retries(isolated_api, monkeypatch):
    created = []

    class Candidate(SQLiteCaseManagerRepository):
        closed = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

        def apply_migration(self, path):
            if len(created) == 1:
                raise RuntimeError("migration failed")
            super().apply_migration(path)

        def close(self):
            super().close()
            self.closed = True

    monkeypatch.setattr(api, "SQLiteCaseManagerRepository", Candidate)
    with pytest.raises(RuntimeError, match="migration failed"):
        api._services()
    assert api._repository is None
    assert created[0].closed
    commands, queries = api._services()
    assert commands.repository is queries.repository is created[1]


def test_concurrent_initialization_publishes_one_repository(isolated_api, monkeypatch):
    entered = Event()
    release = Event()
    attempted = Event()
    finished = Event()
    created = []

    class Candidate(SQLiteCaseManagerRepository):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

        def apply_migration(self, path):
            entered.set()
            assert release.wait(20)
            super().apply_migration(path)

    monkeypatch.setattr(api, "SQLiteCaseManagerRepository", Candidate)

    def second():
        attempted.set()
        try:
            return api._services()
        finally:
            finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(api._services)
        try:
            assert entered.wait(20)
            second_result = pool.submit(second)
            assert attempted.wait(20)
            assert not finished.wait(0.2)
            assert len(created) == 1
        finally:
            release.set()
        first = first_result.result(timeout=20)
        second_services = second_result.result(timeout=20)
    assert first[0].repository is second_services[0].repository
    assert len(created) == 1


def test_migration_cannot_implicitly_commit_an_active_request(repository):
    with pytest.raises(ValueError, match="request rejected"):
        with repository.transaction() as connection:
            repository.insert_case(case(1), connection)
            with pytest.raises(CaseManagerConflict, match="active transaction"):
                repository.apply_migration(api.MIGRATION_PATH)
            raise ValueError("request rejected")
    assert repository.list_cases() == []
