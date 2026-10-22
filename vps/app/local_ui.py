"""admin 静态托管（本机一体化模式，REQ-202610-0940 / M5-02）。

- 仅在 `LOCAL_MODE=true` 时注册路由；
- `LOCAL_ADMIN_DIR` 指向 admin 构建产物（默认仓库内 `admin/dist`）；
- 未知路径回退 `index.html`，支持 TanStack Router 的 SPA 路由；
- 解析后的文件必须位于构建目录内，防止路径穿越。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from app.config import Settings, get_settings

# 这些前缀属于 API / 文档，不参与 SPA 回退
_RESERVED_PREFIXES = ("api/", "local/", "docs", "redoc", "openapi.json")


def resolve_admin_dir(settings: Settings | None = None) -> Path:
    """返回 admin 构建目录（绝对路径）。"""
    current = settings or get_settings()
    if current.LOCAL_ADMIN_DIR:
        return Path(current.LOCAL_ADMIN_DIR).expanduser().resolve()
    # vps/app/local_ui.py → 仓库根目录 / admin / dist
    return (Path(__file__).resolve().parents[2] / "admin" / "dist").resolve()


def _missing_build_response(admin_dir: Path) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": "admin_build_missing",
            "detail": f"未找到 admin 构建产物：{admin_dir}/index.html",
            "hint": "运行 deploy/scripts/local-allinone.sh build 生成并复制构建产物",
        },
    )


def mount_local_ui(app: FastAPI) -> None:
    """注册 admin 静态资源与 SPA 回退（仅本机模式）。"""
    settings = get_settings()
    if not settings.LOCAL_MODE:
        return

    admin_dir = resolve_admin_dir(settings)

    def _serve(full_path: str) -> FileResponse | JSONResponse:
        if not (admin_dir / "index.html").is_file():
            return _missing_build_response(admin_dir)

        relative = full_path.strip("/")
        if relative and relative.startswith(_RESERVED_PREFIXES):
            return JSONResponse(status_code=404, content={"error": "not_found", "path": f"/{relative}"})

        target = (admin_dir / relative).resolve() if relative else admin_dir / "index.html"
        try:
            target.relative_to(admin_dir)
        except ValueError:
            return JSONResponse(status_code=404, content={"error": "not_found", "path": f"/{relative}"})

        if relative and target.is_file():
            return FileResponse(target)
        return FileResponse(admin_dir / "index.html")

    @app.get("/", include_in_schema=False)
    def local_index() -> FileResponse | JSONResponse:
        return _serve("")

    @app.get("/{full_path:path}", include_in_schema=False)
    def local_spa(full_path: str) -> FileResponse | JSONResponse:
        return _serve(full_path)
