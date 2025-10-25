import os
import json
import anthropic
import datetime
from dotenv import load_dotenv

# .env 파일에서 환경 변수를 불러옵니다.
load_dotenv()

try:
    # (추가) import 시점에 환경 변수 값 확인
    api_key = os.getenv("ANTHROPIC_API_KEY")
    print(f"DEBUG (llm_extractor): ANTHROPIC_API_KEY at import time: '{api_key}'") # <<< 디버깅 추가

    if not api_key:
        print("경고 (llm_extractor): ANTHROPIC_API_KEY 환경 변수가 설정되지 않았습니다.")
        client = None
    else:
        # 실제 클라이언트 생성 시 사용되는 키 값 확인
        print(f"DEBUG (llm_extractor): Initializing Anthropic client with key ending in '...{api_key[-4:]}'") # <<< 디버깅 추가 (키 끝 4자리만)
        client = anthropic.Anthropic(api_key=api_key)
except Exception as e:
    print(f"Anthropic 클라이언트 초기화 실패: {e}")
    client = None

# =========================================================================
# 1. (NEW) JSON 파일 로드 헬퍼
# =========================================================================
def load_json_data(file_path: str) -> list | dict | None:
    """JSON 파일을 읽어 파이썬 객체(리스트 또는 딕셔너리)로 반환합니다."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"오류: JSON 파일을 찾을 수 없습니다 - {file_path}")
        return None
    except json.JSONDecodeError:
        print(f"오류: JSON 파싱 실패 - {file_path}")
        return None

# =========================================================================
# 2. (NEW) 동적 스키마/프롬프트 생성을 위한 헬퍼
# =========================================================================
def get_poll_key_and_title(poll: dict) -> tuple[str, str]:
    """
    poll_title을 기반으로 최종 JSON의 Key와 설명을 생성합니다.
    (중요: 이 key_map은 DB팀과 논의하여 확정해야 합니다.)
    """
    poll_id = poll["poll_id"]
    title = poll["poll_title"]
    
    # poll_id를 기반으로 JSON Key를 매핑합니다.
    key_map = {
        1: "preferred_consumption",
        2: "stress_factor",
        3: "stress_relief_method",
        4: "skin_satisfaction",
        5: "skincare_budget",
        6: "skincare_priority",
        7: "recent_expense_area"
    }
    # 매핑에 없으면 poll_id 기반의 기본 키를 사용합니다.
    key = key_map.get(poll_id, f"poll_{poll_id}_answer")
    return key, title

# =========================================================================
# 3. (NEW) poll.json / poll_options.json 기반 동적 생성 함수
# =========================================================================
def generate_dynamic_system_prompt(polls: list, options: list) -> str:
    """polls와 options을 기반으로 System Prompt의 규칙을 동적으로 생성합니다."""
    
    # 기본 규칙 (JSON 출력, 필수값 채우기 등)
    base_prompt_rules = [
        "당신은 '나를 위한 소비' 성향과 스트레스 관리의 연관성을 분석하는 전문적인 인공지능 데이터 구조화 시스템입니다.",
        "\n규칙:",
        "1.  **[가장 중요] 순수 JSON 객체 출력:** 당신의 최종 응답은 **마크다운 코드 블록(예: ```json)을 포함하지 않은** 순수한 JSON 객체(`{...}`)여야 합니다. 다른 설명, 주석, 마크다운 문법을 절대 추가하지 마십시오.",
        "2.  **역할 및 분석:** 사용자의 자연어 질문('user_query')을 분석하여 심리 상태와 소비 의도를 구조화하십시오.",
        "3.  **필수값 채우기:** 모든 필드를 최대한 채우십시오. 추출 불가능 시 STRING은 \"\", INTEGER는 0, BOOLEAN은 false를 사용하십시오."
    ]
    
    # 동적 규칙 (표준화 강제) 생성
    dynamic_rules = []
    rule_number = 4 # 기본 규칙 3개 다음부터 시작
    
    for poll in polls:
        poll_id = poll["poll_id"]
        poll_key, _ = get_poll_key_and_title(poll)
        
        # 이 poll_id에 해당하는 옵션들을 찾습니다.
        poll_options = [opt["option_text"] for opt in options if opt["poll_id"] == poll_id]
        
        if poll_options:
            # 옵션 목록을 문자열로 만듭니다. (e.g., "맛있는 음식 먹기", "여행 가기", ...)
            options_string = '", "'.join(poll_options)
            # 규칙을 추가합니다.
            rule = f"{rule_number}.  **표준화 강제 (analysis.{poll_key}):** 사용자의 답변을 분석하여, 다음 표준 항목 중 가장 적합한 하나를 정확히 사용해야 합니다: \"{options_string}\""
            dynamic_rules.append(rule)
            rule_number += 1

    # 메타데이터 규칙 추가
    dynamic_rules.append(f"{rule_number}.  **메타데이터 처리:** 'model_name'은 \"claude-sonnet-4-20250514\", 'prompt_version'은 \"V1.0-dynamic\"을 사용하십시오.")
    
    return "\n".join(base_prompt_rules + dynamic_rules)


def generate_json_schema_template(polls: list) -> str:
    """
    polls.json을 기반으로 LLM이 채워야 할 '빈 양식지' (JSON 템플릿)을 생성합니다.
    (이 함수가 poll10prompt_schema.json 파일을 대체합니다.)
    """
    
    schema = {
        "request_id": "{unique_request_id}",
        "process_datetime": "{current_datetime}",
        "model_name": "claude-sonnet-4-20250514",
        "prompt_version": "V1.0-dynamic",
        "original_query": "{user_input_text}",
        "analysis": {}
    }
    
    # analysis 객체에 poll 질문을 기반으로 Key를 동적으로 추가
    for poll in polls:
        key, title = get_poll_key_and_title(poll)
        # LLM이 이 필드를 채우도록 설명(주석)을 추가합니다.
        schema["analysis"][key] = f"STRING (분석 결과: {title})"
        
    # JSON 문자열로 변환하여 반환
    return json.dumps(schema, indent=2, ensure_ascii=False)


# =========================================================================
# 4. (MODIFIED) API 호출 함수 (프롬프트와 스키마를 인자로 받도록 수정)
# =========================================================================
def get_structured_response(user_input_text: str, 
                            request_id: str, 
                            system_prompt: str, 
                            json_schema_template: str) -> str:
    """
    사용자 질문을 Claude 모델에 보내고 JSON 스키마 형식의 응답을 반환합니다.
    (이제 system_prompt와 json_schema_template을 인자로 받습니다.)
    """
    if not client:
        return "Anthropic 클라이언트가 초기화되지 않았습니다."
    
    if not json_schema_template or json_schema_template == "{}":
        return "JSON 스키마 템플릿이 비어있어 API 호출을 건너뜁니다."

    # 동적인 데이터 주입
    current_time = datetime.datetime.now().isoformat()

    # 스키마 템플릿에 동적 변수 주입
    filled_schema_template = json_schema_template.replace("{unique_request_id}", request_id)
    filled_schema_template = filled_schema_template.replace("{current_datetime}", current_time)
    
    # (MODIFIED) 사용자의 원본 텍스트에 JSON 특수 문자가 있어도 괜찮도록 처리
    safe_input_text = json.dumps(user_input_text)[1:-1] # 따옴표 제거
    filled_schema_template = filled_schema_template.replace("{user_input_text}", safe_input_text)


    # LLM에 보낼 최종 사용자 프롬프트 구성
    final_user_prompt = f"""
    [입력 데이터]
    사용자 질문 (USER_QUERY): "{user_input_text}"

    [요청]
    위 '사용자 질문'을 분석하고, 아래의 JSON 스키마 템플릿에 맞추어 모든 필드를 채운 최종 JSON 객체만을 출력하십시오.

    [JSON 스키마 출력 템플릿]
    {filled_schema_template}
    """

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048, 
            system=system_prompt, # (MODIFIED) 동적으로 생성된 시스템 프롬프트 사용
            messages=[
                {"role": "user", "content": final_user_prompt}
            ]
        ).content[0].text
        return message
    except Exception as e:
        return f"API 호출 중 오류 발생: {e}"

# =========================================================================
# 5. (REFACTORED) 배치(Batch) 처리 테스트 코드
# =========================================================================
if __name__ == '__main__':
    
    # -----------------------------------------------------------
    # (NEW) 1. 모든 "재료" 파일 로드
    # -----------------------------------------------------------
    # (경로 수정) 파일이 있는 실제 경로로 수정해주세요.
    # (profile_questions.json은 이 코드에서 직접 쓰이진 않지만, 참고용으로 로드합니다.)
    POLLS_FILE_PATH = "../core/json/polls.json"
    OPTIONS_FILE_PATH = "../core/json/poll_options.json"
    USER_ANSWERS_PATH = "../core/json/user_profile_answers.json" # (NEW) 사용자 응답 파일

    polls_data = load_json_data(POLLS_FILE_PATH)
    options_data = load_json_data(OPTIONS_FILE_PATH)
    user_answers_data = load_json_data(USER_ANSWERS_PATH) # (NEW)

    if not polls_data or not options_data:
        print("!!! 오류: polls.json 또는 poll_options.json (규칙/온톨로지) 파일을 로드할 수 없습니다. 경로를 확인하세요.")
    elif not user_answers_data:
        print(f"!!! 오류: {USER_ANSWERS_PATH} (사용자 응답) 파일을 로드할 수 없습니다. 경로를 확인하세요.")
    else:
        # -----------------------------------------------------------
        # (NEW) 2. 시스템 프롬프트 및 JSON 스키마 동적 생성 (1회만 실행)
        # -----------------------------------------------------------
        print("--- 동적 시스템 프롬프트 및 JSON 스키마 생성 중 ---")
        dynamic_system_prompt = generate_dynamic_system_prompt(polls_data, options_data)
        dynamic_json_schema = generate_json_schema_template(polls_data)
        print("--- 생성 완료 ---")
        
        # -----------------------------------------------------------
        # (REFACTORED) 3. 'user_profile_answers.json' 파일 '배치(Batch)' 실행
        # -----------------------------------------------------------
        
        # (REFACTORED) 3-2. for 루프를 통해 모든 'user_answers_data'를 순차적으로 처리
        print(f"\n--- 총 {len(user_answers_data)}개의 'user_profile_answers' 자유 텍스트 응답 분석 시작 ---")
        
        results = [] # 모든 결과를 저장할 리스트

        for i, answer in enumerate(user_answers_data):
            
            # (MODIFIED) 'user_profile_answers.json'의 필드명을 사용합니다.
            # (만약 필드명이 다르면 이 부분을 수정하세요)
            test_query_text = answer.get("answer_value") # (예: "계속된 야근이랑...")
            test_query_id = answer.get("answer_id")   # (예: "ANS_001")

            # 'answer_value'가 비어있거나 텍스트가 아닌 경우 건너뜁니다.
            if not test_query_text or not isinstance(test_query_text, str):
                print(f"\n--- ({i+1}/{len(user_answers_data)}) 스킵 --- (ID: {test_query_id}, 사유: 'answer_value'가 비어있음)")
                continue
            
            print(f"\n--- ({i+1}/{len(user_answers_data)}) Claude AI에 JSON 구조화 요청 --- (ID: {test_query_id})")
            print(f"--- 쿼리: {test_query_text[:40]}... ---")
            
            response_json_string = get_structured_response(
                test_query_text, 
                str(test_query_id), # request_id는 문자열이어야 함
                dynamic_system_prompt,    # (MODIFIED) 동적 프롬프트 전달
                dynamic_json_schema       # (MODIFIED) 동적 스키마 전달
            )
            
            # LLM 응답 출력
            print(f"[Claude AI 응답 (Raw String) - {test_query_id}]")
            print(response_json_string)

            # -----------------------------------------------------------
            # (REFACTORED) 4. 개별 응답 유효성 검증
            # -----------------------------------------------------------
            try:
                parsed_json = json.loads(response_json_string)
                print(f"\n--- JSON 파싱 성공 (ID: {test_query_id}) ---")
                
                # (MODIFIED) 변경된 스키마 'analysis' 기준으로 검증
                if "analysis" in parsed_json:
                    analysis = parsed_json["analysis"]
                    print(f"  > (poll_id: 2) stress_factor: {analysis.get('stress_factor')}")
                    print(f"  > (poll_id: 1) preferred_consumption: {analysis.get('preferred_consumption')}")
                    print(f"  > (poll_id: 5) skincare_budget: {analysis.get('skincare_budget')}")
                    
                    results.append(parsed_json) # 성공한 결과만 저장
                else:
                    print(f"!!! 검증 오류 (ID: {test_query_id}): 응답 JSON에 'analysis' 키가 없습니다.")
                    
            except json.JSONDecodeError:
                print(f"\n!!! JSON 파싱 실패 (ID: {test_query_id}) - 시스템 지침 튜닝 필요 !!!")
        
        print(f"\n--- 총 {len(results)}개의 응답 처리 완료 ---")
        
        # (선택적) 최종 결과물을 파일로 저장
        # with open("../json/analysis_results.json", "w", encoding="utf-8") as f:
        #     json.dump(results, f, indent=2, ensure_ascii=False)
        # print("\n[최종 결과가 'analysis_results.json' 파일로 저장되었습니다.]")