from __future__ import annotations
import os, json, uuid, datetime
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parents[1]
DOTENV_PATH = BASE_DIR / ".env"
# ---- deps --------------------------------------------------------------------
try:
    import anthropic
except ImportError as e:
    raise SystemExit("pip install anthropic python-dotenv 후 다시 실행하세요") from e

try:
    from dotenv import load_dotenv, dotenv_values, find_dotenv
except ImportError:
    raise SystemExit("pip install python-dotenv 필요합니다.")

# usecwd=True로 현재 작업경로 기준 탐색 + 우리가 지정한 경로 우선
load_dotenv(dotenv_path=str(DOTENV_PATH), override=False)
print("[dotenv] used path:", DOTENV_PATH, "| exists:", DOTENV_PATH.exists())
print("[dotenv] has ANTHROPIC_API_KEY:", "ANTHROPIC_API_KEY" in dotenv_values(str(DOTENV_PATH)))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise SystemExit("환경변수 ANTHROPIC_API_KEY가 없습니다 (.env에 설정하세요).")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ---- 경로 설정 (tests/ 폴더 기준으로 프로젝트 루트 탐색) -------------------------
THIS = Path(__file__).resolve()
ROOT = THIS.parents[1]           # 프로젝트 루트 추정 (…/PMI)
JSON_DIR = ROOT / "core" / "json"

POLLS_FILE = JSON_DIR / "polls.json"
OPTIONS_FILE = JSON_DIR / "poll_options.json"
ANSWERS_FILE = JSON_DIR / "user_profile_answers.json"   # 파일명 다르면 여기만 바꿔도 됨.

OUT_DIR = ROOT / "tests"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / "analysis_results.json"

# ---- 파일 로더 ----------------------------------------------------------------
def load_json(p: Path):
    if not p.exists():
        raise FileNotFoundError(f"JSON 파일을 찾을 수 없습니다: {p}")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

# ---- 동적 프롬프트/스키마 ------------------------------------------------------
def get_poll_key_and_title(poll: dict) -> tuple[str, str]:
    key_map = {
        1: "preferred_consumption",
        2: "stress_factor",
        3: "stress_relief_method",
        4: "skin_satisfaction",
        5: "skincare_budget",
        6: "skincare_priority",
        7: "recent_expense_area",
    }
    pid = poll["poll_id"]
    title = poll["poll_title"]
    return key_map.get(pid, f"poll_{pid}_answer"), title

def generate_dynamic_system_prompt(polls: list, options: list) -> str:
    base = [
        "당신은 '나를 위한 소비' 성향과 스트레스 관리의 연관성을 분석하는 전문적인 인공지능 데이터 구조화 시스템입니다.",
        "\n규칙:",
        "1.  **[가장 중요] 순수 JSON 객체 출력:** 최종 응답은 마크다운 코드블록 없이 `{...}` 형태의 순수 JSON만 출력.",
        "2.  **역할 및 분석:** user_query를 분석하여 심리상태와 소비의도를 구조화.",
        "3.  **필수값 채우기:** 추출 불가 시 STRING은 \"\", INTEGER는 0, BOOLEAN은 false.",
    ]
    dyn = []
    rule_no = 4
    for p in polls:
        pid = p["poll_id"]
        key, _ = get_poll_key_and_title(p)
        opts = [o["option_text"] for o in options if o["poll_id"] == pid]
        if opts:
            options_string = '", "'.join(opts)
            dyn.append(
                f'{rule_no}.  **표준화 강제 (analysis.{key}):** 다음 항목 중 정확히 하나만 사용: "{options_string}"'
            )
            rule_no += 1
    dyn.append(f"{rule_no}.  **메타데이터 처리:** 'model_name'은 \"claude-sonnet-4-20250514\", 'prompt_version'은 \"V1.0-dynamic\".")
    return "\n".join(base + dyn)

def generate_json_schema_template(polls: list) -> str:
    schema = {
        "request_id": "{unique_request_id}",
        "process_datetime": "{current_datetime}",
        "model_name": "claude-sonnet-4-20250514",
        "prompt_version": "V1.0-dynamic",
        "original_query": "{user_input_text}",
        "analysis": {}
    }
    for p in polls:
        key, title = get_poll_key_and_title(p)
        schema["analysis"][key] = f"STRING (분석 결과: {title})"
    return json.dumps(schema, ensure_ascii=False, indent=2)

