/**
 * 技术栈图谱路由（M6-04）。
 *
 * GET /api/tech-stack
 * 当前登录用户收藏仓库的语言 / 框架聚合 + 语言 × 框架关系图。
 * 数据全部来自 D1（my_repositories / repo_tags / tags），不依赖 VPS。
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';
import { all } from '../db';
import {
  buildTechStackGraph,
  type TechStackRepoRow,
  type TechStackTagRow,
} from '../tech-stack/aggregate';

const techStack = new Hono<{ Bindings: Env; Variables: Variables }>();

techStack.get('/', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const repos = await all<TechStackRepoRow>(
    c.env.DB,
    `SELECT id, name, language, stars, description, readme_summary
       FROM my_repositories
      WHERE user_id = ?`,
    [user.id]
  );

  const tags = await all<TechStackTagRow>(
    c.env.DB,
    `SELECT rt.repo_id, t.name
       FROM repo_tags rt
       JOIN tags t ON t.id = rt.tag_id
       JOIN my_repositories r ON r.id = rt.repo_id
      WHERE r.user_id = ?`,
    [user.id]
  );

  return c.json(buildTechStackGraph(repos, tags));
});

export default techStack;
