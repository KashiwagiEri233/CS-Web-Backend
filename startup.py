#!/usr/bin/env python3
"""
系统启动脚本
在应用启动前执行数据库表完整性检查和初始化
"""

import sys
import os
import asyncio
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 设置环境变量
os.environ.setdefault("ENV_FILE", ".env")

from app.utils.db_initializer import initialize_database
from app.core.loguru_logger import get_logger

logger = get_logger("startup")


async def initialize_system():
    """系统初始化函数"""
    print("=" * 60)
    print("🚀 FastAPI RBAC Framework 系统初始化")
    print("=" * 60)
    
    try:
        # 1. 数据库表完整性检查和初始化
        print("\n📋 正在检查数据库表完整性...")
        db_result = await initialize_database()
        
        # 输出数据库初始化结果
        print(f"   检查表数量: {db_result['tables_checked']}")
        if db_result['missing_tables']:
            print(f"   缺失表: {db_result['missing_tables']}")
            if db_result['created_tables']:
                print(f"   已创建表: {db_result['created_tables']}")
            if db_result['failed_tables']:
                print(f"   创建失败表: {db_result['failed_tables']}")
        else:
            print("   所有表都已存在")
        
        if not db_result['success']:
            print("❌ 数据库初始化失败")
            for error in db_result['errors']:
                print(f"   错误: {error}")
            return False
        
        print("✅ 数据库初始化完成")
        
        # 2. 其他初始化步骤可以在这里添加
        # 例如：缓存初始化、定时任务初始化等
        
        return True
        
    except Exception as e:
        logger.error(f"系统初始化过程中发生错误: {str(e)}")
        print(f"\n💥 系统初始化失败: {str(e)}")
        return False
    finally:
        print("\n" + "=" * 60)
        print("系统初始化过程结束")
        print("=" * 60)


async def main():
    """主函数"""
    # 执行系统初始化
    success = await initialize_system()
    
    if not success:
        print("\n❌ 系统初始化失败，退出程序")
        return 1
    
    print("\n✅ 系统初始化成功，准备启动应用...")
    
    # 启动主应用
    # 这里我们不直接启动应用，而是返回成功状态
    # 实际的应用启动应该由run.py或其他启动脚本来处理
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)