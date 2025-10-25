# """
# 역할	                        주된 책임	                                파일
# 데이터 수집기 (ETL)	  PostgreSQL에서 텍스트 데이터를 SELECT로 가져오기	workers/ingest_pg_to_qdrant.py
# 임베딩 유틸	          텍스트 → 1024차원 KURE-v1 벡터로 변환	                   workers/embedder.py
# 벡터 저장소 연동기	   Qdrant 컬렉션 생성, 업서트, 검색 등 관리	         infra/qdrant.py 
# """

# from typing import List, Dict
# import psycopg2
# from psycopg2.extras import RealDictCursor
# from workers.embedder import embed_batch
# from qdrant_client import models

# # Qdrant/설정 코드 재사용 
# # 만약 같은 파일에 있다면 import 대신 그대로 호출해도 됨.
# from core.config import settings
# from infra.qdrant import initialize_qdrant, upsert_points  

# # ----- PostgreSQL 접속 정보 -----
# DB_CONFIG = {
#     "dbname":   "pre_capstone",
#     "user":     "pre_capstone",
#     "password": "pre_capstone1234!",
#     "host":     "34.50.13.135",
#     "port":     "5432",
# }

# # 필수: id(정수 PK), title(TEXT), body(TEXT) 는 있어야 아래 로직 그대로 사용 가능
# SQL_FETCH = """
#     SELECT id, title, body, category, updated_at
#     FROM public.search_corpus
#     WHERE id > %s
#     ORDER BY id
#     LIMIT %s
# """

# # 배치 크기
# BATCH = 256 


# def rows_to_points(rows: List[Dict]) -> List[models.PointStruct]:
#     texts = [f"{r['title']}\n{r['body']}" for r in rows]
#     vecs = embed_batch(texts)
#     points: List[models.PointStruct] = []
#     for r, v in zip(rows, vecs):
#         points.append(
#             models.PointStruct(
#                 id=int(r["id"]),      # Qdrant 포인트 ID = PG PK
#                 vector=v,
#                 payload={
#                     "pg_id": int(r["id"]),
#                     "title": r["title"],
#                     "category": r.get("category"),
#                     "updated_at": str(r.get("updated_at")),
#                 },
#             )
#         )
#     return points

# def run():
#     # 0) Qdrant 컬렉션 보장
#     initialize_qdrant(settings.QDRANT_COLLECTION)

#     # 1) PG 연결
#     conn = psycopg2.connect(**DB_CONFIG)
#     cur = conn.cursor(cursor_factory=RealDictCursor)
#     print("PostgreSQL 연결 성공")

#     try:
#         last_id = 0
#         total = 0
#         while True:
#             cur.execute(SQL_FETCH, (last_id, BATCH))
#             rows = cur.fetchall()
#             if not rows:
#                 break

#             points = rows_to_points(rows)
#             upsert_points(points, collection_name=settings.QDRANT_COLLECTION)

#             last_id = rows[-1]["id"]
#             total += len(rows)
#             print(f"indexed so far: {total}")

#         print(f"done. total indexed: {total}")

#     finally:
#         cur.close()
#         conn.close()
#         print("PostgreSQL 연결 종료")

# if __name__ == "__main__":
#     run()



from __future__ import annotations
from typing import List, Dict, Tuple
import json
import psycopg2
from psycopg2.extras import RealDictCursor

from qdrant_client import models
from workers.embedder import embed_batch
from core.config import settings
from infra.qdrant import initialize_qdrant, upsert_points

from workers.llm_extractor import extract_normalized


# ----- PostgreSQL 접속 정보 -----
DB_CONFIG = {
    "dbname":   "pre_capstone",
    "user":     "pre_capstone",
    "password": "pre_capstone1234!",
    "host":     "34.50.13.135",
    "port":     "5432",
}


# DB 정규화 텍스트(norm_text)가 있으면 사용, 없으면 원문(title/body)로 폴백
# 원본 소스 뷰/테이블 (정규화된 DB 텍스트가 여기서 나온다고 가정) if 뷰/테이블이 없다면 LEFT JOIN 부분을 제거해도 동작(아래 COALESCE가 폴백)
SQL_FETCH = """
    SELECT sc.id,
        sc.title,
        sc.body,
        sc.category,
        sc.updated_at,
        COALESCE(scn.norm_text, NULL) AS norm_text
    FROM public.search_corpus sc
    LEFT JOIN public.search_corpus_normalized scn
        ON scn.id = sc.id            -- 있으면 DB 정규화 텍스트 사용
    WHERE sc.id > %s
    ORDER BY sc.id
    LIMIT %s
"""


