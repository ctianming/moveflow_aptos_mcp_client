"""
使用aptos_sdk进行交易签名的简单帮助模块
"""
import os
import getpass
import asyncio
from typing import Dict, Any, Optional
from aptos_sdk.account import Account
from aptos_sdk.async_client import RestClient  # 修正导入

class AptosSigner:
    """
    Aptos交易签名工具类
    直接使用aptos_sdk，不需要额外的钱包管理
    """
    
    def __init__(self, node_url: str = "https://fullnode.mainnet.aptoslabs.com/v1"):
        """
        初始化Aptos签名工具
        
        Args:
            node_url: Aptos节点URL
        """
        self.client = RestClient(node_url)  # 使用异步客户端
        self._account = None
        
    def load_account_from_env(self) -> Optional[Account]:
        """从环境变量加载账户"""
        private_key = os.environ.get("APTOS_PRIVATE_KEY")
        if not private_key:
            return None
        return self.load_account_from_key(private_key)
    
    def load_account_from_key(self, private_key: str) -> Account:
        """从私钥加载账户"""
        self._account = Account.load_key(private_key)
        return self._account
    
    def load_account_interactive(self) -> Account:
        """交互式加载账户私钥"""
        private_key = getpass.getpass("请输入Aptos私钥: ")
        if not private_key:
            raise ValueError("未提供私钥")
        return self.load_account_from_key(private_key)
    
    def ensure_account_loaded(self) -> Account:
        """确保账户已加载，如果没有则尝试从环境变量加载或请求用户输入"""
        if self._account:
            return self._account
            
        # 尝试从环境变量加载
        account = self.load_account_from_env()
        if account:
            return account
            
        # 如果环境变量中没有，请求用户输入
        return self.load_account_interactive()
    
    async def sign_transaction_async(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """异步签名交易"""
        try:
            # 打印接收到的payload结构便于调试
            print(f"准备签名的交易数据: {payload}")
            
            # 创建账户
            account = self.ensure_account_loaded()
            
            # 解析交易数据
            from aptos_sdk.transactions import RawTransaction
            raw_txn = self._parse_transaction(payload)
            
            # 签名
            signature = account.sign(raw_txn.keyed())
            
            return {
                "signature": signature.hex(),
                "public_key": account.public_key().hex(),
                "sender": str(account.address()),
                "transaction_hash": "0x" + raw_txn.hash().hex()
            }
        except Exception as e:
            print(f"签名失败: {e}")
            raise
    
    def sign_transaction(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """同步包装的签名方法"""
        return asyncio.run(self.sign_transaction_async(payload))
    
    def _parse_transaction(self, payload: Dict[str, Any]) -> Any:
        """解析交易数据"""
        from aptos_sdk.transactions import RawTransaction
        if isinstance(payload, dict) and "rawTxn" in payload:
            # 如果payload包含rawTxn字段，使用它
            raw_txn_data = payload["rawTxn"]
            return RawTransaction.from_dict(raw_txn_data)
        elif isinstance(payload, str):
            # 如果payload是字符串，可能是BCS序列化的十六进制
            return RawTransaction.from_bytes(bytes.fromhex(payload.replace("0x", "")))
        else:
            # 尝试直接解析
            return RawTransaction.from_dict(payload)
    
    async def get_account_info(self) -> Dict[str, Any]:
        """
        获取当前账户信息 (异步方法)
        
        Returns:
            账户信息
        """
        # 确保账户已加载
        account = self.ensure_account_loaded()
        
        try:
            address = account.address()
            # 使用异步调用
            resources = await self.client.account_resources(address)
            
            # 获取APT余额
            apt_balance = 0
            for resource in resources:
                if resource["type"] == "0x1::coin::CoinStore<0x1::aptos_coin::AptosCoin>":
                    apt_balance = int(resource["data"]["coin"]["value"])
                    break
            
            return {
                "address": str(address),
                "public_key": account.public_key().hex(),
                "apt_balance": apt_balance / 100000000  # 转换为APT单位
            }
        except Exception as e:
            return {
                "address": str(account.address()),
                "public_key": account.public_key().hex(),
                "error": str(e)
            }
            
    def get_account_info_sync(self) -> Dict[str, Any]:
        """
        获取当前账户信息 (同步版本)
        """
        return asyncio.run(self.get_account_info())
