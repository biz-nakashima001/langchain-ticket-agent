import os

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import Literal


# 出力データの構造を定義
class BugAnalysis(BaseModel):
    category: str = Field(description="バグのカテゴリ")
    severity: Literal["Critical", "High", "Medium", "Low"]
    possible_causes: list[str] = Field(description="考えられる原因")
    recommendations: list[str] = Field(description="推奨する対応方法")


# LLM
llm = ChatOllama(
    model="qwen3:8b",
    base_url=os.environ["OLLAMA_BASE_URL"],
    temperature=0,
    format="json",
)

# OutputParser
parser = JsonOutputParser(pydantic_object=BugAnalysis)

# プロンプト
prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
あなたはソフトウェア品質管理の専門家です。

バグチケットを分析してください。
原因が特定できない場合は、推測として扱ってください。

必ず以下のJSON形式で回答してください。

{format_instructions}
"""
    ),
    ("human", "{ticket}")
])

# バグチケット
tickets = [
    {
        "id": "BUG-001",
        "text": """
ログイン画面で正しいIDとパスワードを入力しても500エラー。
本番環境で全ユーザーに発生。
"""
    },
    {
        "id": "BUG-002",
        "text": """
商品一覧画面の表示に15秒以上かかる。
商品数が1000件を超えると発生。
"""
    },
    {
        "id": "BUG-003",
        "text": """
スマートフォンで購入ボタンが画面外にはみ出す。
PCでは正常に表示される。
"""
    }
]

# LCELでChainを構築
chain = prompt | llm | parser

# 複数の入力を作成
inputs = [
    {
        "ticket": ticket["text"],
        "format_instructions": parser.get_format_instructions()
    }
    for ticket in tickets
]

# 一括実行
results = chain.batch(
    inputs,
    config={"max_concurrency": 1}
)

# 結果表示
for ticket, result in zip(tickets, results):
    print(f"\n===== {ticket['id']} =====")
    print("カテゴリ:", result["category"])
    print("重要度:", result["severity"])

    print("\n原因候補:")
    for cause in result["possible_causes"]:
        print("-", cause)

    print("\n推奨対応:")
    for recommendation in result["recommendations"]:
        print("-", recommendation)
