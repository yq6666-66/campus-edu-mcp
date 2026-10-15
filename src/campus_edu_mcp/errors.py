"""项目统一异常。"""

from __future__ import annotations


class ProjectError(Exception):
    """所有项目异常的基类。"""

    exit_code = 1


class ConfigError(ProjectError):
    """配置缺失或非法。"""

    exit_code = 2


class GuardViolation(ProjectError):
    """请求不在只读白名单内，已被拦截。"""

    exit_code = 1


class SessionMissing(ProjectError):
    """尚未导入会话。"""

    exit_code = 3


class SessionExpired(ProjectError):
    """会话已失效，需要重新导入。"""

    exit_code = 3


class UpstreamError(ProjectError):
    """教务系统返回了无法解析或异常的响应。"""

    exit_code = 3


class StorageError(ProjectError):
    """本地加密存储不可用。"""

    exit_code = 1
