"""create exception log tables

Revision ID: create_exception_log_tables
Revises: 
Create Date: 2023-12-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'create_exception_log_tables'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # 创建异常日志表
    op.create_table(
        'exception_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('traceback_id', sa.String(length=64), nullable=False),
        sa.Column('exception_type', sa.String(length=100), nullable=False),
        sa.Column('error_code', sa.String(length=100), nullable=True),
        sa.Column('exception_message', sa.Text(), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('method', sa.String(length=10), nullable=True),
        sa.Column('endpoint', sa.String(length=255), nullable=True),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('user_id', sa.String(length=64), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('details', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('traceback', sa.Text(), nullable=True),
        sa.Column('context', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('is_resolved', sa.Boolean(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_by', sa.String(length=64), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('priority', sa.String(length=20), nullable=False),
        sa.Column('parent_exception_id', sa.Integer(), nullable=True),
        sa.Column('related_incident_id', sa.String(length=64), nullable=True),
        sa.Column('response_time_ms', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['parent_exception_id'], ['exception_logs.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # 创建异常日志表的索引
    op.create_index(op.f('ix_exception_logs_id'), 'exception_logs', ['id'], unique=False)
    op.create_index('ix_exception_logs_traceback_id', 'exception_logs', ['traceback_id'], unique=False)
    op.create_index('ix_exception_logs_exception_type', 'exception_logs', ['exception_type'], unique=False)
    op.create_index('ix_exception_logs_error_code', 'exception_logs', ['error_code'], unique=False)
    op.create_index('ix_exception_logs_status_code', 'exception_logs', ['status_code'], unique=False)
    op.create_index('ix_exception_logs_method', 'exception_logs', ['method'], unique=False)
    op.create_index('ix_exception_logs_endpoint', 'exception_logs', ['endpoint'], unique=False)
    op.create_index('ix_exception_logs_request_id', 'exception_logs', ['request_id'], unique=False)
    op.create_index('ix_exception_logs_user_id', 'exception_logs', ['user_id'], unique=False)
    op.create_index('ix_exception_logs_created_at', 'exception_logs', ['created_at'], unique=False)
    op.create_index('ix_exception_logs_is_resolved', 'exception_logs', ['is_resolved'], unique=False)
    op.create_index('ix_exception_logs_severity', 'exception_logs', ['severity'], unique=False)
    op.create_index('ix_exception_logs_priority', 'exception_logs', ['priority'], unique=False)
    op.create_index('ix_exception_logs_related_incident_id', 'exception_logs', ['related_incident_id'], unique=False)
    
    # 复合索引
    op.create_index('ix_exception_logs_exception_type_created', 'exception_logs', ['exception_type', 'created_at'], unique=False)
    op.create_index('ix_exception_logs_error_code_created', 'exception_logs', ['error_code', 'created_at'], unique=False)
    op.create_index('ix_exception_logs_status_code_created', 'exception_logs', ['status_code', 'created_at'], unique=False)
    op.create_index('ix_exception_logs_user_id_created', 'exception_logs', ['user_id', 'created_at'], unique=False)
    op.create_index('ix_exception_logs_traceback_id_user', 'exception_logs', ['traceback_id', 'user_id'], unique=False)
    op.create_index('ix_exception_logs_created_at_severity', 'exception_logs', ['created_at', 'severity'], unique=False)
    op.create_index('ix_exception_logs_is_resolved_created', 'exception_logs', ['is_resolved', 'created_at'], unique=False)

    # 创建异常模式表
    op.create_table(
        'exception_patterns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pattern_name', sa.String(length=100), nullable=False),
        sa.Column('pattern_type', sa.String(length=50), nullable=False),
        sa.Column('exception_type', sa.String(length=100), nullable=True),
        sa.Column('error_code', sa.String(length=100), nullable=True),
        sa.Column('endpoint_pattern', sa.String(length=255), nullable=True),
        sa.Column('user_id_pattern', sa.String(length=100), nullable=True),
        sa.Column('occurrence_count', sa.Integer(), nullable=False),
        sa.Column('last_occurrence', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('alert_threshold', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # 创建异常模式表的索引
    op.create_index(op.f('ix_exception_patterns_id'), 'exception_patterns', ['id'], unique=False)
    op.create_index('ix_exception_patterns_pattern_name', 'exception_patterns', ['pattern_name'], unique=True)
    op.create_index('ix_exception_patterns_pattern_type', 'exception_patterns', ['pattern_type'], unique=False)
    op.create_index('ix_exception_patterns_is_active', 'exception_patterns', ['is_active'], unique=False)
    op.create_index('ix_exception_patterns_created_at', 'exception_patterns', ['created_at'], unique=False)
    op.create_index('ix_exception_patterns_updated_at', 'exception_patterns', ['updated_at'], unique=False)

    # 创建异常告警表
    op.create_table(
        'exception_alerts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('alert_id', sa.String(length=64), nullable=False),
        sa.Column('alert_type', sa.String(length=50), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('pattern_id', sa.Integer(), nullable=True),
        sa.Column('exception_log_ids', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('acknowledged_by', sa.String(length=64), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_by', sa.String(length=64), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('notification_sent', sa.Boolean(), nullable=False),
        sa.Column('notification_channels', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['pattern_id'], ['exception_patterns.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # 创建异常告警表的索引
    op.create_index(op.f('ix_exception_alerts_id'), 'exception_alerts', ['id'], unique=False)
    op.create_index('ix_exception_alerts_alert_id', 'exception_alerts', ['alert_id'], unique=True)
    op.create_index('ix_exception_alerts_alert_type', 'exception_alerts', ['alert_type'], unique=False)
    op.create_index('ix_exception_alerts_severity', 'exception_alerts', ['severity'], unique=False)
    op.create_index('ix_exception_alerts_status', 'exception_alerts', ['status'], unique=False)
    op.create_index('ix_exception_alerts_pattern_id', 'exception_alerts', ['pattern_id'], unique=False)
    op.create_index('ix_exception_alerts_created_at', 'exception_alerts', ['created_at'], unique=False)
    op.create_index('ix_exception_alerts_updated_at', 'exception_alerts', ['updated_at'], unique=False)
    op.create_index('ix_exception_alerts_notification_sent', 'exception_alerts', ['notification_sent'], unique=False)

    # 创建异常指标表
    op.create_table(
        'exception_metrics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('time_window', sa.String(length=20), nullable=False),
        sa.Column('window_start', sa.DateTime(), nullable=False),
        sa.Column('window_end', sa.DateTime(), nullable=False),
        sa.Column('total_exceptions', sa.Integer(), nullable=False),
        sa.Column('unique_tracebacks', sa.Integer(), nullable=False),
        sa.Column('client_errors_4xx', sa.Integer(), nullable=False),
        sa.Column('server_errors_5xx', sa.Integer(), nullable=False),
        sa.Column('application_exceptions', sa.Integer(), nullable=False),
        sa.Column('http_exceptions', sa.Integer(), nullable=False),
        sa.Column('validation_exceptions', sa.Integer(), nullable=False),
        sa.Column('database_exceptions', sa.Integer(), nullable=False),
        sa.Column('exceptions_from_authenticated_users', sa.Integer(), nullable=False),
        sa.Column('exceptions_from_anonymous_users', sa.Integer(), nullable=False),
        sa.Column('top_endpoints', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('top_error_codes', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # 创建异常指标表的索引
    op.create_index(op.f('ix_exception_metrics_id'), 'exception_metrics', ['id'], unique=False)
    op.create_index('ix_exception_metrics_time_window', 'exception_metrics', ['time_window'], unique=False)
    op.create_index('ix_exception_metrics_window_start', 'exception_metrics', ['window_start'], unique=False)
    op.create_index('ix_exception_metrics_window_end', 'exception_metrics', ['window_end'], unique=False)
    op.create_index('ix_exception_metrics_created_at', 'exception_metrics', ['created_at'], unique=False)


def downgrade():
    # 删除异常指标表
    op.drop_table('exception_metrics')
    
    # 删除异常告警表
    op.drop_table('exception_alerts')
    
    # 删除异常模式表
    op.drop_table('exception_patterns')
    
    # 删除异常日志表
    op.drop_table('exception_logs')