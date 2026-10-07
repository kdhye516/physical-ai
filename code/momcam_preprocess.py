"""
맘캠(MomCam) 데이터 전처리 파이프라인
=====================================

report/preprocessing.md 에 설계한 순서를 그대로 코드로 옮겼다.

  영상:  샘플링 → 품질 검사 → 마스킹 → 왜곡 보정 → ROI 크롭 → 리사이즈
         → 그레이스케일 → 노이즈 제거 → CLAHE → 정규화 → (AI 판단) → 5초 지속 판정
  오디오: 리샘플링 → 고역통과 → 소음 억제 → 음량 정규화 → 에너지 게이트
         → 멜 스펙트로그램 → 정규화 → (AI 판단) → 지속 시간 판정

필요한 라이브러리:  pip install numpy opencv-python scipy

실행 방법:
  python momcam_preprocess.py                      # 가상 데이터로 전체 흐름 시연
  python momcam_preprocess.py --video night.mp4    # 내 영상 파일로 실행
  python momcam_preprocess.py --audio cry.wav      # 내 오디오 파일로 실행
  python momcam_preprocess.py --save-preview out   # 단계별 결과 이미지를 out 폴더에 저장

※ 맘캠은 보조 모니터링 기기이며 의료기기가 아니다. 이 코드는 학습·실험용이다.
"""

from __future__ import annotations

import argparse
import os
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np
from scipy.signal import butter, resample_poly, sosfilt, sosfilt_zi


# ============================================================================
# 1. 설정값 (preprocessing.md 의 "초기값" 열)
# ============================================================================

@dataclass
class VideoConfig:
    input_fps: int = 15
    target_fps: int = 5                    # ① 15fps → 5fps
    blur_threshold: float = 50.0           # ② 라플라시안 분산이 이보다 작으면 흐림
    saturation_ratio: float = 0.15         # ② 포화 화소(≥250) 비율이 이보다 크면 반사
    roi_margin: float = 0.10               # ⑤ 침대 영역 + 사방 10%
    out_w: int = 256                       # ⑥ 레터박스 크기
    out_h: int = 192
    pad_value: int = 114
    median_ksize: int = 3                  # ⑧ 3×3 메디안
    clahe_clip: float = 2.0                # ⑨ CLAHE
    clahe_tile: int = 8
    norm_mean: float = 0.45                # ⑩ 학습 데이터 평균·표준편차 (학습 후 실제 값으로 교체)
    norm_std: float = 0.25


@dataclass
class PostureDecisionConfig:
    ema_alpha: float = 0.5                 # ⑪ EMA 평활
    on_threshold: float = 0.7              # 확률 0.7 이상이
    window_sec: float = 5.0                # 5초 중
    min_on_sec: float = 4.0                # 4초 이상이면 경보
    off_threshold: float = 0.4             # 0.4 미만이면 해제


@dataclass
class AudioConfig:
    sample_rate: int = 16000               # ① 16kHz 모노
    hpf_cutoff: float = 100.0              # ② 2차 버터워스 100Hz
    hpf_order: int = 2
    win_ms: float = 25.0                   # ⑥ 창 25ms
    hop_ms: float = 10.0                   #    홉 10ms
    n_fft: int = 512
    n_mels: int = 64
    fmin: float = 50.0
    fmax: float = 8000.0
    patch_frames: int = 96                 #    0.96초 분석 창
    patch_hop: int = 48                    #    50% 겹침
    noise_window_sec: float = 3.0          # ③ 최근 3초 최소 에너지
    gate_margin_db: float = 6.0            # ③ 소음 기준 + 6dB 아래는 감쇠
    max_atten_db: float = 12.0             # ③ 최대 −12dB
    target_dbfs: float = -20.0             # ④ AGC 목표
    max_gain_db: float = 12.0              # ④ 최대 이득 +12dB
    energy_gate_db: float = 10.0           # ⑤ 소음 기준 + 10dB 이상일 때만 분석


