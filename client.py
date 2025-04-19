#!/usr/bin/env python3
import subprocess
import json
import uuid
import threading
import time
import os
import sys
from typing import Dict, Any, Optional, Callable
import getpass
import asyncio

# 确保正确加载当前目录下的.env文件
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, '.env')

# 尝试加载环境变量
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=env_path)  # 从指定路径加载.env文件
except ImportError:
    pass  # 如果没有安装dotenv则忽略

# 使用正确的Aptos SDK导入
from aptos_sdk.account import Account
from aptos_sdk.async_client import RestClient

# 将当前脚本所在目录加入到sys.path
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 从环境变量中获取NPX包名
DEFAULT_NPX_PACKAGE = os.environ.get("DEFAULT_NPX_PACKAGE", "@amyseer/moveflow-aptos-mcp-server")

try:
    # 尝试从当前目录导入config模块
    import config
    get_network = config.get_network
    get_node_url = config.get_node_url
    get_read_only = config.get_read_only
except ImportError as e:
    print(f"无法导入配置: {e}")
    # 提供默认配置函数
    def get_network(): return os.environ.get("APTOS_NETWORK", "mainnet")
    def get_node_url(): return os.environ.get("APTOS_NODE_URL", "https://fullnode.mainnet.aptoslabs.com/v1")
    def get_read_only(): return os.environ.get("READ_ONLY_MODE", "true").lower() == "true"

