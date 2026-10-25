export interface HealthResponse {
  status: 'ok'
}

/** 校验服务返回值，再将健康状态交给页面。 */
export async function getHealth(signal: AbortSignal): Promise<HealthResponse> {
  const response = await fetch('/api/health', { signal })

  if (!response.ok) {
    throw new Error(`健康检查失败（HTTP ${response.status}）`)
  }

  const body: unknown = await response.json()

  if (
    typeof body !== 'object' ||
    body === null ||
    !('status' in body) ||
    body.status !== 'ok'
  ) {
    throw new Error('健康接口返回了不符合约定的数据')
  }

  return { status: body.status }
}
