import pandas as pd
import streamlit as st

import coach
import llm
from prompts import EVAL_SCHEMA, INTERVIEWER_SCHEMA, RETRY_SCHEMA, REVERSE_SCHEMA

st.set_page_config(page_title="AI 면접 코치", page_icon="🎤")

state = st.session_state
state.setdefault("started", False)
state.setdefault("done", False)
state.setdefault("understanding", None)
state.setdefault("evaluation", None)
state.setdefault("retries", {})
state.setdefault("reverse", None)


def restart():
    state.clear()


def start_interview(name, job, company, experience):
    df = coach.load_questions()
    state.name, state.job = name, job
    state.company, state.experience = company, experience
    state.questions = coach.pick_questions(df, job)
    state.idx = 0
    state.follow_ups_used = 0
    state.turns = []
    state.messages = [
        {
            "role": "assistant",
            "content": f"안녕하세요, {name}님. 면접을 시작할게요.\n\n{state.questions[0]['질문']}",
        }
    ]
    state.started = True


def show_start_screen():
    st.title("🎤 AI 면접 코치")
    st.caption("직군과 경험을 적고 모의면접을 시작해 보세요.")
    jobs = coach.job_list(coach.load_questions())
    with st.form("start"):
        name = st.text_input("이름")
        job = st.selectbox("지원 직군", jobs)
        company = st.text_input("지원 회사")
        experience = st.text_area(
            f"내 경험 ({coach.MIN_EXPERIENCE_CHARS}자 이상)", height=150
        )
        submitted = st.form_submit_button("면접 시작")
    if not submitted:
        return
    name, company, experience = name.strip(), company.strip(), experience.strip()
    if not (name and company):
        st.warning("이름과 지원 회사를 입력해 주세요.")
    elif len(experience) < coach.MIN_EXPERIENCE_CHARS:
        st.warning(
            f"내 경험을 {coach.MIN_EXPERIENCE_CHARS}자 이상 적어 주세요. (지금 {len(experience)}자)"
        )
    else:
        start_interview(name, job, company, experience)
        st.rerun()


def show_status():
    with st.sidebar:
        st.header("상태창")
        n = min(state.idx + 1, coach.TOTAL_QUESTIONS)
        st.progress(n / coach.TOTAL_QUESTIONS, text=f"질문 {n}/{coach.TOTAL_QUESTIONS}")
        shown = "-" if state.understanding is None else f"{state.understanding}/{coach.UNDERSTANDING_MAX}"
        st.metric("면접관이 본 이해도", shown)
        st.button("처음부터 다시", on_click=restart)


def handle_answer(answer):
    question = state.questions[state.idx]
    turns = state.turns + [("지원자", answer)]
    can_follow_up = state.follow_ups_used < coach.MAX_FOLLOW_UPS
    try:
        with st.spinner("면접관이 생각하고 있어요..."):
            result = llm.ask_json(
                coach.build_instructions(state.job, state.company, state.experience),
                coach.build_user_input(question, turns, can_follow_up),
                INTERVIEWER_SCHEMA,
                "interviewer",
            )
    except llm.LLMError as e:
        st.error(str(e))
        return

    state.messages.append({"role": "user", "content": answer})
    state.understanding = coach.clamp_understanding(result["understanding"])

    if coach.allow_follow_up(result["follow_up"], state.follow_ups_used):
        state.follow_ups_used += 1
        state.turns = turns + [("면접관", result["reply"])]
        state.messages.append({"role": "assistant", "content": result["reply"]})
    else:
        # AI가 꼬리 질문을 더 하자고 해도 코드가 막는다. 그 경우 reply 는 질문이라 버린다.
        comment = "" if result["follow_up"] else result["reply"]
        if state.idx == coach.TOTAL_QUESTIONS - 1:
            state.done = True
            text = "면접이 끝났어요. 수고하셨어요!"
        else:
            state.idx += 1
            state.follow_ups_used = 0
            state.turns = []
            text = state.questions[state.idx]["질문"]
        if comment:
            text = f"{comment}\n\n{text}"
        state.messages.append({"role": "assistant", "content": text})
    st.rerun()


def run_evaluation():
    try:
        with st.spinner("위원 4명이 면접 기록을 보고 있어요..."):
            state.evaluation = llm.ask_json(
                coach.build_eval_instructions(state.job, state.company, state.experience),
                coach.build_transcript(state.messages),
                EVAL_SCHEMA,
                "evaluation",
            )
    except llm.LLMError as e:
        st.error(str(e))
        return
    st.rerun()


def show_answer(answer):
    total = coach.answer_total(answer)
    scores = coach.answer_scores(answer)
    with st.expander(f"답변 {answer['no']} · {total}/{coach.ANSWER_MAX}점"):
        st.write(
            f"구체성 {scores['specific']} · 직무 연관 {scores['relevance']} · "
            f"구조 {scores['structure']} · 근거·검증 {scores['evidence']}"
        )
        st.write(f"가장 약한 점: {answer['weak']}")
        if coach.needs_rewrite(answer):
            st.markdown("**고친 답**")
            st.write(answer["rewrite"])
            if answer["check"]:
                st.markdown("**사람이 확인할 것**")
                for item in answer["check"]:
                    st.write(f"- {item}")


