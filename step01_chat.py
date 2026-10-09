from langchain_ollama import ChatOllama

# NUCのOllamaに接続
llm = ChatOllama(
    model="qwen3:8b",
    base_url="http://192.168.11.31:11434",
    temperature=0,
)

# LLMに問い合わせ
response = llm.invoke(
    "ソフトウェア開発におけるバグチケットとは何か、簡潔に説明してください。"
)

print(response.content)
