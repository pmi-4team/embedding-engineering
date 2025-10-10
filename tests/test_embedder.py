import pytest
from infra import qdrant
from workers import embedder
from qdrant_client import models

# 테스트에 사용할 전용 컬렉션 이름
TEST_COLLECTION_NAME = "feedback_test"

# 임베딩 된 PointStruct 객체들을 저장할 리스트
points = []

@pytest.fixture(scope="module", autouse=True)
def setup_teardown_test_collection():
    """
    모든 테스트 실행 전 '한 번' 실행되어 테스트 컬렉션을 준비하고,
    모든 테스트 종료 후 '한 번' 실행되어 컬렉션을 삭제합니다.
    """
    # Setup: 테스트 시작 전
    print(f"\n--- 테스트 준비 : '{TEST_COLLECTION_NAME}' 컬렉션을 생성---")
    # 혹시 이전에 실패해서 남아있다면 삭제하기
    qdrant.client.delete_collection(collection_name=TEST_COLLECTION_NAME)
    #테스트용 컬렉션 생성
    qdrant.initialize_qdrant(collection_name=TEST_COLLECTION_NAME)

    yield # 여기에서 실제 테스트들이 실행됨

    # Teardown: 테스트 종료 후
    print(f"\n--- 테스트 정리: '{TEST_COLLECTION_NAME}' 컬렉션을 삭제---")
    qdrant.client.delete_collection(collection_name=TEST_COLLECTION_NAME)

def test_embedder_get_embedding():
    """임베더의 get_embedding 함수 테스트"""

    # 테스트용 데이터
    sample_data = [
        {"id": 1, "text": "오늘 날씨가 좋다."},
        {"id": 2, "text": "임베딩 생성 테스트 중입니다."},
        {"id": 3, "text": "오늘 날씨가 화창하다."}
    ]

    # 각 문장에 대해 임베딩 생성 및 PointStruct 객체 생성 후 리스트에 삽입
    for item in sample_data:
        emb = embedder.get_embedding(item["text"])  # 임베딩 생성     

        assert isinstance(emb, list), "임베딩 결과는 리스트여야 합니다."
        assert len(emb) == qdrant.VECTOR_SIZE, f"임베딩 벡터의 크기는 {qdrant.VECTOR_SIZE}여야 합니다."

        point = models.PointStruct(
            id=item["id"],
            vector=emb,
            payload={"text": item["text"]}
        )
        points.append(point)
    
    print("get_embedding 테스트 통과")

def test_qdrant_upsert():
    """데이터 저장(Upsert) 기능 테스트"""
    
    # upsert_points 함수에 테스트용 컬렉션 이름을 명시적으로 전달
    qdrant.upsert_points(points, collection_name=TEST_COLLECTION_NAME)

    # 데이터가 잘 들어갔는지 확인
    assert qdrant.client.count(collection_name=TEST_COLLECTION_NAME, exact=True).count == 3
    print("Upsert 테스트 통과")

def test_qdrant_search():
    """검색(Search) 및 필터링 기능 테스트"""
    query_vector = embedder.get_embedding("오늘 날씨가 맑다.")
    filter_b = models.Filter(must=[models.FieldCondition(key="category", match=models.MatchValue(value="B"))])

    # search_points 함수에 테스트용 컬렉션 이름을 명시적으로 전달
    results = qdrant.search_points(query_vector=query_vector, top_k=3, collection_name=TEST_COLLECTION_NAME)

    assert results[0].id == 1  # "오늘 날씨가 좋다."가 가장 의미가 맞음
    print(f"검색 테스트 통과, 가장 유사한 ID: {results[0].id}")

