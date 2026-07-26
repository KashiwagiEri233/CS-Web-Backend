"""模型层共用的列类型。"""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

# JSON 字典列：PostgreSQL 上落成 jsonb，其它方言回退普通 json。
#
# 为什么必须是 jsonb 而不是 json：PostgreSQL 的 `json` 按原始文本存储，每次读取都要
# 重新解析，且无法建 GIN 索引；`jsonb` 是解析后的二进制格式，读取免解析、可索引、
# 键去重。审计与异常日志的 JSON 列都是「写一次、后续按内容检索」的用法，用 json
# 没有任何好处。
#
# 用 with_variant 而不是直接写 JSONB：保留方言无关性，模型定义本身不绑死 PostgreSQL
# （生产库仍然只支持 PostgreSQL，见 CLAUDE.md）。
JSONDict = JSON().with_variant(JSONB(), "postgresql")
