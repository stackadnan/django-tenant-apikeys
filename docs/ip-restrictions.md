# Restrict API keys by IP address

A key can be limited to specific IP addresses or CIDR networks — IPv4 and
IPv6, mixed freely in the same list.

```python
instance, raw_key = OrganizationAPIKey.generate_key(
    name="Office network only",
    tenant=org,
    allowed_ips=["192.168.1.10", "10.0.0.0/8", "2001:db8::/32"],
)
```

Leave `allowed_ips` empty (the default) for no restriction — every key
created before this field existed behaves this way and keeps working
unchanged.

## How entries are validated

`generate_key()` parses every entry with Python's standard library
`ipaddress` module — `ipaddress.ip_network(entry, strict=False)` — up
front, and raises `ValueError` immediately if one doesn't parse:

```python
OrganizationAPIKey.generate_key(name="k", tenant=org, allowed_ips=["not-an-ip"])
# ValueError: 'not-an-ip' is not a valid IP address or CIDR network
```

No custom parsing — a single address (`"192.168.1.10"`) and a network in
CIDR notation (`"10.0.0.0/8"`) are both accepted, because `ip_network()`
treats a bare address as a network with a full-length mask.

## Checking a request's IP against the allowlist

```python
api_key.is_ip_allowed("192.168.1.10")  # True
api_key.is_ip_allowed("203.0.113.99")  # False, if allowed_ips is set and doesn't cover it
```

`is_ip_allowed()` is a plain model method — no request object, no framework
dependency. An empty `allowed_ips` always returns `True`. A malformed
`client_ip` (not something `ipaddress.ip_address()` can parse) always
returns `False` rather than raising.

## Resolving the client's IP from a request

```python
from django_tenant_apikeys.ip import get_client_ip

client_ip = get_client_ip(request)
```

`get_client_ip()` returns `request.META["REMOTE_ADDR"]` — the actual TCP
connection's source address — **unless** you've explicitly opted into
trusting a different header via `TENANT_API_KEY_TRUSTED_PROXY_HEADER`.

## Trusting a proxy header

If your Django app sits behind a reverse proxy or load balancer,
`REMOTE_ADDR` is the proxy's address, not the real client's — you need the
proxy to forward the original address in a header (commonly
`X-Forwarded-For`), and you need Django to read it.

```python
# settings.py
TENANT_API_KEY_TRUSTED_PROXY_HEADER = "HTTP_X_FORWARDED_FOR"
```

This is **unset by default**, and that's deliberate, not an oversight.
`X-Forwarded-For` and headers like it are ordinary HTTP request headers —
any client can set one to whatever they want. If Django trusted it
unconditionally, an attacker could set `X-Forwarded-For: 192.168.1.10`
themselves and walk straight through an IP allowlist that's supposed to
block them. Trusting the header is only safe when a proxy you control is
the one setting it, *and* stripping any client-supplied copy of that header
before your proxy adds its own — otherwise a client can still forge the
value your proxy passes through untouched.

When the setting is on, `get_client_ip()` reads only the **first** entry of
the header:

```python
# HTTP_X_FORWARDED_FOR: "198.51.100.1, 10.0.0.1, 10.0.0.2"
get_client_ip(request)  # "198.51.100.1"
```

This assumes a single trusted reverse proxy directly in front of Django,
appending the real client's address as the first (leftmost) entry. It does
**not** implement multi-hop trusted-proxy-chain validation (walking the
list from the right and trusting only entries added by known proxies,
similar to what Django's own
[`SECURE_PROXY_SSL_HEADER`](https://docs.djangoproject.com/en/stable/ref/settings/#secure-proxy-ssl-header)
handles for a different header). If you're behind more than one proxy
hop, resolve the real client IP at the edge (or in middleware you control)
and set `TENANT_API_KEY_TRUSTED_PROXY_HEADER` to a header your own
infrastructure guarantees contains only that address.

## Enforcing the restriction

### Django REST Framework

```python
from django_tenant_apikeys.permissions import HasAllowedIP, HasAPIKeyScope

class OrdersView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAllowedIP, HasAPIKeyScope]
    required_scopes = ["orders:read"]
```

A request from outside `allowed_ips` gets a 403. `HasAllowedIP` reads
`request.auth` (must be an API key instance — it returns `False` otherwise)
and calls `get_client_ip(request)` / `is_ip_allowed()` internally.

### Django Ninja

No permission-class system to hook into, so check inline — the same way
[scopes](scopes.md) already are:

```python
from django_tenant_apikeys.ip import get_client_ip

@api.get("/orders")
def list_orders(request):
    if not request.auth.is_ip_allowed(get_client_ip(request)):
        return 403, {"detail": "IP not allowed"}
    ...
```

See [Django Ninja](django-ninja.md) for how this composes with rate
limiting and scope checks in one view.

## Next

- [Rate limiting](rate-limiting.md) — the next check in the policy chain,
  after IP restriction and before scopes.
- [Security](security.md) — IP spoofing as a threat, and why trusting a
  proxy header is opt-in.
