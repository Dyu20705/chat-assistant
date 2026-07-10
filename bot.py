from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp
import discord
from discord import app_commands
from dotenv import load_dotenv


# ============================================================
# BOOTSTRAP / CONFIG
# ============================================================

load_dotenv()


def env_int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        value = default

    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def env_float(name: str, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    raw = os.getenv(name)
    try:
        value = float(raw) if raw is not None else default
    except ValueError:
        value = default

    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "").strip()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2").strip()

OLLAMA_TIMEOUT = env_int("OLLAMA_TIMEOUT", 180, minimum=10, maximum=900)
OLLAMA_NUM_CTX = env_int("OLLAMA_NUM_CTX", 8192, minimum=2048, maximum=131072)
MAX_MEMORY_MESSAGES = env_int("MAX_MEMORY_MESSAGES", 16, minimum=0, maximum=80)
MAX_PROMPT_CHARS = env_int("MAX_PROMPT_CHARS", 24000, minimum=1000, maximum=120000)
MAX_ATTACHMENT_BYTES = env_int("MAX_ATTACHMENT_BYTES", 180000, minimum=1000, maximum=2_000_000)
MAX_PARALLEL_REQUESTS = env_int("MAX_PARALLEL_REQUESTS", 2, minimum=1, maximum=8)
USER_COOLDOWN_SECONDS = env_float("USER_COOLDOWN_SECONDS", 3.0, minimum=0.0, maximum=60.0)
DEFAULT_CONTEXT_MESSAGES = env_int("DEFAULT_CONTEXT_MESSAGES", 0, minimum=0, maximum=10)