class MCPClient:
    """MCP客户端 - 通过stdin/stdout与MCP服务器通信"""
    
    def __init__(self, server_config: Dict[str, Any] = None, npx_package: str = None):
        """
        初始化MCP客户端
        
        Args:
            server_config: 服务器配置，如果未提供则使用默认NPX配置
            npx_package: NPX包名称，默认为 @amyseer/moveflow-aptos-mcp-server
        """
        if server_config:
            self.server_config = server_config
        else:
            # 创建默认的NPX配置
            self.server_config = {
                "command": "npx",
                "args": ["-y", npx_package or DEFAULT_NPX_PACKAGE],
                "env": {}
            }
        
        self.process = None
        self.request_map = {}
        self.running = False
        self.response_thread = None
        
    def start(self):
        """启动MCP服务器进程和响应处理线程"""
        self._start_server()
            
    def _start_server(self):
        """启动MCP服务器"""
        # 准备环境变量
        env = os.environ.copy()
        if "env" in self.server_config:
            env.update(self.server_config["env"])
            
        # 提取命令和参数
        command = self.server_config.get("command", "npx")
        args = self.server_config.get("args", ["-y", DEFAULT_NPX_PACKAGE])
        
        # 组成完整的命令行
        cmd = [command] + args
        print(f"启动服务器: {' '.join(cmd)}")
        
        # 启动进程，运行MCP服务器
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1  # 行缓冲
        )
        
        print(f"MCP服务器已启动，PID: {self.process.pid}")
        
        # 启动stderr监控线程
        def monitor_stderr():
            while self.running:
                line = self.process.stderr.readline()
                if line:
                    print(f"[MCP Server]: {line.strip()}")
                else:
                    break
        
        stderr_thread = threading.Thread(target=monitor_stderr, daemon=True)
        stderr_thread.start()
        
        # 启动响应处理线程
        self.running = True
        self.response_thread = threading.Thread(target=self._handle_responses, daemon=True)
        self.response_thread.start()
        
        # 等待服务器初始化
        time.sleep(2)

    def _handle_responses(self):
        """处理来自MCP服务器的响应"""
        while self.running:
            try:
                line = self.process.stdout.readline()
                if not line:
                    break
                    
                # 解析JSON响应
                try:
                    response = json.loads(line)
                    if 'id' in response and response['id'] in self.request_map:
                        # 获取回调函数并执行
                        callback, future = self.request_map.pop(response['id'])
                        if callback:
                            callback(response)
                        future.set_result(response)
                    else:
                        print(f"收到未匹配的响应: {response}")
                except json.JSONDecodeError:
                    # 这可能是调试输出，不是JSON - 只需打印而不是尝试解析
                    print(f"服务器输出 (非JSON): {line.strip()}")
            except Exception as e:
                print(f"处理响应时出错: {e}")
                
    def stop(self):
        """停止MCP客户端和服务器进程"""
        self.running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
            
    def send_request(self, method: str, params: Dict[str, Any] = None, 
                   callback: Callable = None) -> Dict[str, Any]:
        """
        向MCP服务器发送请求
        
        Args:
            method: MCP方法名称
            params: 请求参数
            callback: 响应回调函数
            
        Returns:
            服务器响应
        """
        import asyncio
        
        # 创建请求ID
        request_id = str(uuid.uuid4())
        
        # 构建请求
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {}
        }
        
        # 创建Future用于等待响应
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 如果没有正在运行的事件循环，创建一个新的
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        future = loop.create_future()
        
        # 存储回调和Future
        self.request_map[request_id] = (callback, future)
        
        # 发送请求到服务器
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        
        # 等待响应
        return loop.run_until_complete(future)

    def call_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用MCP工具
        
        Args:
            tool_name: 工具名称
            args: 工具参数
            
        Returns:
            工具执行结果
        """
        return self.send_request("tool", {
            "name": tool_name,
            "args": args
        })
    
    def get_resource(self, uri: str) -> Dict[str, Any]:
        """
        获取MCP资源
                
        Args:
            uri: 资源URI
            
        Returns:
            资源内容
        """
        return self.send_request("resource", {"uri": uri})        
    
    def get_available_tools(self) -> Dict[str, Any]:
        """获取服务器提供的所有可用工具"""
        try:
            response = self.send_request("tools/list", {})
            if "result" in response and "tools" in response["result"]:
                tools = {}
                for tool in response["result"]["tools"]:
                    tools[tool["name"]] = tool
                return tools
            return {}
        except Exception as e:
            print(f"获取工具列表失败: {e}")
            return {}
            
    def get_available_resources(self) -> Dict[str, Any]:
        """获取服务器提供的所有可用资源"""
        try:
            response = self.send_request("resources/list", {})
            if "result" in response and "resources" in response["result"]:
                return response["result"]["resources"]
            return []
        except Exception as e:
            print(f"获取资源列表失败: {e}")
            return []

class MoveFlowClient:
    """MoveFlow特定客户端，用于与MoveFlow Aptos MCP服务器交互"""
    
    def __init__(self, server_config: Dict[str, Any] = None, 
                 network: str = None, node_url: str = None, read_only: bool = None,
                 private_key: str = None, npx_package: str = None):
        """
        初始化MoveFlow客户端
        
        Args:
            server_config: 服务器配置，如果未提供则使用默认NPX配置
            network: Aptos网络类型（可选，默认从配置加载）
            node_url: Aptos节点URL（可选，默认从配置加载）
            read_only: 是否为只读模式（可选，默认从配置加载）
            private_key: Aptos账户私钥（可选，默认从环境变量加载）
            npx_package: NPX包名称，默认为 @amyseer/moveflow-aptos-mcp-server
        """
        # 优先使用参数值，否则使用配置值
        self.network = network or get_network()
        self.node_url = node_url or get_node_url()
        self.read_only = read_only if read_only is not None else get_read_only()
        self.npx_package = npx_package or DEFAULT_NPX_PACKAGE
        
        # 创建服务器配置
        if server_config is None:
            # 使用默认的NPX配置
            server_config = {
                "command": "npx",
                "args": ["-y", self.npx_package],
                "env": {
                    "APTOS_NETWORK": self.network,
                    "APTOS_NODE_URL": self.node_url,
                    "READ_ONLY_MODE": str(self.read_only).lower()
                }
            }
        else:
            # 确保配置包含必要的环境变量
            if "env" not in server_config:
                server_config["env"] = {}
                
            # 添加Aptos相关环境变量
            server_config["env"].update({
                "APTOS_NETWORK": self.network,
                "APTOS_NODE_URL": self.node_url,
                "READ_ONLY_MODE": str(self.read_only).lower()
            })
        
        # 创建MCP客户端
        self.client = MCPClient(server_config)
        
        # 使用异步客户端
        self.rest_client = RestClient(self.node_url)
        self._private_key = private_key
        self._account = None
        self._available_tools = None
        
        # 添加支持客户端特性检测的属性
        self.supported_features = {
            "resources": True,
            "tools": True,
            "prompts": False,  # 未来可扩展
            "sampling": False,  # 未来可扩展
            "roots": False      # 未来可扩展
        }
        
        # 添加日志记录
        self._transaction_log = []
        
    def start(self):
        """启动MoveFlow客户端"""
        self.client.start()
        
    def stop(self):
        """停止MoveFlow客户端"""
        self.client.stop()
        
    def get_active_streams(self) -> Dict[str, Any]:
        """获取活跃流列表
        
        Returns:
            活跃流列表
        """
        return self.client.get_resource("moveflow://streams/active")    
    
    async def get_account_resources(self, address: str) -> list:
        """异步获取账户资源"""
        try:
            return await self.rest_client.account_resources(address)
        except Exception as e:
            print(f"获取账户资源失败: {str(e)}")
            return []
    
    def get_account_resources_sync(self, address: str) -> list:
        """同步获取账户资源的包装器"""
        return asyncio.run(self.get_account_resources(address))
    
    def _sign_transaction(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """使用Aptos SDK直接签名交易"""
        print("\n正在签名交易...")
        
        try:
            # 获取账户
            account = self._ensure_account_loaded()
            
            # 签名逻辑
            from aptos_sdk.transactions import RawTransaction
            
            # 尝试解析交易数据
            print(f"准备签名的交易数据类型: {type(payload)}")
            
            # 基于payload类型进行处理
            if isinstance(payload, dict) and "rawTxn" in payload:
                raw_txn = RawTransaction.from_dict(payload["rawTxn"])
            else:
                raw_txn = RawTransaction.from_dict(payload)
                
            # 签名
            signature = account.sign(raw_txn.keyed())
            
            # 返回签名结果
            return {
                "signature": signature.hex(),
                "public_key": account.public_key().hex(),
                "sender": str(account.address()),
                "transaction_hash": "0x" + raw_txn.hash().hex()
            }
        except Exception as e:
            print(f"签名失败: {str(e)}")
            raise
    
    def _ensure_account_loaded(self) -> Account:
        """确保账户已加载，从提供的私钥或环境变量获取私钥"""
        if self._account:
            return self._account
        
        # 优先使用构造函数传入的私钥
        private_key = self._private_key
        
        # 如果没有直接提供，从环境变量加载私钥
        if not private_key:
            private_key = os.environ.get("APTOS_PRIVATE_KEY")
            
        if not private_key:
            raise ValueError("未提供私钥，请通过构造函数传入私钥参数或设置APTOS_PRIVATE_KEY环境变量")
        
        # 创建账户
        self._account = Account.load_key(private_key)
        return self._account
    
    def set_private_key(self, private_key: str):
        """设置用于签名交易的私钥"""
        self._private_key = private_key
        self._account = None  # 重置账户，下次需要时会重新创建
    
    def get_available_tools(self) -> Dict[str, Any]:
        """获取服务器提供的所有可用工具
        
        Returns:
            工具名称到工具定义的映射
        """
        if self._available_tools is None:
            self._available_tools = self.client.get_available_tools()
        return self._available_tools
    
    def list_tools(self) -> None:
        """列出所有可用工具"""
        tools = self.get_available_tools()
        if not tools:
            print("没有可用工具")
            return
        print(f"可用工具 ({len(tools)}):")
        for name, tool in tools.items():
            print(f"  - {name}: {tool.get('description', '无描述')}")
    
    def extend_stream(self, stream_id: str, extend_time: int, execute: bool = True) -> Dict[str, Any]:
        """延长流的结束时间"""
        return self._handle_tool_call("extend-stream", {
            "streamId": stream_id,
            "extendTime": extend_time,
            "execute": execute
        })
    
    def pause_stream(self, stream_id: str, execute: bool = True) -> Dict[str, Any]:
        """暂停流"""
        return self._handle_tool_call("pause-stream", {
            "streamId": stream_id,
            "execute": execute
        })
    
    def resume_stream(self, stream_id: str, execute: bool = True) -> Dict[str, Any]:
        """恢复已暂停的流"""
        return self._handle_tool_call("resume-stream", {
            "streamId": stream_id,
            "execute": execute
        })
    
    def batch_create_streams(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """批量创建流"""
        response = self.client.call_tool("batch-create-streams", params)
        return self._handle_transaction_preparation(response)
    
    def batch_withdraw_streams(self, stream_ids: list, execute: bool = True) -> Dict[str, Any]:
        """批量从多个流中提取资金"""
        response = self.client.call_tool("batch-withdraw-streams", {
            "streamIds": stream_ids,
            "execute": execute
        })
        return self._handle_transaction_preparation(response)
    
    def get_stream_info(self, stream_id: str) -> Dict[str, Any]:
        """获取特定流信息"""
        return self.client.call_tool("get-stream-info", {"streamId": stream_id})
    
    def create_stream(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """创建新的流"""
        response = self.client.call_tool("create-stream", params)
        # 处理可能需要签名的情况
        return self._handle_transaction_preparation(response)
        
    def withdraw_stream(self, stream_id: str, execute: bool = True) -> Dict[str, Any]:
        """提取流资金"""
        response = self.client.call_tool("withdraw-stream", {
            "streamId": stream_id, 
            "execute": execute
        })
        # 处理可能需要签名的情况
        return self._handle_transaction_preparation(response)
    
    def close_stream(self, stream_id: str, execute: bool = True) -> Dict[str, Any]:
        """关闭流"""
        return self._handle_tool_call("close-stream", {
            "streamId": stream_id, 
            "execute": execute
        })
    
    def _handle_tool_call(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """通用工具调用处理"""
        print(f"执行工具调用: {tool_name}")
        result = self.client.call_tool(tool_name, params)
        
        # 规范化响应格式，确保与所有客户端兼容
        if isinstance(result, dict) and "content" in result and isinstance(result["content"], list):
            # 标准MCP工具响应格式
            return result
        else:
            # 转换为标准格式
            return {
                "content": [{
                    "type": "text",
                    "text": str(result) if result is not None else "操作完成，但无返回结果"
                }]
            }
    
    def _is_transaction_signing_request(self, response: Dict[str, Any]) -> bool:
        """检查是否是需要签名的交易请求"""
        if not response.get("result"):
            return False
        
        content = response.get("result", {}).get("content", [])
        if not content or len(content) == 0:
            return False
        
        text = content[0].get("text", "")
        return "Transaction prepared but not executed" in text
    
    def _extract_transaction_id(self, response: Dict[str, Any]) -> str:
        """从响应中提取交易ID"""
        content = response.get("result", {}).get("content", [])
        if not content:
            raise ValueError("响应中没有内容")
        
        # 在内容文本中查找交易ID
        for item in content:
            text = item.get("text", "")
            # 使用正则表达式提取交易ID
            import re
            match = re.search(r'transactionId:\s*([a-zA-Z0-9_]+)', text)
            if match:
                return match.group(1)
                
        # 如果没有找到交易ID，尝试在JSON结构中查找
        if isinstance(response.get("result"), dict) and "transactionId" in response["result"]:
            return response["result"]["transactionId"]
            
        raise ValueError("无法从响应中提取交易ID")
    
    def _extract_transaction_payload(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """从响应中提取交易payload"""
        # 首先尝试从响应中直接提取rawTxn
        if isinstance(response.get("result"), dict) and "rawTxn" in response["result"]:
            return response["result"]["rawTxn"]
        
        # 如果没有直接的rawTxn，提取交易ID并获取待处理交易
        try:
            tx_id = self._extract_transaction_id(response)
            return self._get_transaction_data(tx_id)
        except Exception as e:
            print(f"提取交易payload失败: {e}")
            raise ValueError("无法提取交易payload")

    def _handle_transaction_preparation(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """处理交易准备响应，检测是否需要签名"""
        if not response.get("result"):
            return response
        
        # 检测是否包含transactionId和需要签名的指示
        content = response.get("result", {}).get("content", [])
        if not content:
            return response
        
        for item in content:
            text = item.get("text", "")
            # 查找交易ID和签名请求模式
            if "Transaction prepared but not executed" in text and "transactionId" in text:
                # 提取transactionId
                import re
                match = re.search(r'transactionId: ([a-zA-Z0-9_]+)', text)
                if match:
                    tx_id = match.group(1)
                    # 获取原始交易数据
                    tx_data = self._get_transaction_data(tx_id)
                    if tx_data:
                        # 签名交易
                        signature = self._sign_transaction(tx_data)
                        # 提交已签名的交易
                        return self.submit_signed_transaction(tx_id, signature)
        
        return response
        
    def _get_transaction_data(self, tx_id: str) -> Optional[Dict[str, Any]]:
        """获取等待签名的交易数据"""
        try:
            print(f"获取交易 {tx_id} 的详细数据...")
            response = self.client.call_tool("check-pending-transaction", {
                "transactionId": tx_id
            })
            
            # 从响应中提取交易数据
            if response and "result" in response:
                content = response.get("result", {}).get("content", [])
                if not content:
                    print(f"交易 {tx_id} 的响应中没有内容")
                    return None
                
                # 尝试找到包含交易数据的内容
                for item in content:
                    text = item.get("text", "")
                    # 检查是否包含交易数据的JSON字符串
                    if "transaction" in text:
                        # 尝试提取JSON字符串并解析
                        import re
                        import json
                        match = re.search(r'transaction:\s*({.+})', text, re.DOTALL)
                        if match:
                            try:
                                tx_data = json.loads(match.group(1))
                                return tx_data
                            except json.JSONDecodeError:
                                print(f"解析交易数据JSON失败")
                
                # 如果在文本中没找到，查找响应结构中的交易数据
                if "transaction" in response["result"]:
                    return response["result"]["transaction"]
            
            print(f"未能从响应中提取交易 {tx_id} 的数据")
            return None
        except Exception as e:
            print(f"获取交易数据失败: {e}")
            return None
            
    def submit_signed_transaction(self, tx_id: str, signature: Dict[str, Any]) -> Dict[str, Any]:
        """提交已签名的交易"""
        print(f"提交已签名的交易 {tx_id}...")
        try:
            response = self.client.call_tool("submit-signed-transaction", {
                "transactionId": tx_id,
                "signedTransaction": signature
            })
            print(f"交易 {tx_id} 提交结果: {response}")
            return response
        except Exception as e:
            print(f"提交已签名的交易失败: {e}")
            raise
    
    def get_transaction_log(self) -> list:
        """获取交易日志"""
        return self._transaction_log
    
    def _log_transaction(self, action: str, params: Dict[str, Any], result: Dict[str, Any]) -> None:
        """记录交易到日志"""
        self._transaction_log.append({
            "timestamp": time.time(),
            "action": action,
            "params": params,
            "result": result
        })
    
    def get_client_capabilities(self) -> Dict[str, Any]:
        """返回此客户端支持的MCP特性和能力
        
        Returns:
            支持特性的字典
        """
        return {
            "name": "MoveFlow Aptos Client",
            "version": "1.0.0",
            "features": self.supported_features,
            "supportedClients": [
                "Claude Desktop App",
                "Continue",
                "Copilot-MCP",
                "fast-agent"
            ]
        }
    
    def auto_detect_client(self) -> str:
        """尝试检测当前环境中正在使用的MCP客户端
        
        Returns:
            检测到的客户端名称，如果无法检测则返回"unknown"
        """
        # 检查环境变量
        if os.environ.get("CLAUDE_DESKTOP_APP"):
            return "Claude Desktop App"
        elif os.environ.get("CONTINUE_APP"):
            return "Continue"
        # 可以添加更多客户端检测逻辑
        return "unknown"

# 当脚本直接运行时执行的代码
if __name__ == "__main__":
    # 在脚本底部添加一个提示，说明如何使用环境变量
    if os.environ.get("APTOS_PRIVATE_KEY") is None:
        print("\n提示：要使用私钥签名交易，请设置 APTOS_PRIVATE_KEY 环境变量")
        print("PowerShell 临时设置方法: $env:APTOS_PRIVATE_KEY = \"0x123...\"; python client.py")
    
    print("=============================================")
    print("MoveFlow Aptos MCP 客户端测试")
    print("=============================================")
    
    # 创建客户端 - 使用NPX方式
    try:
        # 显示将要连接的配置
        network = get_network()
        node_url = get_node_url()
        read_only = get_read_only()
        
        print(f"网络: {network}")
        print(f"节点URL: {node_url}")
        print(f"只读模式: {read_only}")
        print(f"NPX包: {DEFAULT_NPX_PACKAGE}")
        
        # 创建并启动客户端
        print("\n正在初始化客户端...")
        client = MoveFlowClient()
        
        print("正在启动客户端并连接到MCP服务器...")
        client.start()
        
        # 列出可用工具
        print("\n可用MCP工具:")
        client.list_tools()
        
        # 获取活跃流
        print("\n正在获取活跃流列表...")
        streams = client.get_active_streams()
        
        if "content" in streams.get("result", {}):
            content = streams["result"]["content"]
            if content:
                print(f"找到 {len(content)} 个活跃流:")
                for item in content:
                    print(item.get("text", ""))
            else:
                print("未找到活跃流")
        else:
            print("活跃流查询返回未知格式:", repr(streams))
        
    except Exception as e:
        print(f"\n错误: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        # 确保客户端关闭
        try:
            if 'client' in locals() and client:
                print("\n正在关闭客户端...")
                client.stop()
                print("客户端已关闭")
        except Exception as close_error:
            print(f"关闭客户端时发生错误: {close_error}")
    
    print("\n测试完成")
