"""临时验证：add_pet 工具（写操作）。"""

import asyncio
import json
import sys

from mcp import Client

URL_DEFAULT = "http://127.0.0.1:18080/mcp"


def _parse(block) -> object:
    try:
        return json.loads(block.text)
    except Exception:
        return block.text


async def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else URL_DEFAULT
    async with Client(url) as client:
        tools = await client.list_tools()
        print("tools:", [t.name for t in tools.tools])
        for t in tools.tools:
            if t.name == "add_pet":
                req = t.input_schema.get("required")
                print("add_pet required:", req)
                print("add_pet properties:", list(t.input_schema.get("properties", {}).keys()))

        print("\n== add_pet 正常新增 ==")
        result = await client.call_tool(
            "add_pet",
            {
                "owner_name": "MCP验证主人",
                "owner_phone": "13900001111",
                "disease": "犬瘟热",
                "doctor": "王医生",
                "name": "MCP验证犬",
                "species": "犬",
                "breed": "柯基",
                "gender": "母",
                "age_months": 24,
                "status": "待就诊",
            },
        )
        print("is_error:", result.is_error, "resultType:", result.result_type)
        data = _parse(result.content[0])
        print("created:", json.dumps(data, ensure_ascii=False)[:400])
        created_id = data.get("id") if isinstance(data, dict) else None

        print("\n== 用 list_pets 查回新增记录 ==")
        found = await client.call_tool("list_pets", {"owner_name": "MCP验证主人"})
        fd = _parse(found.content[0])
        print("matched total:", fd.get("total"), "ids:", [p.get("id") for p in fd.get("items", [])])

        print("\n== add_pet 缺必填（应 is_error=true） ==")
        bad = await client.call_tool("add_pet", {"name": "只有名字"})
        print("is_error:", bad.is_error)
        print("text:", _parse(bad.content[0]) if bad.content else "")

        print("\n== add_pet 后端校验失败（非法电话？） ==")
        bad2 = await client.call_tool(
            "add_pet",
            {"owner_name": "X", "owner_phone": "not-a-phone", "disease": "测试", "doctor": "李医生"},
        )
        print("is_error:", bad2.is_error)
        print("text:", _parse(bad2.content[0]) if bad2.content else "")

        print("\nCREATED_ID=", created_id)

    print("== DONE ==")


if __name__ == "__main__":
    asyncio.run(main())