# ---- LLM 호출 -----------------------------------------------------------------
def call_llm(user_input_text: str, request_id: str, system_prompt: str, json_schema_template: str) -> str:
    now = datetime.datetime.now().isoformat()
    filled = (json_schema_template
              .replace("{unique_request_id}", request_id)
              .replace("{current_datetime}", now)
              .replace("{user_input_text}", json.dumps(user_input_text)[1:-1]))  # 안전 삽입

    user_prompt = f"""
[입력 데이터]
사용자 질문 (USER_QUERY): "{user_input_text}"

[요청]
위 '사용자 질문'을 분석하고, 아래의 JSON 스키마 템플릿에 맞추어 모든 필드를 채운 최종 JSON 객체만을 출력하십시오.

[JSON 스키마 출력 템플릿]
{filled}
""".strip()

    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    return resp.content[0].text

# ---- 간단한 복구: 응답에서 가장 바깥 {}만 추출해 파싱 시도 -----------------------
def strict_json_loads(s: str):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # 모델이 앞뒤에 설명을 붙였을 경우, 가장 바깥 { ... }만 추출
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(s[start:end+1])
        raise

# ---- 메인 ---------------------------------------------------------------------
def main(limit: int | None = 3):
    # 1) 자료 로딩
    polls = load_json(POLLS_FILE)
    options = load_json(OPTIONS_FILE)
    answers = load_json(ANSWERS_FILE)

    if not isinstance(polls, list) or not isinstance(options, list):
        raise SystemExit("polls.json / poll_options.json 형식이 리스트여야 합니다.")
    if not isinstance(answers, list):
        raise SystemExit("user_profile_answers.json 형식이 리스트여야 합니다.")

    print(f"[로드 완료] polls={len(polls)}, options={len(options)}, answers={len(answers)}")

    # 2) 동적 시스템 프롬프트/스키마 1회 생성
    system_prompt = generate_dynamic_system_prompt(polls, options)
    schema_template = generate_json_schema_template(polls)

    results = []
    total = len(answers) if limit is None else min(limit, len(answers))
    print(f"\n총 {total}개 응답을 처리합니다.")

    for idx, item in enumerate(answers[:total], start=1):
        # 프로젝트 파일 스키마에 맞춰 필드명 사용
        user_text = item.get("answer_value") or item.get("text") or item.get("value")
        answer_id = item.get("answer_id") or item.get("id") or f"ANS_{idx:03d}"

        if not isinstance(user_text, str) or not user_text.strip():
            print(f"- ({idx}/{total}) 스킵 (ID={answer_id}): answer_value 비어있음")
            continue

        print(f"- ({idx}/{total}) 호출 (ID={answer_id}) | 질의요약: {user_text[:40]}...")

        raw = call_llm(
            user_input_text=user_text,
            request_id=str(answer_id),
            system_prompt=system_prompt,
            json_schema_template=schema_template,
        )

        # RAW 출력(디버그용)
        print("  RAW 길이:", len(raw))

        # 파싱
        try:
            parsed = strict_json_loads(raw)
        except Exception as e:
            print(f"  !!! JSON 파싱 실패 (ID={answer_id}): {e}")
            continue

        # 최소 검증
        if "analysis" not in parsed:
            print(f"  !!! 검증 오류 (ID={answer_id}): 'analysis' 키 없음")
            continue

        # 샘플 키 출력
        a = parsed["analysis"]
        print("  -> preferred_consumption:", a.get("preferred_consumption"))
        print("  -> stress_factor        :", a.get("stress_factor"))
        print("  -> stress_relief_method :", a.get("stress_relief_method"))
        print("  -> skincare_budget      :", a.get("skincare_budget"))

        results.append(parsed)

    # 3) 결과 저장
    with OUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[완료] {len(results)}/{total}건 저장 → {OUT_FILE}")

if __name__ == "__main__":
    # limit=None 으로 주면 answers 전량 처리
    main(limit=5)