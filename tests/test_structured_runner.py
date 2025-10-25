import os, json, argparse, datetime
from pathlib import Path

# 작성한 헬퍼/LLM 호출 함수들 import
# - load_json_data: JSON 파일을 파싱해서 파이썬 객체로 로드
# - generate_dynamic_system_prompt: polls + options를 기반으로 시스템 프롬프트(규칙) 동적 생성
# - generate_json_schema_template: polls를 기반으로 LLM이 채울 JSON 스키마 템플릿 생성
# - get_structured_response: user_input을 LLM에 보내서, 스키마에 맞는 JSON 문자열을 받아옴
from workers.llm_extractor import (
    load_json_data,
    generate_dynamic_system_prompt,
    generate_json_schema_template,
    get_structured_response,
)

# 프로젝트 루트(= tests 폴더의 상위)를 기준 경로로 사용
ROOT = Path(__file__).resolve().parents[1]  # repo 루트 추정

def build_option_map(options: list[dict]) -> dict[int, list[str]]:
    """
    poll_options.json -> { poll_id: [option_text, ...] } 형태의 맵 생성.
    - 나중에 LLM이 만들어준 값이 실제 표준 옵션 목록 중 하나인지 간단 검증할 때 사용.
    """
    m: dict[int, list[str]] = {}
    for opt in options:
        m.setdefault(opt["poll_id"], []).append(opt["option_text"])
    return m

def main():
    # 커맨드라인 인자 정의
    parser = argparse.ArgumentParser()
    parser.add_argument("--polls", default=str(ROOT / "core/json/polls.json"))
    parser.add_argument("--options", default=str(ROOT / "core/json/poll_options.json"))
    parser.add_argument("--answers", default=str(ROOT / "core/json/user_profile_answers.json"))
    parser.add_argument("--limit", type=int, default=5, help="처리할 응답 개수 제한")
    parser.add_argument("--out", default=str(ROOT / "tests/analysis_results.json"))
    parser.add_argument("--dry", action="store_true", help="LLM 호출 없이 스키마만 출력하고 종료")
    args = parser.parse_args()
    
    # 1) 입력 JSON 로드 (온톨로지/질문/사용자 자유서술 답변)
    polls = load_json_data(args.polls)
    options = load_json_data(args.options)
    answers = load_json_data(args.answers)

    # 필수 자원 체크
    if not polls or not options:
        print("polls.json 또는 poll_options.json을 불러오지 못했습니다.")
        return
    if not answers:
        print("user_profile_answers.json을 불러오지 못했습니다.")
        return

    # 2) 한 번만 만들면 되는 고정 리소스
    # - 동적 시스템 프롬프트: 표준화 강제 규칙(옵션 강제 등)을 포함
    # - JSON 스키마 템플릿: LLM이 반드시 채워야 할 키 구조(analysis.*) 제공
    system_prompt = generate_dynamic_system_prompt(polls, options)
    json_schema_template = generate_json_schema_template(polls)
    option_map = build_option_map(options)  # 검증용

    # dry-run 모드: 프롬프트/스키마만 눈으로 확인하고 종료 (LLM 호출 X)
    if args.dry:
        print("---- [DRY RUN] 동적 시스템 프롬프트 ----")
        print(system_prompt)
        print("---- [DRY RUN] JSON 스키마 템플릿 ----")
        print(json_schema_template)
        return

    # 3) 배치 처리 시작
    # - answers에서 최대 limit개까지 순차 처리
    results = []
    now = datetime.datetime.now().isoformat()
    total = min(len(answers), args.limit)
    print(f" - 총 {total}개 응답 테스트 시작")

    for i, ans in enumerate(answers[:total], start=1):
        # 자유서술 텍스트와 식별자
        text = ans.get("answer_value") # 사용자가 실제로 쓴 자유 텍스트
        rid = str(ans.get("answer_id") or f"ANS_{i:03d}") # 요청/레코드 식별자

        # 비어있는 응답은 스킵
        if not isinstance(text, str) or not text.strip():
            print(f"  - ({i}/{total}) 스킵: answer_value 비어있음 (id={rid})")
            continue

        # 3-1) LLM 호출: system_prompt + json_schema_template를 함께 전달
        #      LLM은 반드시 '순수 JSON' 문자열을 반환하도록 프롬프트에서 강제됨
        print(f"\n[{i}/{total}] id={rid}  text='{text[:50]}...'")
        raw = get_structured_response(
            user_input_text=text,
            request_id=rid,
            system_prompt=system_prompt,
            json_schema_template=json_schema_template
        )

        # 3-2) LLM이 가끔 ```json ... ```로 감싸는 경우가 있어 제거 후 파싱 시도
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()

        # 3-3) JSON 파싱
        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError as e:
            print("JSON 파싱 실패:", e)
            print("└ raw:", raw[:200], "...") # 디버깅을 위해 앞부분만 출력
            continue

        # 3-4) 최소 스키마 검증: analysis 키 존재 여부 확인
        ok = True
        if "analysis" not in obj or not isinstance(obj["analysis"], dict):
            print("'analysis' 키 없음")
            ok = False

        # 3-5) 표준 옵션 일치 검증(샘플): LLM이 analysis 에 넣은 값이 실제 옵션 중 하나인지 경고
        #     - 강제 실패로 하고 싶으면 경고 대신 continue/raise로 바꿔도 됨
        sample_checks = {
            1: "preferred_consumption", # poll_id 1
            2: "stress_factor", # poll_id 2 
            3: "stress_relief_method", # poll_id 3
        }
        if ok:
            for poll_id, key in sample_checks.items():
                if key in obj["analysis"]:
                    val = obj["analysis"].get(key)
                    allowed = option_map.get(poll_id, [])
                    if isinstance(val, str) and allowed and val not in allowed:
                        print(f"'{key}' 값이 표준 옵션에 없음: '{val}'  (허용={allowed[:5]}...)")

        # 3-6) 메타 기본값 채우기(누락 시)
        obj.setdefault("request_id", rid)
        obj.setdefault("process_datetime", now)

        # 3-7) 결과 누적
        results.append(obj)
        print("OK")

    # 4) 결과 저장: 테스트 결과를 하나의 JSON 파일로 아웃풋
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n 완료: {len(results)}개 저장 → {out_path}")

if __name__ == "__main__":
    main()