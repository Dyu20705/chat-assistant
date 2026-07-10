import json
from types import SimpleNamespace

import pytest

import bot


@pytest.mark.parametrize(
    ("raw", "default", "minimum", "maximum", "expected"),
    [
        ("42", 7, None, None, 42),
        ("bad", 7, None, None, 7),
        (None, 7, 10, None, 10),
        ("100", 7, None, 20, 20),
        ("5", 7, 10, 20, 10),
    ],
)
def test_env_int(monkeypatch, raw, default, minimum, maximum, expected):
    if raw is None:
        monkeypatch.delenv("BOT_INT", raising=False)
    else:
        monkeypatch.setenv("BOT_INT", raw)

    assert bot.env_int("BOT_INT", default, minimum=minimum, maximum=maximum) == expected


@pytest.mark.parametrize(
    ("raw", "default", "minimum", "maximum", "expected"),
    [
        ("2.5", 1.0, None, None, 2.5),
        ("bad", 1.0, None, None, 1.0),
        (None, 1.0, 2.0, None, 2.0),
        ("8.5", 1.0, None, 3.0, 3.0),
        ("0.5", 1.0, 2.0, 3.0, 2.0),
    ],
)
def test_env_float(monkeypatch, raw, default, minimum, maximum, expected):
    if raw is None:
        monkeypatch.delenv("BOT_FLOAT", raising=False)
    else:
        monkeypatch.setenv("BOT_FLOAT", raw)

    assert bot.env_float("BOT_FLOAT", default, minimum=minimum, maximum=maximum) == expected


def test_clamp_text_handles_none_short_and_long_text():
    assert bot.clamp_text(None, 10) == ""
    assert bot.clamp_text("short", 10) == "short"

    clamped = bot.clamp_text("abcdef", 3)

    assert clamped.startswith("abc")
    assert "đã cắt bớt" in clamped


def test_strip_discord_mentions_removes_bot_mentions_and_normalizes_space():
    text = "  hello   <@123> and <@!123>\nthere <@456> "

    assert bot.strip_discord_mentions(text, 123) == "hello and there <@456>"
    assert bot.strip_discord_mentions("  hello   world  ", None) == "hello world"


def test_split_discord_message_empty_text():
    assert bot.split_discord_message("") == ["Ollama không trả về nội dung."]
    assert bot.split_discord_message("   \n ") == ["Ollama không trả về nội dung."]


def test_split_discord_message_keeps_short_text_intact():
    assert bot.split_discord_message("hello", limit=10) == ["hello"]


def test_split_discord_message_exact_boundary():
    assert bot.split_discord_message("x" * 10, limit=10) == ["x" * 10]


def test_split_discord_message_multiline_chunks_on_line_boundaries():
    chunks = bot.split_discord_message("one\ntwo\nthree", limit=8)

    assert chunks == ["one\ntwo", "three"]


def test_split_discord_message_hard_splits_single_oversized_line():
    chunks = bot.split_discord_message("abcdefghijkl", limit=5)

    assert chunks == ["abcde", "fghij", "kl"]


def test_normalize_mode_and_depth():
    assert bot.normalize_mode("code") == "code"
    assert bot.normalize_mode("missing") == "auto"
    assert bot.normalize_depth("deep") == "deep"
    assert bot.normalize_depth("missing") == "normal"


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    [
        ("notes.md", None, True),
        ("data.JSON", "application/octet-stream", True),
        ("archive.bin", "text/plain", True),
        ("payload.bin", "application/json", True),
        ("payload.bin", "application/x-yaml", True),
        ("payload.bin", "application/octet-stream", False),
    ],
)
def test_is_text_attachment(filename, content_type, expected):
    assert bot.is_text_attachment(filename, content_type) is expected


def test_persistent_memory_round_trip(tmp_path):
    path = tmp_path / "memory.json"
    memory = bot.PersistentMemory(path, max_messages=4)

    memory.add_turn(123, "question", "answer")
    reloaded = bot.PersistentMemory(path, max_messages=4)

    assert reloaded.get(123) == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]


@pytest.mark.parametrize("payload", ["not json", "[]", "{\"user\": \"not-list\"}"])
def test_persistent_memory_ignores_malformed_or_unexpected_json(tmp_path, payload):
    path = tmp_path / "memory.json"
    path.write_text(payload, encoding="utf-8")

    memory = bot.PersistentMemory(path, max_messages=4)

    assert memory.get(123) == []


def test_persistent_memory_filters_and_truncates_loaded_messages(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text(
        json.dumps(
            {
                "123": [
                    {"role": "system", "content": "skip"},
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "second"},
                    {"role": "assistant", "content": "x" * 4100},
                    {"role": "assistant", "content": 123},
                ]
            }
        ),
        encoding="utf-8",
    )

    memory = bot.PersistentMemory(path, max_messages=2)

    assert len(memory.get(123)) == 1
    assert memory.get(123)[0]["role"] == "assistant"
    assert "đã cắt bớt" in memory.get(123)[0]["content"]


