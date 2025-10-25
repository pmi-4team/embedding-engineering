# === PostgreSQL 연결 + Qdrant 기본 동작 + search_corpus→임베딩→Qdrant 업서트 E2E 스모크 테스트 ===
from __future__ import annotations
from typing import List, Dict, Tuple, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from qdrant_client import models
from core.config import settings
from infra.qdrant import (
    client,
    initialize_qdrant,
    upsert_points,
    delete_collection,
)
from workers.embedder import embed_batch


# ------------------------------------------------------------
# 환경/설정
# ------------------------------------------------------------
# 🔹 네가 준 DB 하드코딩
DB_CONFIG = {
    "dbname":   "pre_capstone",
    "user":     "pre_capstone",
    "password": "pre_capstone1234!",
    "host":     "34.50.13.135",
    "port":     "5432",
}

# 🔹 테스트 컬렉션 (운영 오염 방지용)
TEST_COLLECTION = f"{settings.QDRANT_COLLECTION}_smoke"

# 🔹 search_corpus에서 가져올 SQL (id/title/body/category/updated_at 필수)
SQL_FETCH_ONE = """
    SELECT id, title, body, category, updated_at
    FROM public.search_corpus
    ORDER BY id
    LIMIT %s
"""

# 🔹 llm_outputs 존재 가정 (이미 생성되어 있음)
SQL_HAS_LLM = "SELECT 1 FROM public.llm_outputs WHERE source_id = %s"
SQL_PUT_LLM  = """
INSERT INTO public.llm_outputs (source_id, normalized, llm_version)
VALUES (%s, %s, %s)
ON CONFLICT (source_id) DO NOTHING
"""

KEEP_TEST_COLLECTION = False   # True면 컬렉션 유지, False면 마지막에 삭제


# ------------------------------------------------------------
# 유틸
# ------------------------------------------------------------
def call_llm_normalize(title: str, body: str) -> Tuple[str, str]:
    """(임시 스텁) 최초 질의인 경우 LLM이 가공한 텍스트라고 가정."""
    normalized = f"{title}\n{body}"
    llm_version = "stub-0"
    return normalized, llm_version

def choose_text_for_embedding(cur, row: Dict) -> Tuple[str, str, Optional[str]]:
    """
    PM 규칙 반영:
        - 최초 질의: llm_outputs에 없으면 LLM 호출 → normalized 저장 → 이번엔 LLM 텍스트로 임베딩 (source='llm')
        - 재질의: llm_outputs에 있으면 DB 정규화 텍스트로 임베딩 (source='db')
    """
    cur.execute(SQL_HAS_LLM, (row["id"],))
    seen = cur.fetchone() is not None

    if seen:
        text = f"{row['title']}\n{row['body']}"
        return text, "db", None
    else:
        normalized, llm_ver = call_llm_normalize(row["title"], row["body"])
        cur.execute(SQL_PUT_LLM, (row["id"], normalized, llm_ver))
        return normalized, "llm", llm_ver


