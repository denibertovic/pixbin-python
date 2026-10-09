import pytest
import responses

from pixbin import PixbinClient

BASE_URL = "https://pixbin.test"
TOKEN = "test-token"


@pytest.fixture
def client():
    return PixbinClient(api_token=TOKEN, base_url=BASE_URL)


@pytest.fixture
def mocked():
    with responses.RequestsMock(assert_all_requests_are_fired=True) as rsps:
        yield rsps


class FakeClock:
    """Deterministic replacement for the time module used by the client.

    sleep() advances the clock instead of blocking, so polling and retry
    loops run instantly and timeouts are reproducible.
    """

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr("pixbin.client.time", fake)
    return fake
