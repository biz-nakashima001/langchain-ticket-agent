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
ticket = """
ログイン画面で正しいIDとパスワードを入力しても、
500 Internal Server Errorが発生する。

発生環境：本番環境
発生頻度：常時
影響範囲：全ユーザー
"""

# テンプレート変数を設定
messages = prompt.invoke({
    "ticket": ticket,
    "format_instructions": parser.get_format_instructions()
})

# LLMを実行
response = llm.invoke(messages)

# JSONをPythonの辞書に変換
result = parser.invoke(response)

print("カテゴリ:", result["category"])
print("重要度:", result["severity"])

print("\n考えられる原因:")
for cause in result["possible_causes"]:
    print("-", cause)

print("\n推奨対応:")
for recommendation in result["recommendations"]:
    print("-", recommendation)
