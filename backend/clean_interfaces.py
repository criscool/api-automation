"""
清理接口和文档相关数据（保留用户、角色、菜单等系统数据）
用法：python clean_interfaces.py
"""
import asyncio
from tortoise import Tortoise

from app.settings.config import settings


async def clean():
    await Tortoise.init(config=settings.TORTOISE_ORM)

    from app.models.api_automation import (
        ApiDocument, ApiInterface, ApiParameter, ApiResponse,
        TestCase, TestScript, TestExecution, TestResult,
    )

    # 按外键依赖顺序删除
    deleted = {}
    deleted["test_results"] = await TestResult.all().delete()
    deleted["test_executions"] = await TestExecution.all().delete()
    deleted["test_scripts"] = await TestScript.all().delete()
    deleted["test_cases"] = await TestCase.all().delete()
    deleted["api_responses"] = await ApiResponse.all().delete()
    deleted["api_parameters"] = await ApiParameter.all().delete()
    deleted["api_interfaces"] = await ApiInterface.all().delete()
    deleted["api_documents"] = await ApiDocument.all().delete()

    print("清理完成：")
    for table, count in deleted.items():
        print(f"  {table}: {count} 条")

    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(clean())
