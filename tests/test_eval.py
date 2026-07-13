"""Layer 5 — NL->SQL correctness eval (live agent).

A curated set of questions with known historical answers, run through the real
agent. Non-deterministic (LLM), so each case checks that the expected fact
appears anywhere in the result data or summary — not exact wording — and the
facts are all from completed seasons so they don't drift as the weekly sync
adds new data.
"""

import pytest

# (question, expected token that must appear in the answer, case-insensitive)
EVAL_CASES = [
    ("Who won the 2021 Formula 1 drivers' championship?", "verstappen"),
    ("Who was the 2010 Formula 1 drivers' champion?", "vettel"),
    ("How many Grands Prix did Max Verstappen win in 2023?", "19"),
    ("Which constructor won the 2024 constructors' championship?", "mclaren"),
    ("Who won the 2021 Monaco Grand Prix?", "verstappen"),
    ("How many races were held in the 2022 season?", "22"),
    ("Who took pole position for the 2024 Bahrain Grand Prix?", "verstappen"),
]


def _haystack(result: dict) -> str:
    parts: list[str] = []
    for row in result.get("rows") or []:
        parts.extend(str(cell) for cell in row)
    parts.append(result.get("summary") or "")
    return " ".join(parts).lower()


@pytest.mark.llm
@pytest.mark.parametrize("question, expected", EVAL_CASES)
def test_agent_answers(question, expected):
    from agent.graph import answer

    result = answer(question, thread_id=f"eval-{expected}")
    assert not result.get("failure"), f"agent failed: {result.get('summary')}"
    haystack = _haystack(result)
    assert expected in haystack, (
        f"expected {expected!r} in the answer.\n"
        f"SQL: {result.get('sql')}\nAnswer: {result.get('summary')}"
    )