def test_persistent_memory_enforces_history_length(tmp_path):
    memory = bot.PersistentMemory(tmp_path / "memory.json", max_messages=3)

    memory.add_turn(123, "q1", "a1")
    memory.add_turn(123, "q2", "a2")

    assert memory.get(123) == [
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]


def test_persistent_memory_reset(tmp_path):
    memory = bot.PersistentMemory(tmp_path / "memory.json", max_messages=4)
    memory.add_turn(123, "question", "answer")

    memory.reset(123)

    assert memory.get(123) == []
    assert json.loads((tmp_path / "memory.json").read_text(encoding="utf-8")) == {"123": []}


def test_persistent_memory_disabled_does_not_write(tmp_path):
    path = tmp_path / "memory.json"
    memory = bot.PersistentMemory(path, max_messages=0)

    memory.add_turn(123, "question", "answer")
    memory.save()

    assert memory.get(123) == []
    assert not path.exists()


def test_build_messages_uses_normalized_prompts_context_memory_and_limits(monkeypatch):
    class FakeMemory:
        def get(self, user_id):
            assert user_id == 123
            return [{"role": "assistant", "content": "previous answer"}]

    monkeypatch.setattr(bot, "memory", FakeMemory())
    monkeypatch.setattr(bot, "now_string", lambda: "2026-07-10 12:00:00")
    monkeypatch.setattr(bot, "MAX_PROMPT_CHARS", 12)

    messages = bot.build_messages(
        user_id=123,
        question="x" * 20,
        mode="not-real",
        depth="not-real",
        channel_context="recent channel context",
        extra_system="extra instruction",
    )

    assert messages[0]["role"] == "system"
    assert "MODE AUTO" in messages[0]["content"]
    assert "ĐỘ SÂU NORMAL" in messages[0]["content"]
    assert "2026-07-10 12:00:00" in messages[0]["content"]
    assert "extra instruction" in messages[0]["content"]
    assert messages[1]["role"] == "system"
    assert "recent channel context" in messages[1]["content"]
    assert messages[2] == {"role": "assistant", "content": "previous answer"}
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"].startswith("x" * 12)
    assert "đã cắt bớt" in messages[-1]["content"]


