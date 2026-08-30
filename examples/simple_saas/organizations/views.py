from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from django_tenant_apikeys.authentication import TenantAPIKeyAuthentication
from django_tenant_apikeys.permissions import HasAPIKeyScope


class WhoAmIView(APIView):
    """Shows exactly what the library resolves from a request's API key --
    the piece a real endpoint would use to scope a query to the right
    tenant."""

    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAPIKeyScope]
    required_scopes = ["whoami:read"]

    def get(self, request: Request) -> Response:
        api_key = request.auth  # the authenticated OrganizationAPIKey
        return Response(
            {
                "tenant": request.tenant.name,  # attached automatically
                "key_name": api_key.name,
                "key_prefix": api_key.prefix,
                "scopes": api_key.scopes,
            }
        )
