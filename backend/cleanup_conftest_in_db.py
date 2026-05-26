"""
一次性清理：删除 test_scripts 表里因 Task 17 误入的 conftest.py 记录。

用法（backend/ 下）：
    python cleanup_conftest_in_db.py            # dry-run，仅打印将删除的记录
    python cleanup_conftest_in_db.py --apply    # 真正删除

判定条件：file_name='conftest.py' 或 name='conftest.py' 或 file_path 以 conftest.py 结尾。
"""
import asyncio
import sys

from tortoise import Tortoise

from app.settings import TORTOISE_ORM
from app.models.api_automation import TestScript


async def main(apply: bool) -> None:
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        from tortoise.expressions import Q

        qs = TestScript.filter(
            Q(file_name="conftest.py")
            | Q(name="conftest.py")
            | Q(file_path__endswith="conftest.py")
        )
        records = await qs.all()

        if not records:
            print("[OK] 没有 conftest.py 残留记录，无需清理")
            return

        print(f"匹配到 {len(records)} 条 conftest.py 记录：")
        for r in records:
            print(f"  - id={r.id} script_id={r.script_id} name={r.name} file_path={r.file_path}")

        if not apply:
            print("\n（dry-run）加 --apply 真正删除")
            return

        deleted = await qs.delete()
        print(f"\n[DONE] 已删除 {deleted} 条记录")
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    asyncio.run(main(apply))
