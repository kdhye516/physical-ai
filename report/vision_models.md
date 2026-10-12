# 비전 AI 모델 6종 기능 및 사용 예시 보고서

- 작성자: 다혜
- 작성일: 2026-10-12
- 대상 모델: YOLOE, DINO-X, SAM 3, SigLIP, OCR(PaddleOCR), MediaPipe
- 관련 문서: `report/model_yolo.md` (맘캠 주 모델 YOLO26n-pose)

> 각 모델의 수치와 코드는 공식 문서·논문·GitHub 저장소를 기준으로 정리했다(참고 자료 참고). 코드 예시는 공식 예제를 바탕으로 한 것이며, 이 보고서 작성 과정에서 직접 실행해 본 것은 아니다.

---

## 1. 한눈에 비교

| 모델 | 만든 곳 | 한 줄 요약 | 입력(프롬프트) | 출력 | 실행 위치 |
|---|---|---|---|---|---|
| **YOLOE** | Ultralytics | 학습 없이 이름만 주면 찾아 주는 실시간 YOLO | 텍스트, 예시 박스, 프롬프트 없음 | 박스 + 마스크 | 로컬 (GPU·CPU·엣지) |
| **DINO-X** | IDEA Research | 무엇이든 찾는 대형 오픈월드 검출 모델 | 텍스트, 시각 예시, 프롬프트 없음 | 박스, 마스크, 키포인트, 설명 문장 | 클라우드 API |
| **SAM 3** | Meta | 개념(단어)으로 모든 물체를 분할·추적 | 짧은 명사구, 예시 이미지, 점·박스 | 마스크 + 박스 + 영상 추적 | 로컬 GPU (848M) |
| **SigLIP 2** | Google | 이미지와 문장을 같은 공간에 놓는 인코더 | 이미지 + 후보 문장 | 유사도 점수, 임베딩 | 로컬 (GPU·CPU) |
| **OCR (PaddleOCR)** | Baidu PaddlePaddle | 이미지 속 글자를 읽어 텍스트로 변환 | 이미지·PDF | 글자, 글자 위치, 문서 구조 | 로컬 |
| **MediaPipe** | Google | 모바일·웹용 즉시 사용 가능한 비전 작업 모음 | 이미지·영상·카메라 | 랜드마크, 박스, 분할, 분류 | 기기 안 (Android·iOS·Web·Python) |

### 어떤 문제에 어떤 모델을 쓰나

| 하고 싶은 일 | 알맞은 모델 |
|---|---|
| 정해진 물체를 빠르게, 기기 안에서 찾기 | YOLO (학습 필요) |
| 학습 없이 새로운 물체 이름으로 바로 찾기 | **YOLOE** (빠름) / **DINO-X** (정확, 클라우드) |
| 물체 모양을 픽셀 단위로 정확히 오려 내기 | **SAM 3** |
| "이 사진이 무엇에 가까운가" 분류·검색 | **SigLIP 2** |
| 사진 속 글자 읽기 | **OCR** |
| 사람 몸·손·얼굴 관절을 바로 쓰기 | **MediaPipe** |

---

## 2. YOLOE (You Only Look Once — Everything)

### 2-1. 무엇인가

기존 YOLO는 학습한 클래스(예: COCO 80종)만 찾을 수 있다. **YOLOE는 실행할 때 찾을 물체의 이름을 바꿀 수 있는 "오픈 보캐뷸러리" YOLO**다. 새 물체를 찾으려고 다시 학습할 필요가 없고, 검출 박스와 함께 분할 마스크도 낸다.

### 2-2. 주요 기능

| 모드 | 사용법 | 쓰임 |
|---|---|---|
| 텍스트 프롬프트 | `set_classes(["baby", "pillow"])`처럼 이름을 넣음 | 가장 일반적인 방식 |
| 시각 프롬프트 | 참고 이미지에 예시 박스를 그려 줌 | 말로 설명하기 어려운 물체 |
| 프롬프트 없음 (`-pf` 모델) | 아무것도 안 줌 | 내장된 4,585개 이름 중에서 알아서 찾음 |

