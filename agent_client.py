#!/usr/bin/env python3
"""
结合Agent的MoveFlow Aptos MCP客户端
该客户端使用OpenAI与MCP服务器交互，提供更智能的交互体验
"""
import os
import json
import asyncio
import dotenv
import aiohttp
import copy
import pendulum
from typing import Dict, Any, List, Optional, Protocol, runtime_checkable, Tuple
from contextlib import AsyncExitStack
from abc import ABC, abstractmethod

# MCP通信库
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# OpenAI集成 - 使用异步客户端
from openai import AsyncOpenAI

# 加载配置
dotenv.load_dotenv()

class TimeAwareHelper:
    """时间处理助手类，提供时间解析、格式化和转换功能"""
    
    def __init__(self):
        """初始化TimeAwareHelper类"""
        # 设置默认时区为UTC+8 (中国时区)
        self.default_timezone = "Asia/Shanghai"
        # 当前时间点，用于回答关于"现在"、"今天"等时间的查询
        self.now = pendulum.now(self.default_timezone)
        # 支持的时间格式
        self.time_formats = [
            "YYYY-MM-DD HH:mm:ss",
            "YYYY-MM-DD",
            "MM/DD/YYYY",
            "YYYY年MM月DD日",
            "MM月DD日",
            "HH:mm:ss",
            "HH:mm",
        ]
        # 支持的时间短语
        self.time_phrases = {
            "now": self.now,
            "today": self.now.start_of("day"),
            "tomorrow": self.now.add(days=1).start_of("day"),
            "yesterday": self.now.subtract(days=1).start_of("day"),
            "next week": self.now.add(weeks=1).start_of("day"),
            "last week": self.now.subtract(weeks=1).start_of("day"),
            "next month": self.now.add(months=1).start_of("day"),
            "last month": self.now.subtract(months=1).start_of("day"),
            "next year": self.now.add(years=1).start_of("day"),
            "last year": self.now.subtract(years=1).start_of("day"),
        }
    
    def update_current_time(self):
        """更新当前时间"""
        self.now = pendulum.now(self.default_timezone)
        # 更新时间短语字典
        self.time_phrases = {
            "now": self.now,
            "today": self.now.start_of("day"),
            "tomorrow": self.now.add(days=1).start_of("day"),
            "yesterday": self.now.subtract(days=1).start_of("day"),
            "next week": self.now.add(weeks=1).start_of("day"),
            "last week": self.now.subtract(weeks=1).start_of("day"),
            "next month": self.now.add(months=1).start_of("day"),
            "last month": self.now.subtract(months=1).start_of("day"),
            "next year": self.now.add(years=1).start_of("day"),
            "last year": self.now.subtract(years=1).start_of("day"),
        }
    
    def parse_time(self, time_str: str) -> Optional[pendulum.DateTime]:
        """解析时间字符串为pendulum.DateTime对象
        
        Args:
            time_str: 时间字符串，如 "2023-01-01", "now", "tomorrow" 等
            
        Returns:
            Optional[pendulum.DateTime]: 解析后的时间对象，若解析失败则为None
        """
        # 更新当前时间，确保使用最新时间
        self.update_current_time()
        
        # 检查是否是预定义的时间短语
        if time_str.lower() in self.time_phrases:
            return self.time_phrases[time_str.lower()]
        
        # 尝试用不同格式解析时间字符串
        for fmt in self.time_formats:
            try:
                return pendulum.from_format(time_str, fmt, tz=self.default_timezone)
            except ValueError:
                continue
        
        # 尝试自然语言处理
        try:
            # 处理相对时间表达式，如"3天后"、"下周五"等
            if "天后" in time_str:
                days = int(time_str.split("天后")[0].strip())
                return self.now.add(days=days)
            elif "周后" in time_str or "星期后" in time_str:
                weeks = int(time_str.split("周后")[0].strip())
                return self.now.add(weeks=weeks)
            elif "月后" in time_str:
                months = int(time_str.split("月后")[0].strip())
                return self.now.add(months=months)
            elif "年后" in time_str:
                years = int(time_str.split("年后")[0].strip())
                return self.now.add(years=years)
            elif "天前" in time_str:
                days = int(time_str.split("天前")[0].strip())
                return self.now.subtract(days=days)
            elif "周前" in time_str or "星期前" in time_str:
                weeks = int(time_str.split("周前")[0].strip())
                return self.now.subtract(weeks=weeks)
            elif "月前" in time_str:
                months = int(time_str.split("月前")[0].strip())
                return self.now.subtract(months=months)
            elif "年前" in time_str:
                years = int(time_str.split("年前")[0].strip())
                return self.now.subtract(years=years)
            # 处理"下周五"这样的表达式
            elif "下周" in time_str:
                day_of_week = self._parse_day_of_week(time_str.replace("下周", "").strip())
                if day_of_week:
                    return self.now.add(weeks=1).next(day_of_week)
            elif "本周" in time_str:
                day_of_week = self._parse_day_of_week(time_str.replace("本周", "").strip())
                if day_of_week:
                    target_day = self.now.start_of("week").add(days=day_of_week-1)
                    if target_day < self.now:  # 如果目标日已过，则取下周
                        target_day = target_day.add(weeks=1)
                    return target_day
                    
            # 如果都不是，则尝试用pendulum解析
            return pendulum.parse(time_str, tz=self.default_timezone)
        except (ValueError, TypeError):
            # 解析失败，返回None
            return None
    
    def _parse_day_of_week(self, day_str: str) -> Optional[int]:
        """解析星期几
        
        Args:
            day_str: 星期几的字符串表示，如"一"、"Monday"等
            
        Returns:
            Optional[int]: 星期几的数字表示(1-7)，若解析失败则为None
        """
        days_map = {
            "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7,
            "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4, 
            "friday": 5, "saturday": 6, "sunday": 7,
            "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7
        }
        
        day_lower = day_str.lower()
        for key, value in days_map.items():
            if key in day_lower:
                return value
        return None
    
    def format_time(self, dt: pendulum.DateTime, fmt: str = "YYYY-MM-DD HH:mm:ss") -> str:
        """格式化时间对象为字符串
        
        Args:
            dt: pendulum.DateTime对象
            fmt: 格式化字符串
            
        Returns:
            str: 格式化后的时间字符串
        """
        return dt.format(fmt)
    
    def get_timestamp(self, dt: Optional[pendulum.DateTime] = None) -> int:
        """获取时间戳（秒级）
        
        Args:
            dt: pendulum.DateTime对象，若为None则使用当前时间
            
        Returns:
            int: 时间戳（秒级）
        """
        if dt is None:
            dt = self.now
        return int(dt.timestamp())
    
    def timestamp_to_datetime(self, timestamp: int) -> pendulum.DateTime:
        """将时间戳转换为DateTime对象
        
        Args:
            timestamp: 时间戳（秒级）
            
        Returns:
            pendulum.DateTime: DateTime对象
        """
        return pendulum.from_timestamp(timestamp, tz=self.default_timezone)
    
    def format_timestamp(self, timestamp: int, fmt: str = "YYYY-MM-DD HH:mm:ss") -> str:
        """格式化时间戳为字符串
        
        Args:
            timestamp: 时间戳（秒级）
            fmt: 格式化字符串
            
        Returns:
            str: 格式化后的时间字符串
        """
        return self.format_time(self.timestamp_to_datetime(timestamp), fmt)
    
    def get_relative_time_description(self, dt: pendulum.DateTime) -> str:
        """获取相对时间描述，如"3天后"、"昨天"等
        
        Args:
            dt: pendulum.DateTime对象
            
        Returns:
            str: 相对时间描述
        """
        self.update_current_time()
        return dt.diff_for_humans(self.now)
    
    def extract_time_mentions(self, text: str) -> List[Tuple[str, Optional[pendulum.DateTime]]]:
        """从文本中提取时间提及
        
        Args:
            text: 输入文本
            
        Returns:
            List[Tuple[str, Optional[pendulum.DateTime]]]: 时间提及列表，每项为(提及文本, 解析后的时间对象)
        """
        # 这是一个简化版实现，实际应用中可能需要更复杂的自然语言处理技术
        time_mentions = []
        
        # 检查预定义的时间短语
        for phrase in self.time_phrases.keys():
            if phrase in text.lower():
                time_mentions.append((phrase, self.time_phrases[phrase]))
        
        # TODO: 实现更复杂的时间表达式提取
        # 这里可以使用正则表达式或者更高级的NLP技术来提取日期时间表达式
        
        return time_mentions
    
    def time_info_json(self) -> Dict[str, Any]:
        """获取当前时间信息的JSON表示
        
        Returns:
            Dict[str, Any]: 时间信息JSON
        """
        self.update_current_time()
        return {
            "current_time": {
                "iso": self.now.to_iso8601_string(),
                "timestamp": self.get_timestamp(),
                "formatted": self.format_time(self.now),
                "date": self.format_time(self.now, "YYYY-MM-DD"),
                "time": self.format_time(self.now, "HH:mm:ss"),
                "timezone": self.default_timezone,
                "day_of_week": self.now.day_of_week,
                "day_of_year": self.now.day_of_year,
                "week_of_year": self.now.week_of_year,
                "quarter": self.now.quarter,
            },
            "today": {
                "start": self.format_time(self.now.start_of("day")),
                "end": self.format_time(self.now.end_of("day")),
            },
            "tomorrow": {
                "formatted": self.format_time(self.now.add(days=1)),
                "timestamp": self.get_timestamp(self.now.add(days=1)),
            },
            "yesterday": {
                "formatted": self.format_time(self.now.subtract(days=1)),
                "timestamp": self.get_timestamp(self.now.subtract(days=1)),
            },
        }

