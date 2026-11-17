"""
A DNS outage must never be mistaken for "this domain has no mail server".
(On 17 Nov one did, and marked a whole run's 229 leads Invalid.)
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import dns.resolver  # noqa: E402

from fixgenie.common import network  # noqa: E402
from fixgenie.common.models import EmailStatus, Lead  # noqa: E402
from fixgenie.validation import validators  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    validators._mx_cache.clear()
    validators._control_checked_at = 0.0
    monkeypatch.setattr(validators, "_control_checked_at", 0.0)
    monkeypatch.setattr("time.sleep", lambda s: None)


def _resolver(behaviour):
    """behaviour(domain) -> list of answers, or raises."""
    def resolve(domain, rtype, lifetime=None):
        return behaviour(domain)
    return resolve


def _lead(email="jane@acme-plumbing.com"):
    return Lead(business_name="Acme Plumbing", email=email)


def test_dns_down_leaves_lead_unknown_and_deferred(monkeypatch):
    def down(domain):
        raise dns.resolver.LifetimeTimeout(timeout=8)
    monkeypatch.setattr(dns.resolver, "resolve", _resolver(down))

    out = validators.validate_leads([_lead()], on_lead=lambda l: pytest.fail("must not store"))
    assert out == []


def test_offline_nxdomain_is_not_trusted(monkeypatch):
    # Some VPN/hotspot setups answer NXDOMAIN for everything while offline:
    # the control domain fails too, so the result must stay inconclusive.
    def all_nx(domain):
        raise dns.resolver.NXDOMAIN()
    monkeypatch.setattr(dns.resolver, "resolve", _resolver(all_nx))

    lead = _lead()
    assert validators.validate_email(lead) is False
    assert lead.email_status == EmailStatus.UNKNOWN.value


def test_real_nxdomain_with_healthy_dns_is_invalid(monkeypatch):
    def only_lead_missing(domain):
        if domain == validators._CONTROL_DOMAIN:
            return ["gmail-smtp-in.l.google.com"]
        raise dns.resolver.NXDOMAIN()
    monkeypatch.setattr(dns.resolver, "resolve", _resolver(only_lead_missing))

    lead = _lead()
    assert validators.validate_email(lead) is True
    assert lead.email_status == EmailStatus.INVALID.value
    assert "no MX record" in lead.notes


def test_blip_then_recovery_is_valid(monkeypatch):
    calls = {"n": 0}

    def flaky(domain):
        calls["n"] += 1
        if calls["n"] == 1:
            raise dns.resolver.NoNameservers()
        return ["mx.acme-plumbing.com"]
    monkeypatch.setattr(dns.resolver, "resolve", _resolver(flaky))

    stored = []
    out = validators.validate_leads([_lead()], on_lead=stored.append)
    assert [l.email_status for l in out] == [EmailStatus.VALID.value]
    assert stored == out


def test_inconclusive_lookup_is_not_cached(monkeypatch):
    state = {"up": False}

    def maybe(domain):
        if not state["up"]:
            raise dns.resolver.LifetimeTimeout(timeout=8)
        return ["mx.acme-plumbing.com"]
    monkeypatch.setattr(dns.resolver, "resolve", _resolver(maybe))

    assert validators._has_mx("acme-plumbing.com") is None
    state["up"] = True
    assert validators._has_mx("acme-plumbing.com") is True


def test_wait_for_network_returns_when_dns_recovers(monkeypatch):
    results = iter([False, False, True])
    monkeypatch.setattr(network, "is_online", lambda hosts: next(results))
    assert network.wait_for_network(("example.com",), max_wait=60, interval=0, log=lambda m: None)


def test_wait_for_network_gives_up(monkeypatch):
    def fail(host, port):
        raise socket.gaierror(11001, "getaddrinfo failed")
    monkeypatch.setattr(socket, "getaddrinfo", fail)
    assert not network.wait_for_network(("example.com",), max_wait=0, interval=0, log=lambda m: None)