- **핵심 기술:** RepRTA(텍스트 임베딩 보정, 내보낼 때 합쳐져 속도 손실 없음), SAVPE(시각 프롬프트 인코더), LRPC(프롬프트 없는 모드용 대조 방식)
- **성능:** 논문 기준 YOLOE-v8s가 YOLO-Worldv2-S보다 LVIS에서 3.5 AP 높고, 학습 비용은 약 1/3, 추론은 1.4배 빠르다.
- **모델 종류:** `yoloe-26n/s/m/l/x-seg.pt`, `yoloe-11s/m/l-seg.pt`, `yoloe-v8s/m/l-seg.pt` (프롬프트 없는 버전은 이름에 `-pf`)

### 2-3. 사용 예시 코드

```python
from ultralytics import YOLOE

model = YOLOE("yoloe-26s-seg.pt")
model.set_classes(["baby", "pillow", "blanket", "stuffed toy"])   # 찾을 물체 이름

results = model.predict("crib.jpg")
results[0].show()        # 박스 + 마스크 표시
```

처음 `set_classes()`를 호출할 때 텍스트 인코더(약 254MB)를 내려받으므로 인터넷 연결이 필요하다.

### 2-4. 일반 활용 예

- 매장 진열대에서 신제품 이름만 넣어 바로 재고 확인
- 공장 라인에서 새 불량 유형을 학습 없이 먼저 탐지해 보기
- 학습 데이터를 만들기 전, 어떤 물체가 잘 잡히는지 빠르게 실험

### 2-5. 맘캠 활용 예

- **침대 위 위험 물건 감지:** `["pillow", "thick blanket", "stuffed toy", "bumper"]`를 넣어 질식 위험 물건이 침대에 있는지 확인 → 앱에서 "침대에 베개가 있어요" 안내
- **학습 데이터 1차 라벨링:** 수집한 영상에서 `"baby"` 박스를 자동으로 그려 두고 사람이 수정만 하기

### 2-6. 장단점

| 장점 | 단점 |
|---|---|
| 학습 없이 바로 사용, 실시간 속도 | 처음 보는 단어에 대한 정확도는 학습한 YOLO보다 낮음 |
| 박스와 마스크를 함께 출력 | 텍스트 인코더가 커서 엣지 기기에서는 클래스를 고정해 내보내야 함 |

---

## 3. DINO-X

### 3-1. 무엇인가

IDEA Research가 만든 **오픈월드 물체 인식용 대형 모델**이다. Grounding DINO 1.5 구조를 바탕으로, 1억 개 이상의 학습 샘플(Grounding-100M)로 사전학습했다. 텍스트로 찾는 것은 물론 **프롬프트 없이 화면 속 모든 물체를 찾는 기능**이 있다. 공개 모델 파일은 없고 **클라우드 API로만** 쓸 수 있다.

### 3-2. 주요 기능

| 기능 | 설명 |
|---|---|
| 오픈월드 검출 | 텍스트, 시각 예시, 사용자 정의 프롬프트로 물체 찾기 |
| 프롬프트 없는 검출 | `<prompt_free>`로 화면의 모든 물체를 찾아 분할 |
| 분할 | 물체별 마스크 |
| 자세 추정 | 사람·동물 키포인트 |
| 물체 설명 | 찾은 영역을 문장으로 설명(region caption) |
| 개수 세기 | 시각 예시와 같은 물체 개수 세기 |

- **성능 (DINO-X Pro, 학습 없이 평가):** COCO 56.0 AP, LVIS-minival 59.8 AP, LVIS-val 52.4 AP. 드문 클래스에서 기존 최고 성능보다 5.0~5.8 AP 높다.

### 3-3. 사용 방법

```bash
# 1) DeepDataSpace에서 API 토큰 발급
# 2) SDK 설치
pip install dds-cloudapi-sdk
# 3) 공식 저장소(IDEA-Research/DINO-X-API)의 demo.py에 토큰을 넣고 실행
python demo.py               # 텍스트로 물체 찾기
python prompt_free_demo.py   # 프롬프트 없이 모든 물체 찾기
```

