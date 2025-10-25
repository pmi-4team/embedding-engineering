from qdrant_client import QdrantClient
from core.config import settings

client = QdrantClient(
    url=settings.QDRANT_URL,
    api_key=settings.QDRANT_API_KEY
)

# 삭제할 컬렉션 이름
target_collection = settings.QDRANT_COLLECTION  # 보통 "feedback_current"

# 컬렉션 삭제
client.delete_collection(collection_name=target_collection)

print(f"컬렉션 '{target_collection}' 완전히 삭제 완료!")


#python -m tests.delete_qdrant_collection