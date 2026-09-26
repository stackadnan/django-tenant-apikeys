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
    def test_client_supplied_leading_entries_are_never_trusted(self) -> None:
        # A client can send any X-Forwarded-For it likes; a trusted proxy
        # *appends* the real peer address to the right. With one trusted
        # proxy the rightmost entry is the only one that proxy vouches for.
        request = _factory.get(
            "/",
            REMOTE_ADDR="10.0.0.1",
            HTTP_X_FORWARDED_FOR="192.168.1.10, 198.51.100.7",
        )
        assert get_client_ip(request) == "198.51.100.7"

    @override_settings(
        TENANT_API_KEY_TRUSTED_PROXY_HEADER="HTTP_X_FORWARDED_FOR",
        TENANT_API_KEY_TRUSTED_PROXY_COUNT=2,
    )
    def test_proxy_count_selects_the_nth_entry_from_the_right(self) -> None:
        # client -> CDN -> load balancer -> Django: the load balancer appended
        # the CDN's address, the CDN appended the real client's.
        request = _factory.get(
            "/",
            REMOTE_ADDR="10.0.0.2",
            HTTP_X_FORWARDED_FOR="203.0.113.99, 198.51.100.7, 10.0.0.1",
        )
        assert get_client_ip(request) == "198.51.100.7"

    @override_settings(
        TENANT_API_KEY_TRUSTED_PROXY_HEADER="HTTP_X_FORWARDED_FOR",
        TENANT_API_KEY_TRUSTED_PROXY_COUNT=3,
    )
    def test_header_shorter_than_proxy_count_falls_back_to_remote_addr(self) -> None:
        request = _factory.get(
            "/", REMOTE_ADDR="10.0.0.2", HTTP_X_FORWARDED_FOR="198.51.100.7, 10.0.0.1"
        )
        assert get_client_ip(request) == "10.0.0.2"

    @override_settings(
        TENANT_API_KEY_TRUSTED_PROXY_HEADER="HTTP_X_FORWARDED_FOR",
        TENANT_API_KEY_TRUSTED_PROXY_COUNT=0,
    )
    def test_non_positive_proxy_count_falls_back_to_remote_addr(self) -> None:
        request = _factory.get(
            "/", REMOTE_ADDR="10.0.0.2", HTTP_X_FORWARDED_FOR="198.51.100.7"
        )
        assert get_client_ip(request) == "10.0.0.2"

    @override_settings(TENANT_API_KEY_TRUSTED_PROXY_HEADER="HTTP_X_FORWARDED_FOR")
    def test_malformed_entry_is_returned_as_is_for_the_ip_check_to_reject(self) -> None:
        request = _factory.get(
            "/", REMOTE_ADDR="10.0.0.2", HTTP_X_FORWARDED_FOR="198.51.100.7, not-an-ip"
        )
        assert get_client_ip(request) == "not-an-ip"

    @override_settings(TENANT_API_KEY_TRUSTED_PROXY_HEADER="HTTP_X_REAL_IP")
    def test_single_valued_header_works_with_the_default_count(self) -> None:
        request = _factory.get("/", REMOTE_ADDR="10.0.0.2", HTTP_X_REAL_IP="198.51.100.7")
        assert get_client_ip(request) == "198.51.100.7"

    @override_settings(TENANT_API_KEY_TRUSTED_PROXY_HEADER="HTTP_X_FORWARDED_FOR")
    def test_falls_back_to_remote_addr_when_header_is_absent(self) -> None:
        request = _factory.get("/", REMOTE_ADDR="203.0.113.10")
        assert get_client_ip(request) == "203.0.113.10"
