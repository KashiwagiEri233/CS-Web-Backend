"""
数据库输出处理器
支持将日志存储到PostgreSQL数据库中
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from .base import AsyncBaseHandler


class DatabaseHandler(AsyncBaseHandler):
    """数据库日志处理器"""
    
    def __init__(
        self,
        connection_string: str,
        table_name: str = "application_logs",
        level: Union[int, str] = logging.INFO,
        buffer_size: int = 100,
        flush_interval: float = 5.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        batch_size: int = 50
    ):
        """初始化数据库处理器"""
        super().__init__(level, None, buffer_size, flush_interval)
        self.connection_string = connection_string
        self.table_name = table_name
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.batch_size = batch_size
        self._connection = None
        self._setup_complete = False
    
    async def _ensure_setup(self) -> None:
        """确保数据库表已创建"""
        if self._setup_complete:
            return
        
        try:
            await self._create_table()
            self._setup_complete = True
        except Exception as e:
            logging.error(f"Failed to setup database logging: {e}")
            raise
    
    async def _create_table(self) -> None:
        """创建日志表"""
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
            level VARCHAR(10) NOT NULL,
            logger_name VARCHAR(255) NOT NULL,
            message TEXT NOT NULL,
            module VARCHAR(255),
            function_name VARCHAR(255),
            line_number INTEGER,
            thread_id BIGINT,
            thread_name VARCHAR(255),
            process_id INTEGER,
            exception_info TEXT,
            extra_data JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        
        CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON {self.table_name} (timestamp);
        CREATE INDEX IF NOT EXISTS idx_logs_level ON {self.table_name} (level);
        CREATE INDEX IF NOT EXISTS idx_logs_logger_name ON {self.table_name} (logger_name);
        CREATE INDEX IF NOT EXISTS idx_logs_created_at ON {self.table_name} (created_at);
        """
        
        await self._execute_query(create_table_sql)
    
    async def _get_connection(self):
        """获取数据库连接"""
        if self._connection is None:
            # 使用MCP PostgreSQL服务器获取连接
            await self._connect_with_mcp()
        return self._connection
    
    async def _connect_with_mcp(self):
        """使用MCP连接到PostgreSQL"""
        # 这里将使用MCP PostgreSQL服务器
        # 注意：这需要MCP PostgreSQL服务器已配置并可用
        try:
            # 尝试直接执行查询来测试连接
            await self._execute_query("SELECT 1")
        except Exception as e:
            logging.error(f"Failed to connect to database: {e}")
            raise
    
    async def _execute_query(self, query: str, params: Optional[Dict] = None) -> Any:
        """执行数据库查询"""
        # 这里应该使用MCP PostgreSQL服务器的查询工具
        # 由于我们无法直接访问MCP工具，这里提供接口定义
        # 实际实现需要集成MCP PostgreSQL服务器
        
        # 模拟实现 - 实际代码需要调用MCP工具
        import sys
        print(f"Would execute query: {query}")
        if params:
            print(f"Parameters: {params}")
        return []
    
    async def _flush_buffer(self) -> None:
        """刷新缓冲区到数据库"""
        if not self._buffer:
            return
        
        try:
            await self._ensure_setup()
            
            # 分批处理缓冲区
            for i in range(0, len(self._buffer), self.batch_size):
                batch = self._buffer[i:i + self.batch_size]
                await self._insert_batch(batch)
            
            self._buffer.clear()
            
        except Exception as e:
            logging.error(f"Failed to flush log buffer to database: {e}")
            # 缓冲区未清空，下次重试
    
    async def _insert_batch(self, batch: List[logging.LogRecord]) -> None:
        """批量插入日志记录"""
        values = []
        for record in batch:
            values.append(self._record_to_dict(record))
        
        # 构建批量插入SQL
        columns = [
            'timestamp', 'level', 'logger_name', 'message', 'module',
            'function_name', 'line_number', 'thread_id', 'thread_name',
            'process_id', 'exception_info', 'extra_data'
        ]
        
        placeholders = ', '.join(['%s'] * len(columns))
        sql = f"""
        INSERT INTO {self.table_name} ({', '.join(columns)})
        VALUES ({placeholders})
        """
        
        # 提取值
        batch_values = []
        for value_dict in values:
            batch_values.append([value_dict.get(col) for col in columns])
        
        # 执行批量插入
        await self._execute_query(sql, {'values': batch_values})
    
    def _record_to_dict(self, record: logging.LogRecord) -> Dict[str, Any]:
        """将日志记录转换为字典"""
        return {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger_name': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function_name': record.funcName,
            'line_number': record.lineno,
            'thread_id': record.thread,
            'thread_name': record.threadName,
            'process_id': record.process,
            'exception_info': self.formatException(record.exc_info) if record.exc_info else None,
            'extra_data': self._extract_extra_data(record)
        }
    
    def _extract_extra_data(self, record: logging.LogRecord) -> Optional[Dict[str, Any]]:
        """提取额外数据"""
        extra_data = {}
        
        # 检查所有属性，排除标准属性
        standard_attrs = {
            'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
            'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
            'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
            'thread', 'threadName', 'processName', 'process', 'getMessage'
        }
        
        for key, value in record.__dict__.items():
            if key not in standard_attrs:
                extra_data[key] = value
        
        return extra_data if extra_data else None
    
    def sync_emit(self, record: logging.LogRecord) -> None:
        """同步发送（后备方案）"""
        try:
            # 使用线程池执行异步操作
            import concurrent.futures
            
            def async_wrapper():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._flush_buffer())
                finally:
                    loop.close()
            
            # 在后台线程中执行
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(async_wrapper)
                # 不等待完成，继续执行
                
        except Exception as e:
            logging.error(f"Failed to sync emit to database: {e}")
    
    async def query_logs(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        level: Optional[str] = None,
        logger_name: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "timestamp DESC"
    ) -> List[Dict[str, Any]]:
        """查询日志记录"""
        conditions = []
        params = {}
        
        if start_time:
            conditions.append("timestamp >= %(start_time)s")
            params['start_time'] = start_time
        
        if end_time:
            conditions.append("timestamp <= %(end_time)s")
            params['end_time'] = end_time
        
        if level:
            conditions.append("level = %(level)s")
            params['level'] = level
        
        if logger_name:
            conditions.append("logger_name = %(logger_name)s")
            params['logger_name'] = logger_name
        
        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)
        
        sql = f"""
        SELECT * FROM {self.table_name}
        {where_clause}
        ORDER BY {order_by}
        LIMIT %(limit)s OFFSET %(offset)s
        """
        
        params.update({'limit': limit, 'offset': offset})
        
        return await self._execute_query(sql, params)
    
    async def get_log_stats(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """获取日志统计信息"""
        conditions = []
        params = {}
        
        if start_time:
            conditions.append("timestamp >= %(start_time)s")
            params['start_time'] = start_time
        
        if end_time:
            conditions.append("timestamp <= %(end_time)s")
            params['end_time'] = end_time
        
        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)
        
        sql = f"""
        SELECT 
            level,
            COUNT(*) as count,
            MIN(timestamp) as first_occurrence,
            MAX(timestamp) as last_occurrence
        FROM {self.table_name}
        {where_clause}
        GROUP BY level
        ORDER BY count DESC
        """
        
        return await self._execute_query(sql, params)
    
    async def cleanup_old_logs(self, days_to_keep: int = 30) -> int:
        """清理旧日志"""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        sql = f"""
        DELETE FROM {self.table_name}
        WHERE timestamp < %(cutoff_date)s
        """
        
        await self._execute_query(sql, {'cutoff_date': cutoff_date})
        
        # 返回删除的记录数
        count_sql = f"""
        SELECT COUNT(*) as deleted_count FROM {self.table_name}
        WHERE timestamp < %(cutoff_date)s
        """
        
        result = await self._execute_query(count_sql, {'cutoff_date': cutoff_date})
        return result[0]['deleted_count'] if result else 0
    
    async def close(self) -> None:
        """关闭处理器"""
        await self._flush_buffer()
        if self._connection:
            # 关闭数据库连接
            self._connection = None


