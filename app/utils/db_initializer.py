"""
数据库初始化工具模块
用于检查和创建数据库表
"""

from typing import Dict, List
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import engine, Base
from app.core.loguru_logger import get_logger
from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission
from app.models.exception_log import ExceptionLog, ExceptionPattern, ExceptionAlert, ExceptionMetrics

logger = get_logger("db_initializer")


class DatabaseInitializer:
    """数据库初始化器"""
    
    def __init__(self):
        self.expected_tables = [
            "users",
            "roles", 
            "permissions",
            "role_permissions",
            "user_roles",
            "exception_logs",
            "exception_patterns",
            "exception_alerts",
            "exception_metrics"
        ]
        self.logger = get_logger("db_initializer")
    
    async def check_table_existence(self) -> Dict[str, bool]:
        """
        检查所有预期表的存在性
        
        Returns:
            字典，键为表名，值为是否存在
        """
        table_status = {}
        
        async with engine.connect() as conn:
            for table_name in self.expected_tables:
                try:
                    # 使用原始SQL查询检查表是否存在
                    # 这种方法适用于多种数据库
                    query = text(
                        "SELECT 1 FROM information_schema.tables WHERE table_name = :table_name LIMIT 1"
                    )
                    result = await conn.execute(query, {"table_name": table_name})
                    exists = result.fetchone() is not None
                    table_status[table_name] = exists
                    
                    if exists:
                        self.logger.debug(f"表 '{table_name}' 存在")
                    else:
                        self.logger.warning(f"表 '{table_name}' 缺失")
                        
                except SQLAlchemyError as e:
                    self.logger.error(f"检查表 '{table_name}' 时出错: {str(e)}")
                    table_status[table_name] = False
                    
        return table_status
    
    async def create_missing_tables(self) -> Dict[str, bool]:
        """
        创建缺失的表
        
        Returns:
            字典，键为表名，值为是否已创建
        """
        creation_status = {}
        
        try:
            # 获取当前存在的表状态
            table_status = await self.check_table_existence()
            
            # 找出缺失的表
            missing_tables = [table for table, exists in table_status.items() if not exists]
            
            if not missing_tables:
                self.logger.info("所有表都已存在，无需创建")
                return {table: False for table in self.expected_tables}
            
            self.logger.info(f"发现缺失的表: {missing_tables}")
            
            # 创建所有表（SQLAlchemy会自动处理依赖关系）
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            
            self.logger.info("已尝试创建所有缺失的表")
            
            # 再次检查表状态
            updated_status = await self.check_table_existence()
            
            # 记录创建状态
            for table_name in self.expected_tables:
                was_missing = table_name in missing_tables
                now_exists = updated_status.get(table_name, False)
                creation_status[table_name] = was_missing and now_exists
                
                if was_missing and now_exists:
                    self.logger.info(f"成功创建表 '{table_name}'")
                elif was_missing and not now_exists:
                    self.logger.error(f"创建表 '{table_name}' 失败")
                else:
                    self.logger.debug(f"表 '{table_name}' 已存在")
                    
        except Exception as e:
            self.logger.error(f"创建表时发生错误: {str(e)}")
            # 标记所有表创建失败
            for table_name in self.expected_tables:
                creation_status[table_name] = False
                
        return creation_status
    
    async def initialize_database(self) -> Dict[str, any]:
        """
        初始化数据库，检查并创建缺失的表
        
        Returns:
            初始化结果字典
        """
        result = {
            "success": False,
            "tables_checked": 0,
            "missing_tables": [],
            "created_tables": [],
            "failed_tables": [],
            "errors": []
        }
        
        try:
            self.logger.info("开始数据库初始化过程")
            
            # 1. 检查表存在性
            self.logger.info("检查数据库表完整性")
            table_status = await self.check_table_existence()
            result["tables_checked"] = len(table_status)
            
            # 2. 确定缺失的表
            missing_tables = [table for table, exists in table_status.items() if not exists]
            result["missing_tables"] = missing_tables
            
            self.logger.info(f"发现 {len(missing_tables)} 个缺失的表: {missing_tables}")
            
            # 3. 创建缺失的表
            if missing_tables:
                self.logger.info("开始创建缺失的表")
                creation_status = await self.create_missing_tables()
                
                # 更新结果
                created_tables = [table for table, created in creation_status.items() if created]
                failed_tables = [table for table, created in creation_status.items() if not created and table in missing_tables]
                
                result["created_tables"] = created_tables
                result["failed_tables"] = failed_tables
                
                if failed_tables:
                    self.logger.error(f"以下表创建失败: {failed_tables}")
                else:
                    self.logger.info("所有缺失的表均已成功创建")
            else:
                self.logger.info("所有表都已存在，无需创建")
            
            result["success"] = True
            self.logger.info("数据库初始化完成")
            
        except Exception as e:
            error_msg = f"数据库初始化失败: {str(e)}"
            self.logger.error(error_msg)
            result["errors"].append(error_msg)
            
        return result


# 便捷函数
async def initialize_database() -> Dict[str, any]:
    """
    初始化数据库的便捷函数
    
    Returns:
        初始化结果字典
    """
    initializer = DatabaseInitializer()
    return await initializer.initialize_database()


async def check_and_create_tables() -> Dict[str, any]:
    """
    检查并创建缺失表的便捷函数
    
    Returns:
        操作结果字典
    """
    initializer = DatabaseInitializer()
    
    # 检查表状态
    table_status = await initializer.check_table_existence()
    
    # 创建缺失的表
    creation_status = await initializer.create_missing_tables()
    
    return {
        "table_status": table_status,
        "creation_status": creation_status
    }