import re
from typing import Optional

def validate_password_strength(password: str) -> tuple[bool, Optional[str]]:
    """
    验证密码强度
    返回 (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "密码长度至少为8个字符"
    
    if len(password) > 128:
        return False, "密码长度不能超过128个字符"
    
    # 检查是否包含至少一个数字
    if not re.search(r'\d', password):
        return False, "密码必须包含至少一个数字"
    
    # 检查是否包含至少一个字母
    if not re.search(r'[a-zA-Z]', password):
        return False, "密码必须包含至少一个字母"
    
    # 检查是否包含至少一个特殊字符
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "密码必须包含至少一个特殊字符"
    
    return True, None


def validate_username(username: str) -> tuple[bool, Optional[str]]:
    """
    验证用户名
    返回 (is_valid, error_message)
    """
    if len(username) < 3:
        return False, "用户名长度至少为3个字符"
    
    if len(username) > 50:
        return False, "用户名长度不能超过50个字符"
    
    # 只允许字母、数字、下划线和连字符
    if not re.match(r'^[a-zA-Z0-9_-]+$', username):
        return False, "用户名只能包含字母、数字、下划线和连字符"
    
    return True, None


def validate_email(email: str) -> tuple[bool, Optional[str]]:
    """
    验证邮箱格式
    返回 (is_valid, error_message)
    """
    # 基本邮箱格式验证
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_regex, email):
        return False, "邮箱格式不正确"
    
    if len(email) > 255:
        return False, "邮箱长度不能超过255个字符"
    
    return True, None


def sanitize_input(input_string: str, max_length: int = 1000) -> str:
    """
    清理输入字符串，防止XSS和注入攻击
    """
    if not input_string:
        return ""
    
    # 限制长度
    if len(input_string) > max_length:
        input_string = input_string[:max_length]
    
    # 移除潜在的危险字符（根据具体需求调整）
    # 注意：使用参数化查询是最好的防护方式，这只是额外的保护层
    dangerous_chars = ['<', '>', '"', "'", '&', '\x00']
    for char in dangerous_chars:
        input_string = input_string.replace(char, '')
    
    return input_string


def validate_sql_like_pattern(pattern: str) -> tuple[bool, Optional[str]]:
    """
    验证SQL LIKE模式，防止SQL注入
    返回 (is_valid, error_message)
    """
    # 确保不包含SQL特殊字符
    if '%' in pattern and not pattern.startswith('%') and not pattern.endswith('%'):
        return False, "LIKE模式只能以%开头或结尾"
    
    if '[' in pattern or ']' in pattern or '_' in pattern:
        return False, "LIKE模式不能包含特殊字符"
    
    return True, None