<<<<<<< HEAD
**_기본 세팅_**
**_환경_**
Python 3.12.x
VS Code + Python

**_가상환경 설치_**
python -m venv .venv

**_가상환경 실행_**
.\.venv\Scripts\Activate.ps1

**_가상환경 종료_**
deactivate

**_가상환경 안에서 패키지 설치_**
python -m pip install -U pip
python -m pip install fastapi "uvicorn[standard]" pydantic-settings sqlalchemy psycopg2-binary redis qdrant-client minio anthropic tenacity jsonschema numpy

**_서버 실행(가상환경 실행하고 홈에서)_**
python -m uvicorn apps.api.main:app --reload

**_서버 연결 테스트_**
http://127.0.0.1:8000/health

============================================================================================================================================================

**_가이드_**
Python 3.12.x 버전 설치
VSCode 안에서 터미널 열고 작업
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install fastapi "uvicorn[standard]" pydantic-settings sqlalchemy psycopg2-binary redis qdrant-client minio anthropic tenacity jsonschema numpy
python -m uvicorn apps.api.main:app --reload
http://127.0.0.1:8000/health
deactivate

============================================================================================================================================================

**_데이터 엔지니어_**
**_workers/normalize.py_**
PII 1차(정규식/토큰화), 정규화/오탈자 교정, 동의어/표준화 적용.

**_infra/db.py_**
PostgreSQL 연동(SQLAlchemy 엔진/세션), upsert 유틸, 인덱스/파티션 전략.
.env: PG_URL

**_infra/redis.py_**
Redis 연동(클라이언트, 키 스킴, TTL), 레이트리밋/결과 캐시 정책.
.env: REDIS_URL

**_infra/minio.py_**
MinIO 연동(버킷 보장, 업/다운/프리사인드 URL), DLQ/원본/리포트 저장 정책.
.env: MINIO\_\*

**_core/ontology/v0_1/_ \***
동의어 사전/온톨로지 버전 관리(거버넌스, 릴리즈 노트)

**_함께 만지는 파일_**
**_apps/api/routers/insights.py_**
집계용 SQL/뷰/머티리얼라이즈 테이블 쿼리 작성·최적화.

**_core/config.py_**
DB/Redis/MinIO 기본값·ENV 키 추가.

============================================================================================================================================================

**_LLM 엔지니어_**
**_workers/llm_extractor.py_**
Claude 프롬프트/시스템 지침, JSON 스키마 검증, 재시도/백오프, DLQ 기록, 근거 스팬 추출.
.env: ANTHROPIC_API_KEY, LLM_VERSION

**_core/config.py_**
LLM 관련 ENV/리밋, 타임아웃.

**_core/ontology/v0_1/_ \***
매핑 개선 제안(최종 승격은 데이터 엔지니어).

**_함께 만지는 파일_**
**_apps/api/main.py_**
라우터 등록/헬스 유지, LLM 장애 시 헬스 영향 최소화(try/except).

**_tests/_**
구조화 정확도/JSON 유효율 테스트, 가짜 LLM(mock) 픽스처.

============================================================================================================================================================

**_임베딩/검색 엔지니어_**
**_workers/embedder.py_**
KURE-v1 임베딩 생성(무엇을 임베딩할지 정책: 원문/요약/문장), 배치 업서트.
.env: EMBEDDING_VERSION

**_infra/qdrant.py_**
Qdrant 연동(컬렉션 생성/파라미터/HNSW, upsert/search 래퍼), 버저닝+alias.
.env: QDRANT_URL, QDRANT_API_KEY, QDRANT_COLLECTION

**_apps/api/routers/search.py_**
쿼리 임베딩 → Top-K 검색 → (옵션) 리랭커 → Redis 캐시.
필터(기간/토픽/감정) 적용, 응답 스키마.

**_함께 만지는 파일_**
**_infra/redis.py_**
검색 결과 캐시 키/TTL, 캐시 무효화 정책(데이터팀과 합의).

**_apps/api/deps.py_**
Qdrant/Redis 의존성 주입.

============================================================================================================================================================

**_파일 목적_**
apps/api
main.py: FastAPI 서버 기동·라우터 등록·헬스체크.
deps.py: Redis/Qdrant/DB 등 의존성 주입 헬퍼.
routers/search.py: 의미검색 API(Top-K, (옵션) 리랭커, 캐시).
routers/insights.py: 집계/트렌드 조회 API.

workers
normalize.py: PII 1차·정규화·오탈자·동의어/표준화 처리.
llm_extractor.py: LLM 프롬프팅으로 JSON 구조화(+근거·재시도·DLQ).
embedder.py: KURE-v1 임베딩 생성 후 Qdrant 업서트.

infra
db.py: PostgreSQL 연결/세션·업서트 유틸.
redis.py: Redis 클라이언트·캐시 키/TTL 기반.
qdrant.py: Qdrant 컬렉션 보장·검색/업서트 래퍼.
minio.py: MinIO 버킷 관리·파일 업/다운 유틸.

core
config.py: ENV 설정(키/URL/버전/TTL) 중앙 관리.
logging.py: 공통 로깅 포맷·레벨 설정.
ontology/v0_1/lexicon.json: 동의어 사전(표현→표준 용어).
ontology/v0_1/ontology.json: 온톨로지 트리(카테고리 계층).

기타
dags/: Airflow/Prefect 파이프라인 정의.
tests/: 유닛/통합 테스트.
.env: 환경변수 템플릿.
pyproject.toml: 패키지/포맷터/테스트 도구 설정.