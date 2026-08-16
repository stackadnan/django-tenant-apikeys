"""
django-tenant-apikeys
======================

Pluggable multi-tenant API key authentication for Django, with first-class
support for Django REST Framework and Django Ninja.

This top-level package intentionally avoids importing :mod:`django.db.models`
or any Django-app internals at import time, since doing so before Django's
app registry is ready (e.g. while ``INSTALLED_APPS`` is still being
evaluated) raises ``django.core.exceptions.AppRegistryNotReady``. Import from
the relevant submodule instead, e.g. ``from django_tenant_apikeys.models
import AbstractTenantAPIKey``.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