# ------------------------------------------------------------
# 체크/테스트 함수
# ------------------------------------------------------------
def check_postgres():
    print("[PG] 연결 시도…")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT now() AS now_utc")
    print(f"[OK] postgres now() = {cur.fetchone()['now_utc']}")

    cur.execute("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
        LIMIT 10
    """)
    rows = cur.fetchall()
    names = [f"{r['table_schema']}.{r['table_name']}" for r in rows]
    print(f"[OK] public 스키마 테이블 예시: {names}")

    cur.close()
    conn.close()


def check_qdrant_basic():
    print("[Qdrant] 연결/컬렉션 보장…")
    initialize_qdrant(TEST_COLLECTION)
    print("[OK] 테스트 컬렉션 준비 완료")

    # 업서트 → retrieve → 삭제 (필터 인덱스 없이도 통과)
    test_id = 999_999_999
    p = models.PointStruct(
        id=test_id,
        vector=[0.0] * 1024,
        payload={"smoke": True, "note": "connectivity-check"},
    )
    upsert_points([p], collection_name=TEST_COLLECTION)
    print("[OK] upsert 1건")

    got = client.retrieve(
        collection_name=TEST_COLLECTION,
        ids=[test_id],
        with_payload=True,
        with_vectors=False,
    )
    assert len(got) == 1, "retrieve 결과 0건"
    assert got[0].payload.get("smoke") is True, "payload.smoke != True"
    print("[OK] retrieve 확인")

    client.delete(
        collection_name=TEST_COLLECTION,
        points_selector=models.PointIdsList(points=[test_id]),
    )
    print("[OK] cleanup (delete 1건)")


def test_ingest_small_sample(limit: int = 5):
    """
    search_corpus에서 소량 가져와 임베딩 후 TEST_COLLECTION에 업서트 → 하나 임의 조회 확인.
    """
    print(f"[E2E] search_corpus → 임베딩 → Qdrant 업서트 (limit={limit})")

    # 1) 테스트 컬렉션 보장
    initialize_qdrant(TEST_COLLECTION)

    # 2) PG 연결/조회
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    print("[PG] 연결 성공")

    cur.execute(SQL_FETCH_ONE, (limit,))
    rows = cur.fetchall()
    assert rows, "search_corpus에서 레코드를 가져오지 못했음"
    print(f"[PG] fetched {len(rows)} rows")

    # 3) PM 규칙에 따라 임베딩 소스 텍스트/메타 정리
    texts: List[str] = []
    metas: List[Dict] = []
    for r in rows:
        text, source_flag, llm_ver = choose_text_for_embedding(cur, r)
        conn.commit()  # llm_outputs INSERT 반영

        metas.append({
            "id": int(r["id"]),
            "title": r["title"],
            "category": r.get("category"),
            "updated_at": str(r.get("updated_at")),
            "source": source_flag,
            "llm_version": llm_ver,
            "embedding_version": "kure-v1",
        })
        texts.append(text)

    # 4) 임베딩
    vecs = embed_batch(texts)

    # 5) Qdrant 포인트 구성
    points: List[models.PointStruct] = []
    for meta, vec in zip(metas, vecs):
        points.append(
            models.PointStruct(
                id=meta["id"],
                vector=vec,
                payload={
                    "pg_id": meta["id"],
                    "title": meta["title"],
                    "category": meta["category"],
                    "updated_at": meta["updated_at"],
                    "source": meta["source"],
                    "llm_version": meta["llm_version"],
                    "embedding_version": meta["embedding_version"],
                },
            )
        )

    # 6) 업서트
    upsert_points(points, collection_name=TEST_COLLECTION)
    print(f"[OK] upsert {len(points)}건")

    # 7) 카운트/샘플 조회 확인
    total_cnt = client.count(TEST_COLLECTION, exact=True).count
    print(f"[OK] 테스트 컬렉션 전체 개수: {total_cnt}")

    sample_id = metas[0]["id"]
    got = client.retrieve(
        collection_name=TEST_COLLECTION,
        ids=[sample_id],
        with_payload=True,
        with_vectors=False,
    )
    assert len(got) == 1, f"retrieve 실패 (id={sample_id})"
    payload = got[0].payload or {}
    print(f"[OK] 샘플(payload): id={sample_id}, source={payload.get('source')}, title={payload.get('title')!r}")

    cur.close()
    conn.close()
    print("[PG] 연결 종료")


# ------------------------------------------------------------
# main
# ------------------------------------------------------------
if __name__ == "__main__":
    print("Settings loaded successfully!")
    print(f"Qdrant URL: {settings.QDRANT_URL}")
    print("=== SMOKE TESTS START ===")
    try:
        check_postgres()            # 1) PG 붙는지/테이블 보이는지
        check_qdrant_basic()        # 2) Qdrant에 쓰기/읽기/삭제 동작 확인(테스트 컬렉션)
        test_ingest_small_sample(5) # 3) 실제 search_corpus→임베딩→Qdrant 업서트 확인(5건)

        print("=== SMOKE TESTS OK ===")
    finally:
        if not KEEP_TEST_COLLECTION:
            print(f"[CLEANUP] 테스트 컬렉션 삭제: {TEST_COLLECTION}")
            delete_collection(TEST_COLLECTION)