def show_evaluation():
    result = state.evaluation
    if result is None:
        st.write("면접이 끝났어요. 위원 4명의 평가를 받아 보세요.")
        if st.button("위원 4명에게 평가받기"):
            run_evaluation()
        return
    st.metric(
        f"위원 평균 (0~{coach.PANEL_MAX})", f"{coach.panel_average(result['panel']):.1f}"
    )
    scores = coach.panel_scores(result["panel"])
    st.dataframe(
        pd.DataFrame(
            {
                "위원": [p["role"] for p in result["panel"]],
                "뽑지 말아야 할 이유": [p["against"] for p in result["panel"]],
                "좋은 점": [p["good"] for p in result["panel"]],
                "점수": scores,
            }
        ),
        hide_index=True,
        width="stretch",
    )
    st.markdown(f"**판단이 갈린 곳**: {result['conflict']}")
    st.markdown(f"**모두 같은 판단**: {result['agree']}")
    st.subheader("답변별 점수")
    for answer in result["answers"]:
        show_answer(answer)
    st.subheader("다음 연습에서 고칠 것")
    for item in result["next"]:
        st.write(f"- {item}")


def run_retry(item, new_answer):
    try:
        with st.spinner("다시 채점하고 있어요..."):
            state.retries[item["no"]] = llm.ask_json(
                coach.build_retry_instructions(state.job, state.company, state.experience),
                coach.build_retry_input(item["question"], new_answer),
                RETRY_SCHEMA,
                "retry",
            )
    except llm.LLMError as e:
        st.error(str(e))
        return
    st.rerun()


def show_retry():
    if state.evaluation is None:
        st.write("먼저 📊 평가 탭에서 평가를 받아 주세요.")
        return
    items = {i["no"]: i for i in coach.answer_items(state.messages)}
    answers = [a for a in coach.sort_by_score(state.evaluation["answers"]) if a["no"] in items]
    if not answers:
        st.write("다시 답할 답변이 없어요.")
        return
    by_no = {a["no"]: a for a in answers}
    no = st.selectbox(
        "다시 답할 질문 (점수 낮은 순)",
        [a["no"] for a in answers],
        format_func=lambda n: f"답변 {n} · {coach.answer_total(by_no[n])}/{coach.ANSWER_MAX}점",
    )
    item, before = items[no], by_no[no]
    st.markdown("**질문**")
    st.write(item["question"])
    st.markdown("**지난 답**")
    st.write(item["answer"])
    st.write(f"지난 점수: {coach.answer_total(before)}/{coach.ANSWER_MAX}점")
    st.write(f"약한 점: {before['weak']}")
    new_answer = st.text_area("다시 답하기", key=f"retry_{no}", height=150)
    if st.button("다시 채점", key=f"retry_btn_{no}"):
        if new_answer.strip():
            run_retry(item, new_answer.strip())
        else:
            st.warning("다시 답한 내용을 입력해 주세요.")
    after = state.retries.get(no)
    if after:
        result = coach.compare(before, after)
        st.metric("후 점수", f"{result['after']}/{coach.ANSWER_MAX}", delta=result["diff"])
        st.dataframe(pd.DataFrame(result["rows"]), hide_index=True, width="stretch")
        st.write(f"남은 약한 점: {after['weak']}")


def show_reverse():
    st.write("면접 마지막에 면접관에게 할 질문을 적으면 더 좋은 질문으로 고쳐 줘요.")
    original = st.text_area("내가 하려던 역질문", height=100)
    if st.button("역질문 고치기"):
        if not original.strip():
            st.warning("역질문을 입력해 주세요.")
        else:
            try:
                with st.spinner("질문을 고치고 있어요..."):
                    state.reverse = llm.ask_json(
                        coach.build_reverse_instructions(state.job, state.company, state.experience),
                        f"[지원자의 원래 질문] {original.strip()}",
                        REVERSE_SCHEMA,
                        "reverse",
                    )
            except llm.LLMError as e:
                st.error(str(e))
    if state.reverse:
        st.markdown("**고친 질문**")
        for q in state.reverse["questions"][: coach.REVERSE_COUNT]:
            st.write(f"- {q}")
        st.write(f"빠진 것: {state.reverse['why']}")


def show_interview():
    for message in state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
    if not state.done:
        answer = st.chat_input("답변을 입력하세요")
        if answer and answer.strip():
            with st.chat_message("user"):
                st.write(answer)
            handle_answer(answer.strip())


if not state.started:
    show_start_screen()
else:
    show_status()
    st.title("🎤 AI 면접 코치")
    if state.done:
        interview_tab, eval_tab, retry_tab, reverse_tab = st.tabs(["💬 면접", "📊 평가", "🔁 재도전", "🙋 역질문"])
        with interview_tab:
            show_interview()
        with eval_tab:
            show_evaluation()
        with retry_tab:
            show_retry()
        with reverse_tab:
            show_reverse()
    else:
        show_interview()
