import pytest
import numpy as np
from qdrant_client import models
from qdrant_client.http.models import UpdateStatus
from infra import qdrant
from core.config import settings

# 테스트에 사용할 전용 컬렉션 이름
TEST_COLLECTION_NAME = "feedback_test"

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

def test_qdrant_upsert():
    """데이터 저장(Upsert) 기능 테스트"""
    test_points = [
        models.PointStruct(id=1, vector=np.random.rand(1024).tolist(), payload={"category": "A"}),
        models.PointStruct(id=2, vector=np.random.rand(1024).tolist(), payload={"category": "B"}),
    ]
    # upsert_points 함수에 테스트용 컬렉션 이름을 명시적으로 전달
    qdrant.upsert_points(test_points, collection_name=TEST_COLLECTION_NAME)

    # 데이터가 잘 들어갔는지 확인
    assert qdrant.client.count(collection_name=TEST_COLLECTION_NAME, exact=True).count == 2
    print("Upsert 테스트 통과")

def test_qdrant_search_and_filter():
    """검색(Search) 및 필터링 기능 테스트"""
    query_vector = np.random.rand(1024).tolist()
    filter_b = models.Filter(must=[models.FieldCondition(key="category", match=models.MatchValue(value="B"))])

    # search_points 함수에 테스트용 컬렉션 이름을 명시적으로 전달
    filtered_results = qdrant.search_points(query_vector=query_vector, filters=filter_b, top_k=1, collection_name=TEST_COLLECTION_NAME)

    assert filtered_results[0].id == 2
    print("필터링 검색 테스트")