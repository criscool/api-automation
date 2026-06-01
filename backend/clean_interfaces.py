"""
清理接口和文档相关数据（保留用户、角色、菜单等系统数据）
用法：python clean_interfaces.py
"""
import asyncio
from tortoise import Tortoise
from tortoise.exceptions import OperationalError

from app.settings.config import settings


async def clean():
    await Tortoise.init(config=settings.TORTOISE_ORM)

    from app.models.api_automation import (
        ApiDocument, ApiInterface, TestScript,
    )

    # 按外键依赖顺序删除，跳过不存在的表
    tables_to_clean = [
        ("test_scripts", TestScript),
        ("api_interfaces", ApiInterface),
        ("api_documents", ApiDocument),
    ]

    # 尝试清理可能存在的表（用原始 SQL 兜底）
    conn = Tortoise.get_connection("default")
    extra_tables = ["test_results", "test_executions", "test_cases", "api_responses", "api_parameters"]
    for table in extra_tables:
        try:
            await conn.execute_query(f"DELETE FROM {table}")
            print(f"  {table}: 已清理")
        except OperationalError:
            print(f"  {table}: 表不存在，跳过")

    # 清理 ORM 模型对应的表
    for name, model in tables_to_clean:
        try:
            count = await model.all().delete()
            print(f"  {name}: {count} 条")
        except OperationalError:
            print(f"  {name}: 表不存在，跳过")

    print("\n清理完成")
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(clean())
