import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';

export function launchOptions() {
  const settings = JSON.parse(execFileSync('/usr/local/bin/python', ['-c',
    'import json,isolation_runtime;print(json.dumps(isolation_runtime.browser_options()))'],
    { cwd: dirname(fileURLToPath(import.meta.url)), maxBuffer: 8192, timeout: 5000 }).toString());
  return {headless: settings.headless, channel: settings.channel,
    chromiumSandbox: settings.chromium_sandbox, proxy: settings.proxy, args: settings.args};
}
