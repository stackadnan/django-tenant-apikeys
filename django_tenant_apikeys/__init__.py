"""Multi-tenant API key authentication for Django.

No Django imports here on purpose -- this module can get imported before
the app registry is ready. Pull from the actual submodule instead, e.g.
``from django_tenant_apikeys.models import AbstractTenantAPIKey``.
"""

from __future__ import annotations

__version__ = "0.3.0"

__all__ = ["__version__"]