API 호출 코드는 공식 저장소의 `demo.py`를 참고한다. SDK 버전에 따라 호출 방식이 바뀔 수 있다.

### 3-4. 일반 활용 예

- 대량 이미지의 자동 라벨링 (사람이 검수만)
- 로봇·드론이 처음 보는 환경에서 물체 목록 만들기
- 이미지 검색 서비스의 태그 자동 생성

### 3-5. 맘캠 활용 예

- **학습 데이터 자동 라벨링 (개발 단계 한정):** 인형으로 찍은 엎드림 데이터에 아기 박스와 키포인트 후보를 자동으로 달아 라벨링 시간을 줄인다.
- **주의:** 영상을 외부 서버로 보내야 하므로 **실제 가정의 아기 영상에는 쓰지 않는다.** 맘캠의 "영상 클라우드 미전송" 원칙과 맞지 않기 때문이다. 인형·합성 데이터에만 사용한다.

### 3-6. 장단점

| 장점 | 단점 |
|---|---|
| 정확도가 매우 높고 기능이 많음 | 클라우드 API 전용, 호출당 비용 발생 |
| 프롬프트 없이 모든 물체 검출 | 개인정보가 담긴 영상에는 쓰기 어려움, 실시간 기기 탑재 불가 |

---

## 4. SAM 3 (Segment Anything Model 3)

### 4-1. 무엇인가

Meta가 공개한 **분할 모델의 3세대**다. SAM 1·2는 사용자가 점이나 박스를 찍어 준 물체 하나를 오려 냈다. **SAM 3는 "baby", "blanket" 같은 짧은 단어만 주면 그 개념에 해당하는 모든 물체를 찾아 분할하고, 영상에서는 계속 추적한다** (Promptable Concept Segmentation).

### 4-2. 주요 기능

| 기능 | 설명 |
|---|---|
| 개념 분할 | 짧은 명사구나 예시 이미지로 해당하는 모든 물체 분할 |
| 기존 방식 지원 | 점, 박스, 마스크로 특정 물체 분할 (SAM 1·2 방식) |
| 영상 추적 | 찾은 물체를 프레임마다 추적 |
| 프레즌스 토큰 | "흰 이불"과 "회색 이불"처럼 비슷한 표현을 구분 |

- **모델 크기:** 848M 파라미터. 실행에 CUDA GPU가 필요하다(공식 안내: Python 3.12+, PyTorch 2.7+).
- **속도:** H200 GPU에서 물체 100개 이상인 이미지 한 장에 약 30ms.
- **성능:** 개념 분할 지표(cgF1)에서 기존 모델의 약 2배. 사용자 평가에서 OWLv2보다 약 3:1로 선호됐다.
- **SAM 3.1 (2026-03):** 여러 물체를 한 번에 추적하는 기능이 추가돼 영상 처리량이 늘었다.
- **라이선스:** SAM License. 모델 파일은 Hugging Face에서 접근 승인을 받은 뒤 내려받는다.

### 4-3. 사용 예시 코드

```python
from PIL import Image
from sam3.model_builder import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor

model = build_sam3_image_model()
processor = Sam3Processor(model)

image = Image.open("crib.jpg")
state = processor.set_image(image)

output = processor.set_text_prompt(state=state, prompt="baby")
masks, boxes, scores = output["masks"], output["boxes"], output["scores"]
```

### 4-4. 일반 활용 예

- 사진 편집 앱의 "사람만 오려 내기", 배경 지우기
- 의료·농업 영상에서 특정 대상(잎, 세포 등) 면적 측정
- 영상 속 특정 물체만 따라가며 효과 넣기

### 4-5. 맘캠 활용 예

