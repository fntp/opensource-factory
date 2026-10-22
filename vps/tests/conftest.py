"""pytest 全局配置：在导入任何 app 模块之前设置测试环境变量。

约束：测试不访问网络 —— GitHub token 置空（同步任务直接跳过）、
Ollama 地址置空（摘要不发起请求）、数据库指向临时目录。
"""
from __future__ import annotations

import os
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="opensource-factory-tests-")

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'test.db')}"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ["GITHUB_TOKEN"] = ""
os.environ["INTERNAL_TOKEN"] = ""
os.environ["OLLAMA_BASE_URL"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""

# 本机一体化模式（M5-02）：测试默认开启，静态目录指向临时目录
os.environ["LOCAL_MODE"] = "1"
os.environ["LOCAL_USER_ID"] = "local-test"
os.environ["LOCAL_USER_LOGIN"] = "local-test"
os.environ["LOCAL_USER_NAME"] = "本机测试用户"
os.environ["LOCAL_ADMIN_DIR"] = os.path.join(_TMP_DIR, "admin")
os.environ["EMBEDDING_FORCE_FALLBACK"] = "1"
os.environ["VECTORIZE_AUTO"] = "0"  # 测试中不自动入队，避免任务互相干扰
# 默认关闭静默窗口，保证任务测试不受运行时刻影响；静默相关用例显式构造 Settings。
os.environ["PUSH_QUIET_HOURS_START"] = ""
os.environ["PUSH_QUIET_HOURS_END"] = ""
