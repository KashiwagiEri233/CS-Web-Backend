"""
文件输出处理器
支持文件轮转、压缩、归档等功能
"""

import logging
import os
import gzip
import shutil
import time
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Union

from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler


class BaseFileHandler(logging.FileHandler):
    """文件处理器基类"""
    
    def __init__(
        self,
        filename: str,
        mode: str = 'a',
        encoding: str = 'utf-8',
        delay: bool = False,
        create_dir: bool = True
    ):
        """初始化文件处理器"""
        if create_dir:
            # 确保目录存在
            os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        super().__init__(filename, mode, encoding, delay)
    
    def get_file_size(self) -> int:
        """获取当前文件大小"""
        try:
            return os.path.getsize(self.baseFilename)
        except OSError:
            return 0
    
    def backup_file(self, backup_filename: str) -> None:
        """备份当前文件"""
        try:
            if os.path.exists(self.baseFilename):
                shutil.copy2(self.baseFilename, backup_filename)
        except Exception:
            pass


class FileHandler(BaseFileHandler):
    """增强的文件处理器"""
    
    def __init__(
        self,
        filename: str,
        mode: str = 'a',
        encoding: str = 'utf-8',
        delay: bool = False,
        create_dir: bool = True,
        buffer_size: int = 8192,
        flush_interval: float = 1.0
    ):
        """初始化文件处理器"""
        super().__init__(filename, mode, encoding, delay, create_dir)
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        self._last_flush = time.time()
    
    def emit(self, record: logging.LogRecord) -> None:
        """发送日志记录到文件"""
        try:
            msg = self.format(record)
            self.stream.write(msg + self.terminator)
            
            # 定期刷新缓冲区
            current_time = time.time()
            if current_time - self._last_flush >= self.flush_interval:
                self.flush()
                self._last_flush = current_time
                
        except Exception:
            self.handleError(record)