class McpHub:
    """MCP服务器连接和管理核心类"""
    
    def __init__(self):
        """初始化McpHub类"""
        self.connections = {}
        self.exit_stack = AsyncExitStack()
        self.default_server_name = "moveflow-aptos"
        self.client_version = "1.0.0"  # 添加客户端版本信息
        self.connection_timeout = 30  # 设置默认连接超时时间为10秒
        self.connection_retries = 2  # 设置默认重试次数

    async def connect_to_server(self, name: str, config: Dict[str, Any], timeout: int = None, retries: int = None) -> bool:
        """连接到MCP服务器
        
        Args:
            name: 服务器名称
            config: 服务器配置，包括传输类型、命令、参数和环境变量
            timeout: 连接超时时间（秒），如果为None则使用默认值
            retries: 重试次数，如果为None则使用默认值
            
        Returns:
            bool: 连接是否成功
        """
        # 使用提供的超时参数或默认值
        timeout = timeout or self.connection_timeout
        retries = retries or self.connection_retries
        attempt = 0
        
        while attempt <= retries:
            attempt += 1
            try:
                # 移除已存在的连接（如果有）
                if name in self.connections:
                    print(f"移除已存在的服务器连接: {name}")
                    del self.connections[name]
                    
                if config.get("transportType") == "stdio":
                    command = config.get("command")
                    args = config.get("args", [])
                    env = config.get("env", {})
                    
                    # 创建服务器参数
                    server_params = StdioServerParameters(
                        command=command,
                        args=args,
                        env=env
                    )
                    
                    # 初始化MCP客户端对象
                    client = {
                        "identity": {
                            "name": "MoveflowAptosMcpClient",
                            "version": self.client_version,
                        },
                        "capabilities": {}
                    }
                    
                    # 建立连接，使用timeout
                    print(f"尝试连接到服务器 {name}... (尝试 {attempt}/{retries+1})")
                    stdio_transport = await asyncio.wait_for(
                        self.exit_stack.enter_async_context(stdio_client(server_params)),
                        timeout=timeout
                    )
                    self.stdio, self.write = stdio_transport
                    
                    # 使用客户端对象创建会话
                    self.session = await asyncio.wait_for(
                        self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write)),
                        timeout=timeout
                    )
                    
                    # 初始化会话
                    await asyncio.wait_for(self.session.initialize(), timeout=timeout)
                    
                    # 存储连接信息，包括客户端对象
                    self.connections[name] = {
                        "transport": "stdio",
                        "session": self.session,
                        "client": client,  # 存储客户端对象
                        "config": config,
                        "tools": None,  # 初始化为None，后续会加载工具列表
                        "status": "connected"
                    }
                    
                    # 加载工具列表
                    try:
                        await asyncio.wait_for(self.load_tools(name), timeout=timeout)
                    except asyncio.TimeoutError:
                        print(f"加载工具列表超时，但连接已建立")
                        # 连接成功但工具列表加载超时，可以稍后重试加载工具列表
                        pass
                    
                    print(f"已成功连接到服务器: {name}")
                    return True
                    
                elif config.get("transportType") == "sse":
                    url = config.get("url")
                    
                    # 初始化SSE客户端对象
                    client = {
                        "identity": {
                            "name": "MoveflowAptosMcpClient",
                            "version": self.client_version,
                        },
                        "capabilities": {}
                    }
                    
                    # 使用超时参数
                    timeout_client = aiohttp.ClientTimeout(total=timeout)
                    async with aiohttp.ClientSession(timeout=timeout_client) as session:
                        async with session.get(url) as response:
                            if response.status == 200:
                                self.connections[name] = {
                                    "transport": "sse",
                                    "session": session,
                                    "client": client,  # 存储客户端对象
                                    "url": url,
                                    "config": config,
                                    "tools": None,  # 初始化为None，后续会加载工具列表
                                    "status": "connected"
                                }
                                
                                # 尝试加载工具列表
                                try:
                                    await asyncio.wait_for(self.load_tools(name), timeout=timeout)
                                except asyncio.TimeoutError:
                                    print(f"加载工具列表超时，但连接已建立")
                                    pass
                                
                                print(f"已成功连接到服务器: {name} (SSE)")
                                return True
                            else:
                                print(f"连接到服务器失败: {name}, 状态码: {response.status}")
                                if attempt > retries:
                                    return False
                                else:
                                    print(f"将在1秒后重试... ({attempt}/{retries+1})")
                                    await asyncio.sleep(1)
                                    continue
                else:
                    print(f"不支持的传输类型: {config.get('transportType')}")
                    return False
                    
            except asyncio.TimeoutError:
                print(f"连接到服务器 {name} 超时 (尝试 {attempt}/{retries+1})")
                if attempt > retries:
                    print(f"连接失败: 达到最大重试次数")
                    # 更新连接状态为断开
                    if name in self.connections:
                        self.connections[name]["status"] = "disconnected"
                        self.connections[name]["error"] = "连接超时"
                    return False
                else:
                    print(f"将在1秒后重试... ({attempt}/{retries+1})")
                    await asyncio.sleep(1)
            except Exception as e:
                print(f"连接到服务器 {name} 时出错: {str(e)} (尝试 {attempt}/{retries+1})")
                # 更新连接状态为断开
                if name in self.connections:
                    self.connections[name]["status"] = "disconnected"
                    self.connections[name]["error"] = str(e)
                if attempt > retries:
                    return False
                else:
                    print(f"将在1秒后重试... ({attempt}/{retries+1})")
                    await asyncio.sleep(1)

    async def load_tools(self, server_name: str) -> List[Any]:
        """加载服务器提供的工具列表
        
        Args:
            server_name: 服务器名称
            
        Returns:
            List[Any]: 工具列表
        """
        connection = self.connections.get(server_name)
        if not connection:
            print(f"未找到服务器连接: {server_name}")
            return []
            
        try:
            if connection["transport"] == "stdio":
                response = await connection["session"].list_tools()
                tools = response.tools
                connection["tools"] = tools
                return tools
            elif connection["transport"] == "sse":
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{connection['url']}/tools/list") as response:
                        if response.status == 200:
                            tools = await response.json()
                            connection["tools"] = tools
                            return tools
                        else:
                            print(f"获取工具列表失败: {server_name}, 状态码: {response.status}")
                            return []
        except Exception as e:
            print(f"获取服务器 {server_name} 的工具列表时出错: {str(e)}")
            return []

    async def call_tool(self, server_name: str, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        """调用MCP工具
        
        Args:
            server_name: 服务器名称
            tool_name: 工具名称
            tool_args: 工具参数
            
        Returns:
            Any: 工具调用结果
        """
        connection = self.connections.get(server_name)
        if not connection:
            raise Exception(f"未找到服务器连接: {server_name}")

        try:
            print(f"调用工具: {tool_name}, 参数: {json.dumps(tool_args, ensure_ascii=False)}")
            
            if connection["transport"] == "stdio":
                result = await connection["session"].call_tool(tool_name, tool_args)
                return result.content
            elif connection["transport"] == "sse":
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{connection['url']}/tools/call", 
                        json={"toolName": tool_name, "toolArgs": tool_args}
                    ) as response:
                        if response.status == 200:
                            return await response.json()
                        else:
                            error_text = await response.text()
                            raise Exception(f"调用工具失败: {response.status}, {error_text}")
        except Exception as e:
            print(f"调用工具 {tool_name} 时出错: {str(e)}")
            raise

    async def get_resources(self, server_name: str) -> List[Any]:
        """获取服务器提供的资源列表
        
        Args:
            server_name: 服务器名称
            
        Returns:
            List[Any]: 资源列表
        """
        connection = self.connections.get(server_name)
        if not connection:
            print(f"未找到服务器连接: {server_name}")
            return []
            
        try:
            if connection["transport"] == "stdio":
                response = await connection["session"].list_resources()
                return response.resources if hasattr(response, "resources") else []
            elif connection["transport"] == "sse":
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{connection['url']}/resources/list") as response:
                        if response.status == 200:
                            data = await response.json()
                            return data.get("resources", [])
                        else:
                            print(f"获取资源列表失败: {server_name}, 状态码: {response.status}")
                            return []
        except Exception as e:
            print(f"获取服务器 {server_name} 的资源列表时出错: {str(e)}")
            return []

    async def read_resource(self, server_name: str, uri: str) -> Any:
        """读取资源内容
        
        Args:
            server_name: 服务器名称
            uri: 资源URI
            
        Returns:
            Any: 资源内容
        """
        connection = self.connections.get(server_name)
        if not connection:
            raise Exception(f"未找到服务器连接: {server_name}")

        try:
            if connection["transport"] == "stdio":
                response = await connection["session"].read_resource(uri)
                return response.contents
            elif connection["transport"] == "sse":
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{connection['url']}/resources/read", 
                        json={"uri": uri}
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            return data.get("contents", [])
                        else:
                            error_text = await response.text()
                            raise Exception(f"读取资源失败: {response.status}, {error_text}")
        except Exception as e:
            print(f"读取资源 {uri} 时出错: {str(e)}")
            raise

    async def get_all_servers(self) -> List[str]:
        """获取所有已连接的服务器名称
        
        Returns:
            List[str]: 服务器名称列表
        """
        return list(self.connections.keys())

    async def cleanup(self):
        """清理资源并确保所有连接正确关闭"""
        print("正在清理MCP连接资源...")
        try:
            # 确保各个连接都被清理
            for server_name, connection in list(self.connections.items()):
                if connection["transport"] == "stdio" and "session" in connection:
                    print(f"正在关闭服务器连接: {server_name}")
                    # 尝试正常关闭会话，但不等待结果
                    try:
                        session = connection.get("session")
                        if session and hasattr(session, "shutdown"):
                            try:
                                await asyncio.shield(asyncio.wait_for(
                                    session.shutdown(), 
                                    timeout=0.5  # 短超时，防止挂起
                                ))
                            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                                # 忽略超时和其他错误
                                pass
                    except Exception as e:
                        print(f"关闭服务器 {server_name} 会话时出错 (可忽略): {str(e)}")
                        
            # 清空连接字典，防止后续访问
            self.connections = {}
            
            # 最后一步：关闭AsyncExitStack，使用shield避免取消问题
            if hasattr(self, 'exit_stack'):
                try:
                    # 使用shield保护任务不被取消
                    await asyncio.shield(asyncio.wait_for(
                        self.exit_stack.aclose(),
                        timeout=1.0
                    ))
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception) as e:
                    # 忽略超时和取消错误
                    print(f"关闭资源栈时出错 (可忽略): {type(e).__name__}")
                    
        except Exception as e:
            print(f"清理资源过程中发生错误 (可忽略): {str(e)}")
        finally:
            # 确保连接字典被清空
            self.connections = {}

