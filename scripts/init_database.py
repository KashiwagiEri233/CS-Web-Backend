#!/usr/bin/env python3
"""
数据库初始化脚本
用于在系统启动时检查和创建缺失的数据库表
"""

import sys
import os
import asyncio
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 设置环境变量
os.environ.setdefault("ENV_FILE", ".env")

from app.utils.db_initializer import initialize_database
from app.core.loguru_logger import get_logger

logger = get_logger("db_init_script")


async def main():
    """主函数"""
    print("=" * 60)
    print("🚀 数据库初始化脚本启动")
    print("=" * 60)
    
    try:
        # 初始化数据库
        logger.info("开始数据库初始化过程")
        result = await initialize_database()
        
        # 输出结果
        print(f"\n📊 初始化结果:")
        print(f"   成功: {result['success']}")
        print(f"   检查表数量: {result['tables_checked']}")
        if result['missing_tables']:
            print(f"   缺失表: {result['missing_tables']}")
            if result['created_tables']:
                print(f"   创建表: {result['created_tables']}")
            if result['failed_tables']:
                print(f"   失败表: {result['failed_tables']}")
        else:
            print(f"   所有表都已存在，数据库结构完整")
        
        if result['errors']:
            print(f"\n❌ 错误信息:")
            for error in result['errors']:
                print(f"   {error}")
        
        if result['success']:
            if result['missing_tables']:
                if result['failed_tables']:
                    print(f"\n⚠️  部分表创建失败，请检查日志")
                    return 1
                else:
                    print(f"\n✅ 数据库初始化完成，缺失的表已成功创建")
                    return 0
            else:
                print(f"\n✅ 数据库已完整，无需创建新表")
                return 0
        else:
            print(f"\n❌ 数据库初始化失败")
            return 1
            
    except Exception as e:
        logger.error(f"数据库初始化过程中发生未预期的错误: {str(e)}")
        print(f"\n💥 严重错误: {str(e)}")
        return 1
    finally:
        print("\n" + "=" * 60)
        print("数据库初始化脚本执行完毕")
        print("=" * 60)


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)