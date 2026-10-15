# 맘캠(MomCam) 추론 엔진 선정 보고서

- 작성자: 다혜
- 작성일: 2026-10-15
- 관련 문서: `report/model_yolo.md`(기기 탑재 모델), `report/hardware.md`(메인 SoC RV1106)

> **문서 상태:** 후보 4종(ONNX Runtime, NCNN, OpenVINO, TFLite(LiteRT)) 중 맘캠에 맞는 추론 엔진을 고른 **선정안**이다. 속도 수치는 아직 기기에서 재지 않았으며, 시제품에서 측정해 확인한다.

---

## 1. 결론

| 항목 | 결정 |
|---|---|
| **선택한 엔진** | **ONNX Runtime** (모델 형식은 ONNX) |
| 맡는 역할 | ① 학습한 모델의 표준 형식(ONNX)을 만들고, ② PC에서 정답 기준(FP32) 추론을 돌려 기기 모델의 정확도를 검증하는 **기준 엔진** |
| 기기에서 실제로 도는 것 | ONNX 모델을 Rockchip 도구(RKNN-Toolkit2)로 INT8 변환한 **RKNN 모델** → RV1106 NPU에서 실행 |
| 예비안 | NCNN (NPU 변환이 막힐 때 CPU로 돌리는 비상용) |
| 제외 | OpenVINO (Intel 하드웨어용), TFLite/LiteRT (RV1106 NPU로 가는 길이 돌아감) |

**한 줄 요약:** 맘캠의 두뇌인 RV1106 칩의 NPU는 Rockchip 전용 실행기(RKNN)만 쓸 수 있다. 그래서 4개 엔진 중 "NPU로 가는 길에 가장 잘 이어지는 것"을 골랐고, 그것이 **ONNX**다. Rockchip 공식 변환 도구와 예제가 ONNX를 입력으로 쓰고, ONNX Runtime으로 PC에서 같은 모델을 돌려 기기 결과가 맞는지 비교할 수 있다.

---

## 2. 먼저 알아야 할 점: 맘캠 칩의 NPU는 전용 실행기만 쓴다

`report/hardware.md`에서 메인 SoC로 **Rockchip RV1106**(Cortex-A7 CPU + NPU 약 0.5 TOPS)을 골랐다. 이 칩의 사정은 다음과 같다.

| 사실 | 맘캠에 주는 영향 |
|---|---|
| RV1106 NPU는 Rockchip의 **RKNN 형식**만 실행한다 | 후보 4개 엔진 중 어느 것도 이 NPU를 직접 쓰지 못한다 |
| RV1106은 **INT8 전용** NPU다 (FP16 불가) | 모델을 반드시 INT8로 양자화해야 한다 |
| 그래픽 칩(GPU)이 없고 CPU는 Cortex-A7(32비트)이다 | NPU 없이 CPU만으로 YOLO를 초당 5장 돌리기는 빠듯하다 |
| RKNN 모델은 x86 리눅스 PC의 **RKNN-Toolkit2**로 만든다 | 변환 도구에 넣을 "입력 형식"을 골라야 한다 |

그래서 이 보고서의 질문은 "어느 엔진이 기기에서 가장 빠른가"가 아니라 **"어느 엔진(형식)이 RKNN 변환과 검증에 가장 잘 맞는가"** 로 바뀐다.

---

## 3. 후보 4종 비교

### 3-1. 엔진별 특징

| 엔진 | 만든 곳 | 잘하는 것 | 모델 형식 |
|---|---|---|---|
| **ONNX Runtime** | Microsoft | 여러 프레임워크의 모델을 표준 형식 하나로 실행. PC·서버·모바일 모두 지원 | `.onnx` |
| **NCNN** | Tencent | ARM CPU(휴대폰·임베디드)에서 가볍고 빠름. 외부 라이브러리 의존 없음 | `.param` + `.bin` |
| **OpenVINO** | Intel | Intel CPU·내장 GPU·NPU에서 최적화된 추론 | `.xml` + `.bin` |
| **TFLite (LiteRT)** | Google | 안드로이드·마이크로컨트롤러용 경량 실행, 하드웨어 가속(델리게이트) | `.tflite` |

### 3-2. 맘캠 조건으로 평가

◎ 매우 적합 · ○ 적합 · △ 가능하지만 불리 · ✕ 부적합

