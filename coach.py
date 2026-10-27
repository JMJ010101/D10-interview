import random

import pandas as pd

from prompts import CONTEXT, EVALUATOR, INTERVIEWER, PERSONAS, RETRY, REVERSE

TOTAL_QUESTIONS = 5
MAX_FOLLOW_UPS = 1
MIN_EXPERIENCE_CHARS = 30
UNDERSTANDING_MAX = 5
PANEL_MAX = 10
CRITERIA = ["specific", "relevance", "structure", "evidence"]
CRITERIA_LABELS = {
    "specific": "구체성",
    "relevance": "직무 연관",
    "structure": "구조",
    "evidence": "근거·검증",
}
CRITERION_MAX = 5
ANSWER_MAX = CRITERION_MAX * len(CRITERIA)
REWRITE_BELOW = 14
REVERSE_COUNT = 3

COMMON_JOB = "공통"
INTRO_KEYWORD = "자기소개"
TYPE_ORDER = ["직무", "경험", "상황"]


def load_questions(path="data/questions.csv"):
    return pd.read_csv(path, encoding="utf-8-sig")


def job_list(df):
    return [job for job in df["직군"].unique() if job != COMMON_JOB]


def _row(df_part):
    return df_part.sample(1).iloc[0].to_dict()


def pick_questions(df, job):
    """자기소개 1 + 공통 1 + 직무 1 + 경험 1 + 상황 1, 순서 고정."""
    common = df[df["직군"] == COMMON_JOB]
    is_intro = common["질문"].str.contains(INTRO_KEYWORD)
    picked = [_row(common[is_intro]), _row(common[~is_intro])]
    mine = df[df["직군"] == job]
    for kind in TYPE_ORDER:
        picked.append(_row(mine[mine["유형"] == kind]))
    return picked[:TOTAL_QUESTIONS]


def allow_follow_up(ai_wants, used):
    return bool(ai_wants) and used < MAX_FOLLOW_UPS


def clamp_understanding(value):
    return max(0, min(UNDERSTANDING_MAX, int(value)))


def build_context(job, company, experience):
    # 프롬프트 문장에 {칸} 같은 글자가 있어 str.format 대신 replace 를 쓴다.
    # 지원자가 쓴 experience 는 마지막에 넣어, 그 안의 {…} 가 다시 치환되지 않게 한다.
    return (
        CONTEXT.replace("{company}", company)
        .replace("{job}", job)
        .replace("{experience}", experience)
    )


def build_instructions(job, company, experience):
    context = build_context(job, company, experience)
    persona = PERSONAS.get(job) or next(iter(PERSONAS.values()))
    return INTERVIEWER.replace("{persona}", persona).replace("{context}", context)


def build_eval_instructions(job, company, experience):
    return EVALUATOR.replace("{context}", build_context(job, company, experience))


def build_transcript(messages):
    """면접 기록. 지원자 답변마다 [답변 n] 번호를 붙인다."""
    lines, n = [], 0
    for m in messages:
        if m["role"] == "user":
            n += 1
            lines.append(f"[답변 {n}] 지원자: {m['content']}")
        else:
            lines.append(f"면접관: {m['content']}")
    return "\n".join(lines)


def clamp_score(value, high):
    return max(0, min(high, int(value)))


def panel_scores(panel):
    return [clamp_score(p["score"], PANEL_MAX) for p in panel]


def panel_average(panel):
    scores = panel_scores(panel)
    return sum(scores) / len(scores) if scores else 0.0


def answer_scores(answer):
    return {k: clamp_score(answer[k], CRITERION_MAX) for k in CRITERIA}


def answer_total(answer):
    return sum(answer_scores(answer).values())


def needs_rewrite(answer):
    return answer_total(answer) < REWRITE_BELOW


def build_user_input(question, turns, can_follow_up):
    lines = [
        f"[현재 질문] {question['질문']}",
        f"[보는 점] {question['보는 점']}",
        f"[꼬리 질문 가능] {'예' if can_follow_up else '아니오'}",
        "[이 질문의 대화]",
    ]
    lines += [f"{who}: {text}" for who, text in turns]
    return "\n".join(lines)


def build_retry_instructions(job, company, experience):
    return RETRY.replace("{context}", build_context(job, company, experience))


def build_reverse_instructions(job, company, experience):
    return REVERSE.replace("{context}", build_context(job, company, experience))


def answer_items(messages):
    """지원자 답변마다 번호(no), 바로 앞 면접관 말(question), 답(answer)."""
    items, last_question = [], ""
    for m in messages:
        if m["role"] == "assistant":
            last_question = m["content"]
        else:
            items.append(
                {"no": len(items) + 1, "question": last_question, "answer": m["content"]}
            )
    return items


def sort_by_score(answers):
    """점수 낮은 답변부터."""
    return sorted(answers, key=answer_total)


def build_retry_input(question, answer):
    return f"[질문] {question}\n[지원자의 답] {answer}"


def compare(before, after):
    """전 → 후 점수. before/after 는 기준 4개 점수가 든 dict."""
    b, a = answer_scores(before), answer_scores(after)
    return {
        "before": sum(b.values()),
        "after": sum(a.values()),
        "diff": sum(a.values()) - sum(b.values()),
        "rows": [
            {"기준": CRITERIA_LABELS[k], "전": b[k], "후": a[k], "차이": a[k] - b[k]}
            for k in CRITERIA
        ],
    }
