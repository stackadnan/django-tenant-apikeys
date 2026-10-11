"""Proves the tenant-isolation boundary the package actually provides, and
makes explicit where responsibility shifts to the application.

``AbstractTenantAPIKey`` resolves each key to exactly one tenant and attaches
it as ``request.tenant`` (see docs/multi-tenancy.md). The package does *not*
filter any other queryset for you -- that's the documented limit of its
guarantee, not a bug. This test exercises the pattern a protected view is
expected to use (scope every lookup by ``request.tenant``, not just by a
raw primary key) and confirms that pattern actually blocks cross-tenant
access when applied. It is not a test of automatic isolation the library
never claimed to provide.
"""

from __future__ import annotations

import pytest
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from django_tenant_apikeys.authentication import TenantAPIKeyAuthentication
from django_tenant_apikeys.permissions import HasAPIKeyScope
from tests.models import Tenant, TenantAPIKey, TenantResource

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()


class ResourceDetailView(APIView):
    """The pattern every protected view needs: scope the lookup by
    ``request.tenant``, not just by the resource's primary key."""

    authentication_classes = [TenantAPIKeyAuthentication]
    # required_scopes defaults to [] -- any authenticated key is enough here;
    # it's the view's job to require specific scopes, not this test's point.
    permission_classes = [HasAPIKeyScope]

    def get(self, request: object, pk: int) -> Response:
        resource = get_object_or_404(TenantResource, pk=pk, tenant=request.tenant)  # type: ignore[attr-defined]
        return Response({"label": resource.label})


class NaiveResourceDetailView(APIView):
    """The mistake the pattern above guards against: looking a resource up
    by pk alone, trusting that an authenticated key is enough. Used only to
    show *why* the tenant filter in ``ResourceDetailView`` matters -- not an
    endorsement of this shape."""

    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAPIKeyScope]

    def get(self, request: object, pk: int) -> Response:
        resource = get_object_or_404(TenantResource, pk=pk)
        return Response({"label": resource.label})


def call(view: type[APIView], raw_key: str, pk: int) -> Response:
    request = _factory.get(f"/resources/{pk}/", HTTP_AUTHORIZATION=f"Api-Key {raw_key}")
    return view.as_view()(request, pk=pk)  # type: ignore[return-value]


@pytest.fixture
def tenant_a() -> Tenant:
    return Tenant.objects.create(name="Tenant A")


@pytest.fixture
def tenant_b() -> Tenant:
    return Tenant.objects.create(name="Tenant B")


@pytest.fixture
def key_a(tenant_a: Tenant) -> str:
    return TenantAPIKey.generate_key(name="a", tenant=tenant_a)[1]


@pytest.fixture
def key_b(tenant_b: Tenant) -> str:
    return TenantAPIKey.generate_key(name="b", tenant=tenant_b)[1]


@pytest.fixture
def resource_a(tenant_a: Tenant) -> TenantResource:
    return TenantResource.objects.create(tenant=tenant_a, label="A's secret")


@pytest.fixture
def resource_b(tenant_b: Tenant) -> TenantResource:
    return TenantResource.objects.create(tenant=tenant_b, label="B's secret")


class TestCrossTenantAccessIsBlockedByTheDocumentedPattern:
    def test_a_tenant_can_fetch_its_own_resource(
        self, key_a: str, resource_a: TenantResource
    ) -> None:
        response = call(ResourceDetailView, key_a, resource_a.pk)
        assert response.status_code == 200
        assert response.data == {"label": "A's secret"}

    def test_a_tenants_key_cannot_fetch_another_tenants_resource(
        self, key_a: str, resource_b: TenantResource
    ) -> None:
        # The core assertion this module exists for: tenant A's (valid,
        # fully-authenticated) key must not be able to read tenant B's row,
        # just because it knows (or guesses) B's primary key.
        response = call(ResourceDetailView, key_a, resource_b.pk)
        assert response.status_code == 404

    def test_the_denial_does_not_reveal_whether_the_id_exists_for_someone_else(
        self, key_a: str, resource_b: TenantResource
    ) -> None:
        # A nonexistent id and another tenant's real id must look identical:
        # both 404, not a different error that would let a caller enumerate
        # which ids belong to other tenants.
        own = call(ResourceDetailView, key_a, resource_b.pk)
        missing = call(ResourceDetailView, key_a, resource_b.pk + 10_000)
        assert own.status_code == missing.status_code == 404

    def test_an_unauthenticated_request_never_reaches_the_lookup(
        self, resource_a: TenantResource
    ) -> None:
        request = _factory.get(f"/resources/{resource_a.pk}/")
        response = ResourceDetailView.as_view()(request, pk=resource_a.pk)
        assert response.status_code == 401


class TestWhyTheTenantFilterMatters:
    """Demonstrates the failure mode the documented pattern exists to
    prevent -- a view that forgets to filter by ``request.tenant`` leaks
    across tenants despite a perfectly valid, fully-authenticated key."""

    def test_a_view_that_skips_the_tenant_filter_leaks_across_tenants(
        self, key_a: str, resource_b: TenantResource
    ) -> None:
        response = call(NaiveResourceDetailView, key_a, resource_b.pk)
        assert response.status_code == 200
        assert response.data == {"label": "B's secret"}  # the actual leak

    def test_raising_get_object_or_404_directly_without_a_view_also_isolates(
        self, tenant_a: Tenant, resource_b: TenantResource
    ) -> None:
        # Same assertion at the ORM level, without any HTTP machinery in the
        # way, to isolate what the filter itself does.
        with pytest.raises(Http404):
            get_object_or_404(TenantResource, pk=resource_b.pk, tenant=tenant_a)