| 평가 기준 | ONNX Runtime | NCNN | OpenVINO | TFLite (LiteRT) |
|---|:---:|:---:|:---:|:---:|
| ① RV1106 NPU로 이어지는 변환 경로 | ◎ RKNN-Toolkit2의 대표 입력 형식, 공식 예제가 ONNX | ✕ RKNN으로 변환 불가 | ✕ 변환 경로 없음 | △ 입력은 되지만 공식 예제가 적고, TF 양자화와 RKNN 양자화가 겹침 |
| ② YOLO26n-pose 내보내기 (Ultralytics) | ◎ 지원, NMS 없는 끝단 출력 그대로 | ○ 지원 | ○ 지원 | ○ 지원 |
| ③ 기기 정확도 검증 (PC 기준 결과) | ◎ 같은 ONNX를 PC에서 바로 실행해 비교 | △ 따로 변환한 모델이라 비교 기준이 달라짐 | △ 별도 변환 필요 | △ 별도 변환 필요 |
| ④ RV1106 CPU(Cortex-A7)에서 직접 실행 | △ 32비트 임베디드 리눅스에는 무겁다 | ◎ 가볍고 ARM NEON 최적화 | △ Intel 중심, ARM은 부가 지원 | ○ 가능하지만 NPU 가속은 없음 |
| ⑤ 학습·디버깅 도구 생태계 | ◎ Netron 시각화, onnxslim 정리, 양자화 도구 | ○ | ○ | ○ |
| **종합** | **선택** | 예비안 | 제외 | 제외 |

### 3-3. 고르지 않은 엔진의 이유

**OpenVINO — 제외**
Intel 칩에서 가장 좋은 성능을 내도록 만든 엔진이다. 맘캠은 Intel 칩을 쓰지 않고, RV1106 NPU로 가는 변환 경로도 없다. 장점을 하나도 살릴 수 없어서 제외했다.

**TFLite (LiteRT) — 제외 (`model_yolo.md` 계획에서 변경)**
처음 모델 보고서에서는 "LiteRT 등 NPU 벤더가 지원하는 형식"으로 내보내기로 했다. 그런데 RV1106은 LiteRT 델리게이트(가속기 연결 장치)가 없어서, LiteRT로는 NPU를 쓰지 못하고 CPU로만 돈다. RKNN-Toolkit2가 TFLite를 입력으로 받기는 하지만, 그러면 **TensorFlow에서 한 번, RKNN에서 또 한 번** 양자화하게 되어 정확도 손실 원인을 찾기 어려워진다. Rockchip 공식 YOLO 예제도 ONNX 기준이어서 ONNX로 바꿨다.

**NCNN — 예비안으로 보관**
ARM CPU에서는 4개 중 가장 가볍고 빠르다. 하지만 RV1106에서는 NPU를 쓰지 못하고, GPU가 없어 NCNN의 Vulkan(GPU) 가속도 쓸 수 없다. CPU만으로 YOLO를 돌리면 영상 압축·Wi-Fi·오디오 처리와 CPU를 나눠 써야 해서 초당 5장 목표가 위험하다. 대신 **NPU 변환이 막혔을 때 CPU로라도 경보 기능을 살리는 비상용**으로 남겨 둔다.

---

## 4. ONNX Runtime을 고른 이유

### 이유 1. NPU로 가는 가장 짧고 검증된 길이다

```
PyTorch(.pt) ──Ultralytics export──▶ ONNX(.onnx) ──RKNN-Toolkit2 (INT8)──▶ RKNN(.rknn) ──▶ RV1106 NPU
                                         │
                                         └── ONNX Runtime (PC): 정답 기준 결과
```

- Rockchip 공식 모델 모음(rknn_model_zoo)의 YOLO 예제는 모두 **ONNX를 입력**으로 받아 RKNN으로 변환한다.
- Ultralytics의 RKNN 내보내기도 내부에서 **ONNX를 먼저 만든 뒤** RKNN으로 바꾼다.
- 중간 형식이 ONNX 하나라서, 문제가 생기면 "학습 → ONNX" 구간인지 "ONNX → RKNN" 구간인지 바로 나눠 볼 수 있다.

### 이유 2. 자세(pose) 모델은 직접 변환해야 해서 ONNX가 필수다

Ultralytics 문서 기준으로 **RKNN INT8 내보내기는 현재 "검출(detect)" 모델만 지원**하고, RV1106은 INT8 전용 칩이다. 맘캠의 YOLO26n-pose는 자세 모델이므로 버튼 하나로 RKNN이 만들어지지 않는다. 따라서 **ONNX로 내보낸 뒤 RKNN-Toolkit2로 직접 양자화**하는 길을 가야 하고, 이 과정의 출발점이 ONNX다.

### 이유 3. 양자화 손실을 숫자로 검증할 수 있다

`model_yolo.md`의 기준은 "INT8로 바꿔도 **엎드림 재현율 하락이 1%p 이내**"다. 이걸 확인하려면 비교 기준이 필요하다.

| 단계 | 실행 엔진 | 확인하는 것 |
|---|---|---|
| ① FP32 기준 | ONNX Runtime (PC) | 원래 모델의 키포인트·자세 판정 결과 |
| ② INT8 시뮬레이션 | RKNN-Toolkit2 시뮬레이터 (PC) | 양자화만으로 생기는 오차 |
| ③ 실기기 | RKNN Runtime (RV1106 NPU) | 실제 칩에서의 결과와 속도 |

같은 ONNX 파일에서 시작하므로 ①과 ②·③을 같은 시험 이미지로 바로 비교할 수 있다. 차이가 크면 해당 층만 INT8에서 빼는 **혼합 양자화**(rknn_model_zoo의 hybrid quantization)로 고친다.

