"""重放已经选定的指令段和工具变化，不查询宿主内容。"""

from ai.types.messages import SystemMessage


def fold_system(messages):
    """供只发送当前系统状态的协议使用；同名替换保留顺序。"""
    content = []
    sections = {}
    tools = {}
    for message in messages:
        if not isinstance(message, SystemMessage):
            continue
        if message.content:
            content.append(message.content)
        for name, value in message.sections.items():
            if value is None:
                sections.pop(name, None)
            else:
                sections[name] = value
        for name in message.tools_removed:
            tools.pop(name, None)
        for tool in message.tools_added:
            tools[tool.name] = tool
    return "\n\n".join([*content, *sections.values()]), list(tools.values())