@runtime_checkable
class AIService(Protocol):
    """AI服务提供商协议，定义了所有AI服务需要实现的方法"""
    
    async def initialize(self) -> bool:
        """初始化AI服务
        
        Returns:
            bool: 初始化是否成功
        """
        ...
        
    async def generate_response(self, 
                                query: str, 
                                functions: List[Dict[str, Any]], 
                                **kwargs) -> Any:
        """生成响应
        
        Args:
            query: 用户查询
            functions: 可用函数列表
            
        Returns:
            Any: AI服务响应
        """
        ...
        
    async def process_response(self, 
                              response: Any, 
                              server_name: str, 
                              session: Any) -> str:
        """处理AI服务响应
        
        Args:
            response: AI服务响应
            server_name: 服务器名称
            session: 服务器会话
            
        Returns:
            str: 处理结果
        """
        ...
        
    def get_service_name(self) -> str:
        """获取服务名称
        
        Returns:
            str: 服务名称
        """
        ...

class BaseAIService(ABC):
    """AI服务提供商基类"""
    
    def __init__(self):
        self.is_initialized = False
        
    @abstractmethod
    async def initialize(self) -> bool:
        """初始化AI服务"""
        pass
        
    @abstractmethod
    async def generate_response(self, 
                                query: str, 
                                functions: List[Dict[str, Any]], 
                                **kwargs) -> Any:
        """生成响应"""
        pass
        
    @abstractmethod
    async def process_response(self, 
                              response: Any, 
                              server_name: str, 
                              session: Any) -> str:
        """处理AI服务响应"""
        pass
        
    @abstractmethod
    def get_service_name(self) -> str:
        """获取服务名称"""
        pass
        
    def _preprocess_tool_args(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """预处理工具参数，处理特殊参数映射
        
        Args:
            tool_name: 工具名称
            args: 工具参数
            
        Returns:
            Dict[str, Any]: 处理后的工具参数
        """
        # 创建参数的副本，避免修改原始参数
        processed_args = args.copy()
        
        # 处理 create-stream 工具的特殊参数
        if tool_name == "create-stream":
            # 将数值型参数转换为字符串，以避免BigInt序列化问题
            numeric_fields = ["depositAmount", "cliffAmount", "startTime", "stopTime", "interval", "autoWithdrawInterval"]
            for field in numeric_fields:
                if field in processed_args and processed_args[field] is not None:
                    processed_args[field] = str(processed_args[field])
                    
            # 确保布尔值被正确处理
            boolean_fields = ["autoWithdraw", "isFa", "execute"]
            for field in boolean_fields:
                if field in processed_args:
                    # 确保是布尔值而不是字符串
                    if isinstance(processed_args[field], str):
                        processed_args[field] = processed_args[field].lower() == "true"
                        
        # 处理 batch-create-streams 工具的特殊参数
        elif tool_name == "batch-create-streams":
            # 处理数组中的数值
            if "depositAmounts" in processed_args and processed_args["depositAmounts"]:
                processed_args["depositAmounts"] = [str(amt) for amt in processed_args["depositAmounts"]]
            
            if "cliffAmounts" in processed_args and processed_args["cliffAmounts"]:
                processed_args["cliffAmounts"] = [str(amt) for amt in processed_args["cliffAmounts"]]
                
            # 处理单个数值
            single_numeric_fields = ["startTime", "stopTime", "interval", "autoWithdrawInterval"]
            for field in single_numeric_fields:
                if field in processed_args and processed_args[field] is not None:
                    processed_args[field] = str(processed_args[field])
        
        return processed_args

    def _call_tool(self, tool_name: str, tool_args: dict) -> str:
        """调用工具
        
        Args:
            tool_name: 工具名称
            tool_args: 工具参数
            
        Returns:
            str: 工具调用结果
        """
        try:
            # 转换参数中的字符串数字为整数
            for key, value in tool_args.items():
                if isinstance(value, str) and value.isdigit():
                    try:
                        tool_args[key] = int(value)
                    except ValueError:
                        pass  # 保持原值

            # 预处理参数中可能存在的BigInt值
            def convert_args_bigint(obj):
                if isinstance(obj, dict):
                    return {k: convert_args_bigint(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_args_bigint(item) for item in obj]
                elif isinstance(obj, (int, float)) and abs(obj) > 9007199254740991:
                    return str(obj)
                else:
                    return obj

            tool_args = convert_args_bigint(tool_args)

            # 执行工具调用
            tool_result = self._execute_tool_call(tool_name, tool_args)
            
            # 格式化结果为字符串
            result_str = self._format_tool_result(tool_result)
            if self.verbose:
                print(f"[工具结果]: {result_str}")
            return result_str
        except Exception as e:
            error_msg = f"工具调用失败: {e}"
            if self.verbose:
                print(f"[错误] {error_msg}")
            return f"[错误] {error_msg}"

class OpenAIService(BaseAIService):
    """OpenAI服务实现"""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        """初始化OpenAI服务
        
        Args:
            api_key: OpenAI API密钥
            base_url: OpenAI基础URL
            model: 使用的模型名称
        """
        super().__init__()
        self.api_key = api_key or os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("BASE_URL") or os.getenv("OPENAI_BASE_URL")
        self.model = model or os.getenv("MODEL", "gpt-4")
        self.client = None
        
    async def initialize(self) -> bool:
        """初始化OpenAI客户端
        
        Returns:
            bool: 初始化是否成功
        """
        try:
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
            self.is_initialized = True
            return True
        except Exception as e:
            print(f"初始化OpenAI客户端失败: {str(e)}")
            return False
            
    async def generate_response(self, 
                              query: str, 
                              functions: List[Dict[str, Any]], 
                              **kwargs) -> Any:
        """生成OpenAI响应
        
        Args:
            query: 用户查询
            functions: 可用函数列表
            
        Returns:
            Any: OpenAI API响应
        """
        if not self.is_initialized:
            await self.initialize()
            
        messages = [{"role": "user", "content": query}]
        
        try:
            # 使用异步调用OpenAI API
            completion = await self.client.chat.completions.create(
                model=kwargs.get("model", self.model),
                messages=messages,
                tools=[{"type": "function", "function": func} for func in functions],
                tool_choice="auto"
            )
            return completion
            
        except Exception as e:
            print(f"调用OpenAI API时出错: {str(e)}")
            raise
            
    async def process_response(self, 
                             response: Any, 
                             server_name: str, 
                             session: Any) -> str:
        """处理OpenAI API响应，并执行必要的工具调用
        
        Args:
            response: OpenAI API响应
            server_name: 服务器名称
            session: 服务器会话
            
        Returns:
            处理结果
        """
        if not session:
            return "错误: 无法获取服务器会话"
            
        # 初始化结果文本
        final_text = []
        
        # 如果响应包含消息内容
        if hasattr(response, 'choices') and response.choices:
            message = response.choices[0].message
            
            # 添加文本内容到结果中
            if message.content:
                final_text.append(message.content)
                
            # 处理工具调用
            if hasattr(message, 'tool_calls') and message.tool_calls:
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    
                    # 预处理工具参数
                    processed_args = self._preprocess_tool_args(tool_name, tool_args)
                    
                    try:
                        # 调用工具
                        result = await session.call_tool(tool_name, processed_args)
                        
                        # 处理结果，确保可以正确序列化大整数
                        result_str = self._format_tool_result(result)
                        final_text.append(f"\n[调用工具 {tool_name}，结果: {result_str}]")
                    except Exception as e:
                        error_msg = f"\n[调用工具 {tool_name} 失败: {str(e)}]"
                        final_text.append(error_msg)
                        
        # 返回最终结果
        return "\n".join(final_text) if final_text else "处理完成，但没有返回结果"
    
    def _format_tool_result(self, result: Any) -> str:
        """格式化工具调用结果，处理BigInt序列化问题
        
        Args:
            result: 工具调用结果
            
        Returns:
            str: 格式化的结果字符串
        """
        try:
            # 递归处理对象中的BigInt值，将其转换为字符串
            def convert_bigint(obj):
                if isinstance(obj, dict):
                    return {k: convert_bigint(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_bigint(item) for item in obj]
                elif isinstance(obj, (int, float)) and abs(obj) > 9007199254740991:  # JavaScript最大安全整数
                    return str(obj)
                else:
                    return obj
            
            # 首先尝试转换任何BigInt值
            result_converted = convert_bigint(result)
            
            # 如果结果是字典且包含content字段，则尝试处理content
            if isinstance(result_converted, dict) and "content" in result_converted:
                content_list = result_converted.get("content", [])
                
                # 处理文本内容
                if content_list and isinstance(content_list, list):
                    # 提取文本内容
                    text_content = []
                    for item in content_list:
                        if isinstance(item, dict) and "text" in item:
                            # 尝试解析文本内容中的JSON，如果是有效的JSON，则再次处理BigInt并美化输出
                            try:
                                text_obj = json.loads(item["text"])
                                text_obj = convert_bigint(text_obj)
                                
                                # 检查是否为交易相关JSON
                                if "rawTransaction" in text_obj:
                                    # 提取重要信息，美化展示
                                    tx = text_obj["rawTransaction"]
                                    if "payload" in tx and "entryFunction" in tx["payload"]:
                                        entry_func = tx["payload"]["entryFunction"]
                                        args = entry_func.get("args", [])
                                        
                                        # 提取关键信息
                                        stream_name = next((arg["value"] for arg in args if isinstance(arg.get("value"), str) and len(args) > 0), "未知")
                                        recipient = "未知"
                                        deposit_amount = "未知"
                                        
                                        # 查找接收地址
                                        for i, arg in enumerate(args):
                                            if "data" in arg and i > 2:  # 通常接收地址是第4个参数
                                                recipient = "0x" + "".join([f"{v:02x}" for k, v in arg["data"].items() if k.isdigit()])
                                                break
                                        
                                        # 查找金额
                                        for arg in args:
                                            if "value" in arg and isinstance(arg["value"], str) and arg["value"].isdigit() and int(arg["value"]) > 1000000:
                                                deposit_amount = str(int(arg["value"]) / 100000000) + " APT"
                                                break
                                        
                                        # 格式化时间
                                        start_time = None
                                        end_time = None
                                        for i, arg in enumerate(args):
                                            if "value" in arg and isinstance(arg["value"], str) and arg["value"].isdigit():
                                                value = int(arg["value"])
                                                if 1600000000 < value < 2000000000:  # 时间戳范围
                                                    if not start_time:
                                                        start_time = value
                                                    elif not end_time:
                                                        end_time = value
                                                        
                                        duration = "未知"
                                        if start_time and end_time:
                                            duration = f"{(end_time - start_time) // 86400} 天"
                                        
                                        formatted_text = f"""
===== 支付流创建交易 =====
🔹 流名称: {stream_name}
🔹 接收地址: {recipient}
🔹 金额: {deposit_amount}
🔹 持续时间: {duration}
🔹 交易哈希: {tx.get("hash", "等待提交获取")}
🔹 状态: 已创建，等待签名和提交

交易详情已准备好，可以通过客户端签名并提交到链上。
"""
                                        return formatted_text
                                
                                # 如果是已提交的交易结果
                                if "status" in text_obj and text_obj["status"] == "submitted":
                                    formatted_text = f"""
===== 交易已提交 =====
{text_obj.get("message", "")}
🔹 交易哈希: {text_obj.get("transactionHash", "未知")}
🔹 查看链上交易: {text_obj.get("explorerLink", "未知")}
🔹 消耗Gas: {text_obj.get("gasUsed", "未知")}
"""
                                    return formatted_text
                                    
                                # 默认美化输出JSON
                                return json.dumps(text_obj, ensure_ascii=False, indent=2)
                            except json.JSONDecodeError:
                                # 如果不是有效的JSON，直接添加文本
                                text_content.append(item["text"])
                        elif hasattr(item, "text"):  # 如果是对象
                            text_content.append(item.text)
                            
                    return "\n".join(text_content)
                    
            # 如果不是上述情况，尝试使用自定义JSON编码
            return json.dumps(result_converted, ensure_ascii=False, indent=2)
            
        except Exception as e:
            # 如果JSON序列化失败，尝试直接返回字符串表示
            try:
                if isinstance(result, dict):
                    # 当处理字典时，更安全的方式是预处理字典中的所有值
                    safe_dict = {}
                    for k, v in result.items():
                        try:
                            if isinstance(v, (int, float)) and abs(v) > 9007199254740991:
                                safe_dict[k] = str(v)
                            else:
                                safe_dict[k] = v
                        except:
                            safe_dict[k] = str(v)
                    return json.dumps(safe_dict, default=str, ensure_ascii=False, indent=2)
                return str(result)
            except:
                return f"[无法序列化的结果: {type(result).__name__}]"
                
    def get_service_name(self) -> str:
        """获取服务名称
        
        Returns:
            str: 服务名称
        """
        return "OpenAI"

class AnthropicService(BaseAIService):
    """Anthropic (Claude) 服务实现"""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        """初始化Anthropic服务
        
        Args:
            api_key: Anthropic API密钥
            base_url: Anthropic基础URL
            model: 使用的模型名称
        """
        super().__init__()
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.base_url = base_url or os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-3-opus-20240229")
        self.client = None
        
    async def initialize(self) -> bool:
        """初始化Anthropic客户端
        
        Returns:
            bool: 初始化是否成功
        """
        try:
            # 因为 aiohttp 是通用HTTP客户端，我们可以直接使用它
            # 而不是依赖特定的Anthropic库
            self.is_initialized = True
            return True
        except Exception as e:
            print(f"初始化Anthropic客户端失败: {str(e)}")
            return False
            
    async def generate_response(self, 
                              query: str, 
                              functions: List[Dict[str, Any]], 
                              **kwargs) -> Any:
        """生成Anthropic响应
        
        Args:
            query: 用户查询
            functions: 可用函数列表
            
        Returns:
            Any: Anthropic API响应
        """
        if not self.is_initialized:
            await self.initialize()
            
        # 构建Anthropic API请求
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        # 将OpenAI格式的functions转换为Anthropic格式的tools
        tools = []
        for func in functions:
            tools.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {})
            })
            
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": [{"role": "user", "content": query}],
            "tools": tools,
            "max_tokens": 1024
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/v1/messages", 
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result
                    else:
                        error_text = await response.text()
                        raise Exception(f"Anthropic API错误: {response.status}, {error_text}")
        except Exception as e:
            print(f"调用Anthropic API时出错: {str(e)}")
            raise
            
    async def process_response(self, 
                             response: Any, 
                             server_name: str, 
                            session: Any) -> str:
        """处理Anthropic API响应，并执行必要的工具调用
        
        Args:
            response: Anthropic API响应
            server_name: 服务器名称
            session: 服务器会话
            
        Returns:
            处理结果
        """
        if not session:
            return "错误: 无法获取服务器会话"
            
        # 初始化结果文本
        final_text = []
        
        # 处理Anthropic响应
        content = response.get("content", [])
        for block in content:
            if block["type"] == "text":
                final_text.append(block["text"])
            elif block["type"] == "tool_use":
                tool_name = block["name"]
                tool_args = block["input"]
                
                # 预处理工具参数
                processed_args = self._preprocess_tool_args(tool_name, tool_args)
                
                try:
                    # 调用工具
                    result = await session.call_tool(tool_name, processed_args)
                    final_text.append(f"\n[调用工具 {tool_name}，结果: {result}]")
                except Exception as e:
                    error_msg = f"\n[调用工具 {tool_name} 失败: {str(e)}]"
                    final_text.append(error_msg)
                    
        # 返回最终结果
        return "\n".join(final_text) if final_text else "处理完成，但没有返回结果"
        
    def get_service_name(self) -> str:
        """获取服务名称
        
        Returns:
            str: 服务名称
        """
        return "Anthropic (Claude)"

