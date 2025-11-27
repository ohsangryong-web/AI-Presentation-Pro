import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import simpledialog 
import cv2
from PIL import Image, ImageTk
import threading
import time
import numpy as np

# [중요] 반드시 다른 matplotlib import보다 위에 있어야 함
import matplotlib
matplotlib.use('TkAgg') 
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import random
import os
import json
import re
import pyaudio
import wave
import audioop
import sys
import queue
import contextlib 
import difflib 
import math 

# [필수] MediaPipe
import mediapipe as mp

# [필수] Whisper (고성능 분석)
from faster_whisper import WhisperModel

# [필수] Vosk (실시간)
from vosk import Model, KaldiRecognizer

def resource_path(relative_path):
    try:
        # PyInstaller가 생성한 임시 폴더 경로 (.exe 실행 시)
        base_path = sys._MEIPASS
    except Exception:
        # 평소 개발 환경 (.py 실행 시)
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

try:
    import app_config 
    from question_generator import DynamicQuestionGenerator, IMRADValidator
    from analysis_manager import AnalysisManager
    from ai_rewriter import AI_Announcer 
except ImportError as e:
    print(f"경고: 필요한 모듈을 찾을 수 없습니다: {e}")
    class DynamicQuestionGenerator: 
        def __init__(self, *args): pass 
    class IMRADValidator: 
        def __init__(self, *args): pass 
    class AnalysisManager: 
        def __init__(self, *args): pass
    class AI_Announcer: 
        def __init__(self, *args): pass

# --- 전역 변수 설정 ---
is_recording = False
start_time = 0
speech_data = {"full_transcript": "", "word_count": 0, "filler_count": 0}
gaze_data = {"total_frames": 0, "looking_frames": 0, "script_frames": 0} # script_frames 추가
audio_data = {"volumes": [], "tremble_count": 0}
timeline_markers = []
cap = None
out = None
pa = pyaudio.PyAudio()

# MediaPipe 초기화
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True, # 눈동자(Iris) 추적을 위해 필수
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

# 얼굴 인식 최적화 변수
current_face_box = None
frame_count = 0

# --- mainFinal.py 수정할 부분 ---

vosk_model = None
try:
    # 1순위: 가장 단순한 방법 (잘 되는 코드의 방식)
    if os.path.exists("model"):
        vosk_model = Model("model")
        print("✅ Vosk 오프라인 모델 로드 완료! (상대 경로)")
        
    # 2순위: 만약 위 방법이 안 되면 resource_path 사용 (PyInstaller 등 대비)
    else:
        model_path = resource_path("model")
        if os.path.exists(model_path):
            vosk_model = Model(model_path)
            print(f"✅ Vosk 오프라인 모델 로드 완료! (절대 경로): {model_path}")
        else:
            print(f"⚠️ 경고: 모델 경로를 찾을 수 없습니다.")

