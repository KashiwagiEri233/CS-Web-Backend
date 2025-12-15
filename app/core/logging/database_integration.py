"""
数据库日志存储集成模块
集成MCP PostgreSQL服务器进行日志存储
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field

# MCP导入（需要配置后才能使用）
# from mcp import call_tool


@dataclass
class DatabaseConfig:
    """数据库配置"""
    host: str = "localhost"
    port: int = 5432
    database: str = "fastapi_logs"
    username: str = "postgres"
    password: str = ""
    schema: str = "public"
    connection_timeout: int = 30
    
    def to_connection_string(self) -> str:
        """生成连接字符串"""
        return f"postgresql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass
class LogEntry:
    """日志条目"""
    timestamp: datetime
    level: str
    logger_name: str
    message: str
    module: Optional[str] = None
    function_name: Optional[str] = None
    line_number: Optional[int] = None
    thread_id: Optional[int] = None
    thread_name: Optional[str] = None
    process_id: Optional[int] = None
    exception_info: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = field(default_factory=dict)
    trace_id: Optional[str] = None
    request_id: Optional[str] = None
    user_id: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'level': self.level,
            'logger_name': self.logger_name,
            'message': self.message,
            'module': self.module,
            'function_name': self.function_name,
            'line_number': self.line_number,
            'thread_id': self.thread_id,
            'thread_name': self.thread_name,
            'process_id': self.process_id,
            'exception_info': self.exception_info,
            'extra_data': json.dumps(self.extra_data) if self.extra_data else None,
            'trace_id': self.trace_id,
            'request_id': self.request_id,
            'user_id': self.user_id
        }


class MCPDatabaseLogger:
    """使用MCP的数据库日志记录器"""
    
    def __init__(
        self,
        config: DatabaseConfig,
        table_name: str = "application_logs",
        enabled: bool = True,
        batch_size: int = 100,
        flush_interval: float = 5.0,
        retry_attempts: int = 3,
        retry_delay: float = 1.0
    ):
        """初始化MCP数据库日志记录器"""
        self.config = config
        self.table_name = table_name
        self.enabled = enabled
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        
        # 批处理队列
        self._queue = asyncio.Queue()
        self._flush_task = None
        self._running = False
        
        # 错误计数
        self._error_count = 0
        self._max_errors = 10
    
    async def start(self) -> None:
        """启动日志记录器"""
        if not self.enabled:
            return
        
        if not self._running:
            self._running = True
            
            # 初始化数据库表
            await self._ensure_table_exists()
            
            # 启动刷新任务
            self._flush_task = asyncio.create_task(self._flush_loop())
    
    async def stop(self) -> None:
        """停止日志记录器"""
        if not self._running:
            return
        
        self._running = False
        
        # 停止刷新任务
        if self._flush_task:
            # 发送停止信号
            await self._queue.put(None)
            
            # 等待任务完成
            await self._flush_task
    
    async def _ensure_table_exists(self) -> None:
        """确保数据库表存在"""
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
            trace_id VARCHAR(64),
            request_id VARCHAR(64),
            user_id INTEGER,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        
        -- 创建索引
        CREATE INDEX IF NOT EXISTS idx_{self.table_name}_timestamp ON {self.table_name} (timestamp);
        CREATE INDEX IF NOT EXISTS idx_{self.table_name}_level ON {self.table_name} (level);
        CREATE INDEX IF NOT EXISTS idx_{self.table_name}_logger_name ON {self.table_name} (logger_name);
        CREATE INDEX IF NOT EXISTS idx_{self.table_name}_trace_id ON {self.table_name} (trace_id);
        CREATE INDEX IF NOT EXISTS idx_{self.table_name}_request_id ON {self.table_name} (request_id);
        CREATE INDEX IF NOT EXISTS idx_{self.table_name}_user_id ON {self.table_name} (user_id);
        """
        
        await self._execute_query(create_table_sql)
    
    async def log(self, entry: LogEntry) -> None:
        """记录日志条目"""
        if not self.enabled:
            return
        
        try:
            await self._queue.put(entry)
        except Exception as e:
            self._error_count += 1
            logging.error(f"Failed to queue log entry: {e}")
    
    async def _flush_loop(self) -> None:
        """刷新循环"""
        while self._running:
            try:
                # 收集一批日志条目
                batch = []
                deadline = time.time() + self.flush_interval
                
                # 等待第一批条目或超时
                try:
                    first_entry = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=self.flush_interval
                    )
                    
                    # 如果是停止信号，退出循环
                    if first_entry is None:
                        break
                    
                    batch.append(first_entry)
                    
                except asyncio.TimeoutError:
                    continue
                
                # 收集更多条目直到达到批量大小或超时
                while (
                    len(batch) < self.batch_size and
                    time.time() < deadline
                ):
                    try:
                        entry = await asyncio.wait_for(
                            self._queue.get(),
                            timeout=0.1  # 短超时，避免阻塞
                        )
                        
                        if entry is None:  # 停止信号
                            break
                        
                        batch.append(entry)
                        
                    except asyncio.TimeoutError:
                        continue
                
                # 插入批量数据
                if batch:
                    await self._insert_batch(batch)
                
            except Exception as e:
                self._error_count += 1
                logging.error(f"Error in flush loop: {e}")
                
                # 如果错误太多，可能需要禁用日志记录
                if self._error_count >= self._max_errors:
                    logging.error("Too many errors, disabling database logging")
                    self.enabled = False
                    break
    
    async def _insert_batch(self, batch: List[LogEntry]) -> None:
        """插入批量日志条目"""
        # 构建插入SQL
        columns = [
            'timestamp', 'level', 'logger_name', 'message', 'module',
            'function_name', 'line_number', 'thread_id', 'thread_name',
            'process_id', 'exception_info', 'extra_data', 'trace_id',
            'request_id', 'user_id'
        ]
        
        placeholders = ', '.join(['%s'] * len(columns))
        sql = f"""
        INSERT INTO {self.table_name} ({', '.join(columns)})
        VALUES ({placeholders})
        """
        
        # 准备数据
        values = []
        for entry in batch:
            entry_dict = entry.to_dict()
            values.append([entry_dict.get(col) for col in columns])
        
        # 执行插入
        await self._execute_query(sql, {"values": values})
    
    async def _execute_query(self, sql: str, params: Optional[Dict] = None) -> Any:
        """执行SQL查询"""
        # 这里应该使用MCP PostgreSQL工具
        # 由于MCP需要特定配置，这里提供接口定义
        
        # 尝试通过MCP执行查询
        try:
            # 模拟MCP调用
            # result = await mcp_call_tool(
            #     "PostgreSQL Multi-Schema MCP Server",
            #     "query",
            #     {"sql": sql}
            # )
            
            # 暂时返回模拟结果
            return []
            
        except Exception as e:
            logging.error(f"Failed to execute query via MCP: {e}")
            
            # 重试逻辑
            for attempt in range(self.retry_attempts):
                try:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    # result = await mcp_call_tool(...)
                    return []
                except Exception:
                    continue
            
            raise
    
    async def query_logs(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        level: Optional[str] = None,
        logger_name: Optional[str] = None,
        trace_id: Optional[str] = None,
        request_id: Optional[str] = None,
        user_id: Optional[int] = None,
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
        
        if trace_id:
            conditions.append("trace_id = %(trace_id)s")
            params['trace_id'] = trace_id
        
        if request_id:
            conditions.append("request_id = %(request_id)s")
            params['request_id'] = request_id
        
        if user_id:
            conditions.append("user_id = %(user_id)s")
            params['user_id'] = user_id
        
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
    
    async def get_log_statistics(
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
            MAX(timestamp) as last_occurrence,
            AVG(CASE WHEN user_id IS NOT NULL THEN 1 ELSE 0 END) * 100 as user_activity_rate
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


# 全局数据库日志记录器实例
_database_logger: Optional[MCPDatabaseLogger] = None


def get_database_logger() -> Optional[MCPDatabaseLogger]:
    """获取全局数据库日志记录器"""
    return _database_logger


async def setup_database_logging(
    host: str = "localhost",
    port: int = 5432,
    database: str = "fastapi_logs",
    username: str = "postgres",
    password: str = "",
    table_name: str = "application_logs",
    enabled: bool = True,
    **kwargs
) -> MCPDatabaseLogger:
    """设置数据库日志记录"""
    global _database_logger
    
    config = DatabaseConfig(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password
    )
    
    _database_logger = MCPDatabaseLogger(
        config=config,
        table_name=table_name,
        enabled=enabled,
        **kwargs
    )
    
    await _database_logger.start()
    return _database_logger


async def stop_database_logging() -> None:
    """停止数据库日志记录"""
    global _database_logger
    
    if _database_logger:
        await _database_logger.stop()
        _database_logger = None


# 简单的同步包装器，用于与现有日志系统集成
class DatabaseLogHandler(logging.Handler):
    """数据库日志处理器，同步接口"""
    
    def __init__(self, db_logger: MCPDatabaseLogger, level: int = logging.INFO):
        """初始化处理器"""
        super().__init__(level)
        self.db_logger = db_logger
    
    def emit(self, record: logging.LogRecord) -> None:
        """发送日志记录到数据库"""
        try:
            # 创建日志条目
            entry = LogEntry(
                timestamp=datetime.fromtimestamp(record.created),
                level=record.levelname,
                logger_name=record.name,
                message=record.getMessage(),
                module=record.module,
                function_name=record.funcName,
                line_number=record.lineno,
                thread_id=record.thread,
                thread_name=record.threadName,
                process_id=record.process,
                exception_info=self.formatException(record.exc_info) if record.exc_info else None,
                extra_data=self._extract_extra_data(record),
                trace_id=getattr(record, 'trace_id', None),
                request_id=getattr(record, 'request_id', None),
                user_id=getattr(record, 'user_id', None)
            )
            
            # 异步记录日志
            asyncio.create_task(self.db_logger.log(entry))
            
        except Exception as e:
            self.handleError(record)
    
    def _extract_extra_data(self, record: logging.LogRecord) -> Dict[str, Any]:
        """提取额外数据"""
        extra_data = {}
        
        # 标准属性
        standard_attrs = {
            'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
            'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
            'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
            'thread', 'threadName', 'processName', 'process', 'getMessage'
        }
        
        # 提取额外属性
        for key, value in record.__dict__.items():
            if key not in standard_attrs:
                extra_data[key] = value
        
        return extra_data