class AIServiceFactory:
    """AI服务工厂类，用于创建不同的AI服务实例"""
    
    @staticmethod
    def create_service(service_type: str = None, **kwargs) -> BaseAIService:
        """创建AI服务实例
        
        Args:
            service_type: 服务类型，支持'openai'和'anthropic'
            **kwargs: 其他参数
            
        Returns:
            BaseAIService: AI服务实例
        """
        # 如果未指定服务类型，则从环境变量中获取，默认为'openai'
        service_type = service_type or os.getenv("AI_SERVICE", "openai").lower()
        
        if service_type == "openai":
            return OpenAIService(
                api_key=kwargs.get("api_key"),
                base_url=kwargs.get("base_url"),
                model=kwargs.get("model")
            )
        elif service_type == "anthropic" or service_type == "claude":
            return AnthropicService(
                api_key=kwargs.get("api_key"),
                base_url=kwargs.get("base_url"),
                model=kwargs.get("model")
            )
        else:
            raise ValueError(f"不支持的AI服务类型: {service_type}")

class OpenAIAgent:
    """集成AI服务的MCP客户端"""
    
    def __init__(self, mcp_hub: McpHub, service_type: str = None, **kwargs):
        """初始化AI代理
        
        Args:
            mcp_hub: McpHub实例
            service_type: AI服务类型，支持'openai'和'anthropic'
            **kwargs: 其他参数
        """
        self.mcp_hub = mcp_hub
        
        # 创建AI服务
        self.ai_service = AIServiceFactory.create_service(service_type, **kwargs)
        
    async def process_query(self, query: str, server_name: Optional[str] = None) -> str:
        """处理用户查询并调用相应的工具
        
        Args:
            query: 用户查询
            server_name: 服务器名称，如果为None则使用默认服务器
            
        Returns:
            str: 处理结果
        """
        if server_name is None:
            server_name = self.mcp_hub.default_server_name
            
        if server_name not in await self.mcp_hub.get_all_servers():
            return f"错误: 服务器 {server_name} 未连接"
            
        try:
            # 特殊处理某些系统查询，比如状态检查
            if "当前是否是读写模式" in query or"是否配置了私钥" in query:
                return await self.check_server_status(server_name)
                
            # 获取连接信息
            connection = self.mcp_hub.connections.get(server_name)
            session = connection.get("session")
            
            if not session:
                return "错误: 无法获取服务器会话"
            
            # 获取可用工具列表
            tools_response = await session.list_tools()
            if not tools_response or not hasattr(tools_response, 'tools') or not tools_response.tools:
                return "错误: 无法获取服务器工具列表"
                
            # 构建函数调用参数
            functions = []
            for tool in tools_response.tools:
                description = getattr(tool, 'description', '') or f"Tool {tool.name}"
                functions.append({
                    "name": tool.name,
                    "description": description, 
                    "parameters": tool.inputSchema
                })
            
            if not functions:
                return "错误: 无法构建工具函数列表"
                
            # 调用AI服务生成响应
            response = await self.ai_service.generate_response(query, functions)
            
            # 解析响应并调用工具
            return await self.ai_service.process_response(response, server_name, session)
            
        except Exception as e:
            import traceback
            print(f"处理查询详细错误: {traceback.format_exc()}")
            return f"处理查询时发生错误: {str(e)}"

    async def check_server_status(self, server_name: str) -> str:
        """检查服务器状态，包括读写模式和私钥配置
        
        Args:
            server_name: 服务器名称
            
        Returns:
            str: 服务器状态信息
        """
        try:
            connection = self.mcp_hub.connections.get(server_name)
            if not connection:
                return f"错误: 服务器 {server_name} 未连接"
                
            config = connection.get("config", {})
            env = config.get("env", {})
            
            # 检查读写模式
            read_only_mode = env.get("READ_ONLY_MODE", "true").lower() == "true"
            
            # 检查私钥配置
            has_private_key = bool(env.get("APTOS_PRIVATE_KEY", "").strip())
            
            # 构建状态信息
            if read_only_mode:
                mode_text = "**只读模式**"
                action_text = "我可以帮助你查询信息或生成交易数据，但无法直接执行需要私钥签名的操作（如发送交易）。"
            else:
                if has_private_key:
                    mode_text = "**读写模式**，并且已配置私钥"
                    action_text = "我可以执行需要签名的交易操作。"
                else:
                    mode_text = "**读写模式**，但未配置私钥"
                    action_text = "虽然已设置为读写模式，但由于缺少私钥，我仍然无法执行需要签名的交易操作。"
            
            return f"""我当前处于{mode_text}。{action_text}

如果你需要执行交易，{'我可以直接帮你处理' if not read_only_mode and has_private_key else '可以让我生成交易数据，然后你使用私钥签名并提交'}。

服务器配置信息:
- 读写模式: {'禁用 (只读)' if read_only_mode else '启用 (读写)'}
- 私钥配置: {'已配置' if has_private_key else '未配置'}"""
            
        except Exception as e:
            return f"检查服务器状态时出错: {str(e)}"

