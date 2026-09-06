import path from 'node:path'
import os from 'node:os'

const database = (name: string) => `sqlite+aiosqlite:///${path.join(os.tmpdir(), name).replace(/\\/g, '/')}`

export const liveBackendEnv = {
  AI_CS_APP_ENV: 'development',
  AI_CS_DATABASE_URL: database('live-business.db'),
  AI_CS_JOURNAL_DATABASE_URL: database('live-journal.db'),
  AI_CS_SECRET_KEY: 'frontend-live-e2e-secret-key-at-least-32-characters',
  AI_CS_AUTO_CREATE_SCHEMA: 'true',
  AI_CS_BOOTSTRAP_ENABLED: 'true',
  AI_CS_BOOTSTRAP_ADMIN_PASSWORD: 'frontend-live-password',
  AI_CS_ALLOWED_ORIGINS: '["http://127.0.0.1:5175"]',
  AI_CS_API_ORIGIN: 'http://127.0.0.1:8001',
  AI_CS_PROVIDER_ALLOWED_HOSTS: '["127.0.0.1"]',
  AI_CS_PROVIDER_ALLOW_HTTP_FOR_LOCAL_TESTING: 'true',
  AI_CS_PROVIDER_KEY_ENCRYPTION_KEY: '4kU0RkljzFoedp3-CzIrglE-U0cdLHUYUhW3QEkmZTM=',
}
