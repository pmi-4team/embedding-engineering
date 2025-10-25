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
import psycopg2
from psycopg2.extras import RealDictCursor

from qdrant_client import models
from workers.embedder import embed_batch
from core.config import settings
from infra.qdrant import initialize_qdrant, upsert_points


# ----- PostgreSQL 접속 정보 -----
DB_CONFIG = {
    "dbname":   "pre_capstone",
    "user":     "pre_capstone",
    "password": "pre_capstone1234!",
    "host":     "34.50.13.135",
    "port":     "5432",
}

# 원본 소스 뷰/테이블 (정규화된 DB 텍스트가 여기서 나온다고 가정)
SQL_FETCH = """
    SELECT id, title, body, category, updated_at
    FROM public.search_corpus
    WHERE id > %s
    ORDER BY id
    LIMIT %s
"""


# LLM 처리 여부 확인/조회/저장
SQL_HAS_LLM = "SELECT 1 FROM public.llm_outputs WHERE source_id = %s"
SQL_GET_LLM  = "SELECT normalized, llm_version FROM public.llm_outputs WHERE source_id = %s"
SQL_PUT_LLM  = "INSERT INTO public.llm_outputs (source_id, normalized, llm_version) VALUES (%s, %s, %s) ON CONFLICT (source_id) DO NOTHING"

# 배치 크기
BATCH = 256

# ---- (임시) LLM 호출 스텁 ----
# 실제로는 workers/llm_extractor.py의 함수를 불러 LLM 호출/스키마 검증을 수행하면 됨.
# 여기서는 파이프라인을 맞추기 위해 title+body를 그대로 normalized로 반환.
def call_llm_normalize(title: str, body: str) -> Tuple[str, str]:
    # TODO: 실제 LLM 연동으로 교체
    normalized = f"{title}\n{body}"
    llm_version = "stub-0"  # 프롬프트/모델 버전 명시
    return normalized, llm_version

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
        text = f"{row['title']}\n{row['body']}"
        return text, "db", None
    else:
        # 최초 질의: LLM 경로
        normalized, llm_ver = call_llm_normalize(row["title"], row["body"])
        cur.execute(SQL_PUT_LLM, (row["id"], normalized, llm_ver))
        return normalized, "llm", llm_ver
    
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
                    "source": source_flag,
                    "llm_version": llm_ver,
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