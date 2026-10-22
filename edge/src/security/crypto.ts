/**
 * 安全模块共用的哈希与常量时间比较工具。
 *
 * 不依赖 Hono / D1，便于在 node:test 中直接做纯函数测试。
 */

function bytesToHex(buf: ArrayBuffer): string {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** sha-256 十六进制摘要 */
export async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return bytesToHex(digest);
}

/**
 * 定长十六进制字符串的常量时间比较。
 * 长度不同直接返回 false，但仍按较长一方轮询，避免明显的长度侧信道。
 */
export function timingSafeEqualHex(a: string, b: string): boolean {
  const max = Math.max(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let i = 0; i < max; i += 1) {
    const ca = a.charCodeAt(i % (a.length || 1)) || 0;
    const cb = b.charCodeAt(i % (b.length || 1)) || 0;
    diff |= ca ^ cb;
  }
  return diff === 0;
}
