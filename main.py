import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import simpledialog # API 키를 물어볼 팝업창
import cv2
from PIL import Image, ImageTk
import threading
import time
import speech_recognition as sr
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker # [수정] 그래프 정수 눈금용
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import random
import os
import json
import re
import pyaudio
import wave
import audioop

try:
    import app_config # 설정 파일 (app_config.py)
    from question_generator import DynamicQuestionGenerator, IMRADValidator
    from analysis_manager import AnalysisManager
    from ai_rewriter import AI_Announcer 
except ImportError as e:
    print(f"경고: 필요한 모듈을 찾을 수 없습니다: {e}")
    print("app_config.py, question_generator.py, analysis_manager.py, ai_rewriter.py 파일이 main.py와 같은 폴더에 있는지 확인하세요.")
    # 임시 대체 (오류 방지용)
    class DynamicQuestionGenerator: 
        def __init__(self, *args): pass # [수정] text_model 인수 받도록
    class IMRADValidator: 
        def __init__(self, *args): pass # [수정] text_model 인수 받도록
    class AnalysisManager: 
        def __init__(self, *args): pass
    class AI_Announcer: 
        def __init__(self, *args): pass
# --- ---

# --- 전역 변수 (실시간 스레드 제어용) ---
is_recording = False
start_time = 0
speech_data = {"full_transcript": "", "word_count": 0, "filler_count": 0}
gaze_data = {"total_frames": 0, "looking_frames": 0}
audio_data = {"volumes": [], "tremble_count": 0}
timeline_markers = []
cap = None
out = None
recognizer = sr.Recognizer()
microphone = sr.Microphone()
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
pa = pyaudio.PyAudio() # .wav 저장을 위해 pa 인스턴스는 유지

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI Presentation Pro (Gemini Full Version)")
        self.geometry("1200x950")
        
        # app_config 모듈이 로드되었는지 확인 후 폰트 설정
        if 'app_config' in globals() and hasattr(app_config, 'set_korean_font'):
            app_config.set_korean_font() 
        
        self.user_settings = {}
        self.original_script = ""
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        self.load_and_initialize_apis() # Gemini API 로드
        
        # 모듈이 정상 로드되었을 때만 인스턴스 생성
        if 'app_config' in globals() and hasattr(app_config, 'STOPWORDS'):
            self.analysis_manager = AnalysisManager(app_config.STOPWORDS, app_config.COACHING_CONFIG)
            self.dynamic_generator = DynamicQuestionGenerator(self.text_model) 
            self.imrad_validator = IMRADValidator(self.text_model)
            self.ai_announcer = AI_Announcer(self.text_model) 
        else:
            # 모듈 로드 실패 시 비상용 인스턴스 (오류 방지)
            self.analysis_manager = AnalysisManager({}, {})
            self.dynamic_generator = DynamicQuestionGenerator(None)
            self.imrad_validator = IMRADValidator(None)
            self.ai_announcer = AI_Announcer(None)

        self.extracted_keywords = []

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.load_history()
        self.show_setup_page()

    def load_and_initialize_apis(self):
        """[수정] Gemini API 키로 텍스트 모델만 초기화합니다. (TTS 모델 초기화 삭제)"""
        
        # app_config 모듈이 로드되었는지 확인
        if 'app_config' not in globals() or not hasattr(app_config, 'load_api_keys'):
            messagebox.showerror("치명적 오류", "app_config 모듈을 로드할 수 없습니다.")
            self.AI_AVAILABLE = False
            self.text_model = None
            return

        gemini_key = app_config.load_api_keys()
        
        if not gemini_key:
            gemini_key = simpledialog.askstring("Gemini API 키 필요", 
                                                "Gemini API 키를 입력하세요 (모든 AI 기능에 사용):\n", 
                                                parent=self)
            if gemini_key:
                app_config.save_api_keys(gemini_key) # Gemini 키만 저장

        self.text_model = None  # (MODIFIED) 텍스트 모델
        self.AI_AVAILABLE = False

        if gemini_key:
            try:
                # [수정] app_config 모듈에 있는 genai 사용
                if 'app_config' in globals() and hasattr(app_config, 'genai'):
                    app_config.genai.configure(api_key=gemini_key)
                    
                    # (FIXED) 1. 텍스트 모델 (gemini-2.5-pro)
                    self.text_model = app_config.genai.GenerativeModel('gemini-2.5-pro')
                    
                    self.AI_AVAILABLE = True
                    
                    print("Gemini API가 성공적으로 설정되었습니다. (Text: gemini-2.5-pro)")
                else:
                    raise ImportError("app_config 모듈에서 genai를 찾을 수 없습니다.")
            
            except Exception as e:
                print(f"Gemini API 설정 실패: {e}")
                messagebox.showerror("API 오류", f"Gemini 모델 초기화 실패. API 키를 확인하세요.\n{e}")
        else:
            print("Gemini API 키가 설정되지 않았습니다. AI 기능이 비활성화됩니다.")


    def on_closing(self):
        global is_recording, cap, out, pa
        is_recording = False
        if cap and cap.isOpened(): cap.release()
        if out: out.release()
        if pa: pa.terminate() 
        try:
            if os.path.exists("rewritten_script_output.wav"):
                os.remove("rewritten_script_output.wav")
            if os.path.exists("output.avi"):
                os.remove("output.avi")
            if os.path.exists("output.wav"):
                os.remove("output.wav")
                
        except: pass
        self.destroy()
        os._exit(0) # 스레드가 남아있을 수 있으므로 강제 종료

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
        #utf-8 인코딩 추가 (한글 깨짐 방지)
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
        """연습 페이지로 이동"""
        self.user_settings['atmosphere'] = self.atmosphere_var.get()
        self.show_practice_page()

    def show_practice_page(self):
        self.clear_window()
        main_frame = ttk.Frame(self)
        main_frame.pack(fill='both', expand=True, padx=20, pady=20)
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(pady=10)
        self.video_panel = ttk.Label(top_frame)
        self.video_panel.pack()
        self.audience_frame = tk.Frame(main_frame, bg="#e9ecef", bd=2, relief="sunken")
        self.audience_frame.pack(fill="x", padx=100, pady=10)
        self.aud_labels = [ttk.Label(self.audience_frame) for _ in range(2)]
        for lbl in self.aud_labels: lbl.pack(side="left", expand=True, padx=10, pady=10)
        self.update_audience_images('default', 'default') # [수정] 청중 이미지 로드
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(pady=20)
        self.btn_start = ttk.Button(control_frame, text="▶ 녹화 시작", command=self.start_recording)
        self.btn_start.pack(side="left", padx=10)
        self.btn_question = ttk.Button(control_frame, text="⚡️ 돌발 질문", command=self.trigger_question_event, state="disabled")
        self.btn_question.pack(side="left", padx=10)
        self.btn_stop = ttk.Button(control_frame, text="■ 결과 보기", command=self.stop_recording, state="disabled")
        self.btn_stop.pack(side="left", padx=10)
        self.status_label = ttk.Label(main_frame, text="준비 완료", font=("Arial", 14), foreground="gray")
        self.status_label.pack()
        ttk.Label(main_frame, text="📄 발표 대본 (분석을 위해 필수 입력):", font=("Arial", 12)).pack(anchor='w')
        self.script_text = tk.Text(main_frame, height=6, font=("Arial", 11))
        self.script_text.pack(fill='x', pady=(5, 0))
        self.start_camera()

    def start_camera(self):
        global cap
        try:
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                messagebox.showerror("카메라 오류", "카메라를 열 수 없습니다. 다른 프로그램이 사용 중인지 확인하세요.")
                self.show_setup_page()
                return
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.update_video_stream()
        except Exception as e:
            messagebox.showerror("카메라 오류", f"카메라 초기화 중 알 수 없는 오류 발생: {e}")
            self.show_setup_page()


    def update_video_stream(self):
        global gaze_data, cap
        if not self.winfo_exists(): return
        
        try:
            # [수정] cap이 None이거나 닫혔으면 루프 중단
            if cap is None or not cap.isOpened():
                print("비디오 스트림 중단됨 (캡처 릴리즈됨).")
                return 

            ret, frame = cap.read()
            if ret:
                if is_recording:
                    if out: out.write(frame) # out 객체가 존재할 때만 write
                    gaze_data['total_frames'] += 1
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces = face_cascade.detectMultiScale(gray, 1.3, 5)
                    looking = False
                    for (x, y, w, h) in faces:
                        if 640 * 0.3 < (x + w // 2) < 640 * 0.7: looking = True
                        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0) if looking else (0, 0, 255), 2)
                    if looking: gaze_data['looking_frames'] += 1
                
                frame = cv2.flip(frame, 1)
                if is_recording: cv2.circle(frame, (30, 30), 10, (0, 0, 255), -1)
                
                # [수정] 640x360 (16:9 비율)로 리사이즈
                img = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).resize((640, 360))) 
                self.video_panel.configure(image=img); self.video_panel.image = img
            
            # 루프 지속
            if self.winfo_exists():
                self.after(30, self.update_video_stream)
                
        except Exception as e:
            # 비디오 패널이 파괴된 후에도 self.after가 실행되는 것을 방지
            if self.winfo_exists():
                print(f"비디오 스트림 업데이트 오류: {e}")
                self.after(1000, self.update_video_stream) # 오류 시 1초 후 재시도

    def update_audience_images(self, s1, s2):
        """실제 청중 이미지를 로드합니다."""
        try:
          
            i1 = ImageTk.PhotoImage(Image.open(f"audience1_{s1}.png").resize((200, 150)))
            self.aud_labels[0].configure(image=i1); self.aud_labels[0].image = i1
            i2 = ImageTk.PhotoImage(Image.open(f"audience2_{s2}.png").resize((200, 150)))
            self.aud_labels[1].configure(image=i2); self.aud_labels[1].image = i2
        except Exception as e:
            # print(f"청중 이미지 로드 실패: {e}") # 디버깅 시 주석 해제
            pass # 파일이 없어도 프로그램이 중단되지 않도록 pass

    def start_recording(self):
        global is_recording, start_time, out, speech_data, timeline_markers, gaze_data, audio_data, microphone
        if len(self.script_text.get("1.0", tk.END).strip()) < 10:
            messagebox.showwarning("경고", "정확한 분석을 위해 대본을 10자 이상 입력해주세요.")
            return
        
        try:
            # [수정] 전역 microphone 객체 사용
            with microphone as source:
                print("마이크 장치 확인 완료.")
        except Exception as e:
            messagebox.showerror("오디오 오류", f"마이크를 찾을 수 없습니다. 마이크가 연결되어 있는지 확인하세요.\n{e}")
            return

        is_recording = True; start_time = time.time()
        speech_data = {"full_transcript": "", "word_count": 0, "filler_count": 0}
        gaze_data = {"total_frames": 0, "looking_frames": 0}
        audio_data = {"volumes": [], "tremble_count": 0}
        timeline_markers = []
        self.raw_audio_frames = [] # 오디오 스트림 통합 저장을 위해 초기화
        
        try:
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            out = cv2.VideoWriter('output.avi', fourcc, 20.0, (640, 480))
        except Exception as e:
            messagebox.showerror("비디오 쓰기 오류", f"비디오 파일(output.avi)을 생성할 수 없습니다.\n{e}")
            is_recording = False
            return
            
        # 오디오/STT 통합 스레드 시작
        threading.Thread(target=self.speech_recognition_thread, daemon=True).start()
        
        self.btn_start['state'] = 'disabled'; self.btn_stop['state'] = 'normal'; self.btn_question['state'] = 'normal'
        self.script_text['state'] = 'disabled'
        self.status_label.config(text="🔴 녹화 및 분석 중...", foreground="red")
        self.audience_loop() # [수정] 청중 반응 루프 시작

    def speech_recognition_thread(self):
        """[스레드] 오디오 스트림 통합 관리 (STT, WAV 저장, RMS 분석)"""
        global speech_data, audio_data, recognizer, microphone
        last_vol = 0
        
        with microphone as source:
            # [수정] 자동 임계값 설정 (마이크 민감도 향상)
            print("주변 소음 감지 중... (1초)")
            recognizer.adjust_for_ambient_noise(source, duration=1)
            print(f"마이크 임계값 자동 설정 완료: {recognizer.energy_threshold}")
            
            last_speech_end = time.time()
            
            while is_recording:
                try:
                    audio = recognizer.listen(source, timeout=2, phrase_time_limit=5)
                    
                    # 1. WAV 녹음용 데이터 저장
                    raw_data = audio.get_raw_data(convert_rate=microphone.SAMPLE_RATE, convert_width=microphone.SAMPLE_WIDTH)
                    self.raw_audio_frames.append(raw_data) # 'self' 사용

                    # 2. 에너지/떨림 분석용 RMS 계산
                    rms = audioop.rms(raw_data, microphone.SAMPLE_WIDTH) 
                    if abs(rms - last_vol) > 2000 and rms > 500: 
                        audio_data['tremble_count'] += 1
                    last_vol = rms
                    audio_data['volumes'].append(rms)

                    # 3. STT용 텍스트 변환
                    text = recognizer.recognize_google(audio, language='ko-KR')
                    
                    # --- STT 성공 후 데이터 처리 ---
                    timestamp = time.time() - start_time - 1.5
                    words = text.split() # 'words' 정의
                    speech_data['word_count'] += len(words)
                    speech_data['full_transcript'] += text + " "
                    segment_duration = time.time() - last_speech_end
                    last_speech_end = time.time()
                    
                    if segment_duration > 0.5:
                        instant_wpm = (len(words) / segment_duration) * 60
                        if instant_wpm > 220: self.add_marker(timestamp, '⚡️') # 'self' 사용
                        elif instant_wpm < 60 and len(words) > 2: self.add_marker(timestamp, '🐢') # 'self' 사용
                        
                    chunk_filler = 0
                    if 'app_config' in globals() and hasattr(app_config, 'FILLER_WORDS'):
                        for word in words: # 'word' 정의 및 사용
                            if any(f in word for f in app_config.FILLER_WORDS):
                                chunk_filler += 1; speech_data['filler_count'] += 1
                    if chunk_filler > 0: self.add_marker(timestamp, '💬') # 'self' 사용
                    
                except sr.WaitTimeoutError: # 침묵
                    if time.time() - last_speech_end > 5.0:
                        self.add_marker(time.time() - start_time - 5.0, '🤐') # 'self' 사용
                        last_speech_end = time.time()
                    continue
                except sr.UnknownValueError: # STT 인식 실패
                    print("STT: 음성을 인식할 수 없습니다.")
                    pass 
                except Exception as e:
                    print(f"STT 스레드 오류: {e}")
                    time.sleep(0.5) 

    def add_marker(self, t, emoji):
        if not timeline_markers or (t - timeline_markers[-1]['time'] > 1.5) or timeline_markers[-1]['label'] != emoji:
            timeline_markers.append({'time': max(0.1, t), 'label': emoji})

    def audience_loop(self):
        """4초마다 청중 표정을 랜덤하게 변경합니다."""
        if not is_recording: return
        
        # 10% 확률로 딴짓, 20% 확률로 집중, 70% 확률로 기본
        s1 = random.choice(['default']*7 + ['focused']*2 + ['distracted'])
        s2 = random.choice(['default']*7 + ['focused']*2 + ['distracted'])
        self.update_audience_images(s1, s2)
        
        if self.winfo_exists(): self.after(4000, self.audience_loop) # 4초마다 반복

    # =========================================================================
    # === [수정] "응답 없음" 방지를 위해 돌발 질문 로직을 스레드로 분리 ===
    # =========================================================================
    def trigger_question_event(self):
        """AI 호출을 별도 스레드로 분리하여 GUI 멈춤(응답 없음) 방지"""
        if not self.winfo_exists(): return
        
        # 1. (메인 스레드) GUI 즉시 변경
        asker_idx = random.randint(0, 1)
        if asker_idx == 0: self.update_audience_images('question', 'focused')
        else: self.update_audience_images('focused', 'question')
        self.update() # UI 즉시 새로고침

        # 2. (메인 스레드) AI 스레드에 필요한 데이터를 미리 수집
        try:
            script = self.script_text.get("1.0", tk.END).strip()
            mode = self.user_settings.get('atmosphere', '정보')
        except Exception as e:
            print(f"대본 읽기 오류: {e}")
            return

        # 3. (메인 스레드) AI 및 규칙 분석을 별도 스레드에서 실행
        threading.Thread(target=self._trigger_question_thread, 
                         args=(script, mode), 
                         daemon=True).start()

    def _trigger_question_thread(self, script, mode):
        """(작업 스레드) AI 또는 규칙 기반으로 질문을 생성 (시간 소요)"""
        
        ai_question = None
        possible_questions = []
        
        # 1. (필수) 백업 질문 리스트 확보
        if 'app_config' in globals() and hasattr(app_config, 'BACKUP_QUESTIONS'):
            possible_questions.extend(app_config.BACKUP_QUESTIONS)
        else:
            possible_questions.append("발표 내용 중에 가장 중요하다고 생각하는 점은 무엇인가요?")

        # 2. (선택) AI/규칙 기반 질문 생성 (느린 작업)
        if self.AI_AVAILABLE:
            try:
                if '정보' in mode:
                    ai_question = self.imrad_validator.generate_imrad_question(script)
                elif '설득' in mode:
                    ai_question = self.dynamic_generator.generate_question(script, 'B')
                elif '공감' in mode:
                    ai_question = self.dynamic_generator.generate_question(script, 'C')
                
                if ai_question:
                    possible_questions.append(ai_question)
                else:
                    print("AI/규칙 기반 질문 생성기가 None을 반환했습니다.")
                    
            except Exception as e:
                print(f"AI 질문 생성 중 오류 발생 (백업 질문만 사용): {e}")

        # 3. 최종 질문 선택
        final_question = random.choice(possible_questions)
        
        # 4. (작업 스레드) GUI 업데이트(팝업)를 다시 메인 스레드에 요청
        if self.winfo_exists():
            self.after(0, self._show_question_popup, final_question)

    def _show_question_popup(self, final_question):
        """(메인 스레드) 작업 스레드가 요청한 팝업창을 안전하게 표시"""
        if not self.winfo_exists(): return
        
        self.add_marker(time.time() - start_time, '❓')
        messagebox.showinfo("💡 돌발 질문", final_question)
    # =========================================================================

    # =========================================================================
    # === [수정] "응답 없음" 방지를 위해 녹화 중단 로직을 스레드로 분리 ===
    # =========================================================================
    def stop_recording(self):
        """GUI 멈춤(응답 없음) 방지를 위해 AI 분석을 스레드로 분리"""
        global is_recording
        
        # 1. (메인 스레드) 즉시 녹화 중지
        is_recording = False
        
        # 2. (메인 스레드) GUI 즉시 업데이트
        self.original_script = self.script_text.get("1.0", tk.END).strip()
        self.btn_stop['state'] = 'disabled'
        self.btn_question['state'] = 'disabled'
        self.status_label.config(text="⏳ 녹화 종료! 결과 분석 중입니다...", foreground="blue")
        self.update()
        
        # 3. (메인 스레드) 느린 작업(파일 저장, AI 분석)을 별도 스레드로 실행
        threading.Thread(target=self._finalize_and_analyze_thread, daemon=True).start()

    def _finalize_and_analyze_thread(self):
        """(작업 스레드) 키워드 추출(AI) 및 파일 저장을 수행 (시간 소요)"""
        global cap, out, microphone
        
        # 1. (느린 작업) AI 키워드 추출
        print("대본 분석 및 키워드 추출 중...")
        try:
            self.extracted_keywords = self.analysis_manager.extract_keywords_from_script(
                self.original_script, self.AI_AVAILABLE, self.text_model 
            )
        except Exception as e:
            print(f"키워드 추출 중 오류 발생: {e}")
            self.extracted_keywords = [] # 오류 시 빈 리스트로 초기화
        
        # 2. (느린 작업) 오디오 파일 저장
        try:
            if self.raw_audio_frames:
                print(f"WAV 파일 저장 시도... (총 {len(self.raw_audio_frames)}개 청크)")
                wf = wave.open("output.wav", 'wb')
                
                #  'microphone' 객체 대신 'pyaudio' 기본값 사용
                wf.setnchannels(1) #  1채널(모노)로 고정
                wf.setsampwidth(microphone.SAMPLE_WIDTH)
                wf.setframerate(microphone.SAMPLE_RATE)
                
                wf.writeframes(b''.join(self.raw_audio_frames))
                wf.close()
                print("output.wav 저장 완료.")
            else:
                print("저장할 오디오 데이터가 없습니다.")
        except Exception as e:
            print(f"output.wav 저장 실패: {e}")
     
        # 3. (느린 작업) 비디오 파일 및 카메라 릴리즈 
        time.sleep(1.0) # 비디오 쓰기 완료 대기
        if out: 
            out.release()
            out = None
            print("비디오 라이터 릴리즈 완료.")
        if cap: 
            cap.release()
            cap = None
            print("카메라 캡처 릴리즈 완료.")
            
        # 4. (작업 스레드) 모든 작업 완료 후, 메인 스레드에 결과 페이지 표시 요청
        if self.winfo_exists(): 
            self.after(0, self.show_analysis_page)
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
        
        duration_min = max(0.1, (time.time() - start_time) / 60)
        
        wpm = int(speech_data['word_count'] / duration_min) if speech_data['word_count'] > 0 else 0 
        score_speed = max(0, 100 - abs(130 - wpm))
        total_frames = max(1, gaze_data['total_frames'])
        gaze_ratio = int((gaze_data['looking_frames'] / total_frames) * 100)
        score_gaze = min(100, int(gaze_ratio * 1.43))
        mode = self.user_settings.get('atmosphere', '정보')
        
        if len(speech_data['full_transcript'].strip()) > 10:
            match_rate, match_label_text = self.analysis_manager.calculate_smart_match(
                self.original_script, speech_data['full_transcript'], mode
            )
        else:
            match_rate, match_label_text = 0, "데이터 부족"
            
        score_match = match_rate
        filler_deduction = speech_data['filler_count'] * 3
        tremble_score = max(0, 100 - int(audio_data['tremble_count'] / duration_min * 2))
        score_fluency = int((max(0, 100 - filler_deduction) + tremble_score) / 2)
        
        if '정보' in mode: total_score = int(score_match * 0.4 + score_fluency * 0.3 + score_gaze * 0.2 + score_speed * 0.1)
        elif '설득' in mode: total_score = int(score_gaze * 0.4 + score_speed * 0.2 + score_fluency * 0.2 + score_match * 0.2)
        else: total_score = int(score_match * 0.3 + score_gaze * 0.3 + score_fluency * 0.2 + score_speed * 0.2)
        self.save_history(total_score)
        
        tk.Label(content, text=f"🏆 종합 점수: {total_score}점", font=("Arial", 36, "bold"), fg="#007aff").pack(pady=20)
        summary = ttk.Frame(content); summary.pack(pady=10, fill='x')
        for i in range(4): summary.columnconfigure(i, weight=1)
        self.create_stat_card(summary, 0, "🗣️ 속도", f"{wpm} WPM", score_speed)
        self.create_stat_card(summary, 1, f"📝 {match_label_text}", f"{match_rate}%", score_match)
        self.create_stat_card(summary, 2, "👀 시선 처리", f"{gaze_ratio}%", score_gaze)
        self.create_stat_card(summary, 3, "🌊 유창성", f"{score_fluency}점", score_fluency)
        
        self.create_video_player(content)
        self.create_score_graph(content)
        self.create_feedback_section(content, mode, match_rate, gaze_ratio, score_fluency, wpm, speech_data['full_transcript'], audio_data['volumes'])
        
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
        """[수정됨] X축 눈금 오류를 수정한 그래프 생성"""
        graph_frame = ttk.Frame(parent); graph_frame.pack(fill='x', pady=20, padx=20)
        fig, ax = plt.subplots(figsize=(8, 2.5))
        
        history_len = len(self.history)
        
        if history_len > 0:
            x_ticks = range(1, history_len + 1)
            ax.plot(x_ticks, self.history, marker='o', linestyle='-', color='#007aff', linewidth=2)
            ax.fill_between(x_ticks, self.history, color='#007aff', alpha=0.1)
            ax.set_title("연습 점수 트렌드")
            ax.set_ylim(0, 105)
            
            ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))
            ax.set_xlim(0.5, history_len + 0.5)
            
            if history_len == 1:
                ax.set_xticks([1])
            elif history_len < 10:
                 ax.set_xticks(x_ticks)

            ax.grid(True, linestyle='--')
            
        canvas = FigureCanvasTkAgg(fig, master=graph_frame); canvas.draw(); canvas.get_tk_widget().pack(fill='both')


    def create_feedback_section(self, parent, mode_raw, match_rate, gaze_ratio, fluency, wpm, transcript, volume_data):
        fb_frame = tk.LabelFrame(parent, text="🤖 AI 코치 피드백", font=("Arial", 14, "bold"))
        fb_frame.pack(fill='x', pady=20, ipady=10)
        
        if '정보' in mode_raw: mapped_mode = '논리적'; target_type_key = 'A'
        elif '공감' in mode_raw: mapped_mode = '친화적'; target_type_key = 'C'
        else: mapped_mode = '열정적'; target_type_key = 'B'
        
        final_report_text = ""

        if wpm == 0 and len(transcript.strip()) < 10:
            final_report_text = "🚨 **데이터 부족 경고:**\n음성 데이터가 충분히 인식되지 않았습니다.\n마이크 연결을 확인하고, 녹화 중 더 크게 말씀해주세요."
        else:
            final_report_text += "--- 📈 AI 코칭 리포트 (규칙 기반) ---\n"
            
            style_feedback = self.analysis_manager.analyze_speech_style(transcript, mapped_mode)
            energy_feedback = self.analysis_manager.analyze_vocal_energy(volume_data, mapped_mode)
            delivery_metrics = {"wpm": wpm}
            
            final_report_text += f"{style_feedback}\n"
            final_report_text += f"{energy_feedback}\n\n"
            
            imrad_report = []
            if target_type_key == 'A':
                imrad_report = self.imrad_validator.validate_imrad_sections(self.original_script)
            
            if imrad_report: 
                final_report_text += "--- [논리 구조 경고] ---\n" + "\n".join(imrad_report) + "\n\n"
            
            final_report_text += "--- 🤖 AI 심층 피드백 (Gemini) ---\n"

            ai_generated_feedback = None 
            
            if self.AI_AVAILABLE and self.text_model: 
                print("AI 심층 코칭 리포트 생성을 시도합니다... (gemini-2.5-pro)")
                try:
                    ai_generated_feedback = self.analysis_manager.generate_ai_feedback(
                        self.text_model, transcript, target_type_key, delivery_metrics, 
                        style_feedback, energy_feedback, imrad_report
                    )
                except Exception as e:
                    print(f"AI 심층 피드백 생성 오류: {e}")
                    ai_generated_feedback = f"AI 심층 피드백 생성 중 오류가 발생했습니다: {e}"
            
            if ai_generated_feedback:
                final_report_text += ai_generated_feedback
            else:
                print("AI 코칭 API를 사용할 수 없거나 실패했습니다. 로컬 규칙 기반 피드백을 생성합니다.")
                
                fallback_text = "Gemini AI를 사용할 수 없어 심층 피드백을 생성하지 못했습니다. 대신 로컬 규칙 기반 요약을 제공합니다.\n\n"
                
                if fluency < 70: fallback_text += "⚠️ [유창성] 목소리 떨림이나 '음, 어' 같은 필러워드가 감지되었습니다.\n"
                if wpm > 150: fallback_text += f"⚠️ [속도] 말이 다소 빠릅니다 ({wpm} WPM).\n"
                elif wpm < 100 and wpm > 0: fallback_text += f"⚠️ [속도] 말이 다소 느립니다 ({wpm} WPM).\n"
                
                if len(fallback_text.split('\n')) < 6:
                    fallback_text += "\n🎉 전반적으로 아주 훌륭한 발표 역량을 보여주셨습니다!"
                
                final_report_text += fallback_text
        
        tk.Label(fb_frame, text=final_report_text, font=("Arial", 12), justify="left", wraplength=800, padx=20).pack(anchor='w', fill='x')

    def load_video(self):
        try:
            # 비디오 파일 존재 여부 확인
            if not os.path.exists('output.avi'):
                print("녹화 파일(output.avi)을 찾을 수 없습니다. 플레이어를 로드하지 않습니다.")
                self.vid_player_label.config(text="녹화된 비디오 파일을 찾을 수 없습니다.\n(output.avi)", foreground="red")
                return
                
            self.vid_cap = cv2.VideoCapture('output.avi')
            if not self.vid_cap.isOpened():
                print("녹화 파일(output.avi)을 열 수 없습니다.")
                self.vid_player_label.config(text="녹화 파일을 열 수 없습니다.", foreground="red")
                return
                
            self.vid_duration = max(1, self.vid_cap.get(cv2.CAP_PROP_FRAME_COUNT) / self.vid_cap.get(cv2.CAP_PROP_FPS))
            self.is_playing = False
            self.draw_timeline()
            self.vid_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.update_frame()
        except Exception as e:
            print(f"비디오 로드 오류: {e}")
            if hasattr(self, 'vid_player_label'):
                self.vid_player_label.config(text=f"비디오 로드 오류: {e}", foreground="red")

    def draw_timeline(self):
        if not hasattr(self, 'timeline') or not self.timeline.winfo_exists(): return
        self.timeline.delete("all")
        self.update_idletasks()
        try:
            w = self.timeline.winfo_width()
            if w < 2: w = 1100 # 너비가 0일 경우 기본값
            self.timeline.create_line(0, 20, w, 20, fill="#ced4da", width=2)
            for m in timeline_markers:
                if self.vid_duration > 0:
                    x = (m['time'] / self.vid_duration) * w
                    self.timeline.create_text(x, 20, text=m['label'], font=("Arial", 16), tags=(str(m['time']),))
        except Exception as e:
            print(f"타임라인 그리기 오류: {e}") 

    def on_timeline_click(self, event):
        if not hasattr(self, 'timeline') or not self.timeline.winfo_exists(): return
        tags = self.timeline.gettags(self.timeline.find_closest(event.x, event.y))
        if tags: self.seek(float(tags[0]))

    def on_slider_move(self, val): 
        if hasattr(self, 'vid_duration'):
            self.seek((float(val) / 100) * self.vid_duration)
            
    def seek(self, sec):
        if hasattr(self, 'vid_cap') and self.vid_cap and self.vid_cap.isOpened():
            self.vid_cap.set(cv2.CAP_PROP_POS_FRAMES, int(sec * self.vid_cap.get(cv2.CAP_PROP_FPS)))
            self.update_frame()

    # =========================================================================
    # =========================================================================
    
    def audio_playback_thread(self):
        """오디오 재생을 위한 별도 스레드 (pyaudio 사용)"""
        global pa
        CHUNK = 1024
        
        try:
            if not os.path.exists("output.wav"):
                print("output.wav 파일이 없어 소리 없이 재생합니다.")
                return
            
            wf = wave.open("output.wav", 'rb')
            
            # 전역 'pa' 인스턴스를 사용하여 스트림 열기
            stream = pa.open(format=pa.get_format_from_width(wf.getsampwidth()),
                             channels=wf.getnchannels(),
                             rate=wf.getframerate(),
                             output=True)

            data = wf.readframes(CHUNK)

            # self.is_playing 플래그를 확인하며 데이터 스트리밍
            while data and self.is_playing:
                stream.write(data)
                data = wf.readframes(CHUNK)

            stream.stop_stream()
            stream.close()
            wf.close()
            
        except Exception as e:
            print(f"오디오 재생 스레드 오류: {e}")
        
        # 오디오가 끝나거나 중지되면 is_playing을 False로 설정
        self.is_playing = False

    def play_video_with_sound(self):
        """[수정] 오디오/비디오 스레드를 '동시에' 시작 (winsound 제거)"""
        if self.is_playing: return
        if not hasattr(self, 'vid_cap') or not self.vid_cap or not self.vid_cap.isOpened():
            messagebox.showwarning("재생 오류", "재생할 비디오 파일이 로드되지 않았습니다.")
            return
            
        self.is_playing = True
        
        threading.Thread(target=self.audio_playback_thread, daemon=True).start()
        
        self.play_video_loop()

    def stop_video(self):
        """[수정] is_playing 플래그만 설정 (winsound 제거)"""
        self.is_playing = False

    def play_video_loop(self):
        if not self.winfo_exists(): 
            self.is_playing = False # 창이 닫히면 재생 중지
            return
        if not hasattr(self, 'vid_cap') or not self.vid_cap or not self.vid_cap.isOpened():
            self.is_playing = False
            return
            
        if self.is_playing:
            ret, frame = self.vid_cap.read()
            if ret:
                self.show_frame(frame)
                current_pos = self.vid_cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
                
                if hasattr(self, 'vid_slider'):
                    self.vid_slider.set((current_pos / self.vid_duration) * 100)
                self.after(33, self.play_video_loop) # 약 30fps
            else: 
                self.stop_video()
                if hasattr(self, 'vid_cap') and self.vid_cap:
                    self.vid_cap.set(cv2.CAP_PROP_POS_FRAMES, 0) # 재생 완료 시 처음으로 되감기


    def update_frame(self):
        if hasattr(self, 'vid_cap') and self.vid_cap and self.vid_cap.isOpened():
            ret, frame = self.vid_cap.read()
            if ret: self.show_frame(frame)

    def show_frame(self, frame):
        try:
            if not hasattr(self, 'vid_player_label') or not self.vid_player_label.winfo_exists():
                return
                
            w = self.vid_player_label.winfo_width()
            if w > 1:
                target_h = int(w * (9 / 16)) # 16:9 비율로 높이 계산
                
                # 원본 프레임 비율 유지하며 리사이즈
                h, w_orig = frame.shape[:2]
                scale = target_h / h
                target_w = int(w_orig * scale)
                
                # 리사이즈 (가로/세로 비율 유지)
                resized_frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)

                img = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB)))
                self.vid_player_label.configure(image=img, anchor='center'); self.vid_player_label.image = img
            else:
                img = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).resize((640, 360)))
                self.vid_player_label.configure(image=img, anchor='center'); self.vid_player_label.image = img
        except Exception as e:
            # print(f"프레임 표시 오류: {e}") # 디버깅 시 주석 해제
            pass 

    def show_rewriter_window(self):
        if not self.AI_AVAILABLE:
            messagebox.showerror("기능 비활성화", "Gemini API 키가 설정되지 않아 AI 대본 재작성 기능을 사용할 수 없습니다.")
            return

        self.rewriter_win = tk.Toplevel(self)
        self.rewriter_win.title("📢 AI 대본 재작성 (Gemini)")
        self.rewriter_win.geometry("1000x700")

        main_frame = ttk.Frame(self.rewriter_win, padding=10)
        main_frame.pack(fill='both', expand=True)
        
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill='x', pady=5)
        
        ttk.Label(control_frame, text="변환할 스타일:").pack(side='left', padx=(0, 5))
        self.rewrite_mode = tk.StringVar(value='B')
        modes = [('정보형 (A)', 'A'), ('설득형 (B)', 'B'), ('공감형 (C)', 'C')]
        for text, mode in modes:
            ttk.Radiobutton(control_frame, text=text, variable=self.rewrite_mode, value=mode).pack(side='left', padx=5)
        

        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill='both', expand=True, pady=5)
        text_frame.columnconfigure(0, weight=1); text_frame.columnconfigure(1, weight=1)
        text_frame.rowconfigure(0, weight=1)

        left_pane = ttk.Frame(text_frame, padding=5)
        left_pane.grid(row=0, column=0, sticky='nsew')
        ttk.Label(left_pane, text="[원본 대본]을 여기에 붙여넣으세요:").pack(anchor='w')
        self.original_text = tk.Text(left_pane, height=30, width=50, font=("Arial", 11), wrap='word')
        self.original_text.pack(fill='both', expand=True)

        right_pane = ttk.Frame(text_frame, padding=5)
        right_pane.grid(row=0, column=1, sticky='nsew')
        ttk.Label(right_pane, text="[AI 변환 결과]:").pack(anchor='w')
        self.rewritten_text = tk.Text(right_pane, height=30, width=50, font=("Arial", 11), wrap='word', state='disabled')
        self.rewritten_text.pack(fill='both', expand=True)

        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill='x', pady=10)
        
        self.rewrite_status_label = ttk.Label(action_frame, text="준비 완료.", foreground="gray")
        self.rewrite_status_label.pack(side='left', padx=10)
          
        self.rewrite_btn = ttk.Button(action_frame, text="🚀 대본 변환 실행", command=self.run_rewriter)
        self.rewrite_btn.pack(side='right')

    def run_rewriter(self):
        script = self.original_text.get("1.0", tk.END).strip()
        if len(script) < 20:
            messagebox.showwarning("오류", "원본 대본을 20자 이상 입력하세요.", parent=self.rewriter_win)
            return
            
        if not hasattr(self, 'ai_announcer') or not hasattr(self.ai_announcer, 'rewrite'):
            messagebox.showerror("오류", "AI Rewriter가 제대로 로드되지 않았습니다.", parent=self.rewriter_win)
            return

        mode = self.rewrite_mode.get()
        
        self.rewrite_status_label.config(text="AI가 대본을 재작성 중입니다... (최대 30초 소요)", foreground="blue")
        self.rewrite_btn.config(state='disabled')
        self.rewriter_win.update()

        threading.Thread(target=self._rewrite_thread_target, args=(script, mode), daemon=True).start()

    def _rewrite_thread_target(self, script, mode):
        """[스레드] 대본 재작성 (API 호출)"""
        try:
            rewritten_script = self.ai_announcer.rewrite(script, mode)
            if self.winfo_exists():
                self.after(0, self.update_rewriter_ui, rewritten_script)
        except Exception as e:
            print(f"대본 재작성 스레드 오류: {e}")
            if self.winfo_exists():
                self.after(0, self.update_rewriter_ui, f"오류 발생: {e}")
                
    def update_rewriter_ui(self, rewritten_script):
        if hasattr(self, 'rewriter_win') and self.rewriter_win.winfo_exists():
            self.rewritten_text.config(state='normal')
            self.rewritten_text.delete("1.0", tk.END)
            self.rewritten_text.insert("1.0", rewritten_script)
            self.rewritten_text.config(state='disabled')
            
            if "오류" in rewritten_script or "❌" in rewritten_script:
                self.rewrite_status_label.config(text="대본 재작성 실패.", foreground="red")
                self.rewrite_btn.config(state='normal')
            else:
                self.rewrite_status_label.config(text="변환 완료!", foreground="green")
                self.rewrite_btn.config(state='normal')

if __name__ == "__main__":
    app = App()
    app.mainloop()
