"""Classify a support message with one batched TypeSafe Jev request."""

from __future__ import annotations

from pathlib import Path

from nier import JevQuestion, connect

CONFIG = Path("config/nier.yaml")
MESSAGE = "支付失败两次，客户要求尽快解决。"


def main() -> int:
    with connect(CONFIG) as phone:
        response = phone.jev().system_one(
            state=MESSAGE,
            questions={
                "route": JevQuestion.choice(
                    "应该由哪个团队处理？",
                    criteria={
                        "billing": "支付、账单或扣款问题",
                        "technical": "应用故障或技术问题",
                        "general": "其他一般咨询",
                    },
                ),
                "urgent": JevQuestion.noul("这条消息是否表达了紧急处理需求？"),
                "severity": JevQuestion.score(
                    "客户情绪和问题严重程度如何？",
                    ["低", "中", "高"],
                ),
            },
        )
    print(f"Route: {response.answer('route').choice}")
    print(f"Urgency score: {response.answer('urgent').noul}")
    print(f"Severity score: {response.answer('severity').score}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