class PostgreSQLDatabaseHandler(DatabaseHandler):
    """PostgreSQL专用数据库处理器"""
    
    def __init__(
        self,
        host: str = 'localhost',
        port: int = 5432,
        database: str = 'postgres',
        username: str = 'postgres',
        password: str = '',
        **kwargs
    ):
        """初始化PostgreSQL处理器"""
        connection_string = f"postgresql://{username}:{password}@{host}:{port}/{database}"
        super().__init__(connection_string, **kwargs)
        
        self.host = host
        self.port = port
        self.database = database
        self.username = username
    
    async def _connect_with_mcp(self) -> None:
        """使用MCP连接到PostgreSQL"""
        try:
            # 尝试使用MCP PostgreSQL工具获取描述
            import sys
            print(f"Attempting to connect to PostgreSQL at {self.host}:{self.port}/{self.database}")
            
            # 这里将调用MCP工具来建立连接
            # 实际实现需要使用mcp_call_tool
            
            # 测试连接
            await self._execute_query("SELECT 1")
            
        except Exception as e:
            logging.error(f"Failed to connect to PostgreSQL via MCP: {e}")
            raise


def create_database_handler(
    handler_type: str = 'postgresql',
    **kwargs
) -> DatabaseHandler:
    """创建数据库处理器的便捷函数"""
    if handler_type == 'postgresql':
        return PostgreSQLDatabaseHandler(**kwargs)
    else:
        return DatabaseHandler(**kwargs)