def test_cooldown_remaining_records_first_call_and_blocks_second(monkeypatch):
    times = iter([100.0, 101.0, 104.5])
    monkeypatch.setattr(bot.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(bot, "USER_COOLDOWN_SECONDS", 3.0)
    bot.last_user_call.clear()

    assert bot.cooldown_remaining(123) == 0.0
    assert bot.cooldown_remaining(123) == pytest.approx(2.0)
    assert bot.cooldown_remaining(123) == 0.0


def test_cooldown_remaining_disabled(monkeypatch):
    monkeypatch.setattr(bot, "USER_COOLDOWN_SECONDS", 0.0)
    bot.last_user_call.clear()

    assert bot.cooldown_remaining(123) == 0.0
    assert bot.last_user_call == {}


def test_command_tree_is_registered_without_starting_discord_client():
    command_names = {command.name for command in bot.bot.tree.get_commands()}

    assert {"ask", "codeai", "studyai", "fileai", "pingai", "helpai"}.issubset(command_names)


def test_run_ai_normalizes_mode_depth_and_context_limit_without_network(monkeypatch):
    captured = {}

    async def fake_context(interaction, limit):
        captured["context_limit"] = limit
        return ""

    async def fake_complete(messages, temperature):
        captured["messages"] = messages
        captured["temperature"] = temperature
        return "answer"

    class FakeResponse:
        async def defer(self, **kwargs):
            captured["defer"] = kwargs

    class FakeFollowup:
        async def send(self, content, **kwargs):
            captured.setdefault("followups", []).append((content, kwargs))

    class FakeUser:
        id = 123

    class FakeInteraction:
        user = FakeUser()
        response = FakeResponse()
        followup = FakeFollowup()

    monkeypatch.setattr(bot, "cooldown_remaining", lambda user_id: 0.0)
    monkeypatch.setattr(bot, "get_channel_context_from_interaction", fake_context)
    monkeypatch.setattr(bot.bot, "complete_ollama", fake_complete)
    monkeypatch.setattr(bot.memory, "add_turn", lambda user_id, question, answer: captured.update(memory=True))
    monkeypatch.setattr(bot, "split_discord_message", lambda answer: [answer])

    import asyncio

    asyncio.run(
        bot.run_ai_and_reply(
            interaction=FakeInteraction(),
            question="hello",
            mode="not-real",
            depth="not-real",
            private=True,
            remember=True,
            context_messages=999,
        )
    )

    assert captured["context_limit"] == 10
    assert captured["defer"] == {"thinking": True, "ephemeral": True}
    assert "MODE AUTO" in captured["messages"][0]["content"]
    assert "ĐỘ SÂU NORMAL" in captured["messages"][0]["content"]
    assert captured["temperature"] == bot.TEMPERATURE_BY_MODE["auto"]
    assert captured["memory"] is True
    assert captured["followups"][0][0] == "answer"


@pytest.mark.parametrize(
    ("command", "kwargs", "expected_mode", "expected_depth", "expected_fragment"),
    [
        (bot.ask, {"question": "hello"}, "auto", "normal", "hello"),
        (bot.codeai, {"code": "print('x')", "language": "Python"}, "code", "deep", "Ngôn ngữ: Python"),
        (bot.studyai, {"topic": "kanji", "level": "beginner"}, "study", "deep", "Chủ đề: kanji"),
        (bot.planai, {"goal": "ship CI", "days": 999}, "planner", "deep", "Thời gian: 365 ngày"),
        (bot.criticai, {"idea": "skip tests"}, "critic", "deep", "skip tests"),
        (bot.summarizeai, {"text": "long text"}, "research", "normal", "long text"),
    ],
)
def test_ai_command_callbacks_delegate_to_run_ai(monkeypatch, command, kwargs, expected_mode, expected_depth, expected_fragment):
    captured = {}

    async def fake_run_ai_and_reply(**call_kwargs):
        captured.update(call_kwargs)

    monkeypatch.setattr(bot, "run_ai_and_reply", fake_run_ai_and_reply)

    import asyncio

    asyncio.run(command.callback(SimpleNamespace(), **kwargs))

    assert captured["mode"] == expected_mode
    assert captured["depth"] == expected_depth
    assert expected_fragment in captured["question"]


def test_resetai_resets_memory_and_sends_private_response(monkeypatch):
    captured = {}

    class FakeResponse:
        async def send_message(self, content, **kwargs):
            captured["content"] = content
            captured["kwargs"] = kwargs

    interaction = SimpleNamespace(user=SimpleNamespace(id=123), response=FakeResponse())
    monkeypatch.setattr(bot.memory, "reset", lambda user_id: captured.update(reset_user_id=user_id))

    import asyncio

    asyncio.run(bot.resetai.callback(interaction))

    assert captured["reset_user_id"] == 123
    assert captured["kwargs"]["ephemeral"] is True
    assert "Đã xóa" in captured["content"]


@pytest.mark.parametrize("command", [bot.personaai, bot.helpai])
def test_static_response_commands_send_ephemeral_message(command):
    captured = {}

    class FakeResponse:
        async def send_message(self, content, **kwargs):
            captured["content"] = content
            captured["kwargs"] = kwargs

    import asyncio

    asyncio.run(command.callback(SimpleNamespace(response=FakeResponse())))

    assert captured["content"]
    assert captured["kwargs"]["ephemeral"] is True


def test_fileai_rejects_non_text_attachment_without_reading():
    captured = {}

    class FakeResponse:
        async def send_message(self, content, **kwargs):
            captured["content"] = content
            captured["kwargs"] = kwargs

    class FakeFile:
        filename = "image.png"
        content_type = "image/png"
        size = 10

        async def read(self):
            raise AssertionError("file should not be read")

    interaction = SimpleNamespace(response=FakeResponse())

    import asyncio

    asyncio.run(bot.fileai.callback(interaction, FakeFile()))

    assert "chỉ đọc file text" in captured["content"]
    assert captured["kwargs"]["ephemeral"] is True


def test_fileai_rejects_oversized_text_attachment(monkeypatch):
    captured = {}

    class FakeResponse:
        async def send_message(self, content, **kwargs):
            captured["content"] = content
            captured["kwargs"] = kwargs

    file = SimpleNamespace(filename="notes.txt", content_type="text/plain", size=999)
    monkeypatch.setattr(bot, "MAX_ATTACHMENT_BYTES", 10)

    import asyncio

    asyncio.run(bot.fileai.callback(SimpleNamespace(response=FakeResponse()), file))

    assert "File quá lớn" in captured["content"]
    assert captured["kwargs"]["ephemeral"] is True


def test_fileai_reads_text_attachment_and_sends_analysis(monkeypatch):
    captured = {}

    class FakeResponse:
        async def defer(self, **kwargs):
            captured["defer"] = kwargs

    class FakeFollowup:
        async def send(self, content, **kwargs):
            captured.setdefault("followups", []).append((content, kwargs))

    class FakeFile:
        filename = "code.py"
        content_type = "text/x-python"
        size = 20

        async def read(self):
            return b"print('hello')"

    async def fake_complete(messages, temperature):
        captured["messages"] = messages
        captured["temperature"] = temperature
        return "analysis"

    monkeypatch.setattr(bot, "cooldown_remaining", lambda user_id: 0.0)
    monkeypatch.setattr(bot.bot, "complete_ollama", fake_complete)
    monkeypatch.setattr(bot.memory, "add_turn", lambda *args: captured.update(memory_args=args))

    interaction = SimpleNamespace(
        user=SimpleNamespace(id=123),
        response=FakeResponse(),
        followup=FakeFollowup(),
    )

    import asyncio

    asyncio.run(bot.fileai.callback(interaction, FakeFile(), question="review", private=True))

    assert captured["defer"] == {"thinking": True, "ephemeral": True}
    assert "print('hello')" in captured["messages"][-1]["content"]
    assert captured["temperature"] == 0.3
    assert captured["memory_args"][0] == 123
    assert captured["followups"][0][0] == "analysis"


def test_pingai_reports_success_without_contacting_real_ollama(monkeypatch):
    captured = {}

    class FakeResponse:
        async def defer(self, **kwargs):
            captured["defer"] = kwargs

    class FakeFollowup:
        async def send(self, content, **kwargs):
            captured["content"] = content
            captured["kwargs"] = kwargs

    async def fake_complete(messages, temperature):
        captured["messages"] = messages
        captured["temperature"] = temperature
        return "ok"

    monkeypatch.setattr(bot.bot, "complete_ollama", fake_complete)

    import asyncio

    asyncio.run(bot.pingai.callback(SimpleNamespace(response=FakeResponse(), followup=FakeFollowup())))

    assert captured["defer"] == {"thinking": True, "ephemeral": True}
    assert "Discord bot hoạt động" in captured["content"]
    assert captured["temperature"] == 0.2


def test_modelai_reports_configured_models(monkeypatch):
    captured = {}

    class FakeResponse:
        async def defer(self, **kwargs):
            captured["defer"] = kwargs

    class FakeFollowup:
        async def send(self, content, **kwargs):
            captured["content"] = content
            captured["kwargs"] = kwargs

    async def fake_models():
        return [bot.OLLAMA_MODEL, "other"]

    monkeypatch.setattr(bot.bot, "list_ollama_models", fake_models)

    import asyncio

    asyncio.run(bot.modelai.callback(SimpleNamespace(response=FakeResponse(), followup=FakeFollowup())))

    assert captured["defer"] == {"thinking": True, "ephemeral": True}
    assert "Ollama models" in captured["content"]
    assert "Model đang cấu hình" in captured["content"]


def test_get_channel_context_from_history_filters_and_orders_messages():
    class FakeAuthor:
        def __init__(self, name, bot_user=False):
            self.display_name = name
            self.bot = bot_user

    class FakeMessage:
        def __init__(self, name, content, bot_user=False):
            self.author = FakeAuthor(name, bot_user)
            self.content = content

    class FakeChannel:
        async def history(self, limit, before):
            assert limit == 10
            assert before == "marker"
            for message in [
                FakeMessage("ignored", "bot", bot_user=True),
                FakeMessage("A", "first"),
                FakeMessage("B", ""),
                FakeMessage("C", "second"),
            ]:
                yield message

    import asyncio

    context = asyncio.run(bot.get_channel_context_from_history(FakeChannel(), before="marker", limit=2))

    assert context == "C: second\nA: first"


def test_complete_ollama_success_and_list_models(monkeypatch):
    class FakeResponse:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def text(self):
            return json.dumps(self.payload)

    class FakeHttp:
        def post(self, url, json):
            assert url.endswith("/api/chat")
            assert json["messages"] == [{"role": "user", "content": "hello"}]
            return FakeResponse({"message": {"content": " answer "}})

        def get(self, url):
            assert url.endswith("/api/tags")
            return FakeResponse({"models": [{"name": "llama"}, {"name": 123}, "bad"]})

    client = bot.OllamaDiscordBot()
    client.http = FakeHttp()
    monkeypatch.setattr(client, "ollama_semaphore", bot.asyncio.Semaphore(1))

    import asyncio

    assert asyncio.run(client.complete_ollama([{"role": "user", "content": "hello"}])) == "answer"
    assert asyncio.run(client.list_ollama_models()) == ["llama"]


def test_validate_startup_config(monkeypatch):
    monkeypatch.setattr(bot, "DISCORD_TOKEN", "")

    with pytest.raises(RuntimeError, match="DISCORD_TOKEN"):
        bot.validate_startup_config()

    monkeypatch.setattr(bot, "DISCORD_TOKEN", "token")
    monkeypatch.setattr(bot, "OLLAMA_MODEL", "")

    with pytest.raises(RuntimeError, match="OLLAMA_MODEL"):
        bot.validate_startup_config()
