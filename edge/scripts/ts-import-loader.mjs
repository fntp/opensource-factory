/**
 * node:test 的极简 ESM loader：源码里的相对导入省略了 `.ts` 扩展名
 * （tsconfig moduleResolution=bundler / Wrangler 打包时可解析），
 * 但 Node 原生 strip-types 要求显式扩展名，这里仅在解析失败时补 `.ts`。
 */
export async function resolve(specifier, context, nextResolve) {
  try {
    return await nextResolve(specifier, context);
  } catch (error) {
    if (
      (specifier.startsWith('./') || specifier.startsWith('../')) &&
      !/\.[a-z]+$/i.test(specifier)
    ) {
      return nextResolve(`${specifier}.ts`, context);
    }
    throw error;
  }
}
