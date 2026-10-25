/** HTTP 边界只返回 unknown，由所属功能校验实际需要的字段。 */
export async function requestJson(
  path: string,
  options: RequestInit = {},
): Promise<unknown> {
  const response = await fetch(`/api${path}`, options)
  if (!response.ok)
    throw new Error(`请求失败（${response.status}），请检查后端与数据库。`)
  return response.json()
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