### 이유 4. 개발·시연 도구로도 그대로 쓴다

- PC나 노트북에서 ONNX Runtime으로 같은 모델을 돌려 **웹 데모, 데이터 라벨링 보조, 오탐 사례 재현**에 쓴다.
- 모델 구조를 Netron으로 열어 보고, onnxslim으로 불필요한 연산을 정리해 NPU 변환 성공률을 높일 수 있다.

---

## 5. 배포 흐름 (계획)

| 순서 | 작업 | 도구 | 결과물 |
|---|---|---|---|
| 1 | 아기 자세 데이터로 학습 | Ultralytics | `momcam_pose.pt` |
| 2 | ONNX로 내보내기 (입력 256×192, opset 19, 구조 정리) | Ultralytics + onnxslim | `momcam_pose.onnx` |
| 3 | PC에서 FP32 기준 결과 저장 | **ONNX Runtime** | 시험셋 키포인트·판정 결과 |
| 4 | INT8 양자화 (보정용 이미지: 밤 IR·낮 영상 골고루 약 300장) | RKNN-Toolkit2 (x86 리눅스) | `momcam_pose.rknn` |
| 5 | 시뮬레이터로 ③과 비교 → 재현율 하락 1%p 이내 확인 | RKNN-Toolkit2 + ONNX Runtime | 양자화 손실 보고 |
| 6 | 기기에서 실행·속도 측정 (목표: 초당 5장) | RKNN Runtime (C API) | 실측 속도, 전력 |

```python
from ultralytics import YOLO

model = YOLO("runs/stage2/weights/best.pt")
# 1) ONNX로 내보내기 (자세 모델은 RKNN INT8 직접 내보내기가 아직 안 되므로 ONNX를 거친다)
model.export(format="onnx", imgsz=(256, 192), opset=19, simplify=True)

# 2) PC에서 ONNX Runtime으로 기준 결과 확인
import onnxruntime as ort
sess = ort.InferenceSession("best.onnx", providers=["CPUExecutionProvider"])
```

```python
# 3) RKNN-Toolkit2로 RV1106용 INT8 변환 (x86 리눅스 PC)
from rknn.api import RKNN

rknn = RKNN()
rknn.config(mean_values=[[0, 0, 0]], std_values=[[255, 255, 255]], target_platform="rv1106")
rknn.load_onnx(model="best.onnx")
rknn.build(do_quantization=True, dataset="calib_images.txt")  # 보정용 이미지 목록
rknn.export_rknn("momcam_pose.rknn")
```

---

## 6. 위험 요소와 대책

| 위험 | 내용 | 대책 |
|---|---|---|
| **RV1106에서 자세 모델 미검증** | Rockchip 공식 자세 예제(yolov8_pose)의 지원 칩 목록에 RV1106이 없다 | 시제품 1단계에서 변환·실행부터 확인. 안 되면 ① 키포인트 해석(후처리)만 CPU로 옮기고, ② 그래도 안 되면 FP16도 되는 상위 칩(RV1126B)으로 바꾸는 것을 검토 |
| 지원 안 되는 연산 | NPU가 모르는 연산이 있으면 그 부분은 CPU로 넘어가 느려진다 | 변환 로그 확인, onnxslim 정리, 해당 연산을 같은 의미의 단순 연산으로 바꿈 |
| 양자화 정확도 하락 | 밤 IR 영상처럼 어두운 입력에서 INT8 오차가 커질 수 있다 | 보정용 이미지에 밤 IR 영상을 충분히 넣고, 혼합 양자화 적용 |
| 메모리 부족 | RV1106은 내장 메모리가 작다 | 입력 256×192 유지, 오디오 모델과 실행 시간 나누기 |
| 버전 불일치 | 변환 도구와 기기 실행 라이브러리 버전이 다르면 실행 실패 | RKNN-Toolkit2와 기기의 `librknnmrt` 버전을 맞춰 기록 |

---

## 7. 다음 단계

1. YOLO26n-pose(COCO 사전학습)를 ONNX로 내보내 RV1106용 RKNN 변환이 되는지 먼저 시험한다.
2. ONNX Runtime(FP32)과 RKNN(INT8) 결과를 같은 시험 이미지 100장으로 비교해 키포인트 오차를 잰다.
3. RV1106 개발 보드에서 초당 처리 장수와 전력을 실측해 `report/hardware.md`의 전력 예산과 `report/model_yolo.md`의 기기 실측 항목을 채운다.
4. NPU 실행이 막히면 NCNN으로 CPU 실행 속도를 재서 비상용으로 쓸 수 있는지 판단한다.

> **참고 자료:** Ultralytics 문서 "Rockchip RKNN Export"(RV1106은 INT8 전용, INT8 내보내기는 검출 모델만 지원), Rockchip rknn_model_zoo `examples/yolov8_pose`(ONNX → RKNN 변환 예제, 지원 칩 목록).
