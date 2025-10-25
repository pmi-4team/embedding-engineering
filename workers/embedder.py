# from sentence_transformers import SentenceTransformer

# # 1. 한국어 특화 임베딩 모델 로드
# # - 모델명: "nlpai-lab/KURE-v1"
# # - 벡터 차원: 1024
# model = SentenceTransformer("nlpai-lab/KURE-v1") 

# def get_embedding(text: str) -> list[float]:
#     """
#     텍스트를 받아 문장 임베딩 생성
#     - 반환값: list[float], 차원: 1024
#     """

#     # 2. 문장 임베딩 생성
#     embedding = model.encode(text)

#     # 3. 리스트 형태로 반환
#     return embedding.tolist()

    

# """
# # 토크나이저와 모델을 직접 사용하여 임베딩 생성한 버전

# from transformers import AutoTokenizer, AutoModel
# import torch

# # KURE-v1 토크나이저와 모델 로드 (모델명 업데이트)
# tokenizer = AutoTokenizer.from_pretrained("nlpai-lab/KURE-v1")
# model = AutoModel.from_pretrained("nlpai-lab/KURE-v1")

# # 임베딩 생성 함수
# def get_embedding(text):
#     # 1. 텍스트를 모델 입력용 토큰 시퀀스로 변환
#     # - return_tensors="pt": PyTorch 텐서로 반환
#     # - truncation=True: 모델 최대 입력 길이를 초과하면 자름
#     inputs = tokenizer(text, return_tensors="pt", truncation=True)

#     # 2. 학습이 아닌 추론 단계이므로 gradient 계산 비활성화
#     with torch.no_grad():
#         # 3. 토큰화된 입력 값을 모델에 넣어 각 토큰의 의미 벡터 생성
#         outputs = model(**inputs)

#     # 4. 토큰 벡터들의 평균 값으로 문장 임베딩 생성
#     embedding = outputs.last_hidden_state.mean(dim=1)

#     # 5. 임베딩을 1차원 리스트 형태로 변환하여 반환
#     return embedding.squeeze().tolist()
# """


from __future__ import annotations
from typing import List, Iterable, Optional
from sentence_transformers import SentenceTransformer
import threading

# 모델 로드를 한 번만 수행하기 위한 락
__model_lock = threading.Lock()
__model: Optional[SentenceTransformer] = None

def _get_model() -> SentenceTransformer:
    """
    내부용: 전역 모델을 lazy-init으로 한 번만 로드.
    """
    global __model
    if __model is None:
        with __model_lock:
            if __model is None:
                m = SentenceTransformer("nlpai-lab/KURE-v1")
                # 긴 입력이 잘리는 문제를 줄이기 위한 설정(필요 시 조정)
                # KURE 계열 max_seq_length 기본은 256~512 수준일 수 있음
                # 너희 데이터 길이에 맞게 256/384/512 등으로 조정 가능
                m.max_seq_length = 256
                __model = m
    return __model

def embed_one(text: str) -> List[float]:
    """
    단일 텍스트를 1024차원 임베딩으로 변환.
    코사인 유사도 사용을 가정하므로 정규화(normalize_embeddings=True) 적용.
    """
    model = _get_model()
    vec = model.encode([text], normalize_embeddings=True)[0]
    return vec.tolist()

def embed_batch(texts: Iterable[str]) -> List[List[float]]:
    """
    여러 텍스트를 배치로 임베딩.
    - 입력: Iterable[str]
    - 출력: List[List[float]] (각각 1024차원)
    """
    texts_list = list(texts)
    if not texts_list:
        return []
    model = _get_model()
    vecs = model.encode(texts_list, normalize_embeddings=True)
    # sentence-transformers는 ndarray 반환 → Python list로 변환
    return [v.tolist() for v in vecs]

# 선택: 길이 파라미터/디바이스 변경 헬퍼 (필요할 때만 사용)
def configure(max_seq_length: Optional[int] = None, device: Optional[str] = None) -> None:
    """
    런타임에 임베더 설정을 조정하고 싶을 때 사용.
    예) configure(max_seq_length=384, device='cuda')
    """
    model = _get_model()
    if max_seq_length is not None:
        model.max_seq_length = int(max_seq_length)
    if device is not None:
        model.to(device)
