"""声明模型可用工具，校验调用，并原子记录执行结果。"""

import json
from dataclasses import asdict

from ai import Tool, ToolResultMessage
from ai.errors import ToolValidationError
from ai.tools import validate_tool_call

from dialogue_lab.memory.service import MemoryService
from dialogue_lab.sessions.types import SessionError
from dialogue_lab.storage.memory_store import MemoryStore

STATE_TOOL = Tool(
    name="update_session_state",
    description=(
        "建立、修改或结束持续性的交流约定。一次性问题不更新状态。"
        "省略字段保留原值，activity=null 结束活动，instructions 整体替换，[] 清空要求。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "activity": {"type": ["string", "null"]},
            "instructions": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
        "minProperties": 1,
    },
)

SAVE_MEMORY_TOOL = Tool(
    name="save_memory",
    description=(
        "保存用户明确要求记住的信息或明确表达的稳定偏好。不要保存推测、角色扮演虚构事实。"
        "默认来源是本轮用户消息；只有需要每次加载的偏好才标记 is_core。"
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "content": {"type": "string", "minLength": 1, "maxLength": 4000, "pattern": "\\S"},
            "is_core": {"type": "boolean"},
            "memory_id": {"type": "integer", "minimum": 1},
            "source_message_ids": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "integer", "minimum": 1},
            },
        },
        "required": ["content"],
    },
)

SEARCH_MEMORY_TOOL = Tool(
    name="search_memory",
    description=(
        "按文字片段查找当前角色的记忆，返回最多 10 条及来源；空查询列出近期记忆。"
        "时间过滤使用带时区的 ISO 时间。"
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query": {"type": "string", "maxLength": 200},
            "after": {"type": "string"},
            "before": {"type": "string"},
        },
        "required": ["query"],
    },
)

HISTORY_TOOL = Tool(
    name="read_history",
    description="根据记忆返回的来源定位，读取当前角色的原始对话。",
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "session_id": {"type": "integer", "minimum": 1},
            "message_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 10,
                "uniqueItems": True,
                "items": {"type": "integer", "minimum": 1},
            },
        },
        "required": ["session_id", "message_ids"],
    },
)

FORGET_MEMORY_TOOL = Tool(
    name="forget_memory",
    description="按用户要求撤回指定记忆；撤回后不再作为有效事实使用。",
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {"memory_id": {"type": "integer", "minimum": 1}},
        "required": ["memory_id"],
    },
)


class Tools:
    def __init__(self, sessions, memory=None):
        self.sessions = sessions
        self.memory = memory or MemoryService(MemoryStore(sessions.store.database))

    async def definitions(self, session_id):
        session = await self.sessions.store.get(session_id)
        return available_tools(session["character_id"])

    async def execute(self, session_id, request_id, step, call, signal=None):
        async def operation(connection, session):
            definitions = {tool.name: tool for tool in available_tools(session["character_id"])}
            try:
                tool = definitions.get(call.name)
                if tool is None:
                    raise SessionError("UNKNOWN_TOOL", "当前会话不提供这个工具。")
                arguments = validate_tool_call(tool, call)
                if call.name == "update_session_state":
                    result = await self.sessions.update_state(connection, session, arguments)
                elif call.name == "search_memory":
                    result = await self.memory.search(connection, session, **arguments)
                elif call.name == "read_history":
                    result = await self.sessions.read_history(connection, session, **arguments)
                elif call.name == "forget_memory":
                    result = await self.memory.forget(connection, session, **arguments)
                else:
                    result = await self.memory.save(connection, session, request_id, **arguments)
                payload = asdict(
                    ToolResultMessage(
                        call.id,
                        call.name,
                        json.dumps(result, ensure_ascii=False),
                    )
                )
                if call.name == "save_memory":
                    payload["memory_refs"] = {str(result["id"]): result["revision"]}
                    if "memory_id" in arguments:
                        payload["memory_mutation"] = result["id"]
                elif call.name == "search_memory":
                    payload["memory_refs"] = {
                        str(m["id"]): m["revision"] for m in result["matches"]
                    }
                elif call.name == "forget_memory":
                    payload["memory_mutation"] = arguments["memory_id"]
                elif call.name == "read_history":
                    payload["source_message_ids"] = arguments["message_ids"]
                return payload
            except (ToolValidationError, SessionError) as error:
                return asdict(
                    ToolResultMessage(
                        call.id,
                        call.name,
                        json.dumps(
                            {
                                "code": error.code
                                if isinstance(error, SessionError)
                                else "INVALID_TOOL_ARGUMENTS",
                                "message": str(error),
                            },
                            ensure_ascii=False,
                        ),
                        is_error=True,
                    )
                )

        return await self.sessions.execute_tool(
            session_id,
            request_id,
            step,
            call,
            operation,
            signal,
        )


def available_tools(character_id):
    return (
        [STATE_TOOL, SAVE_MEMORY_TOOL, SEARCH_MEMORY_TOOL, HISTORY_TOOL, FORGET_MEMORY_TOOL]
        if character_id is not None
        else [STATE_TOOL]
    )
