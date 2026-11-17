"""
Brevo sends retry only when the email can't have left: a connection that never
opened. A timeout or mid-request drop may already have sent it, so no retry.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests
from urllib3.exceptions import MaxRetryError, NameResolutionError, ProtocolError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fixgenie.common import network  # noqa: E402
from fixgenie.outreach import senders  # noqa: E402


class _Resp:
    status_code = 201

    def json(self):
        return {"messageId": "<abc@brevo>"}


def _dns_error():
    cause = NameResolutionError("api.brevo.com", None, "getaddrinfo failed")
    return requests.ConnectionError(MaxRetryError(None, "/v3/smtp/email", reason=cause))


@pytest.fixture
def sender(monkeypatch):
    monkeypatch.setattr(network, "wait_for_network", lambda *a, **k: True)
    return senders.BrevoSender("key", "FixGenie", "hi@fixgenie.co")


def _post_sequence(monkeypatch, outcomes):
    calls = []

    def post(*a, **k):
        calls.append(1)
        out = outcomes[len(calls) - 1]
        if isinstance(out, Exception):
            raise out
        return out
    monkeypatch.setattr(senders.requests, "post", post)
    return calls


def test_dns_failure_is_retried_and_sent(monkeypatch, sender):
    calls = _post_sequence(monkeypatch, [_dns_error(), _Resp()])
    ok, detail = sender.send("a@b.com", "A", "s", "t", "h")
    assert ok and detail == "<abc@brevo>"
    assert len(calls) == 2


def test_timeout_is_not_retried(monkeypatch, sender):
    calls = _post_sequence(monkeypatch, [requests.ReadTimeout("read timed out"), _Resp()])
    ok, _ = sender.send("a@b.com", "A", "s", "t", "h")
    assert not ok
    assert len(calls) == 1


def test_dropped_mid_request_is_not_retried(monkeypatch, sender):
    dropped = requests.ConnectionError(ProtocolError("Connection aborted.", ConnectionResetError()))
    calls = _post_sequence(monkeypatch, [dropped, _Resp()])
    ok, _ = sender.send("a@b.com", "A", "s", "t", "h")
    assert not ok
    assert len(calls) == 1


def test_gives_up_after_three_dns_failures(monkeypatch, sender):
    calls = _post_sequence(monkeypatch, [_dns_error(), _dns_error(), _dns_error()])
    ok, detail = sender.send("a@b.com", "A", "s", "t", "h")
    assert not ok and "Brevo request failed" in detail
    assert len(calls) == 3
