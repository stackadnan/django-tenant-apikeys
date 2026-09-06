"""Tests for get_client_ip(): REMOTE_ADDR vs. the opt-in trusted proxy header."""

from __future__ import annotations

from django.test import RequestFactory, override_settings

from django_tenant_apikeys.ip import get_client_ip

_factory = RequestFactory()


class TestGetClientIp:
    def test_defaults_to_remote_addr(self) -> None:
        request = _factory.get("/", REMOTE_ADDR="203.0.113.10")
        assert get_client_ip(request) == "203.0.113.10"

    def test_ignores_forwarded_header_when_not_trusted(self) -> None:
        request = _factory.get(
            "/", REMOTE_ADDR="203.0.113.10", HTTP_X_FORWARDED_FOR="198.51.100.1"
        )
        assert get_client_ip(request) == "203.0.113.10"

    @override_settings(TENANT_API_KEY_TRUSTED_PROXY_HEADER="HTTP_X_FORWARDED_FOR")
    def test_uses_trusted_header_when_configured(self) -> None:
        request = _factory.get(
            "/", REMOTE_ADDR="203.0.113.10", HTTP_X_FORWARDED_FOR="198.51.100.1"
        )
        assert get_client_ip(request) == "198.51.100.1"

    @override_settings(TENANT_API_KEY_TRUSTED_PROXY_HEADER="HTTP_X_FORWARDED_FOR")
    def test_uses_first_entry_of_a_forwarded_chain(self) -> None:
        request = _factory.get(
            "/",
            REMOTE_ADDR="203.0.113.10",
            HTTP_X_FORWARDED_FOR="198.51.100.1, 10.0.0.1, 10.0.0.2",
        )
        assert get_client_ip(request) == "198.51.100.1"

    @override_settings(TENANT_API_KEY_TRUSTED_PROXY_HEADER="HTTP_X_FORWARDED_FOR")
    def test_falls_back_to_remote_addr_when_header_is_absent(self) -> None:
        request = _factory.get("/", REMOTE_ADDR="203.0.113.10")
        assert get_client_ip(request) == "203.0.113.10"
