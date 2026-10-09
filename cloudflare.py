import isolation_runtime as isolated_runtime
from web_security import validate_http_url
from job_tools import run_guarded
from resource_limits import JOB_BUDGET
import hashlib
import sys
#!/usr/bin/env python3
"""
Cloudflare bypasser using Playwright
Handles JS challenge and returns session with cookies
"""
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any

class CloudflareBypasser:
    def __init__(self, headless: bool = True):
        isolated_runtime.require_isolation()
        self.headless = headless
        self.browser = None
        self.context = None
        self.cache_dir = Path("/runtime/cache/cloudflare")
        self.cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    
    def _get_cache_path(self, domain: str) -> Path:
        return self.cache_dir / (hashlib.sha256(domain.encode()).hexdigest()+".json")
    
    def _is_cache_valid(self, domain: str, max_age: int = 3600) -> bool:
        """Check if cached cookies are still valid (less than max_age seconds old)"""
        cache_path = self._get_cache_path(domain)
        if not cache_path.exists():
            return False
        
        try:
            with open(cache_path) as f:
                data = json.load(f)
            
            # Check timestamp
            if time.time() - data.get("timestamp", 0) > max_age:
                return False
            
            # Check if cookies exist
            if not data.get("cookies"):
                return False
            
            return True
        except Exception:
            return False
    
    def _save_cache(self, domain: str, cookies: list, user_agent: str):
        """Save cookies to cache"""
        cache_path = self._get_cache_path(domain)
        with open(cache_path, 'w') as f:
            json.dump({
                "timestamp": time.time(),
                "domain": domain,
                "cookies": cookies,
                "user_agent": user_agent
            }, f)
    
    def _load_cache(self, domain: str) -> Optional[Dict[str, Any]]:
        """Load cookies from cache"""
        cache_path = self._get_cache_path(domain)
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path) as f:
                return json.load(f)
        except Exception:
            return None
    
    async def _create_browser(self):
        """Create playwright browser"""
        from playwright.async_api import async_playwright
        
        p = await async_playwright().start()
        options = isolated_runtime.browser_options()
        options['headless'] = self.headless
        self.browser = await p.chromium.launch(**options)
        return p
    
    async def bypass(self, url: str, timeout: int = 30):
        url = validate_http_url(url)
        lease = JOB_BUDGET.reserve()
        try:
            command = [sys.executable, str(Path(__file__).resolve()), '--worker', url, str(min(timeout, 45))]
            if not self.headless:
                command.append('--headed')
            result = await asyncio.to_thread(run_guarded, command, seconds=60)
            return json.loads(result.stdout) if result.returncode == 0 else None
        finally:
            JOB_BUDGET.release(lease)

    async def _bypass_browser(self, url: str, timeout: int = 30) -> Optional[Dict[str, Any]]:
        """
        Bypass Cloudflare challenge and return cookies + user agent
        """
        from urllib.parse import urlparse
        url = validate_http_url(url)
        parsed = urlparse(url)
        domain = parsed.hostname
        
        # Check cache first
        if self._is_cache_valid(domain):
            print(f"[Cloudflare] Using cached cookies for {domain}")
            return self._load_cache(domain)
        
        print(f"[Cloudflare] Bypassing challenge for {domain}")
        
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                options = isolated_runtime.browser_options()
                options['headless'] = self.headless
                browser = await p.chromium.launch(**options)
                
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Playwright) AppleWebKit/537.36'
                )
                
                page = await context.new_page()
                
                # Track if Cloudflare challenge appeared
                challenge_detected = False
                
                async def handle_response(response):
                    nonlocal challenge_detected
                    if 'cloudflare' in response.url.lower():
                        if response.status in [403, 429]:
                            challenge_detected = True
                
                page.on("response", handle_response)
                
                # Navigate to URL
                try:
                    await page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
                except Exception as e:
                    print(f"[Cloudflare] Navigation error: {e}")
                    await browser.close()
                    return None
                
                # Wait for potential JS challenge
                await asyncio.sleep(3)
                
                # Check if we're on a Cloudflare challenge page
                title = await page.title()
                content = await page.content()
                
                if 'cloudflare' in title.lower() or 'cloudflare' in content.lower()[:1000]:
                    print(f"[Cloudflare] Detected challenge, waiting...")
                    # Wait for challenge to complete (up to timeout)
                    for _ in range(timeout // 2):
                        await asyncio.sleep(2)
                        content = await page.content()
                        if 'cloudflare' not in content.lower()[:500]:
                            break
                
                # Get cookies
                cookies = await context.cookies([page.url])
                user_agent = await context.tracking_protection.get_analytics_context() if hasattr(context, 'tracking_protection') else None
                
                if not user_agent:
                    user_agent = await page.evaluate("() => navigator.userAgent")
                
                # Save to cache
                result = {
                    "cookies": cookies,
                    "user_agent": user_agent,
                    "domain": domain
                }
                self._save_cache(domain, cookies, user_agent)
                
                await browser.close()
                
                print(f"[Cloudflare] Successfully bypassed, got {len(cookies)} cookies")
                return result
                
        except Exception as e:
            print(f"[Cloudflare] Bypass error: {e}")
            return None
    
    def get_session(self, url: str) -> Optional[Dict[str, Any]]:
        """Synchronous wrapper"""
        return asyncio.run(self.bypass(url))


def get_bypassed_session(url: str, timeout: int = 30) -> Optional[Dict[str, Any]]:
    """
    Main entry point - get a session with Cloudflare cookies
    Returns dict with 'cookies' and 'user_agent'
    """
    bypasser = CloudflareBypasser(headless=True)
    return bypasser.get_session(url)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--headed', action='store_true')
    parser.add_argument('url')
    parser.add_argument('timeout', type=int, nargs='?', default=30)
    arguments = parser.parse_args()
    bypasser = CloudflareBypasser(headless=not arguments.headed)
    if arguments.worker:
        async def perform():
            return await bypasser._bypass_browser(arguments.url, max(1, min(arguments.timeout, 45)))
        # Diagnostics stay on stderr; stdout carries only bounded JSON.
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):
            result = asyncio.run(perform())
        serialized = json.dumps(result)
        if len(serialized.encode()) > 65536:
            sys.exit(1)
        print(serialized)
    else:
        print(json.dumps(asyncio.run(bypasser.bypass(arguments.url, arguments.timeout))))
