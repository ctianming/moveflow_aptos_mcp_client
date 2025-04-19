# MoveFlow Aptos MCP 客户端

MoveFlow Aptos MCP 客户端是连接 MoveFlow Aptos MCP 服务器的工具，让用户能够便捷地与 Aptos 区块链上的 MoveFlow 流支付协议交互。

## 功能特性

- 与 MoveFlow Aptos MCP 服务器进行通信
- 查询和管理流支付
- 创建、暂停、恢复和关闭支付流
- 批量操作支持
- 交易签名和链上操作
- AI 代理集成（使用 agent_client.py）

## 安装要求

- Python 3.8+
- uv 包管理工具
- 必要依赖项:
  - aptos-sdk
  - dotenv
  - mcp
  - anthropic
- 可选依赖项 (用于 agent_client.py):
  - agents-protocol
  - openai (或兼容的API)
  - pendulum (时间处理库)

安装 uv (如果未安装):
```bash
# 使用官方安装脚本
curl -sSf https://install.python-uv.org | python3

# 或者使用 pip (不推荐在生产环境)
pip install uv
```

### 设置项目环境

```bash
# 创建虚拟环境
uv venv

# 激活虚拟环境
# 在 Windows 上：
.venv\Scripts\activate
# 在 Unix 或 MacOS 上：
source .venv/bin/activate

# 安装所需的包
uv add mcp anthropic python-dotenv

# 安装可选依赖项 (用于 agent_client.py)
uv add agents-protocol openai pendulum
```

## 快速开始

### 配置环境

在 `client/.env` 文件中配置必要的参数:

```
# OpenAI API配置
API_KEY=你的OpenAI密钥
BASE_URL=https://api.openai.com/v1  # 或其他兼容端点
MODEL=gpt-4  # 或其他支持的模型

# Aptos网络配置
APTOS_NETWORK=testnet  # 或 mainnet, devnet
APTOS_NODE_URL=https://fullnode.testnet.aptoslabs.com/v1
READ_ONLY_MODE=true  # 设置为false启用交易签名
APTOS_PRIVATE_KEY=你的私钥  # 可选，用于签名交易

# AI服务配置
AI_SERVICE=openai  # 或 anthropic
```

### AI代理客户端使用方法

MoveFlow Aptos MCP客户端包含一个内置AI代理，提供智能化交互体验。该代理允许用户通过自然语言查询和执行操作，大大简化了流支付管理流程。

```bash
# 启动AI代理客户端
python agent_client.py
```

#### 代理客户端功能

1. **智能自然语言处理**：接受日常用语表达的需求，无需了解复杂的API
2. **时间感知功能**：
   - 理解各种时间表达方式（"3天后"、"下周五"、"明天上午9点"等）
   - 支持时区管理（默认使用亚洲/上海时区）
   - 自动解析时间戳与日期格式
   - 处理相对时间和绝对时间表达

3. **流支付操作**：
   - 创建流支付：`"创建一个支付流给0x123，金额50 APT，持续30天"`
   - 查询流状态：`"查看我的所有活跃流支付"`
   - 修改流支付：`"暂停ID为5的支付流"`

4. **交易处理**：
   - 只读模式：生成交易但不签名提交
   - 读写模式：生成、签名并提交交易到链上
   - 显示交易结果与链上确认

#### 时间处理示例

```
查询: 创建一个支付流给0x123，从下周一开始，持续30天，每天0.5 APT
代理: 正在创建支付流...
开始时间：2025-04-28 00:00:00 (下周一)
结束时间：2025-05-28 00:00:00 (30天后)
总金额：15 APT
...
```

## 高级功能 

### 时间处理能力

agent_client内置的`TimeAwareHelper`类提供强大的时间处理功能：

- **多格式解析**：支持多种日期时间格式："YYYY-MM-DD"、"MM/DD/YYYY"、"YYYY年MM月DD日"等
- **时间短语识别**：理解"现在"、"今天"、"明天"、"下周"等常用时间表达
- **相对时间处理**：解析"3天后"、"2周前"、"下个月"等相对表达
- **星期识别**：支持"下周五"、"本周一"等表达方式
- **时区处理**：默认使用中国时区(UTC+8)，可自定义

## 说明
因为没有找到python版本的aptos wallet adapter，现处于用私钥管理的阶段；后续可以考虑使用钱包进行签名；