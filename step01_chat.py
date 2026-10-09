import os

from langchain_ollama import ChatOllama

# NUCのOllamaに接続
llm = ChatOllama(
    model="qwen3:8b",
    base_url=os.environ["OLLAMA_BASE_URL"],
    temperature=0,
)

# LLMに問い合わせ
response = llm.invoke(
    "ソフトウェア開発におけるバグチケットとは何か、簡潔に説明してください。"
)

print(response.content)