except Exception as e:
    print(f"❌ Vosk 모델 로드 오류: {e}")

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI Presentation Pro (Final Ver: Enhanced UI & Gaze)")
        self.geometry("1400x950") # 화면을 좀 더 넓게 설정
        
        # 긴장 모드 상태 변수
        self.is_anxious = False
        self.heart_phase = 0.0
        
        if 'app_config' in globals() and hasattr(app_config, 'set_korean_font'):
            app_config.set_korean_font() 
        
        self.user_settings = {}
        self.original_script = ""
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        self.load_and_initialize_apis() 
        
        if 'app_config' in globals() and hasattr(app_config, 'STOPWORDS'):
            self.analysis_manager = AnalysisManager(app_config.STOPWORDS, app_config.COACHING_CONFIG)
            self.dynamic_generator = DynamicQuestionGenerator(self.text_model) 
            self.imrad_validator = IMRADValidator(self.text_model)
            self.ai_announcer = AI_Announcer(self.text_model) 
        else:
            self.analysis_manager = AnalysisManager({}, {})
            self.dynamic_generator = DynamicQuestionGenerator(None)
            self.imrad_validator = IMRADValidator(None)
            self.ai_announcer = AI_Announcer(None)

        self.extracted_keywords = []
        self.raw_audio_frames = []

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.load_history()
        self.show_setup_page()

    def load_and_initialize_apis(self):
        if 'app_config' not in globals() or not hasattr(app_config, 'load_api_keys'):
            self.AI_AVAILABLE = False
            self.text_model = None
            return

        gemini_key = app_config.load_api_keys()
        
        if not gemini_key:
            gemini_key = simpledialog.askstring("Gemini API 키 필요", 
                                                "Gemini API 키를 입력하세요 (AI 피드백용):\n", 
                                                parent=self)
            if gemini_key:
                app_config.save_api_keys(gemini_key)

        self.text_model = None
        self.AI_AVAILABLE = False

        if gemini_key:
            try:
                if 'app_config' in globals() and hasattr(app_config, 'genai'):
                    app_config.genai.configure(api_key=gemini_key)
                    self.text_model = app_config.genai.GenerativeModel('gemini-2.5-pro')
                    self.AI_AVAILABLE = True
                    print("Gemini API 연결 성공")
            except Exception as e:
                print(f"Gemini 연결 실패: {e}")
        else:
            print("Gemini API 키 없음.")

    def on_closing(self):
        global is_recording, cap, out, pa
        is_recording = False
        self.is_anxious = False 
        if cap and cap.isOpened(): cap.release()
        if out: out.release()
        if pa: pa.terminate() 
        try:
            for f in ["rewritten_script_output.wav", "output.avi", "output.wav"]:
                if os.path.exists(f): os.remove(f)
        except: pass
        self.destroy()
        os._exit(0)

    def load_history(self):
        self.history = []
        if 'app_config' in globals() and hasattr(app_config, 'HISTORY_FILE') and os.path.exists(app_config.HISTORY_FILE):
            try:
                with open(app_config.HISTORY_FILE, "r", encoding='utf-8') as f:
                    self.history = json.load(f)
            except: self.history = []

    def save_history(self, score):
        if 'app_config' not in globals() or not hasattr(app_config, 'HISTORY_FILE'): return
        self.history.append(score)
        with open(app_config.HISTORY_FILE, "w", encoding='utf-8') as f:
            json.dump(self.history, f, ensure_ascii=False, indent=4)

    def clear_window(self):
        self.unbind_all("<MouseWheel>")
        for widget in self.winfo_children(): widget.destroy()

    def show_setup_page(self):
        self.clear_window()
        frame = ttk.Frame(self)
        frame.pack(expand=True)
        ttk.Label(frame, text="🎤 AI Presentation Pro", font=("Arial", 30, "bold")).pack(pady=30)
        
        ttk.Label(frame, text="발표 유형 선택:", font=("Arial", 14)).pack()
        self.atmosphere_var = tk.StringVar(value="📘 정보 전달형 (정확성 중시)")
        modes = ["📘 정보 전달형 (정확성 중시)", "🔥 설득/동기부여형 (에너지 중시)", "🤝 공감/소통형 (밸런스 중시)"]
        ttk.Combobox(frame, textvariable=self.atmosphere_var, values=modes, state="readonly", font=("Arial", 12), width=35).pack(pady=15)
        
        ttk.Button(frame, text="연습 시작하기", command=self.go_to_practice).pack(pady=20, ipadx=20, ipady=10)
        ttk.Button(frame, text="📢 AI 대본 재작성 (Gemini)", command=self.show_rewriter_window).pack(pady=10, ipadx=10, ipady=5)

    def go_to_practice(self):
        self.user_settings['atmosphere'] = self.atmosphere_var.get()
        self.show_practice_page()

    # =========================================================================
    # [UI 대규모 수정] 화면 상단: 청중/내얼굴 병렬 배치, 하단: 대본 스크롤
    # =========================================================================
    def show_practice_page(self):
        self.clear_window()
        
        # 전체 메인 프레임
        main_frame = ttk.Frame(self)
        main_frame.pack(fill='both', expand=True, padx=20, pady=20)

        # --- 상단 영역: 화면 분할 (청중 | 내 얼굴) ---
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(side='top', fill='both', expand=True, pady=(0, 10))
        
        # 상단 그리드 설정 (1행 2열, 균등 비율)
        top_frame.columnconfigure(0, weight=1) # 청중 영역
        top_frame.columnconfigure(1, weight=1) # 내 얼굴 영역
        top_frame.rowconfigure(0, weight=1)

        # 1. 청중 패널 (왼쪽)
        self.audience_frame = tk.Frame(top_frame, bg="#e9ecef", bd=2, relief="sunken")
        self.audience_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        
        # 청중 이미지가 중앙에 오도록 내부 프레임 사용
        aud_inner = tk.Frame(self.audience_frame, bg="#e9ecef")
        aud_inner.pack(expand=True)
        self.aud_labels = [ttk.Label(aud_inner) for _ in range(2)]
        for lbl in self.aud_labels: lbl.pack(side="left", padx=5)

        # 2. 내 얼굴 패널 (오른쪽)
        video_bg_frame = tk.Frame(top_frame, bg="black", bd=2, relief="sunken")
        video_bg_frame.grid(row=0, column=1, sticky="nsew")
        
        self.video_panel = ttk.Label(video_bg_frame)
        self.video_panel.pack(expand=True)

        # 초기 청중 이미지 설정
        self.update_audience_images('default', 'default') 
        
        # --- 중단 영역: 컨트롤 버튼 ---
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(side='top', fill='x', pady=10)
        
        # 버튼들 중앙 정렬을 위한 내부 프레임
        btn_box = ttk.Frame(control_frame)
        btn_box.pack(anchor='center')

        self.btn_start = ttk.Button(btn_box, text="▶ 녹화 시작", command=self.start_recording)
        self.btn_start.pack(side="left", padx=10)
        
        self.btn_panic = tk.Button(btn_box, text="😰 긴장 모드: OFF", font=("Arial", 10), bg="#dddddd", command=self.toggle_anxiety)
        self.btn_panic.pack(side="left", padx=10)
        
        self.btn_question = ttk.Button(btn_box, text="⚡️ 돌발 질문", command=self.trigger_question_event, state="disabled")
        self.btn_question.pack(side="left", padx=10)
        
        self.btn_stop = ttk.Button(btn_box, text="■ 결과 보기", command=self.stop_recording, state="disabled")
        self.btn_stop.pack(side="left", padx=10)
        
        self.status_label = ttk.Label(btn_box, text="준비 완료", font=("Arial", 12), foreground="gray")
        self.status_label.pack(side="left", padx=20)

        # --- 하단 영역: 대본 (스크롤 가능, 크게) ---
        bottom_frame = ttk.LabelFrame(main_frame, text="📄 발표 대본 (시선이 내려가면 감점됩니다!)")
        bottom_frame.pack(side='bottom', fill='both', expand=True, pady=(10, 0))
        
        # 대본 텍스트 위젯 + 스크롤바
        self.script_text = tk.Text(bottom_frame, height=8, font=("Arial", 14), bg="white", fg="black", wrap="word")
        scrollbar = ttk.Scrollbar(bottom_frame, orient="vertical", command=self.script_text.yview)
        self.script_text.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        self.script_text.pack(side="left", fill="both", expand=True)
        
        self.start_camera()

    # =========================================================================
    # [기능 복구] 긴장 모드 토글 (텍스트 하얗게 변해서 안 보이는 기능)
    # =========================================================================
    def toggle_anxiety(self):
        self.is_anxious = not self.is_anxious
        if self.is_anxious:
            self.btn_panic.config(text="😰 긴장 모드: ON", bg="#ffcccc", fg="red")
            self.script_text.config(fg="white", bg="white") # 글씨를 흰색으로 변경 (안 보이게)
            
            # [긴장 효과] 청중들이 즉시 산만해짐 (Distracted)
            self.update_audience_images('distracted', 'distracted')
            
            threading.Thread(target=self.anxiety_sound_loop, daemon=True).start()
        else:
            self.btn_panic.config(text="😰 긴장 모드: OFF", bg="#dddddd", fg="black")
            self.script_text.config(fg="black", bg="white") # 글씨 복구
            
            # [복구] 다시 평범한 상태로
            self.update_audience_images('default', 'default')
    # =========================================================================
    # 리얼 심장 사운드 생성기
    # =========================================================================
    
    def anxiety_sound_loop(self):
        RATE = 16000
        BPM = 115 
        DURATION = 60 / BPM 
        t = np.linspace(0, DURATION, int(RATE * DURATION), False)
        
        s1_freq = 40
        s1_envelope = np.exp(-t * 25)
        s1 = (np.sin(2 * np.pi * s1_freq * t) + 0.6 * np.sin(2 * np.pi * 25 * t)) * s1_envelope
        
        s2_delay = 0.2
        t_s2 = t - s2_delay
        s2_freq = 60
        s2_envelope = np.exp(-t_s2 * 35) * (t_s2 > 0) 
        s2 = np.sin(2 * np.pi * s2_freq * t_s2) * s2_envelope * 0.8 

        heartbeat = s1 + s2 # Heartbeat sound
        tinnitus = np.sin(2 * np.pi * 8500 * t) * 0.04 # 고주파음
        noise = np.random.uniform(-0.015, 0.015, len(t)) # 백색 소음
        
        audio_signal = heartbeat * 1.2 + tinnitus + noise
        audio_signal = np.clip(audio_signal, -1, 1) * 32767
        audio_bytes = audio_signal.astype(np.int16).tobytes()
        
        try:
            p = pyaudio.PyAudio()
            stream = p.open(format=pyaudio.paInt16, channels=1, rate=RATE, output=True)
            while self.is_anxious:
                stream.write(audio_bytes)
                time.sleep(random.uniform(0.0, 0.03))
            stream.stop_stream(); stream.close(); p.terminate()
        except Exception as e:
            print(f"사운드 재생 오류: {e}")

    def start_camera(self):
        global cap
        try:
            # 1단계: exe 환경에서 가장 안정적인 DSHOW 모드 시도
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            
            # 2단계: DSHOW가 실패했거나 카메라가 안 열리면 일반 모드로 재시도
            if cap is None or not cap.isOpened():
                print("⚠️ DSHOW 모드 실패, 일반 모드로 재시도합니다.")
                if cap: cap.release()
                cap = cv2.VideoCapture(0) # 일반 모드
            
            # 3단계: 그래도 안 되면 -1번 장치 시도 (일부 노트북용)
            if cap is None or not cap.isOpened():
                cap = cv2.VideoCapture(-1)

            # 최종 확인
            if not cap.isOpened():
                messagebox.showerror("카메라 오류", "카메라를 연결할 수 없습니다.\n다른 프로그램이 카메라를 쓰고 있는지 확인해주세요.")
                return

            # 해상도 설정 (640x360)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)
            
            # 화면 업데이트 시작
            self.update_video_stream()
            
        except Exception as e:
            # 어떤 오류인지 정확히 메시지로 띄워줍니다.
            messagebox.showerror("카메라 오류", f"초기화 실패 원인:\n{e}")

    # =========================================================================
    # [핵심 수정] 정교한 시선 추적 (Iris Tracking & Head Pitch)
    # =========================================================================
    def update_video_stream(self):
        global gaze_data, cap, frame_count, face_mesh 
        if not self.winfo_exists(): return
        
        try:
            if cap is None or not cap.isOpened(): return 

            ret, frame = cap.read()
            if not ret: return
            
            frame = cv2.flip(frame, 1)
            frame_count += 1
            h, w, _ = frame.shape

            # --- 긴장 시각 효과(스크린 펌프 효과) ---       
            if self.is_anxious:
                try:
                    self.heart_phase += 0.35
                    pulse = (np.sin(self.heart_phase) + 1) / 2 
                    
                    overlay = frame.copy()
                    h, w, channels = frame.shape
                    if channels == 4: overlay[:] = (0, 0, 255, 255)   
                    else: overlay[:] = (0, 0, 255)      
                    
                    alpha = pulse * 0.25 
                    frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)
                    
                    dx = random.randint(-5, 5)
                    dy = random.randint(-5, 5)
                    M = np.float32([[1, 0, dx], [0, 1, dy]])
                    frame = cv2.warpAffine(frame, M, (w, h))
                except: pass 

            # --- MediaPipe 얼굴/시선 분석 ---
            script_gaze_detected = False
            
            # 성능을 위해 2프레임마다 분석하지만, 녹화 중에는 매 프레임 체크가 더 정확할 수 있음
            # 여기서는 2프레임 간격 유지
            if frame_count % 2 == 0: 
                try:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = face_mesh.process(rgb_frame)
                    
                    if results.multi_face_landmarks:
                        landmarks = results.multi_face_landmarks[0].landmark
                        
                        # 3D 좌표 변환
                        mesh_points = np.array([np.multiply([p.x, p.y], [w, h]).astype(int) for p in landmarks])
                        
                        # [알고리즘 복구] 눈동자 수직 위치 비율 (Vertical Gaze Ratio)
                        # 왼쪽 눈: 159(위), 145(아래), 468(눈동자)
                        # 오른쪽 눈: 386(위), 374(아래), 473(눈동자)
                        
                        def get_gaze_ratio(top, bottom, iris):
                            eye_height = np.linalg.norm(top - bottom)
                            dist_to_top = np.linalg.norm(top - iris)
                            # 눈을 감았거나 인식이 불안정하면 0.5(정면) 반환
                            if eye_height < 3: return 0.5 
                            return dist_to_top / eye_height

                        left_ratio = get_gaze_ratio(mesh_points[159], mesh_points[145], mesh_points[468])
                        right_ratio = get_gaze_ratio(mesh_points[386], mesh_points[374], mesh_points[473])
                        avg_ratio = (left_ratio + right_ratio) / 2
                        
                        # [핵심 수정] 임계값 재조정 (0.68)
                        # 0.50: 정면
                        # 0.57: 너무 예민함 (가만히 있어도 걸림)
                        # 0.75: 너무 둔감함 (대본 봐도 안 걸림)
                        # --> 0.68로 설정하여 안정성 확보
                        if avg_ratio > 0.57: 

                            script_gaze_detected = True
                            # 시각적 피드백
                            cv2.putText(frame, "LOOKING DOWN!", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                            cv2.circle(frame, tuple(mesh_points[468]), 3, (0, 0, 255), -1)
                            cv2.circle(frame, tuple(mesh_points[473]), 3, (0, 0, 255), -1)
                        else:
                            # 정면 응시
                            cv2.circle(frame, tuple(mesh_points[468]), 3, (0, 255, 0), -1)
                            cv2.circle(frame, tuple(mesh_points[473]), 3, (0, 255, 0), -1)
                        
                        # 눈 윤곽선
                        cv2.polylines(frame, [mesh_points[[33, 133]]], True, (200, 200, 200), 1)
                        cv2.polylines(frame, [mesh_points[[362, 263]]], True, (200, 200, 200), 1)


                    # 데이터 집계
                    if is_recording:
                        gaze_data['total_frames'] += 1
                        if script_gaze_detected:
                            gaze_data['script_frames'] += 1 # 감점 요인
                        elif results.multi_face_landmarks:
                            gaze_data['looking_frames'] += 1 # 득점 요인 (정면 응시)
                            
                except Exception as e: 
                    # print(f"Medipipe 오류: {e}") 
                    pass

            if is_recording and out: 
                out.write(frame)
                cv2.circle(frame, (30, 30), 10, (0, 0, 255), -1)

            # 화면 표시를 위해 크기 조정 (640x360)
            img = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).resize((640, 360))) 
            self.video_panel.configure(image=img); self.video_panel.image = img
            
            if self.winfo_exists():
                self.after(30, self.update_video_stream)
                
        except Exception as e:
            if self.winfo_exists():
                self.after(1000, self.update_video_stream)

    # =========================================================================
    # [수정됨] 청중 이미지 업데이트 (크기 640x360에 맞춰 조정)
    # =========================================================================
    def update_audience_images(self, s1, s2):
        def get_image(idx, state):
            filename = f"audience{idx}_{state}.png" 
            path = resource_path(filename)
            if not os.path.exists(path): path = resource_path(f"audience{idx}_default.png")
            try:
                # 화면 분할 크기에 맞춰 이미지 리사이징 (약 320x240 정도가 적당)
                return ImageTk.PhotoImage(Image.open(path).resize((300, 225)))
            except: return None

        img1 = get_image(1, s1)
        img2 = get_image(2, s2)
        
        if img1: self.aud_labels[0].configure(image=img1); self.aud_labels[0].image = img1
        if img2: self.aud_labels[1].configure(image=img2); self.aud_labels[1].image = img2

    # =========================================================================
    # 청중 행동 루프
    # =========================================================================
    def audience_loop(self):
        if not is_recording: return
        if self.is_anxious:
            s1, s2 = 'distracted', 'distracted'
        else:
            states = ['default']*6 + ['focused']*2 + ['distracted']*1 + ['question']*1
            s1 = random.choice(states)
            s2 = random.choice(states)
        self.update_audience_images(s1, s2)
        if self.winfo_exists(): self.after(4000, self.audience_loop)

    # =========================================================================
    # 돌발 질문 트리거
    # =========================================================================
    def trigger_question_event(self):
        if not self.winfo_exists(): return
        
        # 질문자 선정 (한 명은 질문, 한 명은 쳐다봄)
        asker_idx = random.randint(0, 1)
        if asker_idx == 0: self.update_audience_images('question', 'focused')
        else: self.update_audience_images('focused', 'question')
        
        self.update()
        threading.Thread(target=self._trigger_question_thread, args=(self.script_text.get("1.0", tk.END).strip(), self.user_settings.get('atmosphere', '정보')), daemon=True).start()

    def _trigger_question_thread(self, script, mode):
        ai_question = None
        possible_questions = []
        if 'app_config' in globals() and hasattr(app_config, 'BACKUP_QUESTIONS'):
            possible_questions.extend(app_config.BACKUP_QUESTIONS)
        else:
            possible_questions.append("가장 중요하다고 생각하는 점은 무엇인가요?")

        if self.AI_AVAILABLE:
            try:
                if '정보' in mode: ai_question = self.imrad_validator.generate_imrad_question(script)
                elif '설득' in mode: ai_question = self.dynamic_generator.generate_question(script, 'B')
                elif '공감' in mode: ai_question = self.dynamic_generator.generate_question(script, 'C')
                if ai_question: possible_questions.append(ai_question)
            except: pass

        final_question = random.choice(possible_questions)
        if self.winfo_exists(): self.after(0, self._show_question_popup, final_question)

    def _show_question_popup(self, final_question):
        if not self.winfo_exists(): return
        self.add_marker(time.time() - start_time, '❓')
        messagebox.showinfo("💡 돌발 질문", final_question)
    
    def start_recording(self):
        global is_recording, start_time, out, speech_data, timeline_markers, gaze_data, audio_data
        if len(self.script_text.get("1.0", tk.END).strip()) < 10:
            messagebox.showwarning("경고", "대본을 10자 이상 입력해주세요.")
            return
        
        if not vosk_model:
            if not messagebox.askyesno("경고", "음성 인식 모델(Vosk)이 없습니다. 소리 없이 녹화만 하시겠습니까?"):
                return

        is_recording = True; start_time = time.time()
        speech_data = {"full_transcript": "", "word_count": 0, "filler_count": 0}
        # 데이터 초기화 (script_frames 포함)
        gaze_data = {"total_frames": 0, "looking_frames": 0, "script_frames": 0}
        audio_data = {"volumes": [], "tremble_count": 0}
        timeline_markers = []
        self.raw_audio_frames = [] 
        
        try:
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            out = cv2.VideoWriter('output.avi', fourcc, 20.0, (640, 360)) # 해상도 맞춤
        except Exception as e:
            messagebox.showerror("오류", f"비디오 파일 생성 실패: {e}")
            is_recording = False
            return
            
        threading.Thread(target=self.speech_recognition_thread, daemon=True).start()
        
        self.btn_start['state'] = 'disabled'; self.btn_stop['state'] = 'normal'; self.btn_question['state'] = 'normal'
        self.script_text['state'] = 'normal' # 녹화 중에도 스크롤 해야 하므로 normal
        self.status_label.config(text="🔴 녹화 중", foreground="red")
        self.audience_loop()

    # [수정됨] Vosk 기반 실시간 SPM(음절) 측정 스레드
    def speech_recognition_thread(self):
        global speech_data, audio_data, pa, vosk_model
        
        SENSITIVITY = 5.0  
        RATE = 16000
        CHUNK = 4096
        
        if not vosk_model: return

        rec = KaldiRecognizer(vosk_model, RATE)
        
        try:
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True, frames_per_buffer=CHUNK)
        except Exception as e:
            print(f"마이크 오류: {e}")
            return

        last_speech_end = time.time()
        last_vol = 0

        print(f"🎤 마이크 민감도 {SENSITIVITY}배 / SPM 모드로 시작")

        while is_recording:
            try:
                if stream.get_read_available() < CHUNK:
                    time.sleep(0.01)
                    continue
                
                data = stream.read(CHUNK, exception_on_overflow=False)
                
                # --- [민감도 조절] ---
                audio_array = np.frombuffer(data, dtype=np.int16)
                audio_array = audio_array * SENSITIVITY
                audio_array = np.clip(audio_array, -32768, 32767)
                data = audio_array.astype(np.int16).tobytes()
                # ---------------------

                self.raw_audio_frames.append(data)

                # 볼륨/떨림 분석
                rms = audioop.rms(data, 2)
                if abs(rms - last_vol) > 2000 and rms > 500: 
                    audio_data['tremble_count'] += 1
                last_vol = rms
                audio_data['volumes'].append(rms)

                #vosk 음성 인식
                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    text = result.get('text', '')
                    
                    if text:
                        print(f"🎤 인식됨: {text}") # 디버깅용
                        timestamp = time.time() - start_time
                        
                        # SPM(Syllables Per Minute) 로직
                         # 공백 제거 후 순수 글자 수(음절)만 셉니다.
                        syllable_count = len(text.replace(" ", "")) 
                        speech_data['full_transcript'] += text + " "

                        # 변수 이름은 word_count지만, 실제로는 이제 '음절 수'가 저장됩니다.
                        speech_data['word_count'] += syllable_count 
                        
                        # 순간 속도(Instant SPM) 계산
                        segment_duration = time.time() - last_speech_end
                        if segment_duration > 0.5:
                            # (글자수 / 시간초) * 60 = 분당 글자수
                            instant_spm = (syllable_count / segment_duration) * 60
                            
                             # ⚡ SPM 기준 마커 찍기 (한국어 기준)
                            # 450타 이상 = 말이 너무 빠름
                            if instant_spm > 450: self.add_marker(timestamp, '⚡️') 
                            # 200타 이하이고 글자가 좀 길면 = 말이 너무 느림
                            elif instant_spm < 200 and syllable_count > 5: self.add_marker(timestamp, '🐢') 
                            
                        last_speech_end = time.time()

                        if 'app_config' in globals() and hasattr(app_config, 'FILLER_WORDS'):
                             words = text.split() 
                             chunk_filler = sum(1 for w in words if w in app_config.FILLER_WORDS)
                             speech_data['filler_count'] += chunk_filler
                             if chunk_filler > 0: self.add_marker(timestamp, '💬')

            except Exception as e:
                print(f"오디오 스레드 오류: {e}")
                continue

        stream.stop_stream()
        stream.close()
        
        # 마지막 버퍼 처리 (FinalResult)
        final_res = json.loads(rec.FinalResult())
        final_text = final_res.get('text', '')
        if final_text:
            speech_data['full_transcript'] += final_text + " "
            # 여기도 음절 수로 저장
            speech_data['word_count'] += len(final_text.replace(" ", ""))

    def add_marker(self, t, emoji):
        if not timeline_markers or (t - timeline_markers[-1]['time'] > 1.5) or timeline_markers[-1]['label'] != emoji:
            timeline_markers.append({'time': max(0.1, t), 'label': emoji})

    def stop_recording(self):
        global is_recording
        is_recording = False
        self.original_script = self.script_text.get("1.0", tk.END).strip()
        self.btn_stop['state'] = 'disabled'
        self.btn_question['state'] = 'disabled'
        self.status_label.config(text="⏳ 저장 및 분석 중 (Whisper 구동)...", foreground="blue")
        self.update()
        threading.Thread(target=self._finalize_and_analyze_thread, daemon=True).start()

    def _finalize_and_analyze_thread(self):
        global cap, out, speech_data 
        
        try:
            self.extracted_keywords = self.analysis_manager.extract_keywords_from_script(
                self.original_script, self.AI_AVAILABLE, self.text_model 
            )
        except: self.extracted_keywords = []
        
        try:
            if self.raw_audio_frames:
                wf = wave.open("output.wav", 'wb')
                wf.setnchannels(1) 
                wf.setsampwidth(2) 
                wf.setframerate(16000) 
                wf.writeframes(b''.join(self.raw_audio_frames))
                wf.close()
                print("✅ output.wav 저장 완료.")
            else:
                print("❌ 저장할 오디오 데이터 없음")
                return 
        except Exception as e:
            print(f"wav 저장 실패: {e}")

        # Whisper 하이브리드 로직
        # Vosk가 대충 받아적은걸 Whisper가 '정밀 청취'하여 덮어씁니다.
        try:
            print("⏳ Whisper 정밀 분석 시작 (잠시만 기다리세요)...")

            # 모델 로드 (tiny, base, small 중 선택. small이 한국어 성능/속도 밸런스 굿)
            # device="cpu", compute_type="int8" -> CPU에서 빠르게 돌리기 위한 설정
            model = WhisperModel("small", device="cpu", compute_type="int8")

            # 변환 실행 (beam_size=5는 정확도를 높임)
            segments, info = model.transcribe("output.wav", beam_size=5, language="ko")
            
            whisper_text = ""
            for segment in segments:
                whisper_text += segment.text + " "
            
            print(f"✅ Whisper 변환 결과: {whisper_text}")
            # [핵심] Vosk가 작성한 엉성한 대본을 Whisper의 완벽한 대본으로 교체!
            speech_data['full_transcript'] = whisper_text.strip()
            
        except Exception as e:
            print(f"❌ Whisper 분석 실패 (Vosk 결과 유지): {e}")
     
        time.sleep(1.0)
        if out: out.release(); out = None
        if cap: cap.release(); cap = None
            
        if self.winfo_exists(): 
            self.after(0, self.show_analysis_page)

    # =========================================================================
    # [수정됨] 분석 페이지: 감점 로직 반영
    # =========================================================================
    def show_analysis_page(self):
        self.clear_window()
        main_canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=main_canvas.yview)
        scrollable_frame = ttk.Frame(main_canvas)
        scrollable_frame.bind("<Configure>", lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all")))
        canvas_frame = main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        main_canvas.bind("<Configure>", lambda e: main_canvas.itemconfig(canvas_frame, width=e.width))
        main_canvas.configure(yscrollcommand=scrollbar.set)
        main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.bind_all("<MouseWheel>", lambda e: main_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        content = ttk.Frame(scrollable_frame, padding=30)
        content.pack(fill='both', expand=True)

        global speech_data, gaze_data, audio_data, start_time
        
        # 실제 오디오 길이 기반 시간 측정
        duration_min = max(0.1, (time.time() - start_time) / 60)
        try:
            # output.wav 파일의 헤더를 읽어서 정확한 녹음 시간(초)을 구함
            with contextlib.closing(wave.open("output.wav", 'r')) as f:
                frames = f.getnframes()
                rate = f.getframerate()
                duration_sec = frames / float(rate)
                duration_min = max(0.01, duration_sec / 60)
                print(f"⏱️ 실제 녹음 시간: {duration_sec:.2f}초") # 디버깅용
        except Exception as e:
            print(f"시간 계산 오류(백업 로직 사용): {e}")
            duration_min = max(0.1, (time.time() - start_time) / 60)

        # Whisper 텍스트 가져오기
        current_transcript = speech_data['full_transcript']
        
        # 공백 제외 순수 글자 수 (음절)
        char_count = len(current_transcript.replace(" ", ""))   

        # 속도 점수
        spm = int(speech_data['word_count'] / duration_min) if speech_data['word_count'] > 0 else 0 
        score_speed = max(0, 100 - int(abs(350 - spm) * 0.4))
        speed_eval = "적정"
        if spm < 280: speed_eval = "느림 🐢"
        elif spm > 420: speed_eval = "빠름 ⚡"
        
        # 시선 처리 점수 (감점 로직 적용)
        total_frames = max(1, gaze_data['total_frames'])
        
        # 1. 정면 응시율 (기본 점수)
        base_gaze_score = (gaze_data['looking_frames'] / total_frames) * 100
        
        # 2. 대본 응시(Looking Down) 감점
        script_penalty = (gaze_data['script_frames'] / total_frames) * 150 # 감점 가중치
        
        # 3. 최종 시선 점수
        final_gaze_score = max(0, min(100, int(base_gaze_score - script_penalty)))
        
        # 전달률 점수(Whisper 기반)
        import difflib
        script = self.original_script
        if len(current_transcript.strip()) > 5:
            def clean_text(text):
                return re.sub(r'[^가-힣a-zA-Z0-9]', '', text)
            clean_script = clean_text(script)
            clean_trans = clean_text(current_transcript)
            matcher = difflib.SequenceMatcher(None, clean_script, clean_trans)
            raw_score = matcher.ratio() * 100
            match_rate = int(raw_score * 1.05) 
            if match_rate > 100: match_rate = 100
            match_label_text = "전달률"
        else:
            match_rate = 0
            match_label_text = "데이터 부족"

        # 유창성 점수
        filler_deduction = speech_data['filler_count'] * 3
        tremble_score = max(0, 100 - int(audio_data['tremble_count'] / duration_min * 2))
        score_fluency = int((max(0, 100 - filler_deduction) + tremble_score) / 2)
        
        # 종합 점수
        mode = self.user_settings.get('atmosphere', '정보')
        if '정보' in mode: total_score = int(match_rate * 0.4 + score_fluency * 0.3 + final_gaze_score * 0.2 + score_speed * 0.1)
        elif '설득' in mode: total_score = int(final_gaze_score * 0.4 + score_speed * 0.2 + score_fluency * 0.2 + match_rate * 0.2)
        else: total_score = int(match_rate * 0.3 + final_gaze_score * 0.3 + score_fluency * 0.2 + score_speed * 0.2)
        self.save_history(total_score)
        
        # UI 표시
        tk.Label(content, text=f"🏆 종합 점수: {total_score}점", font=("Arial", 36, "bold"), fg="#007aff").pack(pady=20)
        
        if gaze_data['script_frames'] > total_frames * 0.2:
            tk.Label(content, text=f"⚠️ 대본을 너무 자주 보셨습니다! (감점 -{int(script_penalty)}점)", font=("Arial", 12), fg="red").pack()

        summary = ttk.Frame(content)
        summary.pack(pady=10, fill='x')
        for i in range(4): summary.columnconfigure(i, weight=1)
        self.create_stat_card(summary, 0, f"🗣️ 속도 ({speed_eval})", f"{spm} SPM", score_speed)
        self.create_stat_card(summary, 1, f"📝 {match_label_text}", f"{match_rate}%", match_rate)
        self.create_stat_card(summary, 2, "👀 시선 처리", f"{final_gaze_score}점", final_gaze_score)
        self.create_stat_card(summary, 3, "🌊 유창성", f"{score_fluency}점", score_fluency)
        
        try:
            self.create_video_player(content)
        except Exception as e:
            tk.Label(content, text=f"비디오 플레이어 오류: {e}", fg="red").pack()

            # 그래프 그리기 (가장 에러 많이 나는 곳 - 안전장치 추가)
        try:
            self.create_score_graph(content)
        except Exception as e:
                tk.Label(content, text=f"그래프 생성 실패: {e}", fg="red").pack()
        self.create_feedback_section(content, mode, match_rate, final_gaze_score, score_fluency, spm, speech_data['full_transcript'], audio_data['volumes'])
        
        ttk.Button(content, text="처음으로 돌아가기", command=self.show_setup_page).pack(pady=30)
        self.load_video()

        
    def create_stat_card(self, parent, col, title, value, score):
        frame = tk.Frame(parent, bg="white", bd=1, relief="solid")
        frame.grid(row=0, column=col, padx=10, sticky="nsew")
        tk.Label(frame, text=title, font=("Arial", 12, "bold"), bg="white").pack(pady=(10,5))
        tk.Label(frame, text=value, font=("Arial", 18), fg="#007aff", bg="white").pack()
        tk.Label(frame, text=f"(점수: {score})", font=("Arial", 10), fg="gray", bg="white").pack(pady=(0,10))

    def create_video_player(self, parent):
        player_frame = ttk.LabelFrame(parent, text=" 🎦 녹화 영상 리뷰 (타임라인 클릭) ")
        player_frame.pack(fill='both', expand=True, padx=20, pady=20)
        self.vid_player_label = ttk.Label(player_frame); self.vid_player_label.pack(pady=10, fill='both', expand=True)
        self.timeline = tk.Canvas(player_frame, height=40, bg="#e9ecef"); self.timeline.pack(fill='x', padx=10)
        self.timeline.bind("<Button-1>", self.on_timeline_click)
        self.vid_slider = ttk.Scale(player_frame, from_=0, to=100, orient="horizontal", command=self.on_slider_move)
        self.vid_slider.pack(fill='x', padx=10, pady=(0, 10))
        btn_frame = ttk.Frame(player_frame); btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="▶ 재생 (소리 ON)", command=self.play_video_with_sound).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="■ 정지", command=self.stop_video).pack(side='left', padx=5)

    def create_score_graph(self, parent):
        graph_frame = ttk.Frame(parent)
        graph_frame.pack(fill='x', pady=20, padx=20)

        fig, ax = plt.subplots(figsize=(8, 2.5))
        history_len = len(self.history)

        if history_len > 0:
            # X축 데이터 생성 (1, 2, 3...)
            x_ticks = range(1, history_len + 1)
            
            # 그래프 그리기
            ax.plot(x_ticks, self.history, marker='o', linestyle='-', color='#007aff', linewidth=2)
            ax.fill_between(x_ticks, self.history, color='#007aff', alpha=0.1)
            ax.set_title("연습 점수 트렌드")
            ax.set_ylim(0, 105)
            ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))
 
            
            ax.set_xlim(0.5, history_len + 0.5)
            ax.grid(True, linestyle='--')
            
        else:
            # 데이터가 없을 때 빈 그래프 처리
            ax.set_title("아직 연습 기록이 없습니다")
            ax.set_yticks([])
            ax.set_xticks([])

        canvas = FigureCanvasTkAgg(fig, master=graph_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill='both')

    def create_feedback_section(self, parent, mode_raw, match_rate, gaze_ratio, fluency, spm, transcript, volume_data):
        fb_frame = tk.LabelFrame(parent, text="🤖 AI 코치 피드백", font=("Arial", 14, "bold"))
        fb_frame.pack(fill='x', pady=20, ipady=10)
        
        if '정보' in mode_raw: mapped_mode = '논리적'; target_type_key = 'A'
        elif '공감' in mode_raw: mapped_mode = '친화적'; target_type_key = 'C'
        else: mapped_mode = '열정적'; target_type_key = 'B'
        
        final_report_text = ""
        if spm == 0 and len(transcript.strip()) < 10:
            final_report_text = "🚨 **데이터 부족:** 음성 데이터가 충분히 인식되지 않았습니다."
        else:
            final_report_text += "--- 📈 AI 코칭 리포트 (규칙 기반) ---\n"
            style_feedback = self.analysis_manager.analyze_speech_style(transcript, mapped_mode)
            energy_feedback = self.analysis_manager.analyze_vocal_energy(volume_data, mapped_mode)
            delivery_metrics = {"spm": spm} 
            
            final_report_text += f"{style_feedback}\n{energy_feedback}\n\n"
            
            imrad_report = []
            if target_type_key == 'A': imrad_report = self.imrad_validator.validate_imrad_sections(self.original_script)
            if imrad_report: final_report_text += "--- [논리 구조 경고] ---\n" + "\n".join(imrad_report) + "\n\n"
            
            final_report_text += "--- 🤖 AI 심층 피드백 (Gemini) ---\n"
            ai_generated_feedback = None 
            if self.AI_AVAILABLE and self.text_model: 
                try:
                    ai_generated_feedback = self.analysis_manager.generate_ai_feedback(
                        self.text_model, transcript, target_type_key, delivery_metrics, 
                        style_feedback, energy_feedback, imrad_report
                    )
                except Exception as e:
                    ai_generated_feedback = f"오류: {e}"
            
            if ai_generated_feedback: final_report_text += ai_generated_feedback
            else: final_report_text += "Gemini API 미연결로 심층 피드백을 건너뜁니다."
        
        tk.Label(fb_frame, text=final_report_text, font=("Arial", 12), justify="left", wraplength=800, padx=20).pack(anchor='w', fill='x')

    def load_video(self):
        try:
            if not os.path.exists('output.avi'): return
            self.vid_cap = cv2.VideoCapture('output.avi')
            self.vid_duration = max(1, self.vid_cap.get(cv2.CAP_PROP_FRAME_COUNT) / self.vid_cap.get(cv2.CAP_PROP_FPS))
            self.is_playing = False
            self.draw_timeline()
            self.vid_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.update_frame()
        except: pass

    def draw_timeline(self):
        if not hasattr(self, 'timeline') or not self.timeline.winfo_exists(): return
        self.timeline.delete("all")
        try:
            w = self.timeline.winfo_width()
            if w < 2: w = 1100 
            self.timeline.create_line(0, 20, w, 20, fill="#ced4da", width=2)
            for m in timeline_markers:
                if self.vid_duration > 0:
                    x = (m['time'] / self.vid_duration) * w
                    self.timeline.create_text(x, 20, text=m['label'], font=("Arial", 16), tags=(str(m['time']),))
        except: pass

    def on_timeline_click(self, event):
        if not hasattr(self, 'timeline') or not self.timeline.winfo_exists(): return
        tags = self.timeline.gettags(self.timeline.find_closest(event.x, event.y))
        if tags: self.seek(float(tags[0]))

    def on_slider_move(self, val): 
        if hasattr(self, 'vid_duration'): self.seek((float(val) / 100) * self.vid_duration)
            
    def seek(self, sec):
        if hasattr(self, 'vid_cap') and self.vid_cap and self.vid_cap.isOpened():
            self.vid_cap.set(cv2.CAP_PROP_POS_FRAMES, int(sec * self.vid_cap.get(cv2.CAP_PROP_FPS)))
            self.update_frame()

    def audio_playback_thread(self):
        global pa
        CHUNK = 1024
        try:
            if not os.path.exists("output.wav"): return
            wf = wave.open("output.wav", 'rb')
            stream = pa.open(format=pa.get_format_from_width(wf.getsampwidth()),
                             channels=wf.getnchannels(), rate=wf.getframerate(), output=True)
            data = wf.readframes(CHUNK)
            while data and self.is_playing:
                stream.write(data)
                data = wf.readframes(CHUNK)
            stream.stop_stream(); stream.close(); wf.close()
        except Exception as e: print(f"오디오 재생 오류: {e}")
        self.is_playing = False

    def play_video_with_sound(self):
        if self.is_playing: return
        self.is_playing = True
        threading.Thread(target=self.audio_playback_thread, daemon=True).start()
        self.play_video_loop()

    def stop_video(self):
        self.is_playing = False

    def play_video_loop(self):
        if not self.winfo_exists() or not self.is_playing: return
        if self.vid_cap and self.vid_cap.isOpened():
            ret, frame = self.vid_cap.read()
            if ret:
                self.show_frame(frame)
                current_pos = self.vid_cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
                if hasattr(self, 'vid_slider'): self.vid_slider.set((current_pos / self.vid_duration) * 100)
                self.after(33, self.play_video_loop) 
            else: 
                self.stop_video()
                self.vid_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def update_frame(self):
        if self.vid_cap and self.vid_cap.isOpened():
            ret, frame = self.vid_cap.read()
            if ret: self.show_frame(frame)

    def show_frame(self, frame):
        try:
            if not hasattr(self, 'vid_player_label') or not self.vid_player_label.winfo_exists(): return
            w = self.vid_player_label.winfo_width()
            if w > 1:
                target_h = int(w * (9 / 16)) 
                h, w_orig = frame.shape[:2]
                scale = target_h / h
                target_w = int(w_orig * scale)
                resized_frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
                img = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB)))
                self.vid_player_label.configure(image=img, anchor='center'); self.vid_player_label.image = img
            else:
                img = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).resize((640, 360)))
                self.vid_player_label.configure(image=img, anchor='center'); self.vid_player_label.image = img
        except: pass 

    def show_rewriter_window(self):
        if not self.AI_AVAILABLE:
            messagebox.showerror("오류", "Gemini API 키가 없어 실행할 수 없습니다.")
            return
        self.rewriter_win = tk.Toplevel(self)
        self.rewriter_win.title("📢 AI 대본 재작성")
        self.rewriter_win.geometry("1000x700")
        main_frame = ttk.Frame(self.rewriter_win, padding=10); main_frame.pack(fill='both', expand=True)
        control_frame = ttk.Frame(main_frame); control_frame.pack(fill='x', pady=5)
        ttk.Label(control_frame, text="스타일:").pack(side='left', padx=(0, 5))
        self.rewrite_mode = tk.StringVar(value='B')
        for text, mode in [('정보형 (A)', 'A'), ('설득형 (B)', 'B'), ('공감형 (C)', 'C')]:
            ttk.Radiobutton(control_frame, text=text, variable=self.rewrite_mode, value=mode).pack(side='left', padx=5)
        text_frame = ttk.Frame(main_frame); text_frame.pack(fill='both', expand=True, pady=5)
        text_frame.columnconfigure(0, weight=1); text_frame.columnconfigure(1, weight=1); text_frame.rowconfigure(0, weight=1)
        self.original_text = tk.Text(text_frame, height=30, width=50, font=("Arial", 11)); self.original_text.grid(row=0, column=0)
        self.rewritten_text = tk.Text(text_frame, height=30, width=50, font=("Arial", 11), state='disabled'); self.rewritten_text.grid(row=0, column=1)
        action_frame = ttk.Frame(main_frame); action_frame.pack(fill='x', pady=10)
        self.rewrite_status_label = ttk.Label(action_frame, text="준비 완료", foreground="gray"); self.rewrite_status_label.pack(side='left', padx=10)
        self.rewrite_btn = ttk.Button(action_frame, text="🚀 변환 실행", command=self.run_rewriter); self.rewrite_btn.pack(side='right')

    def run_rewriter(self):
        script = self.original_text.get("1.0", tk.END).strip()
        if len(script) < 20: return
        self.rewrite_status_label.config(text="AI가 변환 중...", foreground="blue")
        threading.Thread(target=self._rewrite_thread_target, args=(script, self.rewrite_mode.get()), daemon=True).start()

    def _rewrite_thread_target(self, script, mode):
        try:
            res = self.ai_announcer.rewrite(script, mode)
            if self.winfo_exists(): self.after(0, self.update_rewriter_ui, res)
        except Exception as e:
            if self.winfo_exists(): self.after(0, self.update_rewriter_ui, f"오류: {e}")

    def update_rewriter_ui(self, res):
        if hasattr(self, 'rewriter_win') and self.rewriter_win.winfo_exists():
            self.rewritten_text.config(state='normal'); self.rewritten_text.delete("1.0", tk.END); self.rewritten_text.insert("1.0", res); self.rewritten_text.config(state='disabled')
            self.rewrite_status_label.config(text="완료" if "오류" not in res else "실패", foreground="green" if "오류" not in res else "red")

if __name__ == "__main__":
    app = App()
    app.mainloop()
