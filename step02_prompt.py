import os

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate

# LLM
llm = ChatOllama(
    model="qwen3:8b",
    base_url=os.environ["OLLAMA_BASE_URL"],
    temperature=0,
)

# プロンプトテンプレート
prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
あなたはソフトウェア品質管理の専門家です。

入力されたバグチケットを分析し、
以下の項目を日本語で回答してください。

1. バグのカテゴリ
2. 重要度（Critical / High / Medium / Low）
3. 考えられる原因
4. 推奨する対応方法

原因が特定できない場合は、推測であることを明示してください。
"""
    ),
    (
        "human",
        "{ticket}"
    )
])

# バグチケット
ticket = """
ログイン画面で正しいIDとパスワードを入力しても、
500 Internal Server Errorが発生する。

発生環境：本番環境
発生頻度：常時
影響範囲：全ユーザー
"""

# テンプレートに値を渡す
messages = prompt.invoke({"ticket": ticket})

# LLMに問い合わせ
response = llm.invoke(messages)

print(response.content)
