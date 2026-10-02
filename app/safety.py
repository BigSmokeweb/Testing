import ipaddress
import socket
import urllib.parse
from typing import Tuple, List

# Cloud metadata IPs and forbidden ranges
METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),  # AWS, GCP, Azure, OpenStack
    ipaddress.ip_address("169.254.170.2"),    # AWS ECS
}


def is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> Tuple[bool, str]:
    if ip in METADATA_IPS:
        return True, "Cloud metadata IP address is forbidden."
    if ip.is_loopback:
        return True, "Loopback address is forbidden."
    if ip.is_private:
        return True, "Private network IP address is forbidden."
    if ip.is_link_local:
        return True, "Link-local IP address is forbidden."
    if ip.is_multicast:
        return True, "Multicast IP address is forbidden."
    if ip.is_reserved:
        return True, "Reserved IP address is forbidden."
    if ip.is_unspecified:
        return True, "Unspecified IP address is forbidden."
    return False, ""


def resolve_hostname_ips(hostname: str) -> List[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    ips = []
    try:
        addr_info = socket.getaddrinfo(hostname, None)
        for item in addr_info:
            sockaddr = item[4]
            ip_str = sockaddr[0]
            try:
                ips.append(ipaddress.ip_address(ip_str))
            except ValueError:
                pass
    except Exception:
        pass
    return ips


def validate_url(url: str) -> Tuple[bool, str]:
    """
    Validates a URL for SSRF protection:
    - Only http/https
    - Rejects credentials embedded in URL (user:pass@)
    - Resolves hostname (A/AAAA)
    - Rejects loopback, private, link-local, multicast, reserved, cloud metadata IPs
    Returns (is_valid, error_reason).
    """
    if not url:
        return False, "URL is empty."

    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception:
        return False, "Malformed URL."

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Scheme '{parsed.scheme}' not allowed. Only HTTP and HTTPS are permitted."

    if parsed.username or parsed.password:
        return False, "URL containing embedded credentials (user:password@) is forbidden."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL missing hostname."

    hostname = hostname.lower()

    # Direct IP literal check
    try:
        ip = ipaddress.ip_address(hostname)
        blocked, reason = is_ip_blocked(ip)
        if blocked:
            return False, reason
        return True, ""
    except ValueError:
        pass

    # Hostname resolution check
    resolved_ips = resolve_hostname_ips(hostname)
    if not resolved_ips:
        return False, f"Cannot resolve hostname '{hostname}' to an IP address."

    for ip in resolved_ips:
        blocked, reason = is_ip_blocked(ip)
        if blocked:
            return False, f"Hostname '{hostname}' resolves to forbidden IP {ip}: {reason}"

    return True, ""


async def install_request_guard(context, on_blocked_callback=None):
    """
    Playwright route guard: validates EVERY request URL including redirects.
    Aborts blocked requests and invokes on_blocked_callback(url, reason) if provided.
    """
    async def route_handler(route):
        req = route.request
        valid, reason = validate_url(req.url)
        if not valid:
            if on_blocked_callback:
                on_blocked_callback(req.url, reason)
            await route.abort()
        else:
            await route.continue_()

    await context.route("**/*", route_handler)
