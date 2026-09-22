"""LLM・Graph・HTTP API の間で受け渡すデータの形式を定義する。

Pydantic の BaseModel により、必要な項目と許可する値を明示する。
Diagnosis は LLM の構造化出力にも使われるため、クラスや Field の説明は
開発者向けの文書だけでなく、LLM に提示する JSON Schema の説明にもなる。
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class Diagnosis(BaseModel):
    """調査で集めた観測結果を、後続処理が扱える形式にまとめた診断結果。

    root_cause は具体的な推定原因、evidence はそれを裏付ける観測事実の一覧。
    recommended_action は提案する最小限の復旧操作で、起動・再起動・DB 接続の切断・
    手動対応・操作不要のいずれかを選ぶ。target_service に対象サービスを指定し、
    DB 接続を切断する場合は target_application に観測した application_name を入れる。
    それ以外の操作では target_application を 'none' にする。

    action_reason は操作を提案する理由、confidence は推定の確信度を表す。
    このモデルは形式を検証するもので、原因の正しさや実行の承認を保証するものではない。
    """

    root_cause: str = Field(description="最も可能性が高い根本原因を日本語で具体的に記述する。")
    evidence: list[str] = Field(
        min_length=1,
        description="根本原因の判断を裏付ける、観測された事実を各項目に日本語で記述する。",
    )
    recommended_action: Literal[
        "start_container",
        "restart_container",
        "terminate_postgres_connections",
        # TODO E5: DB disk-full 用の復旧 action を追加する
        "manual",
        "none",
    ] = Field(description="この Agent が実行できる、安全かつ最小限の復旧操作。")
    target_service: Literal["httpd", "tomcat", "postgres", "none"]
    target_application: str = Field(
        default="none",
        description=(
            "recommended_action が terminate_postgres_connections の場合は、"
            "切断対象の PostgreSQL の application_name を指定する。それ以外は 'none' にする。"
        ),
    )
    action_reason: str = Field(description="この操作が適切で、提案できる程度に安全だと判断した理由を日本語で記述する。")
    confidence: Literal["low", "medium", "high"]


class ApprovalRequest(BaseModel):
    """復旧操作の前に、人間へ提示する承認依頼のデータ。

    action と対象、推定原因、観測根拠、操作を提案する理由をひとまとめにする。
    Graph の approval ノードが Diagnosis から作成し、model_dump() で辞書にして
    interrupt() に渡す。研修画面はこの情報を使って承認・却下の判断材料を表示する。
    このオブジェクトを作っただけでは、承認や復旧操作は実行されない。
    """

    action: str
    target_service: str
    target_application: str = "none"
    root_cause: str
    evidence: list[str]
    reason: str


class ApprovalBody(BaseModel):
    """研修画面が承認・却下の判断を送信する HTTP リクエスト本文。

    approved=True は承認、False は却下を表す。POST /api/approval が受け取り、
    AgentRuntime.approve() を通して停止中の Graph に判断を渡す。
    対象の障害 ID は本文には含めず、実行管理側が保持する承認待ちの障害を対象にする。
    """

    approved: bool
