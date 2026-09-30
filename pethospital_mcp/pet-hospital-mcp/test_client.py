"""临时验证脚本：用 SDK 自带 Client 走 HTTP 验证 list_pets（MVP 验收用）。"""

import asyncio
import json
import sys

from mcp import Client

URL_DEFAULT = "http://127.0.0.1:18080/mcp"

CASES = [
    ("空参（第一页默认 pageSize=20）", {}),
    ("species=犬", {"species": "犬"}),
    ("owner_name + sortBy=totalCost&order=desc", {"owner_name": "张", "sort_by": "totalCost", "order": "desc"}),
    ("q 全文检索", {"q": "肠胃炎"}),
    ("page_size=5&page=2", {"page_size": 5, "page": 2}),
    ("min_cost/max_cost", {"min_cost": 1000, "max_cost": 5000}),
    ("status + breed", {"status": "已康复", "breed": "金毛"}),
]


def _summary(parsed: object) -> str:
    if isinstance(parsed, dict) and "items" in parsed:
        return (
            f"items={len(parsed['items'])} total={parsed.get('total')} "
            f"page={parsed.get('page')} pageSize={parsed.get('pageSize')} "
            f"totalPages={parsed.get('totalPages')} totalCost={parsed.get('totalCost')}"
        )
    return str(parsed)[:200]


async def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else URL_DEFAULT
    async with Client(url) as client:
        print("== server_info ==")
        print(client.server_info)

        print("\n== list_tools ==")
        tools = await client.list_tools()
        for t in tools.tools:
            print(f"tool: {t.name}")
            print("  schema:", json.dumps(t.input_schema, ensure_ascii=False))

        for label, args in CASES:
            print(f"\n== call_tool list_pets | {label} ==")
            try:
                result = await client.call_tool("list_pets", args)
            except Exception as exc:
                print("EXC:", type(exc).__name__, exc)
                continue
            print("resultType:", result.result_type, "| is_error:", result.is_error)
            for block in result.content:
                if block.type == "text":
                    try:
                        parsed = json.loads(block.text)
                        print("summary:", _summary(parsed))
                    except Exception:
                        print("text:", block.text[:300])
                else:
                    print("block:", block.type)

    print("\n== DONE ==")


if __name__ == "__main__":
    asyncio.run(main())