async def setup_mcp_server():
    """设置MCP服务器连接"""
    # 创建McpHub实例
    mcp_hub = McpHub()
    
    try:
        # 加载私钥和其他敏感信息
        aptos_private_key = os.getenv("APTOS_PRIVATE_KEY", "")
        
        # 直接配置 moveflow-aptos 服务器
        server_name = "moveflow-aptos"
        server_config = {
            "transportType": "stdio",
            "command": "npx",
            "args": ["-y", "@amyseer/moveflow-aptos-mcp-server@latest"],
            "env": {
                "APTOS_NETWORK": os.getenv("APTOS_NETWORK", "testnet"),
                "APTOS_NODE_URL": os.getenv("APTOS_NODE_URL", "https://fullnode.testnet.aptoslabs.com/v1"),
                "READ_ONLY_MODE": os.getenv("READ_ONLY_MODE", "true"),
                "SIGNING_MODE": os.getenv("SIGNING_MODE", "false"),
            }
        }
        
        # 注入私钥（如果存在）
        if aptos_private_key:
            server_config["env"]["APTOS_PRIVATE_KEY"] = aptos_private_key
        
        # 连接到服务器
            # 显示详细配置信息
            print(f"\n=== 正在连接服务器: {server_name} ===")
            print(f"网络配置: {server_config['env']['APTOS_NETWORK']}")
            print(f"节点URL: {server_config['env'].get('APTOS_NODE_URL', '默认')}")
            print(f"读写模式: {'只读' if server_config['env']['READ_ONLY_MODE'] == 'true' else '读写'}")
            print(f"签名模式: {server_config['env'].get('SIGNING_MODE', '未指定')}")
            
            await mcp_hub.connect_to_server(server_name, server_config)
            
            print("\n=== 连接状态 ===")
            print(f"服务器 {server_name} 已连接")
            print(f"当前网络: {server_config['env']['APTOS_NETWORK']}")
            print(f"节点地址: {server_config['env'].get('APTOS_NODE_URL', '未配置')}")
            print(f"水龙头地址: {server_config['env'].get('APTOS_FAUCET_URL', '未配置')}")
    except Exception as e:
        print(f"连接服务器时出错: {str(e)}")
        raise Exception("无法连接到MCP服务器")
        
    return mcp_hub

