import asyncio
import gc
import re
import weakref
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from tkb_api.bluesky_auth import (
    AuthenticatedAccount,
    AuthenticationError,
    BlueskyAuthenticator,
    LoginProfile,
)
from tkb_api.sessions import SESSION_TTL_SECONDS, SessionStore


@dataclass(frozen=True)
class FakeProfile:
    did: str = "did:plc:example"
    handle: str = "demo.bsky.social"


class FakeClient:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.received: tuple[str, str] | None = None

    async def login(self, identifier: str, password: str) -> LoginProfile:
        self.received = (identifier, password)
        if self.failure is not None:
            raise self.failure
        return FakeProfile()


class ScheduledCall:
    def __init__(self, delay: float, callback: Callable[[], None]) -> None:
        self.delay = delay
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeScheduler:
    def __init__(self) -> None:
        self.calls: list[ScheduledCall] = []

    def __call__(self, delay: float, callback: Callable[[], None]) -> ScheduledCall:
        call = ScheduledCall(delay, callback)
        self.calls.append(call)
        return call


def test_authentication_retains_only_account_and_client() -> None:
    client = FakeClient()
    authenticator = BlueskyAuthenticator(lambda: client)
    app_password = "private-app-password"  # noqa: S105 - テスト専用の架空の値

    account = asyncio.run(authenticator.authenticate("demo.bsky.social", app_password))

    assert client.received == ("demo.bsky.social", app_password)
    assert account.did == "did:plc:example"
    assert account.client is client
    assert app_password not in repr(account)
    assert not hasattr(account, "app_password")


def test_sdk_failure_does_not_expose_credentials() -> None:
    app_password = "private-app-password"  # noqa: S105 - テスト専用の架空の値
    client = FakeClient(failure=RuntimeError(f"login rejected: {app_password}"))

    with pytest.raises(AuthenticationError) as error:
        asyncio.run(
            BlueskyAuthenticator(lambda: client).authenticate("demo.bsky.social", app_password)
        )

    assert app_password not in str(error.value)
    assert error.value.__suppress_context__


def test_session_expires_after_thirty_minutes_and_logout_revokes_it() -> None:
    now = [100.0]
    account = asyncio.run(BlueskyAuthenticator(lambda: FakeClient()).authenticate("demo", "pw"))
    scheduler = FakeScheduler()
    store = SessionStore(
        clock=lambda: now[0], session_id_factory=lambda: "test-session", schedule=scheduler
    )

    session_id = store.create(account)
    assert store.get(session_id) is account
    now[0] += SESSION_TTL_SECONDS - 1
    assert store.get(session_id) is account
    now[0] += 1
    assert store.get(session_id) is None
    assert not store.revoke(session_id)
    store.close()

    second = SessionStore(session_id_factory=lambda: "second-session", schedule=FakeScheduler())
    second_id = second.create(account)
    assert second.revoke(second_id)
    assert second.get(second_id) is None
    second.close()


def test_idle_session_releases_client_when_timer_fires() -> None:
    now = [100.0]
    scheduler = FakeScheduler()
    client = FakeClient()
    account = AuthenticatedAccount(did="did:plc:example", handle="demo.bsky.social", client=client)
    client_ref = weakref.ref(client)
    store = SessionStore(clock=lambda: now[0], schedule=scheduler)
    store.create(account)
    assert scheduler.calls[0].delay == SESSION_TTL_SECONDS

    del account, client
    gc.collect()
    assert client_ref() is not None

    now[0] += SESSION_TTL_SECONDS
    scheduler.calls[0].callback()
    gc.collect()
    assert client_ref() is None
    store.close()


def test_session_ids_are_random_and_url_safe() -> None:
    account = asyncio.run(BlueskyAuthenticator(lambda: FakeClient()).authenticate("demo", "pw"))
    store = SessionStore()

    first = store.create(account)
    second = store.create(account)

    assert first != second
    assert len(first) >= 40
    assert re.fullmatch(r"[A-Za-z0-9_-]+", first)
    store.close()


def test_rejects_session_id_collision() -> None:
    account = asyncio.run(BlueskyAuthenticator(lambda: FakeClient()).authenticate("demo", "pw"))
    store = SessionStore(session_id_factory=lambda: "same", schedule=FakeScheduler())
    store.create(account)

    with pytest.raises(RuntimeError):
        store.create(account)
    store.close()