- **분할 라벨 자동 생성:** "baby", "blanket"으로 마스크를 만들어 이불이 아기 몸의 몇 %를 덮는지 계산 → "얼굴 가림" 학습 데이터 제작
- **가림 증강 데이터 만들기:** 이불 마스크를 잘라 다른 아기 이미지에 붙여 가림 상황을 합성
- **주의:** 848M 파라미터라 맘캠 기기(모델 예산 15MB)에는 올릴 수 없다. **개발용 PC에서 데이터 만들 때만** 쓴다.

### 4-6. 장단점

| 장점 | 단점 |
|---|---|
| 단어 하나로 모든 물체를 정밀하게 분할 | 모델이 커서 GPU 필수, 기기 탑재 불가 |
| 영상 추적까지 한 번에 | 모델 파일 접근 승인 필요, 라이선스 조건 확인 필요 |

---

## 5. SigLIP / SigLIP 2

### 5-1. 무엇인가

Google이 만든 **이미지-텍스트 인코더**다. 이미지와 문장을 같은 숫자 공간(임베딩)에 놓아 "이 사진과 이 문장이 얼마나 어울리는가"를 점수로 낸다. CLIP과 비슷하지만, 학습할 때 소프트맥스 대신 **시그모이드 손실**을 써서 이미지-문장 쌍을 하나씩 독립적으로 판단한다. 그래서 결과가 "합이 1인 확률"이 아니라 **각 문장마다 따로 0~1 점수**로 나온다.

SigLIP 2는 여러 언어 지원을 넓히고, 분할·깊이 추정 같은 세밀한 작업 성능을 높였다.

### 5-2. 주요 기능

| 기능 | 설명 |
|---|---|
| 제로샷 분류 | 학습 없이 후보 문장 중 가장 맞는 것 고르기 |
| 이미지·텍스트 검색 | 문장으로 사진 찾기, 비슷한 사진 찾기 |
| 특징 추출기 | 다른 모델(분류기, VLM)의 이미지 인코더로 사용 |

- **모델 예:** `google/siglip2-base-patch16-224`, `google/siglip2-so400m-patch14-384`, `google/siglip2-base-patch16-naflex`(원본 비율 유지)
- **주의:** 소문자 텍스트로 학습돼 있어, 프로세서를 거치지 않으면 소문자 변환·길이 64 패딩을 직접 맞춰야 한다.

### 5-3. 사용 예시 코드

```python
from transformers import pipeline

clf = pipeline(task="zero-shot-image-classification",
               model="google/siglip2-base-patch16-224")

labels = ["a baby sleeping on its back",
          "a baby sleeping on its stomach",
          "an empty crib"]
print(clf("crib.jpg", candidate_labels=labels))
```

### 5-4. 일반 활용 예

- 쇼핑몰에서 "빨간 원피스" 문장으로 상품 사진 검색
- 사진 앨범 자동 분류 (음식, 풍경, 사람)
- 부적절한 이미지 걸러내기

### 5-5. 맘캠 활용 예

- **수집 데이터 정리:** 수천 장의 영상 프레임에서 "빈 침대", "보호자가 화면에 있음", "아기가 엎드림"에 가까운 장면을 문장으로 검색해 라벨링 우선순위를 정한다.
- **중복 프레임 제거:** 임베딩이 거의 같은 프레임을 묶어 비슷한 장면만 잔뜩 학습하는 것을 막는다.
- **주의:** 제로샷 분류 결과를 그대로 엎드림 판정에 쓰면 안 된다. 안전 판정은 학습·검증한 YOLO26n-pose로 하고, SigLIP은 **데이터 정리 도구**로 쓴다.

### 5-6. 장단점

| 장점 | 단점 |
|---|---|
| 학습 없이 문장만으로 분류·검색 | 위치(박스)는 알려 주지 않음 |
| 다른 모델의 인코더로 재사용 가능 | 세밀한 차이(엎드림 vs 옆으로)는 학습 모델보다 약함 |

---

## 6. OCR (광학 문자 인식) — PaddleOCR 중심

### 6-1. 무엇인가

