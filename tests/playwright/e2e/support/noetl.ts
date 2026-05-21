import { execFileSync } from 'child_process';
import path from 'path';
import { test } from '@playwright/test';

export const NOETL_HOST = process.env.NOETL_HOST ?? 'localhost';
export const NOETL_PORT = process.env.NOETL_PORT ?? '8082';
export const NOETL_API_BASE_URL =
    process.env.NOETL_API_BASE_URL ?? `http://${NOETL_HOST}:${NOETL_PORT}`;
export const NOETL_UI_BASE_URL =
    process.env.NOETL_UI_BASE_URL ?? process.env.NOETL_BASE_URL ?? 'http://localhost:30080';

const REPO_ROOT = path.resolve(process.cwd(), '..', '..');

export function skipUnlessUiE2EEnabled(): void {
    test.skip(
        process.env.NOETL_RUN_UI_E2E !== '1',
        'NoETL UI E2E requires the gateway/UI service; set NOETL_RUN_UI_E2E=1 and NOETL_UI_BASE_URL.'
    );
}

export function registerPlaybook(playbookPath: string): void {
    const resolvedPath = path.isAbsolute(playbookPath)
        ? playbookPath
        : path.resolve(REPO_ROOT, playbookPath);

    execFileSync(
        'noetl',
        ['--host', NOETL_HOST, '--port', NOETL_PORT, 'register', 'playbook', '--file', resolvedPath],
        { stdio: 'inherit' }
    );
}
