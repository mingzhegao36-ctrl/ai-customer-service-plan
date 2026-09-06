export type Role = 'admin' | 'member'
export type RunStatus = 'running' | 'completed' | 'cancelled' | 'failed'
export type Scenario = 'normal' | 'disconnect' | 'budget'
export interface Answer {
  id: string
  text: string
  status: RunStatus
  reason?: string
  feedback?: 'up' | 'down'
  inputTokens: number
  outputTokens: number
}
export interface Turn { id: string; question: string; answers: Answer[]; activeAnswerId?: string }
export interface Conversation {
  id: string
  title: string
  owner: Role
  updatedAt: string
  turns: Turn[]
}
export interface UsageEntry {
  id: string
  label: string
  status: 'actual' | 'unknown' | 'running'
  tokens: number
  costCents: number
  heldCents: number
  time: string
}
export interface DemoJob {
  id: string
  title: string
  type: 'export' | 'delete' | 'reconcile' | 'provider_test'
  status: 'queued' | 'running' | 'completed' | 'failed' | 'blocked'
  createdAt: string
  detail: string
  payload?: string
  sourceIds?: string[]
}
export interface AssistantVersion { id: string; prompt: string; state: 'active' | 'draft' | 'revoked'; date: string; revision?: number; deploymentId?: string }
export interface Connection {
  id?: string
  name: string
  baseUrl: string
  model: string
  tested: boolean
  status?: string
  revision?: number
  secretConfigured?: boolean
  secretHint?: string
  deploymentId?: string
  currency?: string
  inputPrice?: number
  outputPrice?: number
  maxInputTokens?: number
  maxOutputTokens?: number
  secret?: string
}
export interface ConnectionTestTicket { readonly revision: number; readonly sequence: number; readonly snapshot: Readonly<Omit<Connection, 'tested'>> }