MEMORY_FILE = Path(os.getenv("MEMORY_FILE", "ollama_memory.json"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ollama_discord_bot")


# ============================================================
# PERSONA / PROMPTS
# ============================================================

SYSTEM_PROMPT = """
Bạn là "Tiểu Hầu Cận", AI hầu cận tri thức riêng của Duy trong Discord server.

BẢN SẮC:
- Bạn là hầu cận thông thái, lễ phép, dí dỏm, sắc bén, tận tâm.
- Bạn hỗ trợ Duy học tập, lập trình, nghiên cứu, productivity, đọc lỗi, thiết kế dự án, phản biện ý tưởng.
- Bạn có thể xưng là "tiểu hầu cận" hoặc "thần", nhưng dùng vừa phải.
- Có thể gọi người dùng là "Duy" hoặc "chủ nhân" theo phong cách vui, không quá lố.
- Không biến cuộc trò chuyện thành nhập vai quá đà. Trọng tâm là giúp Duy mạnh hơn mỗi ngày.

NGUYÊN TẮC TRẢ LỜI:
- Mặc định trả lời bằng tiếng Việt.
- Rõ ràng, sâu sắc, thực dụng, không lan man.
- Không bịa. Nếu không chắc, nói rõ mức độ chắc chắn.
- Không giả vờ đã chạy code, đã đọc file, đã truy cập web nếu chưa thật sự làm.
- Nếu câu hỏi mơ hồ, tự đưa giả định hợp lý rồi trả lời.
- Khi liên quan code: nêu lỗi chính, nguyên nhân, cách sửa, ví dụ ngắn.
- Khi liên quan học tập: giải thích từ gốc, có ví dụ, có bài luyện nhỏ nếu phù hợp.
- Khi liên quan dự án: chia theo scope, design, implementation, test, deploy.
- Khi người dùng hỏi tối ưu: ưu tiên checklist hành động thực tế.

FORMAT ƯU TIÊN:
1. Kết luận nhanh.
2. Giải thích ngắn gọn.
3. Checklist / code / ví dụ.
4. Gợi ý bước tiếp theo.

GIỚI HẠN:
- Không hỗ trợ hack, đánh cắp tài khoản, mã độc, bypass bảo mật, lừa đảo, spam.
- Không đưa hướng dẫn nguy hiểm.
- Không khuyến khích hành vi gây hại.
- Không spam emoji. Tối đa 1-3 emoji nếu thật sự hợp.
""".strip()

MODE_PROMPTS = {
    "auto": """
MODE AUTO:
- Tự nhận diện ý định của Duy.
- Nếu là code, hãy như senior reviewer.
- Nếu là học tập, hãy như giảng viên.
- Nếu là dự án, hãy như technical leader.
- Nếu là câu hỏi vui, trả lời thú vị nhưng vẫn có ích.
""".strip(),
    "code": """
MODE CODE:
- Đóng vai senior software engineer.
- Ưu tiên bug, edge case, runtime, memory, clean code, maintainability.
- Khi sửa code, đưa phiên bản code chạy được nếu đủ dữ liệu.
- Giải thích vì sao sửa như vậy.
- Nếu phù hợp, thêm test case tối thiểu.
""".strip(),
    "study": """
MODE STUDY:
- Đóng vai gia sư học thuật.
- Giải thích từ nền tảng đến nâng cao.
- Dùng ví dụ dễ hiểu.
- Cuối câu trả lời nên có bài tập nhỏ hoặc câu hỏi kiểm tra.
""".strip(),
    "research": """
MODE RESEARCH:
- Đóng vai trợ lý nghiên cứu.
- Phân tích khái niệm, giả định, hướng tiếp cận, ưu nhược điểm.
- Không bịa nguồn.
- Nếu thiếu dữ liệu mới, nói rõ cần kiểm chứng thêm.
""".strip(),
    "planner": """
MODE PLANNER:
- Đóng vai project manager / technical leader.
- Luôn chia việc thành phase, checklist, deliverable, definition of done.
- Ưu tiên kế hoạch gọn, có thể làm ngay.
""".strip(),
    "critic": """
MODE CRITIC:
- Đóng vai phản biện sắc bén nhưng xây dựng.
- Chỉ ra điểm yếu, rủi ro, giả định sai, phần còn thiếu.
- Sau khi phê bình, phải đưa cách sửa.
""".strip(),
    "fun": """
MODE FUN:
- Trả lời vui hơn, có chất hầu cận hơn.
- Vẫn phải đúng, hữu ích, không lố.
- Không biến thành roleplay tình cảm.
""".strip(),
}

DEPTH_PROMPTS = {
    "quick": """
ĐỘ SÂU QUICK:
- Trả lời ngắn.
- Ưu tiên kết luận và bước làm ngay.
- Tránh giải thích dài.
""".strip(),
    "normal": """
ĐỘ SÂU NORMAL:
- Trả lời vừa đủ.
- Có giải thích, ví dụ, checklist nếu cần.
""".strip(),
    "deep": """
ĐỘ SÂU DEEP:
- Phân tích kỹ.
- Nêu giả định, nguyên nhân, lựa chọn, trade-off.
- Có checklist hoặc lộ trình rõ ràng.
""".strip(),
}

TEMPERATURE_BY_MODE = {
    "auto": 0.55,
    "code": 0.25,
    "study": 0.45,
    "research": 0.35,
    "planner": 0.40,
    "critic": 0.35,
    "fun": 0.75,
}

CODE_EXTENSIONS = {".py", ".js", ".ts", ".java", ".cpp", ".c", ".cs", ".sh", ".bat", ".ps1", ".sql"}
READABLE_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".java", ".cpp", ".c", ".cs",
    ".html", ".css", ".json", ".yaml", ".yml", ".toml", ".ini",
    ".env", ".log", ".csv", ".sql", ".sh", ".bat", ".ps1", ".xml",
}


# ============================================================
# UTILS
# ============================================================


def now_string() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clamp_text(text: str | None, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n...[đã cắt bớt vì quá dài]"


def strip_discord_mentions(text: str, bot_user_id: int | None) -> str:
    text = text or ""
    if bot_user_id is not None:
        text = text.replace(f"<@{bot_user_id}>", "").replace(f"<@!{bot_user_id}>", "")
    return re.sub(r"\s+", " ", text).strip()


def split_discord_message(text: str, limit: int = 1900) -> list[str]:
    """Split long AI output into Discord-safe chunks."""
    text = (text or "").strip()
    if not text:
        return ["Ollama không trả về nội dung."]

    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""

    for line in text.splitlines():
        # Very long single line: hard split it.
        if len(line) > limit:
            if current.strip():
                chunks.append(current.strip())
                current = ""
            for i in range(0, len(line), limit):
                chunks.append(line[i:i + limit])
            continue

        candidate = f"{current}{line}\n"
        if len(candidate) <= limit:
            current = candidate
        else:
            if current.strip():
                chunks.append(current.strip())
            current = f"{line}\n"

    if current.strip():
        chunks.append(current.strip())

    return chunks


def safe_error(error: Exception | str) -> str:
    return clamp_text(str(error), 700)


def normalize_mode(mode: str) -> str:
    return mode if mode in MODE_PROMPTS else "auto"


def normalize_depth(depth: str) -> str:
    return depth if depth in DEPTH_PROMPTS else "normal"


def is_text_attachment(filename: str, content_type: str | None) -> bool:
    suffix = Path(filename).suffix.lower()
    content_type = content_type or ""
    return (
        suffix in READABLE_EXTENSIONS
        or content_type.startswith("text/")
        or "json" in content_type
        or "xml" in content_type
        or "yaml" in content_type
        or "csv" in content_type
    )


# ============================================================
# MEMORY
# ============================================================


class PersistentMemory:
    def __init__(self, path: Path, max_messages: int):
        self.path = path
        self.max_messages = max_messages
        self.histories: defaultdict[str, deque[dict[str, str]]] = defaultdict(
            lambda: deque(maxlen=max_messages)
        )
        self.load()

    def load(self) -> None:
        if self.max_messages <= 0 or not self.path.exists():
            return

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as error:
            logger.warning("Cannot load memory file %s: %s", self.path, error)
            return

        if not isinstance(raw, dict):
            return

        for user_id, messages in raw.items():
            if not isinstance(messages, list):
                continue

            clean_messages: list[dict[str, str]] = []
            for msg in messages[-self.max_messages:]:
                if not isinstance(msg, dict):
                    continue

                role = msg.get("role")
                content = msg.get("content")
                if role in {"user", "assistant"} and isinstance(content, str):
                    clean_messages.append({
                        "role": role,
                        "content": clamp_text(content, 4000),
                    })

            self.histories[str(user_id)] = deque(clean_messages, maxlen=self.max_messages)

    def save(self) -> None:
        if self.max_messages <= 0:
            return

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {user_id: list(messages) for user_id, messages in self.histories.items()}
            tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(self.path)
        except Exception as error:
            logger.warning("Cannot save memory file %s: %s", self.path, error)

    def get(self, user_id: int) -> list[dict[str, str]]:
        if self.max_messages <= 0:
            return []
        return list(self.histories[str(user_id)])

    def add_turn(self, user_id: int, question: str, answer: str) -> None:
        if self.max_messages <= 0:
            return

        key = str(user_id)
        self.histories[key].append({"role": "user", "content": clamp_text(question, 4000)})
        self.histories[key].append({"role": "assistant", "content": clamp_text(answer, 4000)})
        self.save()

    def reset(self, user_id: int) -> None:
        self.histories[str(user_id)].clear()
        self.save()


memory = PersistentMemory(MEMORY_FILE, MAX_MEMORY_MESSAGES)


# ============================================================
# RATE LIMIT
# ============================================================


last_user_call: dict[int, float] = {}


def cooldown_remaining(user_id: int) -> float:
    if USER_COOLDOWN_SECONDS <= 0:
        return 0.0

    now = time.monotonic()
    last = last_user_call.get(user_id, 0.0)
    remaining = USER_COOLDOWN_SECONDS - (now - last)

    if remaining <= 0:
        last_user_call[user_id] = now
        return 0.0

    return remaining


# ============================================================
# PROMPT BUILDER
# ============================================================


def build_messages(
    user_id: int,
    question: str,
    mode: str = "auto",
    depth: str = "normal",
    channel_context: str = "",
    extra_system: str = "",
) -> list[dict[str, str]]:
    mode = normalize_mode(mode)
    depth = normalize_depth(depth)

    system = f"""
{SYSTEM_PROMPT}

THỜI ĐIỂM BOT:
- Thời gian máy chạy bot: {now_string()}.
- Nếu câu hỏi cần dữ liệu mới/current/latest mà không có dữ liệu trong prompt, hãy nói rõ cần kiểm chứng thêm.

{MODE_PROMPTS[mode]}

{DEPTH_PROMPTS[depth]}

{extra_system}
""".strip()

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]

    if channel_context.strip():
        messages.append({
            "role": "system",
            "content": (
                "Context gần đây trong kênh Discord, chỉ dùng nếu liên quan. "
                "Không lộ thông tin không cần thiết.\n\n"
                + clamp_text(channel_context, 6000)
            ),
        })

    messages.extend(memory.get(user_id))
    messages.append({"role": "user", "content": clamp_text(question, MAX_PROMPT_CHARS)})
    return messages


# ============================================================
# DISCORD BOT
# ============================================================


class OllamaDiscordBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        # Bật Message Content Intent trong Discord Developer Portal nếu muốn:
        # - đọc context_messages
        # - bot trả lời khi được mention
        intents.message_content = True

        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.http: aiohttp.ClientSession | None = None
        self.ollama_semaphore = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)

    async def setup_hook(self) -> None:
        timeout = aiohttp.ClientTimeout(total=OLLAMA_TIMEOUT)
        self.http = aiohttp.ClientSession(timeout=timeout)

        if DISCORD_GUILD_ID:
            try:
                guild_id = int(DISCORD_GUILD_ID)
            except ValueError as error:
                raise RuntimeError("DISCORD_GUILD_ID phải là số ID của server Discord.") from error

            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info("Synced %s slash command(s) to guild %s", len(synced), guild_id)
        else:
            synced = await self.tree.sync()
            logger.info("Synced %s global slash command(s)", len(synced))

    async def close(self) -> None:
        if self.http and not self.http.closed:
            await self.http.close()
        await super().close()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s", self.user)
        logger.info("Ollama host: %s", OLLAMA_HOST)
        logger.info("Ollama model: %s", OLLAMA_MODEL)

    async def on_message(self, message: discord.Message) -> None:
        """Allow natural use: DM the bot or mention it in a server."""
        if message.author.bot or self.user is None:
            return

        is_dm = message.guild is None
        is_mentioned = self.user in message.mentions
        if not is_dm and not is_mentioned:
            return

        question = strip_discord_mentions(message.content, self.user.id)
        if not question:
            await message.reply(
                "Duy gọi tiểu hầu cận có việc gì? Hãy hỏi trực tiếp hoặc dùng `/ask` nhé.",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        remaining = cooldown_remaining(message.author.id)
        if remaining > 0:
            await message.reply(
                f"⏳ Tiểu hầu cận đang hồi mana. Thử lại sau `{remaining:.1f}s`.",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        async with message.channel.typing():
            try:
                context = await get_channel_context_from_message(message, DEFAULT_CONTEXT_MESSAGES)
                messages = build_messages(
                    user_id=message.author.id,
                    question=question,
                    mode="auto",
                    depth="normal",
                    channel_context=context,
                )
                answer = await self.complete_ollama(messages, temperature=TEMPERATURE_BY_MODE["auto"])
                memory.add_turn(message.author.id, question, answer)
            except Exception as error:
                await message.reply(
                    "⚠️ Tiểu hầu cận không gọi được Ollama.\n\n"
                    f"Lỗi: `{safe_error(error)}`\n\n"
                    "Checklist: `ollama serve`, `ollama list`, kiểm tra `.env`.",
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return

        first = True
        for chunk in split_discord_message(answer):
            if first:
                await message.reply(
                    chunk,
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                first = False
            else:
                await message.channel.send(chunk, allowed_mentions=discord.AllowedMentions.none())

    async def complete_ollama(self, messages: list[dict[str, str]], temperature: float = 0.55) -> str:
        if self.http is None:
            raise RuntimeError("HTTP session chưa sẵn sàng.")

        payload: dict[str, Any] = {
            "model": OLLAMA_MODEL,
            "stream": False,
            "messages": messages,
            "options": {
                "temperature": temperature,
                "top_p": 0.9,
                "repeat_penalty": 1.1,
                "num_ctx": OLLAMA_NUM_CTX,
            },
        }

        async with self.ollama_semaphore:
            async with self.http.post(f"{OLLAMA_HOST}/api/chat", json=payload) as response:
                raw = await response.text()

        if response.status != 200:
            raise RuntimeError(f"Ollama API error {response.status}: {clamp_text(raw, 700)}")

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Ollama trả về JSON lỗi: {clamp_text(raw, 700)}") from error

        answer = data.get("message", {}).get("content", "")
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("Ollama không trả về nội dung.")

        return answer.strip()

    async def list_ollama_models(self) -> list[str]:
        if self.http is None:
            raise RuntimeError("HTTP session chưa sẵn sàng.")

        async with self.http.get(f"{OLLAMA_HOST}/api/tags") as response:
            raw = await response.text()

        if response.status != 200:
            raise RuntimeError(f"Ollama API error {response.status}: {clamp_text(raw, 700)}")

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Ollama trả về JSON lỗi: {clamp_text(raw, 700)}") from error

        models = data.get("models", [])
        if not isinstance(models, list):
            return []

        names: list[str] = []
        for model in models:
            if isinstance(model, dict):
                name = model.get("name")
                if isinstance(name, str):
                    names.append(name)
        return names


bot = OllamaDiscordBot()


# ============================================================
# CONTEXT READERS
# ============================================================


async def get_channel_context_from_history(
    channel: Any,
    before: Any,
    limit: int,
) -> str:
    limit = max(0, min(limit, 10))
    if limit <= 0 or channel is None or not hasattr(channel, "history"):
        return ""

    lines: list[str] = []

    try:
        async for msg in channel.history(limit=limit + 8, before=before):
            if msg.author.bot:
                continue
            content = (msg.content or "").strip()
            if not content:
                continue

            display_name = getattr(msg.author, "display_name", str(msg.author))
            lines.append(f"{display_name}: {clamp_text(content, 700)}")

            if len(lines) >= limit:
                break
    except Exception as error:
        logger.debug("Cannot read channel context: %s", error)
        return ""

    lines.reverse()
    return "\n".join(lines)


async def get_channel_context_from_interaction(interaction: discord.Interaction, limit: int) -> str:
    return await get_channel_context_from_history(interaction.channel, interaction.created_at, limit)


async def get_channel_context_from_message(message: discord.Message, limit: int) -> str:
    return await get_channel_context_from_history(message.channel, message.created_at, limit)


# ============================================================
# RESPONSE HELPER
# ============================================================


async def run_ai_and_reply(
    interaction: discord.Interaction,
    question: str,
    mode: str = "auto",
    depth: str = "normal",
    private: bool = False,
    remember: bool = True,
    context_messages: int = 0,
    extra_system: str = "",
) -> None:
    mode = normalize_mode(mode)
    depth = normalize_depth(depth)
    context_messages = max(0, min(context_messages, 10))

    remaining = cooldown_remaining(interaction.user.id)
    if remaining > 0:
        await interaction.response.send_message(
            f"⏳ Tiểu hầu cận đang hồi mana. Thử lại sau `{remaining:.1f}s`.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return

    await interaction.response.defer(thinking=True, ephemeral=private)

    try:
        channel_context = await get_channel_context_from_interaction(interaction, context_messages)
        messages = build_messages(
            user_id=interaction.user.id,
            question=question,
            mode=mode,
            depth=depth,
            channel_context=channel_context,
            extra_system=extra_system,
        )

        answer = await bot.complete_ollama(messages, temperature=TEMPERATURE_BY_MODE.get(mode, 0.55))

        if remember:
            memory.add_turn(interaction.user.id, question, answer)

    except asyncio.TimeoutError:
        await interaction.followup.send(
            "⚠️ Ollama phản hồi quá lâu nên bị timeout.\n\n"
            "Cách xử lý:\n"
            "- Dùng model nhẹ hơn.\n"
            "- Giảm độ dài câu hỏi/file.\n"
            "- Tăng `OLLAMA_TIMEOUT` trong `.env`.\n"
            "- Kiểm tra máy có đủ RAM/VRAM không.",
            ephemeral=private,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return

    except Exception as error:
        await interaction.followup.send(
            "⚠️ Tiểu hầu cận không gọi được Ollama.\n\n"
            f"Lỗi: `{safe_error(error)}`\n\n"
            "Checklist:\n"
            "- Chạy: `ollama serve`\n"
            f"- Pull model: `ollama pull {OLLAMA_MODEL}`\n"
            "- Kiểm tra `.env`: `OLLAMA_HOST=http://localhost:11434`\n"
            "- Kiểm tra model có tồn tại chưa: `ollama list`",
            ephemeral=private,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return

    for chunk in split_discord_message(answer):
        await interaction.followup.send(
            chunk,
            ephemeral=private,
            allowed_mentions=discord.AllowedMentions.none(),
        )


# ============================================================
# SLASH COMMANDS
# ============================================================


@bot.tree.command(name="ask", description="Hỏi Tiểu Hầu Cận AI với mode, depth, memory và context")
@app_commands.describe(
    question="Câu hỏi bạn muốn hỏi AI",
    mode="Chế độ trả lời",
    depth="Độ sâu câu trả lời",
    private="Chỉ bạn thấy câu trả lời",
    remember="Lưu vào trí nhớ hội thoại ngắn",
    context_messages="Đọc thêm bao nhiêu tin nhắn gần đây trong kênh, 0-10",
)
@app_commands.choices(
    mode=[
        app_commands.Choice(name="Auto", value="auto"),
        app_commands.Choice(name="Code", value="code"),
        app_commands.Choice(name="Study", value="study"),
        app_commands.Choice(name="Research", value="research"),
        app_commands.Choice(name="Planner", value="planner"),
        app_commands.Choice(name="Critic", value="critic"),
        app_commands.Choice(name="Fun", value="fun"),
    ],
    depth=[
        app_commands.Choice(name="Quick", value="quick"),
        app_commands.Choice(name="Normal", value="normal"),
        app_commands.Choice(name="Deep", value="deep"),
    ],
)
async def ask(
    interaction: discord.Interaction,
    question: str,
    mode: str = "auto",
    depth: str = "normal",
    private: bool = False,
    remember: bool = True,
    context_messages: int = 0,
) -> None:
    await run_ai_and_reply(
        interaction=interaction,
        question=question,
        mode=mode,
        depth=depth,
        private=private,
        remember=remember,
        context_messages=context_messages,
    )


@bot.tree.command(name="codeai", description="Nhờ AI review, sửa lỗi hoặc tối ưu code")
@app_commands.describe(
    code="Dán code hoặc lỗi cần phân tích",
    language="Ngôn ngữ lập trình, ví dụ Python, Java, C++",
    private="Chỉ bạn thấy câu trả lời",
)
async def codeai(
    interaction: discord.Interaction,
    code: str,
    language: str = "không rõ",
    private: bool = True,
) -> None:
    question = f"""
Ngôn ngữ: {language}

Hãy review/sửa/tối ưu đoạn code hoặc lỗi sau:

```text
{code}
```
""".strip()

    extra_system = """
Nhiệm vụ riêng cho /codeai:
- Tìm lỗi logic, lỗi runtime, lỗi syntax nếu có.
- Đưa bản code sửa được nếu đủ dữ liệu.
- Nếu thiếu context, nêu giả định rồi sửa theo giả định.
- Có test case nhỏ nếu phù hợp.
""".strip()

    await run_ai_and_reply(
        interaction=interaction,
        question=question,
        mode="code",
        depth="deep",
        private=private,
        remember=True,
        context_messages=0,
        extra_system=extra_system,
    )


@bot.tree.command(name="studyai", description="Biến AI thành gia sư học tập")
@app_commands.describe(
    topic="Chủ đề muốn học",
    level="Trình độ hiện tại, ví dụ beginner/intermediate/advanced",
    private="Chỉ bạn thấy câu trả lời",
)
async def studyai(
    interaction: discord.Interaction,
    topic: str,
    level: str = "beginner",
    private: bool = False,
) -> None:
    question = f"""
Hãy dạy tôi chủ đề sau như một gia sư giỏi.

Chủ đề: {topic}
Trình độ hiện tại: {level}

Yêu cầu:
- Giải thích dễ hiểu.
- Có ví dụ.
- Có checklist học.
- Có 3 câu hỏi kiểm tra cuối bài.
""".strip()

    await run_ai_and_reply(
        interaction=interaction,
        question=question,
        mode="study",
        depth="deep",
        private=private,
        remember=True,
    )


@bot.tree.command(name="planai", description="Tạo kế hoạch học tập hoặc dự án")
@app_commands.describe(
    goal="Mục tiêu cần lập kế hoạch",
    days="Số ngày muốn hoàn thành",
    private="Chỉ bạn thấy câu trả lời",
)
async def planai(
    interaction: discord.Interaction,
    goal: str,
    days: int = 7,
    private: bool = False,
) -> None:
    days = max(1, min(days, 365))
    question = f"""
Hãy lập kế hoạch cho mục tiêu sau:

Mục tiêu: {goal}
Thời gian: {days} ngày

Yêu cầu:
- Chia phase rõ ràng.
- Có checklist từng ngày hoặc từng giai đoạn.
- Có output cần đạt.
- Có definition of done.
- Có cách đo tiến độ.
""".strip()

    await run_ai_and_reply(
        interaction=interaction,
        question=question,
        mode="planner",
        depth="deep",
        private=private,
        remember=True,
    )


@bot.tree.command(name="criticai", description="Nhờ AI phản biện ý tưởng hoặc kế hoạch")
@app_commands.describe(
    idea="Ý tưởng/kế hoạch cần phản biện",
    private="Chỉ bạn thấy câu trả lời",
)
async def criticai(
    interaction: discord.Interaction,
    idea: str,
    private: bool = True,
) -> None:
    question = f"""
Hãy phản biện kế hoạch/ý tưởng sau một cách sắc bén nhưng xây dựng:

{idea}

Yêu cầu:
- Chỉ ra điểm yếu.
- Chỉ ra rủi ro.
- Chỉ ra phần còn mơ hồ.
- Đưa phiên bản cải thiện.
""".strip()

    await run_ai_and_reply(
        interaction=interaction,
        question=question,
        mode="critic",
        depth="deep",
        private=private,
        remember=True,
    )


@bot.tree.command(name="summarizeai", description="Tóm tắt văn bản dài")
@app_commands.describe(
    text="Văn bản cần tóm tắt",
    private="Chỉ bạn thấy câu trả lời",
)
async def summarizeai(
    interaction: discord.Interaction,
    text: str,
    private: bool = True,
) -> None:
    question = f"""
Hãy tóm tắt văn bản sau:

{text}

Yêu cầu:
- Tóm tắt ngắn.
- Gạch ý chính.
- Nêu việc cần làm tiếp theo nếu có.
""".strip()

    await run_ai_and_reply(
        interaction=interaction,
        question=question,
        mode="research",
        depth="normal",
        private=private,
        remember=False,
    )


@bot.tree.command(name="fileai", description="Gửi file text/code/log cho AI phân tích")
@app_commands.describe(
    file="File text/code/log cần phân tích",
    question="Bạn muốn hỏi gì về file này?",
    private="Chỉ bạn thấy câu trả lời",
)
async def fileai(
    interaction: discord.Interaction,
    file: discord.Attachment,
    question: str = "Hãy phân tích file này và chỉ ra điểm quan trọng.",
    private: bool = True,
) -> None:
    suffix = Path(file.filename).suffix.lower()

    if not is_text_attachment(file.filename, file.content_type):
        await interaction.response.send_message(
            "⚠️ Hiện tại `/fileai` chỉ đọc file text/code/log/json/csv/sql/md. "
            "File này có vẻ không phải dạng text.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return

    if file.size > MAX_ATTACHMENT_BYTES:
        await interaction.response.send_message(
            f"⚠️ File quá lớn: `{file.size}` bytes.\n"
            f"Giới hạn hiện tại: `{MAX_ATTACHMENT_BYTES}` bytes.\n"
            "Hãy cắt phần lỗi/code quan trọng rồi gửi lại, hoặc tăng `MAX_ATTACHMENT_BYTES` trong `.env`.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return

    remaining = cooldown_remaining(interaction.user.id)
    if remaining > 0:
        await interaction.response.send_message(
            f"⏳ Tiểu hầu cận đang hồi mana. Thử lại sau `{remaining:.1f}s`.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return

    await interaction.response.defer(thinking=True, ephemeral=private)

    try:
        raw_bytes = await file.read()
        file_text = raw_bytes.decode("utf-8", errors="replace")
    except Exception as error:
        await interaction.followup.send(
            f"⚠️ Không đọc được file: `{safe_error(error)}`",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return

    prompt = f"""
Tên file: {file.filename}
Loại file: {file.content_type or "không rõ"}
Kích thước: {file.size} bytes

Câu hỏi của Duy:
{question}

Nội dung file:

```text
{clamp_text(file_text, MAX_PROMPT_CHARS)}
```
""".strip()

    extra_system = """
Nhiệm vụ riêng cho /fileai:
- Phân tích đúng nội dung file được cung cấp.
- Nếu là code/log, ưu tiên lỗi, nguyên nhân, cách sửa.
- Nếu là tài liệu, ưu tiên tóm tắt, insight, việc cần làm.
- Không giả vờ đã chạy file nếu chỉ mới đọc nội dung.
""".strip()

    mode = "code" if suffix in CODE_EXTENSIONS else "research"

    try:
        messages = build_messages(
            user_id=interaction.user.id,
            question=prompt,
            mode=mode,
            depth="deep",
            extra_system=extra_system,
        )
        answer = await bot.complete_ollama(messages, temperature=0.3)
        memory.add_turn(interaction.user.id, f"[fileai] {file.filename}: {question}", answer)
    except Exception as error:
        await interaction.followup.send(
            f"⚠️ Ollama lỗi khi phân tích file: `{safe_error(error)}`",
            ephemeral=private,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return

    for chunk in split_discord_message(answer):
        await interaction.followup.send(
            chunk,
            ephemeral=private,
            allowed_mentions=discord.AllowedMentions.none(),
        )


@bot.tree.command(name="resetai", description="Xóa trí nhớ hội thoại ngắn của bạn với AI")
async def resetai(interaction: discord.Interaction) -> None:
    memory.reset(interaction.user.id)
    await interaction.response.send_message(
        "🧹 Đã xóa trí nhớ hội thoại ngắn của bạn với Tiểu Hầu Cận.",
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@bot.tree.command(name="personaai", description="Xem persona hiện tại của bot")
async def personaai(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        "**Persona hiện tại:** Tiểu Hầu Cận — hầu cận tri thức của Duy.\n\n"
        "- Hỗ trợ học tập, lập trình, nghiên cứu, productivity.\n"
        "- Có mode: auto, code, study, research, planner, critic, fun.\n"
        "- Có memory ngắn theo từng user.\n"
        "- Có thể đọc context kênh nếu dùng `context_messages`.\n"
        "- Có thể đọc file text/code/log bằng `/fileai`.\n"
        "- Có thể trả lời khi được mention hoặc khi nhắn DM.\n\n"
        "Gợi ý mạnh nhất: dùng `/ask mode:Critic depth:Deep` để phản biện ý tưởng, "
        "hoặc `/codeai` để soi code.",
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@bot.tree.command(name="pingai", description="Kiểm tra Discord bot và Ollama")
async def pingai(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True, ephemeral=True)

    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Trả lời cực ngắn: hệ thống AI đang hoạt động chưa?"},
        ]
        answer = await bot.complete_ollama(messages, temperature=0.2)
        await interaction.followup.send(
            f"✅ Discord bot hoạt động.\n"
            f"🤖 Ollama model: `{OLLAMA_MODEL}`\n"
            f"📡 Host: `{OLLAMA_HOST}`\n"
            f"🧠 AI trả lời: {answer}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except Exception as error:
        await interaction.followup.send(
            f"✅ Discord bot hoạt động, nhưng Ollama lỗi: `{safe_error(error)}`",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


@bot.tree.command(name="modelai", description="Kiểm tra danh sách model Ollama")
async def modelai(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True, ephemeral=True)

    try:
        names = await bot.list_ollama_models()

        if not names:
            await interaction.followup.send(
                "⚠️ Ollama đang chạy nhưng chưa thấy model nào. "
                f"Hãy chạy: `ollama pull {OLLAMA_MODEL}`",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        model_list = "\n".join(f"- `{name}`" for name in names[:30])
        if len(names) > 30:
            model_list += f"\n- ... và {len(names) - 30} model khác"

        status = (
            "✅ Model đang cấu hình có trong Ollama."
            if any(name == OLLAMA_MODEL or name.startswith(f"{OLLAMA_MODEL}:") for name in names)
            else "⚠️ Model trong `.env` có thể chưa tồn tại trong Ollama."
        )

        await interaction.followup.send(
            f"**Ollama models:**\n{model_list}\n\n"
            f"Model đang dùng: `{OLLAMA_MODEL}`\n"
            f"{status}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except Exception as error:
        await interaction.followup.send(
            f"⚠️ Không kiểm tra được model Ollama: `{safe_error(error)}`",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


@bot.tree.command(name="helpai", description="Xem hướng dẫn dùng các lệnh AI")
async def helpai(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        "**Lệnh Tiểu Hầu Cận**\n\n"
        "- `/ask` — hỏi tự do, chọn mode/depth/context/memory.\n"
        "- `/codeai` — review, sửa lỗi, tối ưu code.\n"
        "- `/studyai` — học một chủ đề như có gia sư.\n"
        "- `/planai` — lập kế hoạch học tập/dự án.\n"
        "- `/criticai` — phản biện ý tưởng/kế hoạch.\n"
        "- `/summarizeai` — tóm tắt văn bản dài.\n"
        "- `/fileai` — phân tích file text/code/log.\n"
        "- `/resetai` — xóa memory ngắn của riêng bạn.\n"
        "- `/pingai` — kiểm tra bot + Ollama.\n"
        "- `/modelai` — xem model Ollama hiện có.\n\n"
        "Bạn cũng có thể mention bot trong kênh hoặc nhắn DM nếu đã bật Message Content Intent.",
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


# ============================================================
# START
# ============================================================


def validate_startup_config() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError("Thiếu DISCORD_TOKEN trong file .env")
    if not OLLAMA_MODEL:
        raise RuntimeError("Thiếu OLLAMA_MODEL trong file .env")


def main() -> None:
    validate_startup_config()
    bot.run(DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