OCR은 **이미지 속 글자를 찾아 텍스트로 바꾸는 기술**이다. 보통 ① 글자 영역 찾기(검출) → ② 글자 읽기(인식) 두 단계로 동작한다. 대표 오픈소스로 PaddleOCR, EasyOCR, Tesseract가 있고, 이 보고서는 기능이 가장 넓은 **PaddleOCR**를 기준으로 정리했다.

### 6-2. 주요 기능 (PaddleOCR 3.x)

| 구성 | 설명 |
|---|---|
| PP-OCR (v5·v6) | 일반 글자 검출·인식. PP-OCRv6는 tiny(1.5M)·small(7.7M)·medium(34.5M) 크기 제공 |
| PP-StructureV3 | 표·레이아웃이 있는 문서를 Markdown·JSON으로 변환 |
| PaddleOCR-VL | 0.9B 문서 이해용 VLM, 한국어 포함 109개 언어 지원 |

### 6-3. 사용 예시 코드

```python
from paddleocr import PaddleOCR

ocr = PaddleOCR(lang="korean")          # 한국어 인식 모델
result = ocr.predict("label.jpg")
for res in result:
    res.print()                         # 인식한 글자와 위치 출력
    res.save_to_img("output")           # 결과 그림 저장
    res.save_to_json("output")          # 결과 JSON 저장
```

`lang` 값은 공식 문서의 지원 언어 부록에서 정확한 이름을 확인한다.

### 6-4. 일반 활용 예

- 영수증·명함·신분증 정보 자동 입력
- 차량 번호판 인식
- 종이 문서 디지털화, 표 추출

### 6-5. 맘캠 활용 예

맘캠 카메라의 핵심 기능(자세·울음 감지)과는 **관련이 적다.** 보조 기능에는 쓸 수 있다.

- **보호자 앱의 수유 기록:** 분유통·이유식 라벨을 찍으면 제품명과 용량을 자동으로 기록
- **설치 도우미:** 카메라 밑면의 시리얼 번호를 찍어 기기 등록

### 6-6. 장단점

| 장점 | 단점 |
|---|---|
| 작은 모델(수 MB)도 있어 휴대폰에서 실행 가능 | 흐리거나 휘어진 글자, 손글씨에 약함 |
| 한국어 지원, 문서 구조까지 추출 | 맘캠 핵심 기능과의 관련성이 낮음 |

---

## 7. MediaPipe

### 7-1. 무엇인가

Google이 만든 **기기 안(온디바이스)에서 바로 돌리는 AI 작업 모음**이다. 학습된 모델과 실행 코드가 함께 제공돼, 몇 줄의 코드로 Android·iOS·Web·Python에서 실시간으로 쓸 수 있다.

### 7-2. 주요 기능 (MediaPipe Tasks)

| 분야 | 작업 |
|---|---|
| 비전 | 얼굴 검출, 얼굴 랜드마크, 손 랜드마크, 제스처 인식, **포즈 랜드마크**, 전신(홀리스틱) 랜드마크, 물체 검출, 이미지 분류·임베딩·분할, 대화형 분할 |
| 텍스트 | 언어 감지, 텍스트 분류·임베딩 등 |
| 오디오 | 오디오 분류 |
| 생성형 | LLM 추론 API |

- 물체 검출, 이미지 분류, 제스처 인식은 **내 데이터로 맞춤 학습**(Model Maker)도 가능하다.
- 예전 "Legacy Solutions"(구 `mp.solutions.pose` 등)는 2023년 3월 지원이 끝났다. 새 프로젝트는 **Tasks API**를 쓴다.

### 7-3. 사용 예시 코드 (포즈 랜드마크)

```python
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

options = vision.PoseLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_path="pose_landmarker_lite.task"))
detector = vision.PoseLandmarker.create_from_options(options)

image = mp.Image.create_from_file("person.jpg")
result = detector.detect(image)
for lm in result.pose_landmarks[0][:5]:      # 33개 관절 중 앞 5개 (코, 눈 주변)
    print(round(lm.x, 3), round(lm.y, 3), round(lm.visibility, 2))
```

`pose_landmarker_lite.task` 모델 파일은 MediaPipe 공식 페이지에서 내려받는다.