class RotatingFileHandler(RotatingFileHandler):
    """增强的轮转文件处理器"""
    
    def __init__(
        self,
        filename: str,
        mode: str = 'a',
        maxBytes: int = 10 * 1024 * 1024,  # 10MB
        backupCount: int = 5,
        encoding: str = 'utf-8',
        delay: bool = False,
        create_dir: bool = True,
        compress_backups: bool = True
    ):
        """初始化轮转文件处理器"""
        if create_dir:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        super().__init__(
            filename, mode, maxBytes, backupCount, encoding, delay
        )
        self.compress_backups = compress_backups
    
    def doRollover(self) -> None:
        """执行文件轮转"""
        if self.stream:
            self.stream.close()
            self.stream = None
        
        # 执行标准轮转
        super().doRollover()
        
        # 压缩备份文件（可选）
        if self.compress_backups:
            self._compress_backups()
    
    def _compress_backups(self) -> None:
        """压缩备份文件"""
        for i in range(1, self.backupCount + 1):
            source = f"{self.baseFilename}.{i}"
            if os.path.exists(source):
                target = f"{source}.gz"
                try:
                    with open(source, 'rb') as f_in:
                        with gzip.open(target, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    os.remove(source)  # 删除原始文件
                except Exception:
                    pass


class TimedRotatingFileHandler(TimedRotatingFileHandler):
    """增强的定时轮转文件处理器"""
    
    def __init__(
        self,
        filename: str,
        when: str = 'midnight',
        interval: int = 1,
        backupCount: int = 7,
        encoding: str = 'utf-8',
        delay: bool = False,
        utc: bool = False,
        create_dir: bool = True,
        compress_backups: bool = True,
        archive_dir: Optional[str] = None
    ):
        """初始化定时轮转文件处理器"""
        if create_dir:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        super().__init__(
            filename, when, interval, backupCount, encoding, delay, utc
        )
        self.compress_backups = compress_backups
        self.archive_dir = archive_dir
    
    def doRollover(self) -> None:
        """执行定时轮转"""
        if self.stream:
            self.stream.close()
            self.stream = None
        
        # 获取当前时间戳用于轮转文件命名
        current_time = datetime.now()
        
        # 执行标准轮转
        super().doRollover()
        
        # 压缩和归档备份文件
        if self.compress_backups:
            self._compress_and_archive(current_time)
    
    def _compress_and_archive(self, current_time: datetime) -> None:
        """压缩和归档备份文件"""
        try:
            # 查找所有备份文件
            backup_files = []
            for file in os.listdir(os.path.dirname(self.baseFilename)):
                if (file.startswith(os.path.basename(self.baseFilename)) and 
                    file != os.path.basename(self.baseFilename)):
                    backup_files.append(file)
            
            # 压缩每个备份文件
            for backup_file in backup_files:
                source_path = os.path.join(os.path.dirname(self.baseFilename), backup_file)
                
                # 压缩文件
                if not backup_file.endswith('.gz'):
                    compressed_path = f"{source_path}.gz"
                    with open(source_path, 'rb') as f_in:
                        with gzip.open(compressed_path, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    os.remove(source_path)
                    backup_file = compressed_path
                
                # 移动到归档目录（如果指定）
                if self.archive_dir:
                    os.makedirs(self.archive_dir, exist_ok=True)
                    target_path = os.path.join(self.archive_dir, backup_file)
                    shutil.move(source_path, target_path)
                    
        except Exception:
            pass


class JSONFileHandler(BaseFileHandler):
    """JSON格式文件处理器"""
    
    def __init__(
        self,
        filename: str,
        mode: str = 'a',
        encoding: str = 'utf-8',
        delay: bool = False,
        create_dir: bool = True,
        pretty_print: bool = False,
        ensure_ascii: bool = False
    ):
        """初始化JSON文件处理器"""
        super().__init__(filename, mode, encoding, delay, create_dir)
        self.pretty_print = pretty_print
        self.ensure_ascii = ensure_ascii
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化为JSON"""
        # 构建日志字典
        log_data = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'thread': record.thread,
            'thread_name': record.threadName,
            'process': record.process,
        }
        
        # 添加异常信息
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        # 添加额外字段
        if hasattr(record, '__dict__'):
            for key, value in record.__dict__.items():
                if key not in {
                    'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                    'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
                    'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
                    'thread', 'threadName', 'processName', 'process', 'getMessage'
                }:
                    log_data[key] = value
        
        # 转换为JSON
        if self.pretty_print:
            return json.dumps(log_data, indent=2, ensure_ascii=self.ensure_ascii)
        else:
            return json.dumps(log_data, ensure_ascii=self.ensure_ascii)


class MultiFileHandler:
    """多文件处理器，根据条件将日志写入不同文件"""
    
    def __init__(
        self,
        default_filename: str,
        condition_handlers: Optional[Dict[str, str]] = None,
        create_dir: bool = True
    ):
        """初始化多文件处理器"""
        self.default_filename = default_filename
        self.condition_handlers = condition_handlers or {}
        self.handlers = {}
        
        # 创建默认处理器
        self.handlers['default'] = FileHandler(
            default_filename, create_dir=create_dir
        )
        
        # 创建条件处理器
        for condition, filename in self.condition_handlers.items():
            self.handlers[condition] = FileHandler(
                filename, create_dir=create_dir
            )
    
    def set_level(self, level: Union[int, str]) -> None:
        """设置所有处理器的级别"""
        for handler in self.handlers.values():
            handler.setLevel(level)
    
    def emit(self, record: logging.LogRecord) -> None:
        """发送记录到相应的文件"""
        # 确定使用哪个处理器
        handler_key = self._determine_handler(record)
        handler = self.handlers.get(handler_key, self.handlers['default'])
        
        try:
            handler.emit(record)
        except Exception:
            pass
    
    def _determine_handler(self, record: logging.LogRecord) -> str:
        """确定使用哪个处理器"""
        # 根据日志级别确定
        if record.levelno >= logging.ERROR:
            if 'error' in self.handlers:
                return 'error'
        
        # 根据日志器名称确定
        logger_name = record.name.lower()
        for key in self.handlers:
            if key != 'default' and key in logger_name:
                return key
        
        return 'default'
    
    def flush(self) -> None:
        """刷新所有处理器"""
        for handler in self.handlers.values():
            try:
                handler.flush()
            except Exception:
                pass
    
    def close(self) -> None:
        """关闭所有处理器"""
        for handler in self.handlers.values():
            try:
                handler.close()
            except Exception:
                pass


def create_file_handler(
    filename: str,
    handler_type: str = 'basic',
    **kwargs
) -> Union[BaseFileHandler, RotatingFileHandler, TimedRotatingFileHandler, JSONFileHandler]:
    """创建文件处理器的便捷函数"""
    if handler_type == 'rotating':
        return RotatingFileHandler(filename, **kwargs)
    elif handler_type == 'timed':
        return TimedRotatingFileHandler(filename, **kwargs)
    elif handler_type == 'json':
        return JSONFileHandler(filename, **kwargs)
    else:
        return FileHandler(filename, **kwargs)


def setup_log_files(
    log_dir: str,
    app_name: str = 'fastapi_app',
    max_size_mb: int = 10,
    backup_count: int = 5,
    use_compression: bool = True
) -> Dict[str, logging.Handler]:
    """设置多个日志文件的便捷函数"""
    os.makedirs(log_dir, exist_ok=True)
    
    handlers = {}
    
    # 应用日志（轮转）
    app_log = os.path.join(log_dir, f"{app_name}.log")
    handlers['app'] = RotatingFileHandler(
        app_log,
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=backup_count,
        compress_backups=use_compression
    )
    
    # 错误日志（轮转）
    error_log = os.path.join(log_dir, f"{app_name}_error.log")
    handlers['error'] = RotatingFileHandler(
        error_log,
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=backup_count,
        compress_backups=use_compression
    )
    
    # JSON格式日志（轮转）
    json_log = os.path.join(log_dir, f"{app_name}_structured.log")
    handlers['json'] = RotatingFileHandler(
        json_log,
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=backup_count,
        compress_backups=use_compression
    )
    handlers['json'].setFormatter(logging.Formatter('%(message)s'))
    
    # 访问日志（按日轮转）
    access_log = os.path.join(log_dir, f"{app_name}_access.log")
    handlers['access'] = TimedRotatingFileHandler(
        access_log,
        when='midnight',
        backupCount=30,
        compress_backups=use_compression
    )
    
    return handlers