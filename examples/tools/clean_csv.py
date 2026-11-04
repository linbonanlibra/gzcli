#!/usr/bin/env python3
"""示例团队脚本工具：CSV 清洗（演示 script 后端的 argv/env 映射）。"""

import argparse
import csv
import json
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="CSV 清洗工具")
    parser.add_argument("--input", required=True, help="输入 CSV 路径")
    parser.add_argument("--strict", action="store_true", help="严格模式：空行直接报错")
    args = parser.parse_args()

    rows = []
    with open(args.input, newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.reader(f), start=1):
            if not any(cell.strip() for cell in row):
                if args.strict:
                    print(f"第 {i} 行为空行（strict 模式）", file=sys.stderr)
                    return 1
                continue
            rows.append([cell.strip() for cell in row])

    print(json.dumps({
        "input": args.input,
        "strict": args.strict,
        "rows": len(rows),
        "team": os.environ.get("DATA_TEAM", "unknown"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
