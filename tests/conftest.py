import os

os.environ["OLLAMA_DISCORD_SKIP_DOTENV"] = "1"
os.environ["MAX_MEMORY_MESSAGES"] = "0"
os.environ["MEMORY_FILE"] = "pytest-memory.json"