# LLM 처리 여부 확인/조회/저장
SQL_HAS_LLM = "SELECT 1 FROM public.llm_outputs WHERE source_id = %s"
SQL_PUT_LLM = "INSERT INTO public.llm_outputs (source_id, normalized, llm_version, raw_json) VALUES (%s, %s, %s, %s::jsonb) ON CONFLICT (source_id) DO NOTHING"
SQL_PUT_LLM_ERR = "INSERT INTO public.llm_outputs (source_id, error_msg) VALUES (%s, %s) ON CONFLICT (source_id) DO NOTHING"

# 배치 크기
BATCH = 256


def call_llm_normalize(title: str, body: str) -> Tuple[str, str, dict]:
    """
    실제 LLM 연동:
    workers.llm_extractor.extract_normalized() -> {normalized_text, llm_version}
    """
    data = extract_normalized(title, body)  # TypedDict
    # data 예: {"normalized_text": "...", "llm_version": "claude-xxx-normalize-v0.1"}
    return data["normalized_text"], data["llm_version"], data

def choose_text_for_embedding(cur, row: Dict) -> Tuple[str, str, str | None]:
    """
    규칙:
    - 최초 질의: llm_outputs에 없으면 LLM 호출 → normalized 저장 → 이번엔 LLM 텍스트로 임베딩 (source='llm')
    - 재질의: llm_outputs에 있으면 DB 정규화 텍스트로 임베딩 (source='db')
    반환: (embedding_text, source_flag, llm_version_or_None)
    """
    # LLM 처리 이력 있는지 확인
    cur.execute(SQL_HAS_LLM, (row["id"],))
    seen = cur.fetchone() is not None

    if seen:
        # 재질의: DB 직행
        db_text = row.get("norm_text")
        if db_text and isinstance(db_text, str) and db_text.strip():
            return db_text, "db", None
        
        # DB 정규화가 아직 없다면 임시로 원문 사용(운영 정책에 따라 스킵도 가능)
        raw_text = f"{row['title']}\n{row['body']}"
        return raw_text, "fallback_raw", None

    try:
        normalized, llm_ver, raw_json = call_llm_normalize(row["title"], row["body"])
        cur.execute(SQL_PUT_LLM, (row["id"], normalized, llm_ver, json.dumps(raw_json)))
        return normalized, "llm", llm_ver
    except Exception as e:
        # 실패 시 기록만 남기고 폴백(정책상 스킵하려면 여기서 raise)
        cur.execute(SQL_PUT_LLM_ERR, (row["id"], str(e)))
        raw_text = f"{row['title']}\n{row['body']}"
        return raw_text, "fallback_raw", None
    
def run():
    # 0) Qdrant 컬렉션 보장
    initialize_qdrant(settings.QDRANT_COLLECTION)

    # 1) PG 연결
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    print("PostgreSQL 연결 성공")

    try:
        last_id = 0
        total = 0

        while True:
            cur.execute(SQL_FETCH, (last_id, BATCH))
            rows = cur.fetchall()
            if not rows:
                break

            # 규칙에 맞춰 임베딩 입력 텍스트/메타 결정
            texts: List[str] = []
            metas: List[Dict] = []

            for r in rows:
                text, source_flag, llm_ver = choose_text_for_embedding(cur, r)
                # llm_outputs INSERT 반영
                conn.commit()

                texts.append(text)
                metas.append({
                    "id": int(r["id"]),
                    "title": r["title"],
                    "category": r.get("category"),
                    "updated_at": str(r.get("updated_at")),
                    "source": source_flag, # 'llm' | 'db' | 'fallback_raw'
                    "llm_version": llm_ver,  # 최초 질의면 값 존재
                    "embedding_version": "kure-v1",
                })

            # 3) 임베딩
            vecs = embed_batch(texts)

            # 4) Qdrant 포인트 구성
            points: List[models.PointStruct] = []
            for meta, vec in zip(metas, vecs):
                points.append(
                    models.PointStruct(
                        id=meta["id"],          # 동일 id에 upsert → 이후 실행에서 DB버전으로 덮어씀
                        vector=vec,
                        payload={
                            "pg_id": meta["id"],
                            "title": meta["title"],
                            "category": meta["category"],
                            "updated_at": meta["updated_at"],
                            "source": meta["source"],                   # 'llm' or 'db'
                            "llm_version": meta["llm_version"],
                            "embedding_version": meta["embedding_version"],
                        },
                    )
                )

            # 5) 업서트
            upsert_points(points, collection_name=settings.QDRANT_COLLECTION)

            last_id = rows[-1]["id"]
            total += len(rows)
            print(f"indexed so far: {total}")

        print(f"done. total indexed: {total}")

    finally:
        cur.close()
        conn.close()
        print("PostgreSQL 연결 종료")


if __name__ == "__main__":
    run()