async def chat_loop(agent: OpenAIAgent):
    """运行交互式聊天循环"""
    print(f"\nMoveFlow Aptos MCP 客户端已启动! (使用 {agent.ai_service.get_service_name()} AI服务)")
    print("输入你的查询或输入 'quit' 退出。")

    while True:
        try:
            query = input("\n查询: ").strip()

            if query.lower() == 'quit':
                break

            # 处理查询
            response = await agent.process_query(query)
            print("\n" + response)

        except Exception as e:
            print(f"\n错误: {str(e)}")

async def main():
    """主函数"""
    mcp_hub = None
    try:
        # 设置MCP服务器
        mcp_hub = await setup_mcp_server()
        
        # 获取AI服务类型
        service_type = os.getenv("AI_SERVICE", "openai")
        
        # 创建AI代理
        agent = OpenAIAgent(mcp_hub, service_type)
        
        # 运行聊天循环
        await chat_loop(agent)
        
    except KeyboardInterrupt:
        print("\n程序被用户中断...")
    except Exception as e:
        print(f"初始化失败: {str(e)}")
    finally:
        # 确保资源被清理
        if mcp_hub is not None:
            print("正在清理资源...")
            try:
                await mcp_hub.cleanup()
                print("资源清理完成")
            except Exception as e:
                print(f"清理资源时出错: {str(e)}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"程序执行出错: {str(e)}")