@dataclass
class CryDecisionConfig:
    median_len: int = 3                    # ⑧ 3구간 중앙값
    threshold: float = 0.6                 #    확률 0.6 이상이
    min_duration_sec: float = 10.0         #    10초 이상이면 알림


# ============================================================================
# 2. 영상 전처리
# ============================================================================

@dataclass
class FrameResult:
    ok: bool                               # 모델에 넣을 수 있는 프레임인지
    reason: str                            # 건너뛴 이유 ("sampled_out", "blur", "glare", "ok")
    tensor: np.ndarray | None = None       # (1, H, W) float32, 모델 입력
    debug: dict = field(default_factory=dict)  # 단계별 중간 결과 (미리보기용)


class VideoPreprocessor:
    """영상 프레임을 한 장씩 받아 모델 입력으로 바꾼다."""

    def __init__(
        self,
        frame_size: tuple[int, int],                       # (width, height) 원본 해상도
        bed_roi: tuple[int, int, int, int],                # 보정된 화면 기준 침대 영역 (x, y, w, h)
        privacy_polygons: list[np.ndarray] | None = None,  # 원본 화면 기준 가림 영역 다각형 목록
        camera_matrix: np.ndarray | None = None,           # 캘리브레이션 결과 (없으면 왜곡 보정 생략)
        dist_coeffs: np.ndarray | None = None,
        cfg: VideoConfig | None = None,
        keep_debug: bool = False,
    ):
        self.cfg = cfg or VideoConfig()
        self.w, self.h = frame_size
        self.keep_debug = keep_debug
        self.step = max(1, round(self.cfg.input_fps / self.cfg.target_fps))
        self.frame_idx = -1

        # ③ 가림 영역 마스크: 설치할 때 한 번만 만든다
        self.privacy_mask = None
        if privacy_polygons:
            mask = np.full((self.h, self.w), 255, np.uint8)
            cv2.fillPoly(mask, [p.astype(np.int32) for p in privacy_polygons], 0)
            self.privacy_mask = mask

        # ④ 왜곡 보정 변환표: 매 프레임 계산하지 않도록 미리 한 번만 만든다
        self.undistort_maps = None
        if camera_matrix is not None and dist_coeffs is not None:
            self.undistort_maps = cv2.initUndistortRectifyMap(
                camera_matrix, dist_coeffs, None, camera_matrix, (self.w, self.h), cv2.CV_16SC2
            )

        # ⑤ ROI에 여유를 더하고 화면 밖으로 나가지 않게 자른다
        x, y, rw, rh = bed_roi
        mx, my = int(rw * self.cfg.roi_margin), int(rh * self.cfg.roi_margin)
        x0, y0 = max(0, x - mx), max(0, y - my)
        x1, y1 = min(self.w, x + rw + mx), min(self.h, y + rh + my)
        self.roi = (x0, y0, x1, y1)

        # ⑨ CLAHE 객체도 한 번만 만든다
        self.clahe = cv2.createCLAHE(
            clipLimit=self.cfg.clahe_clip, tileGridSize=(self.cfg.clahe_tile, self.cfg.clahe_tile)
        )

    # ---- 개별 단계 -------------------------------------------------------

    def sample(self) -> bool:
        """① 프레임 샘플링: 15fps 중 3장마다 1장만 분석 (5fps)."""
        self.frame_idx += 1
        return self.frame_idx % self.step == 0

    def quality_check(self, frame: np.ndarray) -> str:
        """② 품질 검사: 작은 크기로 줄여 흐림·반사를 빠르게 판정."""
        small = cv2.resize(frame, (160, int(160 * self.h / self.w)), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
        if cv2.Laplacian(gray, cv2.CV_64F).var() < self.cfg.blur_threshold:
            return "blur"                      # 김서림·렌즈 오염
        if np.mean(gray >= 250) > self.cfg.saturation_ratio:
            return "glare"                     # IR 빛 반사로 하얗게 날아감
        return "ok"

    def apply_privacy_mask(self, frame: np.ndarray) -> np.ndarray:
        """③ 사생활 보호 마스킹: 가림 영역을 0으로 채운다. 가장 먼저 해야 한다."""
        if self.privacy_mask is None:
            return frame
        return cv2.bitwise_and(frame, frame, mask=self.privacy_mask)

    def undistort(self, frame: np.ndarray) -> np.ndarray:
        """④ 렌즈 왜곡 보정: 미리 만든 변환표로 remap (빠름)."""
        if self.undistort_maps is None:
            return frame
        return cv2.remap(frame, *self.undistort_maps, interpolation=cv2.INTER_LINEAR)

    def crop_roi(self, frame: np.ndarray) -> np.ndarray:
        """⑤ 침대 영역 크롭: 보정된 화면 좌표 기준."""
        x0, y0, x1, y1 = self.roi
        return frame[y0:y1, x0:x1]

    def letterbox(self, frame: np.ndarray) -> np.ndarray:
        """⑥ 비율 유지 리사이즈: 남는 곳은 회색(114)으로 채운다."""
        h, w = frame.shape[:2]
        scale = min(self.cfg.out_w / w, self.cfg.out_h / h)
        nw, nh = int(round(w * scale)), int(round(h * scale))
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
        shape = (self.cfg.out_h, self.cfg.out_w) + resized.shape[2:]
        canvas = np.full(shape, self.cfg.pad_value, np.uint8)
        top, left = (self.cfg.out_h - nh) // 2, (self.cfg.out_w - nw) // 2
        canvas[top:top + nh, left:left + nw] = resized
        return canvas

    @staticmethod
    def to_gray(frame: np.ndarray) -> np.ndarray:
        """⑦ 그레이스케일: 밝기(Y) 채널만 써서 수유등 색 편향을 없앤다."""
        if frame.ndim == 2:
            return frame
        return cv2.cvtColor(frame, cv2.COLOR_BGR2YUV)[:, :, 0]

    def denoise(self, gray: np.ndarray) -> np.ndarray:
        """⑧ 노이즈 제거: 3×3 메디안 (ISP 3D 노이즈 감소가 있으면 이 단계는 생략 가능)."""
        return cv2.medianBlur(gray, self.cfg.median_ksize)

    def enhance_contrast(self, gray: np.ndarray) -> np.ndarray:
        """⑨ 대비 보정: CLAHE. 노이즈 제거 뒤에 해야 노이즈가 커지지 않는다."""
        return self.clahe.apply(gray)

    def normalize(self, gray: np.ndarray) -> np.ndarray:
        """⑩ 정규화: 학습 때와 같은 평균·표준편차. 항상 마지막 단계."""
        x = gray.astype(np.float32) / 255.0
        x = (x - self.cfg.norm_mean) / self.cfg.norm_std
        return x[None, :, :]                   # (1, H, W)

    # ---- 전체 파이프라인 ------------------------------------------------

    def process(self, frame: np.ndarray) -> FrameResult:
        if not self.sample():
            return FrameResult(False, "sampled_out")

        quality = self.quality_check(frame)
        if quality != "ok":
            return FrameResult(False, quality)  # 판정 단계에서 "확인 필요"로 처리

        debug = {}
        x = self.apply_privacy_mask(frame); debug["3_mask"] = x
        x = self.undistort(x);              debug["4_undistort"] = x
        x = self.crop_roi(x);               debug["5_roi"] = x
        x = self.letterbox(x);              debug["6_letterbox"] = x
        x = self.to_gray(x);                debug["7_gray"] = x
        x = self.denoise(x);                debug["8_denoise"] = x
        x = self.enhance_contrast(x);       debug["9_clahe"] = x
        tensor = self.normalize(x)

        return FrameResult(True, "ok", tensor, debug if self.keep_debug else {})


class PostureDecision:
    """⑪ 모델이 낸 '엎드림 확률'을 평활하고, 5초 지속 여부로 경보를 판정한다.
    시간 평활은 입력 영상이 아니라 모델 결과에만 적용한다."""

    def __init__(self, fps: int = 5, cfg: PostureDecisionConfig | None = None):
        self.cfg = cfg or PostureDecisionConfig()
        self.window = deque(maxlen=int(self.cfg.window_sec * fps))
        self.min_on = int(self.cfg.min_on_sec * fps)
        self.ema = None
        self.alarm = False

    def update(self, prone_prob: float | None) -> dict:
        # 품질 불량 프레임(None)은 판단 보류: "확인 필요" 상태로 알린다
        if prone_prob is None:
            return {"state": "확인 필요", "alarm": self.alarm, "ema": self.ema}

        self.ema = prone_prob if self.ema is None else (
            self.cfg.ema_alpha * prone_prob + (1 - self.cfg.ema_alpha) * self.ema
        )
        self.window.append(self.ema >= self.cfg.on_threshold)

        if not self.alarm and sum(self.window) >= self.min_on:
            self.alarm = True                  # 5초 중 4초 이상 → 경보
        elif self.alarm and self.ema < self.cfg.off_threshold:
            self.alarm = False                 # 히스테리시스: 0.4 미만이어야 해제
            self.window.clear()

        state = "엎드림 의심 경보" if self.alarm else ("관찰 중" if self.ema >= self.cfg.on_threshold else "정상")
        return {"state": state, "alarm": self.alarm, "ema": round(self.ema, 3)}


# ============================================================================
# 3. 오디오 전처리
# ============================================================================

def mel_filterbank(sr: int, n_fft: int, n_mels: int, fmin: float, fmax: float) -> np.ndarray:
    """HTK 방식 멜 필터뱅크 (librosa 없이 numpy로 계산)."""
    def hz_to_mel(f): return 2595.0 * np.log10(1.0 + f / 700.0)
    def mel_to_hz(m): return 700.0 * (10 ** (m / 2595.0) - 1.0)

    mels = np.linspace(hz_to_mel(fmin), hz_to_mel(min(fmax, sr / 2)), n_mels + 2)
    hz = mel_to_hz(mels)
    bins = np.fft.rfftfreq(n_fft, 1.0 / sr)
    fb = np.zeros((n_mels, len(bins)), np.float32)
    for m in range(1, n_mels + 1):
        left, center, right = hz[m - 1], hz[m], hz[m + 1]
        up = (bins - left) / (center - left)
        down = (right - bins) / (right - center)
        fb[m - 1] = np.maximum(0, np.minimum(up, down))
    return fb


class AudioPreprocessor:
    """마이크 소리를 조각(chunk) 단위로 받아 로그 멜 패치(0.96초)로 바꾼다.
    실시간 스트림처럼 필터 상태와 소음 기준을 계속 이어서 유지한다."""

    def __init__(self, input_sr: int, cfg: AudioConfig | None = None,
                 feat_mean: np.ndarray | None = None, feat_std: np.ndarray | None = None):
        self.cfg = cfg or AudioConfig()
        c = self.cfg
        self.input_sr = input_sr
        self.win = int(c.sample_rate * c.win_ms / 1000)          # 400 샘플
        self.hop = int(c.sample_rate * c.hop_ms / 1000)          # 160 샘플
        self.window_fn = np.hanning(self.win).astype(np.float32)
        self.mel_fb = mel_filterbank(c.sample_rate, c.n_fft, c.n_mels, c.fmin, c.fmax)

        # ② 고역통과 필터 (상태를 유지해 조각 경계에서 끊김이 없게)
        self.sos = butter(c.hpf_order, c.hpf_cutoff, btype="highpass", fs=c.sample_rate, output="sos")
        self.zi = sosfilt_zi(self.sos) * 0.0

        # ③ 소음 기준: 최근 3초 동안의 프레임별 파워 스펙트럼
        self.noise_hist = deque(maxlen=int(c.noise_window_sec * 1000 / c.hop_ms))
        self.noise_floor = None

        # ⑦ 학습 데이터에서 구한 고정 정규화 값 (없으면 임시값)
        self.feat_mean = feat_mean if feat_mean is not None else np.full(c.n_mels, -6.0, np.float32)
        self.feat_std = feat_std if feat_std is not None else np.full(c.n_mels, 3.0, np.float32)

        self.buffer = np.zeros(0, np.float32)    # 프레임으로 나누고 남은 샘플
        self.mel_frames: list[np.ndarray] = []   # 패치를 만들기 위해 모아두는 멜 프레임
        self.active_frames: list[bool] = []

    # ---- 개별 단계 -------------------------------------------------------

    def resample(self, x: np.ndarray) -> np.ndarray:
        """① 리샘플링: 스테레오면 모노로 합치고 16kHz로 변환."""
        if x.ndim == 2:
            x = x.mean(axis=1)
        x = x.astype(np.float32)
        if np.abs(x).max(initial=0) > 1.5:     # int16 범위면 −1~1로
            x = x / 32768.0
        if self.input_sr != self.cfg.sample_rate:
            g = np.gcd(self.input_sr, self.cfg.sample_rate)
            x = resample_poly(x, self.cfg.sample_rate // g, self.input_sr // g).astype(np.float32)
        return x

    def highpass(self, x: np.ndarray) -> np.ndarray:
        """② 고역통과 100Hz: 에어컨·가습기 저음 제거. DC 성분도 함께 사라진다."""
        y, self.zi = sosfilt(self.sos, x, zi=self.zi)
        return y.astype(np.float32)

    def frames(self, x: np.ndarray) -> np.ndarray:
        """25ms 창, 10ms 홉으로 자르고 파워 스펙트럼을 구한다."""
        self.buffer = np.concatenate([self.buffer, x])
        n = 0 if len(self.buffer) < self.win else 1 + (len(self.buffer) - self.win) // self.hop
        if n == 0:
            return np.zeros((0, self.cfg.n_fft // 2 + 1), np.float32)
        idx = np.arange(self.win)[None, :] + self.hop * np.arange(n)[:, None]
        fr = self.buffer[idx] * self.window_fn
        self.buffer = self.buffer[n * self.hop:]
        spec = np.fft.rfft(fr, n=self.cfg.n_fft, axis=1)
        return (np.abs(spec) ** 2).astype(np.float32)

    def update_noise_floor(self, power: np.ndarray, active: np.ndarray):
        """③-a 소음 기준 추정: 울음이 아닌(조용한) 프레임만으로 최근 3초 최소값을 추적."""
        for p, a in zip(power, active):
            if not a or self.noise_floor is None:
                self.noise_hist.append(p)
        if self.noise_hist:
            self.noise_floor = np.min(np.stack(self.noise_hist), axis=0) + 1e-10

    def spectral_gate(self, power: np.ndarray) -> np.ndarray:
        """③-b 스펙트럼 게이팅: 소음 기준 + 6dB 아래 성분을 최대 −12dB 감쇠."""
        c = self.cfg
        thresh = self.noise_floor * 10 ** (c.gate_margin_db / 10)
        atten = 10 ** (-c.max_atten_db / 10)
        return np.where(power < thresh, power * atten, power)

    def agc(self, power: np.ndarray) -> np.ndarray:
        """④ 음량 정규화: 조각 전체 RMS를 −20dBFS로, 단 이득은 최대 +12dB까지만."""
        c = self.cfg
        rms = np.sqrt(power.sum(axis=1).mean() / (self.cfg.n_fft * self.window_fn.sum() ** 2 / self.win) + 1e-12)
        gain_db = np.clip(c.target_dbfs - 20 * np.log10(rms + 1e-12), -40.0, c.max_gain_db)
        return power * (10 ** (gain_db / 10))

    def energy_gate(self, power: np.ndarray) -> np.ndarray:
        """⑤ 에너지 게이트: 소음 기준 + 10dB 넘는 프레임만 '활성'. 조용하면 모델을 쉬게 한다."""
        if self.noise_floor is None:
            return np.ones(len(power), bool)
        frame_e = 10 * np.log10(power.sum(axis=1) + 1e-10)
        floor_e = 10 * np.log10(self.noise_floor.sum() + 1e-10)
        return frame_e > floor_e + self.cfg.energy_gate_db

    def log_mel(self, power: np.ndarray) -> np.ndarray:
        """⑥ 로그 멜 스펙트로그램 (64 멜)."""
        return np.log(power @ self.mel_fb.T + 1e-6).astype(np.float32)

    def normalize(self, mel: np.ndarray) -> np.ndarray:
        """⑦ 특징 정규화: 학습 데이터 기준 고정값 (클립마다 따로 하지 않는다)."""
        return (mel - self.feat_mean) / self.feat_std

    # ---- 전체 파이프라인 ------------------------------------------------

    def process(self, chunk: np.ndarray) -> list[dict]:
        """소리 조각을 넣으면 완성된 0.96초 패치 목록을 돌려준다.
        각 패치: {"features": (1, 96, 64), "active": 분석할 가치가 있는지}"""
        x = self.resample(chunk)
        x = self.highpass(x)
        power = self.frames(x)
        if len(power) == 0:
            return []

        active = self.energy_gate(power)        # 판정은 억제 전 원래 크기로
        self.update_noise_floor(power, active)
        power = self.spectral_gate(power)
        power = self.agc(power)
        mel = self.normalize(self.log_mel(power))

        self.mel_frames.extend(mel)
        self.active_frames.extend(active.tolist())
        out = []
        c = self.cfg
        while len(self.mel_frames) >= c.patch_frames:
            patch = np.stack(self.mel_frames[:c.patch_frames])
            act = np.mean(self.active_frames[:c.patch_frames]) > 0.2
            out.append({"features": patch[None, :, :], "active": bool(act)})
            self.mel_frames = self.mel_frames[c.patch_hop:]
            self.active_frames = self.active_frames[c.patch_hop:]
        return out


class CryDecision:
    """⑧ 울음 확률을 3구간 중앙값으로 평활하고, 10초 이상 이어질 때만 알린다."""

    def __init__(self, patch_hop_sec: float = 0.48, cfg: CryDecisionConfig | None = None):
        self.cfg = cfg or CryDecisionConfig()
        self.hist = deque(maxlen=self.cfg.median_len)
        self.patch_hop_sec = patch_hop_sec
        self.cry_sec = 0.0
        self.notified = False

    def update(self, cry_prob: float) -> dict:
        self.hist.append(cry_prob)
        smooth = float(np.median(self.hist))
        if smooth >= self.cfg.threshold:
            self.cry_sec += self.patch_hop_sec
        else:
            self.cry_sec, self.notified = 0.0, False
        notify = self.cry_sec >= self.cfg.min_duration_sec and not self.notified
        if notify:
            self.notified = True               # 한 번 울음에 알림은 한 번만
        state = "울음 알림" if notify else ("울음 지속 중" if self.cry_sec > 0 else "조용함")
        return {"state": state, "notify": notify, "smooth": round(smooth, 3), "cry_sec": round(self.cry_sec, 2)}


# ============================================================================
# 4. 시연용 가상 데이터와 임시 모델
#    실제 모델이 준비되면 dummy_*_model 함수를 교체한다.
# ============================================================================

def synthetic_ir_frame(w: int, h: int, t: float, prone: bool, rng: np.random.Generator) -> np.ndarray:
    """밤 IR 화면을 흉내 낸 가상 프레임 (노이즈 + 침대 + 아기)."""
    img = np.full((h, w, 3), 40, np.uint8)
    cv2.rectangle(img, (int(w * .25), int(h * .15)), (int(w * .75), int(h * .9)), (70, 70, 70), -1)
    for yy in range(int(h * .15), int(h * .9), 18):            # 잔무늬 시트
        cv2.line(img, (int(w * .25), yy), (int(w * .75), yy), (80, 80, 80), 2)
    cx, cy = int(w * .5), int(h * .55)
    cv2.ellipse(img, (cx, cy), (int(w * .07), int(h * .18)), 15 if prone else 0, 0, 360, (105, 105, 105), -1)
    head = (150, 150, 150) if not prone else (95, 95, 95)       # 엎드리면 얼굴이 안 보여 어둡게
    cv2.circle(img, (cx, int(h * .33)), int(h * .06), head, -1)
    cv2.rectangle(img, (int(w * .82), int(h * .55)), (w - 10, h - 10), (200, 200, 200), -1)  # 부모 침대
    noise = rng.normal(0, 12, img.shape)                        # IR 센서 노이즈
    return np.clip(img + noise, 0, 255).astype(np.uint8)


def dummy_posture_model(tensor: np.ndarray) -> float:
    """임시 모델: 얼굴이 보이면 머리가 몸보다 밝고, 엎드리면 어둡다는 점만 이용한다.
    실제로는 학습한 자세 인식 모델로 교체해야 한다."""
    img = tensor[0]
    h, w = img.shape
    head = img[int(h * .22):int(h * .32), int(w * .46):int(w * .54)].mean()
    body = img[int(h * .45):int(h * .65), int(w * .44):int(w * .56)].mean()
    return float(1 / (1 + np.exp(6 * (head - body))))


def synthetic_audio(sr: int, sec: float, cry_from: float, cry_to: float, rng: np.random.Generator) -> np.ndarray:
    """백색소음기 + 에어컨 저음 위에 아기 울음(450Hz 배음)을 섞은 가상 소리."""
    t = np.arange(int(sr * sec)) / sr
    x = 0.02 * rng.standard_normal(len(t))                      # 백색소음기
    x += 0.05 * np.sin(2 * np.pi * 60 * t)                      # 에어컨 웅웅거림
    cry = sum(np.sin(2 * np.pi * 450 * k * t * (1 + 0.03 * np.sin(2 * np.pi * 3 * t))) / k for k in range(1, 6))
    env = ((t >= cry_from) & (t < cry_to)) * (0.5 + 0.5 * np.abs(np.sin(2 * np.pi * 0.8 * t)))
    return (x + 0.15 * cry * env).astype(np.float32)


def dummy_cry_model(features: np.ndarray) -> float:
    """임시 모델: 울음처럼 배음이 뚜렷하면(멜 대역 간 대비가 크면) 울음 확률을 높게 낸다.
    백색소음처럼 평평한 소리는 대비가 작다. 실제 학습 모델로 교체할 것."""
    f = features[0]
    contrast = (f.max(axis=1) - np.median(f, axis=1)).mean()
    return float(1 / (1 + np.exp(-4 * (contrast - 1.2))))


# ============================================================================
# 5. 실행
# ============================================================================

def run_video(path: str | None, preview_dir: str | None):
    print("\n[영상 파이프라인]")
    rng = np.random.default_rng(0)
    cap = cv2.VideoCapture(path) if path else None
    if cap is not None and not cap.isOpened():
        raise SystemExit(f"영상을 열 수 없습니다: {path}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if cap else 1920
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if cap else 1080
    fps = int(round(cap.get(cv2.CAP_PROP_FPS))) if cap else 15

    # 설치할 때 앱에서 지정하는 값 (여기서는 예시)
    bed_roi = (int(w * .25), int(h * .15), int(w * .5), int(h * .75))
    privacy = [np.array([[w * .80, h * .5], [w, h * .5], [w, h], [w * .80, h]])]
    K = np.array([[w * .9, 0, w / 2], [0, w * .9, h / 2], [0, 0, 1]], np.float64)  # 캘리브레이션 결과로 교체
    D = np.array([-0.12, 0.03, 0, 0, 0], np.float64)

    pre = VideoPreprocessor((w, h), bed_roi, privacy, K, D,
                            VideoConfig(input_fps=fps), keep_debug=bool(preview_dir))
    decide = PostureDecision(fps=pre.cfg.target_fps)
    counts = {"ok": 0, "sampled_out": 0, "blur": 0, "glare": 0}

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if cap else fps * 16
    last_state = None
    for i in range(total):
        if cap:
            ok, frame = cap.read()
            if not ok:
                break
        else:                                   # 4~12초 구간에 엎드림 상황을 만든다
            frame = synthetic_ir_frame(w, h, i / fps, prone=4 <= i / fps < 12, rng=rng)

        r = pre.process(frame)
        counts[r.reason] = counts.get(r.reason, 0) + 1
        if r.reason == "sampled_out":
            continue
        prob = dummy_posture_model(r.tensor) if r.ok else None
        d = decide.update(prob)
        if d["state"] != last_state:
            print(f"  {i / fps:5.1f}초  상태: {d['state']:<10}  평활 확률: {d['ema']}")
            last_state = d["state"]

        if preview_dir and r.ok and counts["ok"] == 1:
            os.makedirs(preview_dir, exist_ok=True)
            cv2.imwrite(os.path.join(preview_dir, "0_original.png"), frame)
            for name, img in r.debug.items():
                cv2.imwrite(os.path.join(preview_dir, f"{name}.png"), img)
            print(f"  단계별 미리보기 이미지를 '{preview_dir}' 폴더에 저장했습니다.")

    print(f"  프레임 처리 결과: {counts}")
    print(f"  모델 입력 크기: (1, {pre.cfg.out_h}, {pre.cfg.out_w})")


def run_audio(path: str | None):
    print("\n[오디오 파이프라인]")
    rng = np.random.default_rng(1)
    if path:
        from scipy.io import wavfile
        sr, audio = wavfile.read(path)
    else:                                       # 3~18초 구간에 울음을 넣은 25초 가상 소리
        sr, audio = 44100, synthetic_audio(44100, 25, 3, 18, rng)

    pre = AudioPreprocessor(sr)
    decide = CryDecision(patch_hop_sec=pre.cfg.patch_hop * pre.cfg.hop_ms / 1000)
    chunk = sr // 2                             # 0.5초씩 실시간처럼 흘려보낸다
    n_patch, n_active, last_state = 0, 0, None
    for start in range(0, len(audio), chunk):
        for patch in pre.process(audio[start:start + chunk]):
            n_patch += 1
            t = n_patch * decide.patch_hop_sec
            if not patch["active"]:             # ⑤ 조용하면 모델을 돌리지 않는다
                d = decide.update(0.0)
            else:
                n_active += 1
                d = decide.update(dummy_cry_model(patch["features"]))
            if d["state"] != last_state:
                print(f"  {t:5.1f}초  상태: {d['state']:<8}  평활 확률: {d['smooth']}  지속: {d['cry_sec']}초")
                last_state = d["state"]
    print(f"  0.96초 패치 {n_patch}개 중 모델 실행 {n_active}개 (나머지는 에너지 게이트로 생략)")
    print(f"  모델 입력 크기: (1, {pre.cfg.patch_frames}, {pre.cfg.n_mels})")


def main():
    ap = argparse.ArgumentParser(description="맘캠 전처리 파이프라인")
    ap.add_argument("--video", help="분석할 영상 파일 (없으면 가상 데이터)")
    ap.add_argument("--audio", help="분석할 WAV 파일 (없으면 가상 데이터)")
    ap.add_argument("--save-preview", metavar="DIR", help="영상 단계별 결과 이미지를 저장할 폴더")
    args = ap.parse_args()

    run_video(args.video, args.save_preview)
    run_audio(args.audio)
    print("\n※ 임시 모델(dummy_*_model)을 쓴 시연입니다. 실제 학습 모델로 교체해야 합니다.")


if __name__ == "__main__":
    main()
