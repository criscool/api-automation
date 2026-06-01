import uvicorn
import os
from pathlib import Path

if __name__ == "__main__":
    # 获取当前脚本所在目录
    current_dir = Path(__file__).parent
    log_config_path = current_dir / "uvicorn_loggin_config.json"

    # uvicorn 0.34 的 reload_dirs 实现陷阱（见 uvicorn/supervisors/watchfilesreload.py:64-69）：
    # 若 reload_dirs 里的目录是 CWD 的子目录（app/ 就是），它会被跳过并退化为监视整个 CWD。
    # 所以 reload_dirs=["app"] 单独写不起限制作用——必须再用 reload_excludes 把运行期
    # 写入的目录显式排除，否则 generated_tests/ uploads/ 等下的 .py 写入会触发 reload。
    exclude_candidates = [
        "generated_tests",  # AI 生成的测试脚本和 allure 报告
        "uploads",          # 上传的接口文档
        "reports",          # pytest 执行报告
        "logs",             # 运行日志
        "backups",          # 数据库备份
        "migrations",       # Aerich 迁移历史
        "api-docs",         # API 文档静态资源
    ]
    reload_excludes = []
    for sub in exclude_candidates:
        p = current_dir / sub
        if p.exists():
            reload_excludes.append(str(p))

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=9999,
        reload=True,
        reload_dirs=["app"],
        reload_excludes=reload_excludes,
        log_config=str(log_config_path) if log_config_path.exists() else None
    )
