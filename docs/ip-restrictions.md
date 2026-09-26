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

When the setting is on, `get_client_ip()` picks one entry from the header
by counting from the **right**:

```python
# HTTP_X_FORWARDED_FOR: "192.168.1.10, 198.51.100.7"
#                        ^ sent by the client   ^ appended by your proxy
get_client_ip(request)  # "198.51.100.7"  (the default: one trusted proxy)
```

Every proxy *appends* the address of the peer it received the request
from, so anything to the **left** was written by the client (or an earlier,
untrusted hop) and is never used. Only the entries your own proxies added —
on the right — mean anything. That's why the default is the rightmost entry,
and why reading the leftmost one would let any caller who holds a stolen key
prepend an address from the allowlist.

If more than one trusted proxy sits in front of Django, say how many:

```python
# client -> CDN -> load balancer -> Django
TENANT_API_KEY_TRUSTED_PROXY_COUNT = 2   # default: 1
```

The client is then the 2nd entry from the right. If the header has fewer
entries than that (the request didn't pass through every expected proxy) or
is missing, `get_client_ip()` falls back to `REMOTE_ADDR`. A proxy that
*overwrites* the header with a single address, or a single-valued header
like `X-Real-IP`, works with the default.

A value that isn't an IP address is returned as-is and simply never matches
an allowlist entry, so a restricted key fails closed.

## Enforcing the restriction

`allowed_ips` is enforced **during authentication**, in both Django REST
Framework and Django Ninja: a key used from an address outside its
allowlist is refused with a 403 before your view (or any permission class)
runs. There is nothing to add to a view, so a view can't accept the key and
forget to check.

```python
class OrdersView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAPIKeyScope]      # no IP class needed
    required_scopes = ["orders:read"]
```

The client address comes from `get_client_ip(request)` (above). A key with
`allowed_ips` set and *no* known client address — for example calling
`TenantAPIKeyAuthentication().authenticate_credentials(raw_key)` without a
request — is refused rather than waved through. `HasAllowedIP` remains for
compatibility, but only repeats the check authentication already made; it's
deprecated.

If you use the helpers yourself: `api_key.is_ip_allowed(get_client_ip(request))`.

**Upgrading from 0.4:** before 0.5, `allowed_ips` was only checked where you
had added `HasAllowedIP` (DRF) or an inline check (Ninja). Keys with
`allowed_ips` set are now enforced everywhere, so any client calling from an
address not on the list — or every client, if you're behind a proxy and
haven't set `TENANT_API_KEY_TRUSTED_PROXY_HEADER` — starts getting 403s. Find
the affected keys first: `OrganizationAPIKey.objects.exclude(allowed_ips=[])`.

## Next

- [Rate limiting](rate-limiting.md) — the next check in the policy chain,
  after IP restriction and before scopes.
- [Security](security.md) — IP spoofing as a threat, and why trusting a
  proxy header is opt-in.
