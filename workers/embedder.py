from sentence_transformers import SentenceTransformer

# 1. 한국어 특화 임베딩 모델 로드
# - 모델명: "nlpai-lab/KURE-v1"
# - 벡터 차원: 1024
model = SentenceTransformer("nlpai-lab/KURE-v1") 

def get_embedding(text: str) -> list[float]:
    """
    텍스트를 받아 문장 임베딩 생성
    - 반환값: list[float], 차원: 1024
    """

    # 2. 문장 임베딩 생성
    embedding = model.encode(text)

    # 3. 리스트 형태로 반환
    return embedding.tolist()

    

"""
# 토크나이저와 모델을 직접 사용하여 임베딩 생성한 버전

from transformers import AutoTokenizer, AutoModel
import torch

# KURE-v1 토크나이저와 모델 로드 (모델명 업데이트)
tokenizer = AutoTokenizer.from_pretrained("nlpai-lab/KURE-v1")
model = AutoModel.from_pretrained("nlpai-lab/KURE-v1")

# 임베딩 생성 함수
def get_embedding(text):
    # 1. 텍스트를 모델 입력용 토큰 시퀀스로 변환
    # - return_tensors="pt": PyTorch 텐서로 반환
    # - truncation=True: 모델 최대 입력 길이를 초과하면 자름
    inputs = tokenizer(text, return_tensors="pt", truncation=True)

    # 2. 학습이 아닌 추론 단계이므로 gradient 계산 비활성화
    with torch.no_grad():
        # 3. 토큰화된 입력 값을 모델에 넣어 각 토큰의 의미 벡터 생성
        outputs = model(**inputs)

    # 4. 토큰 벡터들의 평균 값으로 문장 임베딩 생성
    embedding = outputs.last_hidden_state.mean(dim=1)

    # 5. 임베딩을 1차원 리스트 형태로 변환하여 반환
    return embedding.squeeze().tolist()
"""