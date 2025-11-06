import tkinter as tk
from tkinter import ttk, messagebox
import cv2
from PIL import Image, ImageTk
import threading
import time
import speech_recognition as sr
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import random
import os
import json
import re
import pyaudio
import wave
import winsound
import audioop

# --- 분리된 모듈 임포트 ---
# config.py에서 모든 설정, 상수, API 클라이언트, 플래그를 가져옴
from config import *
# question_generator.py에서 질문 생성기 클래스들을 가져옴
from question_generator import DynamicQuestionGenerator, IMRADQuestionGenerator
# analysis_manager.py에서 분석 로직 클래스를 가져옴
from analysis_manager import AnalysisManager
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
pa = pyaudio.PyAudio()

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI Presentation Pro")
        self.geometry("1200x950")
        
        set_korean_font() # config에서 폰트 설정 함수 호출
        
        self.user_settings = {}
        self.original_script = ""
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # --- 분석 및 질문 모듈 인스턴스화 ---
        # config.py에서 가져온 상수를 AnalysisManager에 주입
        self.analysis_manager = AnalysisManager(STOPWORDS, COACHING_CONFIG)
        self.dynamic_generator = DynamicQuestionGenerator()
        self.imrad_generator = IMRADQuestionGenerator()
        # --- ---
        
        self.extracted_keywords = []
        self.client = openai_client # config에서 가져온 OpenAI 클라이언트
        self.gemini_model = gemini_model # config에서 가져온 Gemini 모델

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.load_history()
        self.show_setup_page()

    def on_closing(self):
        """프로그램 종료 시 모든 리소스 정리"""
        global is_recording, cap, out
        is_recording = False
        if cap and cap.isOpened(): cap.release()
        if out: out.release()
        try:
            if hasattr(self, 'audio_stream') and self.audio_stream.is_active():
                self.audio_stream.stop_stream()
                self.audio_stream.close()
        except: pass
        self.destroy()
        os._exit(0)

    def load_history(self):
        """점수 기록 불러오기"""
        self.history = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f: self.history = json.load(f)
            except: self.history = []

    def save_history(self, score):
        """점수 기록 저장"""
        self.history.append(score)
        with open(HISTORY_FILE, "w") as f: json.dump(self.history, f)

    def clear_window(self):
        """페이지 전환 시 모든 위젯 삭제"""
        self.unbind_all("<MouseWheel>")
        for widget in self.winfo_children(): widget.destroy()

    def show_setup_page(self):
        """초기 설정 페이지 (모드 선택)"""
        self.clear_window()
        frame = ttk.Frame(self)
        frame.pack(expand=True)
        ttk.Label(frame, text="🎤 AI Presentation Pro", font=("Arial", 30, "bold")).pack(pady=30)
        ttk.Label(frame, text="발표 유형 선택:", font=("Arial", 14)).pack()
        self.atmosphere_var = tk.StringVar(value="📘 정보 전달형")
        modes = ["📘 정보 전달형 (정확성 중시)", "🔥 설득/동기부여형 (에너지 중시)", "🤝 공감/소통형 (밸런스 중시)"]
        ttk.Combobox(frame, textvariable=self.atmosphere_var, values=modes, state="readonly", font=("Arial", 12), width=35).pack(pady=15)
        ttk.Button(frame, text="연습 시작하기", command=self.go_to_practice).pack(pady=30, ipadx=20, ipady=10)

    def go_to_practice(self):
        """연습 페이지로 이동"""
        self.user_settings['atmosphere'] = self.atmosphere_var.get()
        self.show_practice_page()

    def show_practice_page(self):
        """메인 연습 페이지 (카메라, 버튼, 대본)"""
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
        self.update_audience_images('default', 'default')
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
        """OpenCV 카메라 시작"""
        global cap
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.update_video_stream()

    def update_video_stream(self):
        """비디오 프레임 실시간 업데이트 및 시선 추적"""
        global gaze_data
        if not self.winfo_exists(): return
        if cap is not None and cap.isOpened():
            ret, frame = cap.read()
            if ret:
                if is_recording:
                    out.write(frame)
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
                img = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).resize((640, 360)))
                self.video_panel.configure(image=img); self.video_panel.image = img
        if not is_recording and cap is None: return
        if self.winfo_exists(): self.after(30, self.update_video_stream)

    def update_audience_images(self, s1, s2):
        """가상 청중 이미지 변경"""
        try:
            i1 = ImageTk.PhotoImage(Image.open(f"audience1_{s1}.png").resize((200, 150)))
            self.aud_labels[0].configure(image=i1); self.aud_labels[0].image = i1
            i2 = ImageTk.PhotoImage(Image.open(f"audience2_{s2}.png").resize((200, 150)))
            self.aud_labels[1].configure(image=i2); self.aud_labels[1].image = i2
        except: pass # 이미지 파일이 없어도 오류 없이 통과

    def start_recording(self):
        """녹화 시작"""
        global is_recording, start_time, out, speech_data, timeline_markers, gaze_data, audio_data
        if len(self.script_text.get("1.0", tk.END).strip()) < 10:
            messagebox.showwarning("경고", "정확한 분석을 위해 대본을 10자 이상 입력해주세요.")
            return
        is_recording = True; start_time = time.time()
        speech_data = {"full_transcript": "", "word_count": 0, "filler_count": 0}
        gaze_data = {"total_frames": 0, "looking_frames": 0}
        audio_data = {"volumes": [], "tremble_count": 0}
        timeline_markers = []
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        out = cv2.VideoWriter('output.avi', fourcc, 20.0, (640, 480))
        self.audio_frames = []
        self.audio_stream = pa.open(format=pyaudio.paInt16, channels=1, rate=44100, input=True, frames_per_buffer=1024)
        threading.Thread(target=self.audio_recording_thread, daemon=True).start()
        threading.Thread(target=self.speech_recognition_thread, daemon=True).start()
        self.btn_start['state'] = 'disabled'; self.btn_stop['state'] = 'normal'; self.btn_question['state'] = 'normal'
        self.script_text['state'] = 'disabled'
        self.status_label.config(text="🔴 녹화 및 분석 중...", foreground="red")
        self.audience_loop()

    def audio_recording_thread(self):
        """[스레드] 오디오 녹음 및 실시간 떨림 분석"""
        last_vol = 0
        while is_recording:
            try:
                data = self.audio_stream.read(1024)
                self.audio_frames.append(data)
                rms = audioop.rms(data, 2)
                if abs(rms - last_vol) > 2000 and rms > 500: audio_data['tremble_count'] += 1
                last_vol = rms
                audio_data['volumes'].append(rms)
            except: pass

    def speech_recognition_thread(self):
        """[스레드] 실시간 음성 인식(STT) 및 속도/필러워드 분석"""
        global speech_data
        with microphone as source:
            try: recognizer.adjust_for_ambient_noise(source, duration=1)
            except: pass
            last_speech_end = time.time()
            while is_recording:
                try:
                    audio = recognizer.listen(source, timeout=2, phrase_time_limit=5)
                    text = recognizer.recognize_google(audio, language='ko-KR')
                    timestamp = time.time() - start_time - 1.5
                    words = text.split()
                    speech_data['word_count'] += len(words)
                    speech_data['full_transcript'] += text + " "
                    segment_duration = time.time() - last_speech_end
                    last_speech_end = time.time()
                    if segment_duration > 0.5:
                         instant_wpm = (len(words) / segment_duration) * 60
                         if instant_wpm > 220: self.add_marker(timestamp, '⚡️')
                         elif instant_wpm < 60 and len(words) > 2: self.add_marker(timestamp, '🐢')
                    chunk_filler = 0
                    for word in words:
                        if any(f in word for f in FILLER_WORDS):
                            chunk_filler += 1; speech_data['filler_count'] += 1
                    if chunk_filler > 0: self.add_marker(timestamp, '💬')
                except sr.WaitTimeoutError:
                     if time.time() - last_speech_end > 5.0:
                         self.add_marker(time.time() - start_time - 5.0, '🤐')
                         last_speech_end = time.time()
                     continue
                except: pass

    def add_marker(self, t, emoji):
        """타임라인에 마커 추가 (중복 방지)"""
        if not timeline_markers or (t - timeline_markers[-1]['time'] > 1.5) or timeline_markers[-1]['label'] != emoji:
             timeline_markers.append({'time': max(0.1, t), 'label': emoji})

    def audience_loop(self):
        """가상 청중 반응 루프"""
        if not is_recording: return
        mood = self.user_settings.get('atmosphere', '정보')
        weights = [0.8, 0.2, 0] if '정보' in mood else [0.3, 0.4, 0.3] if '설득' in mood else [0.5, 0.4, 0.1]
        s1, s2 = random.choices(['default', 'focused', 'distracted'], weights=weights, k=2)
        self.update_audience_images(s1, s2)
        if self.winfo_exists(): self.after(4000, self.audience_loop)

    def trigger_question_event(self):
        """⚡️ 돌발 질문 (모드별 AI 질문 생성)"""
        if random.choice([True, False]): self.update_audience_images('question', 'focused')
        else: self.update_audience_images('focused', 'question')
        self.update()
        
        script = self.script_text.get("1.0", tk.END).strip()
        mode = self.user_settings.get('atmosphere', '정보')
        question = None

        try:
            if '정보' in mode:
                question = self.imrad_generator.generate_question(script)
            elif '설득' in mode:
                question = self.dynamic_generator.generate_question(script, 'B')
            elif '공감' in mode:
                question = self.dynamic_generator.generate_question(script, 'C')
        except Exception as e:
            print(f"질문 생성 오류: {e}")
            question = None
            
        if not question: # AI 질문 생성 실패 시 백업 질문 사용
            question = random.choice(BACKUP_QUESTIONS)
            
        self.add_marker(time.time() - start_time, '❓')
        self.after(500, lambda: messagebox.showinfo("💡 돌발 질문", question))

    def stop_recording(self):
        """녹화 중지 및 키워드 추출"""
        global is_recording
        self.original_script = self.script_text.get("1.0", tk.END).strip()
        
        print("대본 분석 및 키워드 추출 중...")
        try:
            self.extracted_keywords = self.analysis_manager.extract_keywords_from_script(
                self.original_script, AI_AVAILABLE, self.gemini_model
            )
        except Exception as e:
            print(f"키워드 추출 중 오류 발생: {e}")
            
        is_recording = False
        self.btn_stop['state'] = 'disabled'
        self.status_label.config(text="⏳ 녹화 종료! 결과 분석 중입니다...", foreground="blue")
        self.update()
        threading.Thread(target=self.finalize_recording, daemon=True).start()

    def finalize_recording(self):
        """[스레드] 녹화 파일 저장 및 분석 페이지 호출"""
        global cap, out
        try:
            if self.audio_stream.is_active(): self.audio_stream.stop_stream()
            self.audio_stream.close()
        except: pass
        wf = wave.open("output.wav", 'wb'); wf.setnchannels(1); wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16)); wf.setframerate(44100); wf.writeframes(b''.join(self.audio_frames)); wf.close()
        time.sleep(1.0)
        if cap: cap.release()
        if out: out.release()
        cap = None; out = None
        if self.winfo_exists(): self.after(0, self.show_analysis_page)

    def show_analysis_page(self):
        """결과 분석 페이지"""
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
        
        # --- 점수 계산 (AnalysisManager 활용) ---
        duration_min = max(0.1, (time.time() - start_time) / 60)
        wpm = int(speech_data['word_count'] / duration_min)
        score_speed = max(0, 100 - abs(130 - wpm))
        total_frames = max(1, gaze_data['total_frames'])
        gaze_ratio = int((gaze_data['looking_frames'] / total_frames) * 100)
        score_gaze = min(100, int(gaze_ratio * 1.43))
        mode = self.user_settings.get('atmosphere', '정보')
        
        match_rate, match_label_text = self.analysis_manager.calculate_smart_match(
            self.original_script, speech_data['full_transcript'], mode
        )
        score_match = match_rate
        
        filler_deduction = speech_data['filler_count'] * 3
        tremble_score = max(0, 100 - int(audio_data['tremble_count'] / duration_min * 2))
        score_fluency = int((max(0, 100 - filler_deduction) + tremble_score) / 2)
        
        # 모드별 가중치 적용
        if '정보' in mode: total_score = int(score_match * 0.4 + score_fluency * 0.3 + score_gaze * 0.2 + score_speed * 0.1)
        elif '설득' in mode: total_score = int(score_gaze * 0.4 + score_speed * 0.2 + score_fluency * 0.2 + score_match * 0.2)
        else: total_score = int(score_match * 0.3 + score_gaze * 0.3 + score_fluency * 0.2 + score_speed * 0.2)
        self.save_history(total_score)
        
        # --- UI 생성 ---
        tk.Label(content, text=f"🏆 종합 점수: {total_score}점", font=("Arial", 36, "bold"), fg="#007aff").pack(pady=20)
        summary = ttk.Frame(content); summary.pack(pady=10, fill='x')
        for i in range(4): summary.columnconfigure(i, weight=1)
        self.create_stat_card(summary, 0, "🗣️ 속도", f"{wpm} WPM", score_speed)
        self.create_stat_card(summary, 1, f"📝 {match_label_text}", f"{match_rate}%", score_match)
        self.create_stat_card(summary, 2, "👀 시선 처리", f"{gaze_ratio}%", score_gaze)
        self.create_stat_card(summary, 3, "🌊 유창성", f"{score_fluency}점", score_fluency)
        
        self.create_video_player(content)
        self.create_score_graph(content)
        
        # AI 또는 로컬 피드백 생성
        self.create_feedback_section(content, mode, match_rate, gaze_ratio, score_fluency, wpm, speech_data['full_transcript'], audio_data['volumes'])
        
        ttk.Button(content, text="처음으로 돌아가기", command=self.show_setup_page).pack(pady=30)
        self.load_video()

    def create_stat_card(self, parent, col, title, value, score):
        """점수 카드 UI 생성"""
        frame = tk.Frame(parent, bg="white", bd=1, relief="solid")
        frame.grid(row=0, column=col, padx=10, sticky="nsew")
        tk.Label(frame, text=title, font=("Arial", 12, "bold"), bg="white").pack(pady=(10,5))
        tk.Label(frame, text=value, font=("Arial", 18), fg="#007aff", bg="white").pack()
        tk.Label(frame, text=f"(점수: {score})", font=("Arial", 10), fg="gray", bg="white").pack(pady=(0,10))

    def create_video_player(self, parent):
        """비디오 플레이어 UI 생성"""
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
        """점수 기록 그래프 UI 생성"""
        graph_frame = ttk.Frame(parent); graph_frame.pack(fill='x', pady=20, padx=20)
        fig, ax = plt.subplots(figsize=(8, 2.5))
        if len(self.history) > 0:
            ax.plot(range(1, len(self.history) + 1), self.history, marker='o', linestyle='-', color='#007aff', linewidth=2)
            ax.fill_between(range(1, len(self.history) + 1), self.history, color='#007aff', alpha=0.1)
            ax.set_title("연습 점수 트렌드"); ax.set_ylim(0, 105); ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True)); ax.grid(True, linestyle='--')
        canvas = FigureCanvasTkAgg(fig, master=graph_frame); canvas.draw(); canvas.get_tk_widget().pack(fill='both')

    def create_feedback_section(self, parent, mode_raw, match_rate, gaze_ratio, fluency, wpm, transcript, volume_data):
        """AI 코칭 리포트 또는 로컬 피드백 UI 생성"""
        fb_frame = tk.LabelFrame(parent, text="🤖 AI 코치 피드백", font=("Arial", 14, "bold"))
        fb_frame.pack(fill='x', pady=20, ipady=10)
        
        if '정보' in mode_raw: mapped_mode = '논리적'; target_type_key = 'A'
        elif '공감' in mode_raw: mapped_mode = '친화적'; target_type_key = 'C'
        else: mapped_mode = '열정적'; target_type_key = 'B'
        
        style_feedback = self.analysis_manager.analyze_speech_style(transcript, mapped_mode)
        energy_feedback = self.analysis_manager.analyze_vocal_energy(volume_data, mapped_mode)
        delivery_metrics = {"wpm": wpm}
        
        feedback_report = None
        
        if AI_COACH_AVAILABLE and self.client:
            print("AI 코칭 리포트 생성을 시도합니다...")
            feedback_report = self.analysis_manager.generate_ai_feedback(
                self.client,
                transcript, 
                target_type_key, 
                delivery_metrics, 
                style_feedback, 
                energy_feedback
            )
        else:
            print("AI 코칭 API를 사용할 수 없습니다. 로컬 규칙 기반 피드백을 생성합니다.")

        if feedback_report is None: # AI 리포트 생성 실패 시 로컬 피드백으로 대체
            feedback_report = f"선택하신 [{mode_raw.split(' ')[1]}] 모드 기준 분석 결과입니다.\n\n"
            if mapped_mode == '논리적':
                if match_rate < 95: feedback_report += "⚠️ [정확성] 정보 전달은 정확성이 핵심입니다. 대본 숙지도를 더 높여보세요.\n"
                else: feedback_report += "✅ [정확성] 대본 전달이 매우 정확했습니다.\n"
            elif mapped_mode == '열정적':
                if gaze_ratio < 70: feedback_report += "⚠️ [시선] 설득력을 높이려면 청중을 더 강렬하고 끈기 있게 응시해야 합니다.\n"
                else: feedback_report += "✅ [시선] 자신감 있는 시선 처리가 돋보였습니다.\n"
            elif mapped_mode == '친화적':
                if match_rate > 95: feedback_report += "⚠️ [자연스러움] 너무 대본을 읽는 느낌입니다. 조금 더 대화하듯 편안하게 말해보세요.\n"
            
            feedback_report += energy_feedback
            feedback_report += style_feedback
            if fluency < 70: feedback_report += "⚠️ [유창성] 목소리 떨림이나 '음, 어' 같은 필러워드가 감지되었습니다. 호흡을 가다듬어 보세요.\n"
            if wpm > 150: feedback_report += f"⚠️ [속도] 말이 다소 빠릅니다 ({wpm} WPM). 청중이 이해할 시간을 주세요.\n"
            
            if len(feedback_report.split('\n')) < 6:
                feedback_report += "\n🎉 전반적으로 아주 훌륭한 발표 역량을 보여주셨습니다!"
        
        tk.Label(fb_frame, text=feedback_report, font=("Arial", 12), justify="left", wraplength=800, padx=20).pack(anchor='w', fill='x')

    # --- 비디오 플레이어 제어 ---
    def load_video(self):
        self.vid_cap = cv2.VideoCapture('output.avi')
        if not self.vid_cap.isOpened(): return
        self.vid_duration = max(1, self.vid_cap.get(cv2.CAP_PROP_FRAME_COUNT) / self.vid_cap.get(cv2.CAP_PROP_FPS))
        self.is_playing = False
        self.draw_timeline()
        self.vid_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self.update_frame()

    def draw_timeline(self):
        self.timeline.delete("all")
        self.update_idletasks()
        w = self.timeline.winfo_width()
        self.timeline.create_line(0, 20, w, 20, fill="#ced4da", width=2)
        for m in timeline_markers:
            if self.vid_duration > 0:
                x = (m['time'] / self.vid_duration) * w
                self.timeline.create_text(x, 20, text=m['label'], font=("Arial", 16), tags=(str(m['time']),))

    def on_timeline_click(self, event):
        tags = self.timeline.gettags(self.timeline.find_closest(event.x, event.y))
        if tags: self.seek(float(tags[0]))

    def on_slider_move(self, val): 
        self.seek((float(val) / 100) * self.vid_duration)
        
    def seek(self, sec):
        if self.vid_cap:
            self.vid_cap.set(cv2.CAP_PROP_POS_FRAMES, int(sec * self.vid_cap.get(cv2.CAP_PROP_FPS)))
            self.update_frame()

    def play_video_with_sound(self):
        if self.is_playing: return
        self.is_playing = True
        try: winsound.PlaySound("output.wav", winsound.SND_ASYNC | winsound.SND_FILENAME)
        except: pass
        self.play_video_loop()

    def stop_video(self):
        self.is_playing = False
        try: winsound.PlaySound(None, winsound.SND_PURGE)
        except: pass

    def play_video_loop(self):
        if not self.winfo_exists(): return
        if not self.vid_cap or not self.vid_cap.isOpened(): return
        if self.is_playing:
            ret, frame = self.vid_cap.read()
            if ret:
                self.show_frame(frame)
                current_pos = self.vid_cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
                self.vid_slider.set((current_pos / self.vid_duration) * 100)
                self.after(33, self.play_video_loop)
            else: self.stop_video()

    def update_frame(self):
        ret, frame = self.vid_cap.read()
        if ret: self.show_frame(frame)

    def show_frame(self, frame):
        w = self.vid_player_label.winfo_width()
        if w > 1:
            h = int(w * 3 / 4)
            img = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).resize((w, h)))
            self.vid_player_label.configure(image=img); self.vid_player_label.image = img

if __name__ == "__main__":
    app = App()
    app.mainloop()