### 7-4. 일반 활용 예

- 홈트레이닝 앱의 운동 자세 교정, 횟수 세기
- 손동작으로 화면 조작, 수어 인식
- 화상회의 배경 흐림, 얼굴 필터

### 7-5. 맘캠 활용 예

- **빠른 시제품:** YOLO 학습 전에 MediaPipe 포즈로 "코·어깨가 보이는가"를 판정하는 규칙을 먼저 만들어, 전체 흐름(전처리 → 자세 → 5초 판정 → 경보)이 동작하는지 확인
- **보호자 앱 기능:** 휴대폰 카메라로 아기방을 비추면 카메라 설치 각도를 안내
- **주의:** MediaPipe 포즈 모델은 **성인 위주로 학습**돼 있어 속싸개를 한 영아, 밤 IR 영상에서는 정확도가 크게 떨어질 수 있다. 실제 제품의 엎드림 판정은 아기 데이터로 학습한 YOLO26n-pose를 쓴다.

### 7-6. 장단점

| 장점 | 단점 |
|---|---|
| 설치·사용이 매우 쉽고 모바일에서 실시간 | 제공된 모델 위주라 세부 조정 범위가 좁음 |
| Android·iOS·Web·Python 모두 지원 | 성인 기준 모델이라 영아·IR 영상에는 그대로 쓰기 어려움 |

---

## 8. 맘캠 개발에서의 역할 정리

| 단계 | 사용 모델 | 역할 | 기기 탑재 |
|---|---|---|---|
| 시제품 | MediaPipe | 자세 판정 흐름을 빠르게 검증 | ✕ (개발용) |
| 데이터 정리 | SigLIP 2 | 장면 검색, 중복 제거, 라벨링 우선순위 | ✕ |
| 자동 라벨링 | YOLOE, DINO-X(인형 데이터만), SAM 3 | 아기 박스·키포인트·이불 마스크 초안 생성 | ✕ |
| 데이터 증강 | SAM 3 | 이불 마스크로 가림 상황 합성 | ✕ |
| **제품 탑재** | **YOLO26n-pose (+ 오디오 CNN)** | 엎드림 의심 감지, 울음 감지 | **○** |
| 부가 기능 | YOLOE | 침대 위 베개·두꺼운 이불 안내 (선택) | △ (클래스 고정 후) |
| 보호자 앱 | OCR | 분유 라벨 기록, 기기 시리얼 등록 | 휴대폰 |

**결론:** 이번에 살펴본 큰 모델들(DINO-X, SAM 3, SigLIP 2)은 정확하고 기능이 많지만, 맘캠 기기(모델 예산 15MB, 저전력 NPU)에 올리기에는 너무 크거나 클라우드가 필요하다. 그래서 이 모델들은 **"좋은 학습 데이터를 빠르게 만드는 개발 도구"**로 쓰고, 기기에는 그 데이터로 학습한 **작은 YOLO26n-pose**를 올리는 구조가 맘캠에 가장 알맞다.

---

## 참고 자료

- Ultralytics, *YOLOE*: https://docs.ultralytics.com/models/yoloe/
- IDEA Research, *DINO-X API*: https://github.com/IDEA-Research/DINO-X-API
- Ren et al., *DINO-X: A Unified Vision Model for Open-World Object Detection and Understanding* (arXiv:2411.14347): https://arxiv.org/abs/2411.14347
- Meta, *SAM 3* 저장소: https://github.com/facebookresearch/sam3
- Meta AI 블로그, *Segment Anything Model 3*: https://ai.meta.com/blog/segment-anything-model-3/
- Hugging Face, *SigLIP2* 문서: https://huggingface.co/docs/transformers/model_doc/siglip2
- PaddleOCR 저장소: https://github.com/PaddlePaddle/PaddleOCR
- PaddleOCR, *General OCR Pipeline* 문서: https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html
- Google, *MediaPipe Solutions guide*: https://developers.google.com/edge/mediapipe/solutions/guide
