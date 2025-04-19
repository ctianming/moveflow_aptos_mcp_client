"""
MoveFlow Aptos MCP 客户端配置模块
统一管理配置变量如网络、节点URL等
"""
import os
import json
from typing import Dict, Any, Optional

# 默认配置
DEFAULT_CONFIG = {
    "network": "mainnet",
    "node_url": "https://fullnode.mainnet.aptoslabs.com/v1",
    "read_only": True,
    # 使用正确的相对路径
    "server_path": "D:/projects/AI/mcp/moveflow_aptos_mcp/moveflow_aptos_mcp_server/build/index.js",
    # 服务器配置
    "server_type": "stdio",  # 'stdio' 或 'sse'
    "server_config": {
        # stdio 配置
        "command": "node",
        "args": ["D:/projects/AI/mcp/moveflow_aptos_mcp/moveflow_aptos_mcp_server/build/index.js"],
        "env": {},
        # sse 配置
        "url": "http://localhost:8080/sse"
    }
}

# 配置文件路径
CONFIG_FILE_PATH = os.path.expanduser("~/.moveflow/config.json")

_config = None


def load_config() -> Dict[str, Any]:
    """
    加载配置，按优先级：
    1. 环境变量
    2. 配置文件
    3. 默认值
    """
    global _config
    if _config is not None:
        return _config

    config = DEFAULT_CONFIG.copy()

    # 尝试从配置文件加载
    try:
        if os.path.exists(CONFIG_FILE_PATH):
            with open(CONFIG_FILE_PATH, "r") as f:
                file_config = json.load(f)
                config.update(file_config)
    except Exception as e:
        print(f"警告：无法加载配置文件 {CONFIG_FILE_PATH}: {e}")

    # 从环境变量覆盖
    env_mapping = {
        "APTOS_NETWORK": "network",
        "APTOS_NODE_URL": "node_url",
        "MOVEFLOW_READ_ONLY": "read_only",
        "MOVEFLOW_SERVER_PATH": "server_path"
    }

    for env_var, config_key in env_mapping.items():
        if env_var in os.environ:
            # 特殊处理布尔值
            if config_key == "read_only" and isinstance(config[config_key], bool):
                config[config_key] = os.environ[env_var].lower() == "true"
            else:
                config[config_key] = os.environ[env_var]

    _config = config
    return config


def save_config(config: Dict[str, Any]) -> None:
    """保存配置到文件"""
    global _config
    _config = config

    # 确保目录存在
    os.makedirs(os.path.dirname(CONFIG_FILE_PATH), exist_ok=True)
    
    with open(CONFIG_FILE_PATH, "w") as f:
        json.dump(config, f, indent=2)


def get_network() -> str:
    """获取当前网络配置"""
    return load_config()["network"]


def get_node_url() -> str:
    """获取节点URL配置"""
    return load_config()["node_url"]


def get_read_only() -> bool:
    """获取只读模式配置"""
    return load_config()["read_only"]


def get_server_path() -> str:
    """获取服务器路径配置"""
    return load_config()["server_path"]


def get_server_type() -> str:
    """获取服务器连接类型 (stdio 或 sse)"""
    return load_config()["server_type"]


def get_server_config() -> Dict[str, Any]:
    """获取服务器配置"""
    return load_config()["server_config"]


def set_server_config(config_type: str, config: Dict[str, Any]) -> None:
    """设置服务器配置
    
    Args:
        config_type: 'stdio' 或 'sse'
        config: 服务器配置
    """
    full_config = load_config()
    full_config["server_type"] = config_type
    full_config["server_config"] = config
    save_config(full_config)


def update_config(key: str, value: Any) -> None:
    """更新单个配置项"""
    config = load_config()
    config[key] = value
    save_config(config)
