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


def install_request_guard(context, on_blocked_callback=None):
    """
    Playwright route guard: validates EVERY request URL including redirects.
    Aborts blocked requests and invokes on_blocked_callback(url, reason) if provided.
    Works with sync Playwright context.
    """
    def route_handler(route):
        req = route.request
        valid, reason = validate_url(req.url)
        if not valid:
            if on_blocked_callback:
                on_blocked_callback(req.url, reason)
            route.abort()
        else:
            route.continue_()

    context.route("**/*", route_handler)


def safe_http_fetch(
    url: str,
    method: str = "GET",
    headers: dict = None,
    cookies: dict = None,
    timeout: int = 5,
    max_redirects: int = 5,
    max_bytes: int = 100 * 1024,  # 100 KB cap
) -> Tuple[int, bytes, str]:
    """
    Safely fetches a URL via HTTP:
    - Validates target URL with validate_url before every hop
    - Manually follows up to max_redirects hops
    - Does NOT send cookies to different hostnames on redirect
    - Uses stream=True and aborts if content exceeds max_bytes
    Returns (status_code, content_bytes, final_url).
    """
    import requests
    current_url = url
    current_cookies = cookies or {}
    initial_host = urllib.parse.urlparse(url).netloc.lower()

    for hop in range(max_redirects + 1):
        safe, reason = validate_url(current_url)
        if not safe:
            raise ValueError(f"Blocked URL at hop {hop} ({current_url}): {reason}")

        current_host = urllib.parse.urlparse(current_url).netloc.lower()
        hop_cookies = current_cookies if current_host == initial_host else {}

        resp = requests.request(
            method,
            current_url,
            headers=headers or {},
            cookies=hop_cookies,
            timeout=timeout,
            allow_redirects=False,
            stream=True,
        )

        if resp.is_redirect and "Location" in resp.headers:
            if hop == max_redirects:
                raise ValueError(f"Exceeded maximum redirects ({max_redirects})")
            next_url = urllib.parse.urljoin(current_url, resp.headers["Location"])
            current_url = next_url
            continue

        # Non-redirect: stream content up to max_bytes
        content = b""
        for chunk in resp.iter_content(chunk_size=4096):
            content += chunk
            if len(content) > max_bytes:
                resp.close()
                raise ValueError(f"Response body exceeded limit of {max_bytes} bytes")

        return resp.status_code, content, current_url

    raise ValueError("Unexpected redirect termination")
