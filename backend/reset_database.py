"""
数据库重置脚本
删除旧数据库和迁移文件，重新初始化
"""
import os
import sys
import shutil
import asyncio
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger


def backup_database():
    """备份现有数据库（可选）"""
    db_path = Path("db.sqlite3")
    if db_path.exists():
        backup_dir = Path("backups")
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f"db_backup_{int(os.path.getmtime(db_path))}.sqlite3"
        shutil.copy2(db_path, backup_path)
        logger.info(f"数据库已备份到: {backup_path}")
        return backup_path
    return None


def clean_old_files():
    """删除旧的数据库和迁移文件"""
    # 删除数据库文件
    db_path = Path("db.sqlite3")
    if db_path.exists():
        db_path.unlink()
        logger.info("已删除旧数据库: db.sqlite3")

    # 清空迁移目录
    migrations_dir = Path("migrations/models")
    if migrations_dir.exists():
        for file in migrations_dir.glob("*.py"):
            file.unlink()
            logger.info(f"已删除迁移文件: {file.name}")

    # 删除 aerich 表记录（如果存在）
    aerich_dir = Path("migrations")
    if aerich_dir.exists():
        for file in aerich_dir.glob("*.py"):
            if file.name != "__init__.py":
                file.unlink()
                logger.info(f"已删除: {file.name}")


async def init_database():
    """初始化数据库"""
    from tortoise import Tortoise
    from app.settings.config import settings

    # 初始化 Tortoise ORM
    await Tortoise.init(
        config=settings.TORTOISE_ORM
    )

    # 生成数据库表结构
    await Tortoise.generate_schemas()
    logger.info("数据库表结构创建成功")

    # 关闭连接
    await Tortoise.close_connections()


async def init_aerich():
    """初始化 Aerich 迁移工具"""
    from aerich import Migrate
    from app.settings.config import settings

    # 初始化 Aerich
    await Migrate.init(
        config=settings.TORTOISE_ORM,
        location="./migrations",
        app="models"
    )

    # 生成初始迁移
    await Migrate.init_db(safe=True)
    logger.info("Aerich 初始化成功")

    # 关闭连接
    await Migrate.close_connections()


async def insert_initial_data():
    """插入初始数据"""
    from tortoise import Tortoise
    from app.settings.config import settings
    from app.database.create_tables import insert_initial_data

    await Tortoise.init(config=settings.TORTOISE_ORM)
    await insert_initial_data()
    await Tortoise.close_connections()


def main():
    """主函数"""
    logger.info("=" * 50)
    logger.info("开始重置数据库")
    logger.info("=" * 50)

    # 1. 备份现有数据库
    backup_path = backup_database()

    # 2. 清理旧文件
    clean_old_files()

    # 3. 初始化数据库
    logger.info("正在初始化数据库...")
    asyncio.run(init_database())

    # 4. 初始化 Aerich (可选，SQLite 可跳过)
    try:
        logger.info("正在初始化 Aerich...")
        asyncio.run(init_aerich())
    except Exception as e:
        logger.warning(f"Aerich 初始化跳过 (SQLite 迁移非必须): {e}")

    # 5. 插入初始数据
    logger.info("正在插入初始数据...")
    asyncio.run(insert_initial_data())

    logger.info("=" * 50)
    logger.info("数据库重置完成！")
    if backup_path:
        logger.info(f"备份文件: {backup_path}")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
