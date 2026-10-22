/**
 * 技术栈框架词表（M6-04 技术栈图谱）。
 *
 * 说明：
 * - 只收录「框架 / 库 / 基础设施」等可作为技术栈标签的名称，不收录编程语言
 *   （语言由仓库 `language` 字段单独聚合）；
 * - `aliases` 用于标签精确匹配与摘要文本的启发式识别，全部小写；
 * - 词表顺序同时作为同权重框架的稳定排序依据，新增条目请追加到对应分类末尾。
 */
export interface FrameworkSpec {
  name: string;
  category: string;
  aliases: readonly string[];
}

export const FRAMEWORK_CATALOG: readonly FrameworkSpec[] = [
  // 前端
  { name: 'React', category: '前端', aliases: ['react', 'react.js', 'reactjs'] },
  { name: 'Vue', category: '前端', aliases: ['vue', 'vue.js', 'vuejs'] },
  { name: 'Next.js', category: '前端', aliases: ['next.js', 'nextjs', 'next js'] },
  { name: 'Nuxt', category: '前端', aliases: ['nuxt', 'nuxt.js', 'nuxtjs'] },
  { name: 'Angular', category: '前端', aliases: ['angular', 'angular.js', 'angularjs'] },
  { name: 'Svelte', category: '前端', aliases: ['svelte', 'sveltekit'] },
  { name: 'Solid', category: '前端', aliases: ['solidjs', 'solid.js'] },
  { name: 'Astro', category: '前端', aliases: ['astro'] },
  { name: 'Remix', category: '前端', aliases: ['remix'] },
  { name: 'Tailwind CSS', category: '前端', aliases: ['tailwind', 'tailwindcss', 'tailwind css'] },
  { name: 'shadcn/ui', category: '前端', aliases: ['shadcn', 'shadcn/ui', 'shadcn ui'] },

  // 后端
  { name: 'Node.js', category: '后端', aliases: ['node.js', 'nodejs', 'node js'] },
  { name: 'Express', category: '后端', aliases: ['express', 'express.js', 'expressjs'] },
  { name: 'NestJS', category: '后端', aliases: ['nestjs', 'nest.js', 'nest js'] },
  { name: 'Koa', category: '后端', aliases: ['koa', 'koa.js', 'koajs'] },
  { name: 'Django', category: '后端', aliases: ['django'] },
  { name: 'Flask', category: '后端', aliases: ['flask'] },
  { name: 'FastAPI', category: '后端', aliases: ['fastapi'] },
  { name: 'Spring', category: '后端', aliases: ['spring', 'spring boot', 'springboot'] },
  { name: 'Laravel', category: '后端', aliases: ['laravel'] },
  { name: 'Rails', category: '后端', aliases: ['rails', 'ruby on rails'] },
  { name: '.NET', category: '后端', aliases: ['.net', 'dotnet', 'asp.net'] },
  { name: 'Gin', category: '后端', aliases: ['gin-gonic', 'gin framework'] },
  { name: 'Actix', category: '后端', aliases: ['actix', 'actix-web'] },
  { name: 'Axum', category: '后端', aliases: ['axum'] },

  // 数据库 / 中间件
  { name: 'PostgreSQL', category: '数据库', aliases: ['postgresql', 'postgres', 'pgsql'] },
  { name: 'MySQL', category: '数据库', aliases: ['mysql'] },
  { name: 'SQLite', category: '数据库', aliases: ['sqlite', 'sqlite3'] },
  { name: 'MongoDB', category: '数据库', aliases: ['mongodb', 'mongo'] },
  { name: 'Redis', category: '数据库', aliases: ['redis'] },
  { name: 'Elasticsearch', category: '数据库', aliases: ['elasticsearch', 'elastic search'] },
  { name: 'ClickHouse', category: '数据库', aliases: ['clickhouse'] },
  { name: 'Kafka', category: '数据库', aliases: ['kafka'] },
  { name: 'RabbitMQ', category: '数据库', aliases: ['rabbitmq'] },
  { name: 'GraphQL', category: '数据库', aliases: ['graphql'] },
  { name: 'gRPC', category: '数据库', aliases: ['grpc'] },
  { name: 'WebSocket', category: '数据库', aliases: ['websocket', 'web socket'] },

  // AI / 数据
  { name: 'TensorFlow', category: 'AI/数据', aliases: ['tensorflow', 'tensor flow'] },
  { name: 'PyTorch', category: 'AI/数据', aliases: ['pytorch', 'torch'] },
  { name: 'LangChain', category: 'AI/数据', aliases: ['langchain'] },
  { name: 'LlamaIndex', category: 'AI/数据', aliases: ['llamaindex', 'llama index'] },
  { name: 'Transformers', category: 'AI/数据', aliases: ['transformers', 'huggingface transformers'] },
  { name: 'Hugging Face', category: 'AI/数据', aliases: ['hugging face', 'huggingface'] },
  { name: 'Ollama', category: 'AI/数据', aliases: ['ollama'] },
  { name: 'vLLM', category: 'AI/数据', aliases: ['vllm'] },
  { name: 'OpenCV', category: 'AI/数据', aliases: ['opencv'] },

  // 移动端 / 桌面端
  { name: 'Flutter', category: '移动端', aliases: ['flutter'] },
  { name: 'React Native', category: '移动端', aliases: ['react native', 'react-native'] },
  { name: 'Electron', category: '桌面端', aliases: ['electron', 'electron.js'] },
  { name: 'Tauri', category: '桌面端', aliases: ['tauri'] },

  // DevOps / 云服务
  { name: 'Docker', category: 'DevOps', aliases: ['docker'] },
  { name: 'Kubernetes', category: 'DevOps', aliases: ['kubernetes', 'k8s'] },
  { name: 'Terraform', category: 'DevOps', aliases: ['terraform'] },
  { name: 'Ansible', category: 'DevOps', aliases: ['ansible'] },
  { name: 'Nginx', category: 'DevOps', aliases: ['nginx'] },
  { name: 'Prometheus', category: 'DevOps', aliases: ['prometheus'] },
  { name: 'Grafana', category: 'DevOps', aliases: ['grafana'] },
  { name: 'OpenTelemetry', category: 'DevOps', aliases: ['opentelemetry', 'open telemetry'] },
  { name: 'Sentry', category: 'DevOps', aliases: ['sentry'] },
  { name: 'Supabase', category: '云服务', aliases: ['supabase'] },
  { name: 'Firebase', category: '云服务', aliases: ['firebase'] },
  { name: 'Stripe', category: '云服务', aliases: ['stripe'] },

  // 测试 / 工具链
  { name: 'Jest', category: '测试', aliases: ['jest'] },
  { name: 'Vitest', category: '测试', aliases: ['vitest'] },
  { name: 'Playwright', category: '测试', aliases: ['playwright'] },
  { name: 'Cypress', category: '测试', aliases: ['cypress'] },
  { name: 'Storybook', category: '测试', aliases: ['storybook'] },
  { name: 'Prisma', category: '工具链', aliases: ['prisma'] },
  { name: 'Drizzle ORM', category: '工具链', aliases: ['drizzle', 'drizzle orm'] },
  { name: 'SQLAlchemy', category: '工具链', aliases: ['sqlalchemy'] },
  { name: 'Celery', category: '工具链', aliases: ['celery'] },
  { name: 'Pydantic', category: '工具链', aliases: ['pydantic'] },
  { name: 'Vite', category: '工具链', aliases: ['vite', 'vite.js', 'vitejs'] },
  { name: 'Webpack', category: '工具链', aliases: ['webpack'] },
  { name: 'Rollup', category: '工具链', aliases: ['rollup'] },
  { name: 'Turborepo', category: '工具链', aliases: ['turborepo', 'turbo repo'] },
  { name: 'pnpm', category: '工具链', aliases: ['pnpm'] },
];
