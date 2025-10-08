from qdrant_client import QdrantClient, models

# pydantic-setting 라이브러리를 통해 .env 파일을 읽어오는 설정 객체
from core.config import settings

# 클라이언트 초기화
# settings 객체가 .env 파일에서 QDRANT_URL과 QDRANT_API_KEY를 자동으로 읽어온다.
try:
    client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY
    )
    print("Qdrant Cloud에 성공적으로 연결됐습니다.")
except Exception as e:
    print(f"Qdrant Cloud 연결에 실패했습니다: {e}")

# 상수 정의
VECTOR_SIZE = 1024  # KURE-v1 모델의 벡터 차원(1024)
DISTANCE_METRIC = models.Distance.COSINE # 벡터 유사도 계산 방식(코사인 유사도로 진행)

# 컬렉션 및 인덱스 생성 함수
def initialize_qdrant(collection_name: str = settings.QDRANT_COLLECTION):
    """
    Qdrant 컬렉션과 payload index의 존재를 보장하는 함수
    서버가 시작될 때 한 번만 호출하면 된다.
    """ 
    try:
        client.get_collection(collection_name=collection_name)
        print(f"Collection '{collection_name}'이 이미 존재합니다.")
    except Exception:
        print(f"Collection '{collection_name}'을 찾을 수 없어 새로 생성합니다.")
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=VECTOR_SIZE,
                distance=DISTANCE_METRIC # 코사인 유사도
            )
        )
        print("Collection 생성 완료")

        print("Payload Index를 생성")
        # 검색 시 필터링 속도를 높이기 위해 인덱스를 생성
        client.create_payload_index(
            collection_name=collection_name,
            field_name="category", # 예시를 들자면 "제품 불만", "기능 문의" 등 빠르게 조회해야 하는 필드들
            field_schema=models.PayloadSchemaType.KEYWORD
        )
        # 아래와 같이 추가로 인덱스 여러개 생성 가능
        # field_name에 들어가는 문자열은 나중에 Qdrant에 저장할 데이터(Payload)의 'Key' 이름과 정확히 일치해야 한다.
        # client.create_payload_index(
        #     collection_name=settings.QDRANT_COLLECTION, 
        #     field_name="sentiment",
        #     field_schema=models.PayloadSchemaType.KEYWORD
        # )
        print("Payload Index 생성 완료")

# 데이터 추가/검색을 위한 래퍼 함수
# points 리스트의 각 원소는 models.PointStruct 타입
def upsert_points(points: list[models.PointStruct], collection_name: str = settings.QDRANT_COLLECTION):
    """여러 데이터 포인트를 Qdrant에 저장(upsert)합니다"""
    client.upsert(
        collection_name=collection_name,
        points=points,
        wait=True # 작업이 완료될 때까지 기다리기
    )

def search_points(query_vector: list[float], filters: models.Filter = None, top_k: int = 5, collection_name: str = settings.QDRANT_COLLECTION):
    return client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=filters,
        limit=top_k
    ).points
