/** HTTP 边界只返回 unknown，由所属功能校验实际需要的字段。 */
export async function requestJson(
  path: string,
  options: RequestInit = {},
): Promise<unknown> {
  const response = await fetch(`/api${path}`, options)
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    if (isRecord(body) && typeof body.message === 'string')
      throw new Error(body.message)
    if (response.status === 422) throw new Error('请检查填写内容和图片格式。')
    throw new Error(`请求失败（${response.status}），请检查后端与数据库。`)
  }
  return response.json()
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
