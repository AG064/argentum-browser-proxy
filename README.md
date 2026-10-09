# Argentum Browser Proxy

Authenticated public-web browsing, media extraction and H.264/AAC HLS for PS4 through a bounded Linux deployment.

## Start

Use Linux Docker Engine with Compose, cgroup v2 and a kernel supporting Chromium user namespaces. Generate private credentials for the host name or LAN IP you will open:

```bash
python3 deploy/bootstrap.py --host YOUR_LAN_IP
ARGENTUM_BIND_IP=YOUR_LAN_IP docker compose up -d --build
```

Read the access code from the ignored deploy/private/access-code file. Trust the generated TLS certificate on your client or replace the certificate/key with a trusted certificate, then sign in at https://YOUR_LAN_IP:8765/login. Setup preserves existing files and prints no credential. Raw Python servers and helpers fail closed without the verified worker boundary.

Port 8765 serves the main browser, 8767 the standalone browser, and 8788 the stream API. Published ports bind only to 127.0.0.1 unless ARGENTUM_BIND_IP is explicitly set. All access-code holders share one deployment. Native forms and HLS clients use Secure, HttpOnly, SameSiteStrict cookies lasting eight hours.

## Network boundary

The worker installs default-deny IPv4/IPv6 firewalls before starting services. New connections can reach only the fixed egress broker TCP port. Direct TCP, UDP, DNS, host gateways and proxy fallback are blocked. The only loopback fetch listener is a capability-protected per-job media transport; other loopback services remain blocked. Services run as UID 10001 without capabilities or new privileges; Chromium sandboxing remains enabled.

At each connection the broker validates all DNS answers, rejects non-public/mixed/scoped/transition addresses, and connects the exact numeric peer through an external route. Host addresses, connected subnets and specific routes are rejected; only the external default route is permitted. HTTP forwarding and HTTPS CONNECT preserve bodies, Range and signed queries. Redirects, browser subrequests and FFmpeg secondary fetches cross this boundary. Public HTTP port 80 and HTTPS port 443 are supported. ARGENTUM_EGRESS_DENY_CIDRS can add exclusions for public ranges belonging to an operator's private deployment.

A separate capability-protected connector queries the fixed host SearXNG search endpoint, bounds its JSON response and follows no redirects. It creates no general private-URL exception. Browsing localhost URLs is rejected.

Upstream documents use an opaque sandbox and URL-bound fetch capabilities. Native forms and rewritten resources work without management authority. Capabilities last at most five minutes, and descendants cannot renew that expiry. The browser's own Play video button uses reported media URLs that the worker validates. Submitted bodies are limited to 32 MiB and decoded responses to 64 MiB.

## Resources and cleanup

Expensive requests share two active/preparing slots and six active/retained records. Browser helpers and extraction have deadlines and bounded output capture. FFmpeg uses bounded codec threads. All its network inputs pass through the private per-job media transport, whose HTTP client verifies TLS and preserves Secure, host-only, domain and path scope across redirects; FFmpeg does not receive cookie credentials. Playlist resources are rewritten through that same transport. Signed media URLs are not decoded twice.

The worker has hard aggregate limits of two CPUs, 1536 MiB memory with no swap, 256 PIDs and 1024 file descriptors. Its root filesystem is read-only. Writable runtime, temporary and shared-memory mounts are separately bounded at 256, 64 and 128 MiB, with inode caps. Broker/gateway resources and Docker logs are also bounded. Runtime checks reject missing limits.

Job supervisors adopt and kill detached descendants. Server or supervisor failure exits the worker PID namespace. Stop and rollback retain ownership until termination and output cleanup are confirmed. Successful final HLS output remains for two minutes. Jobs also have a four-hour watchdog and observed 128 MiB output threshold, in addition to the hard mount quota. Playlists retain no-cache headers and segments retain Range support.

## Dependencies and verification

Docker bases are pinned by digest. The worker bundles Node 22 and Python 3.12. Node/Python Playwright share release 1.63.0 and the matching full Chromium. Waitress 3.0.2 serves the applications. Python bounds are not a complete transitive lockfile; rebuild against updated security packages and run the audits.

The vendored [Playwright seccomp policy](https://github.com/microsoft/playwright/blob/v1.63.0/utils/docker/seccomp_profile.json) permits pidfd operations for supervision and chroot for Chromium's user-namespace sandbox while retaining the default-deny syscall policy. The service holds no capabilities in the container namespace. Host IPC, SYS_ADMIN, disabled browser sandboxing and direct-network fallback are not used.

CI validates source/policy controls and the production images against offline DNS, HTTP, TLS and media fixtures. Physical PS4 playback and real provider availability remain deployment checks.
