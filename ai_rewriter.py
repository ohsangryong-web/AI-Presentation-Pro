import os
import threading
import time
import winsound
import base64 
import struct 
import wave   

# =========================================
# [설정] 강화된 프롬프트 엔진
# =========================================
FINAL_CONFIG = {
    "role": {
        "identity": "Expert Speech Writer & Communication Psychologist",
        "core_rules": [
             "NEVER add NEW facts/data not in source.",
             "PRESERVE core message integrity.",
             "MUST be read-aloud friendly (natural spoken Korean)."
        ]
    },
    "styles": {
        "A": {
            "name": "📘 정보 전달형 (Informational)",
            "focus": "Clarity, Accuracy, Logical Structure (IMRAD)",
            "guide": """
            1. [Structure] Reorganize into 'Introduction(배경/목적)-Methods(방법)-Results(결과)-Discussion(의미)' if applicable.
            2. [Clarity] Replace vague adjectives with exact data from the text. Remove emotional fluff.
            3. [Tone] Objective, professional, and analytical.
            """
        },
        "B": {
            "name": "🔥 설득/동기부여형 (Persuasive)",
            "focus": "Action, Impact, Psychological Triggers",
            "guide": """
            1. [Structure] Use Monroe's Motivated Sequence (Attention -> Need -> Satisfaction -> Visualization -> Action).
            2. [Principles] Apply Cialdini's principles:
                - Authority: Cite sources confidently.
                - Scarcity: Emphasize what is lost if NO action is taken NOW.
                - Social Proof: Imply consensus or successful precedents.
            3. [Magic Words]
                - Use Nouns for identity ("Be a voter" > "Vote").
                - Use 'Don't' over 'Can't' for agency.
                - Use strong, definitive action verbs.
            """
        },
        "C": {
            "name": "🤝 공감/소통형 (Emotional)",
            "focus": "Rapport, Vulnerability, Storytelling",
            "guide": """
            1. [Structure] Use a Story Arc (Struggle -> Realization -> Growth).
            2. [Connection]
                - Share Vulnerability: Admit minor flaws/struggles to build relatability.
                - Use 'We/Us' language frequently.
                - Invite audience reflection with soft rhetorical questions ("Have you ever felt...?").
                - Tone: Warm, sincere, conversational (use natural Korean endings like ~했어요, ~잖아요).
            """
        }
    }
}

class AI_Announcer:
    def __init__(self, text_model, tts_model):
        """(MODIFIED) 텍스트 모델과 TTS 모델을 별도로 전달받음"""
        self.text_model = text_model
        self.tts_model = tts_model # 'gemini-2.5-flash-preview-tts' 모델 객체

    def rewrite(self, script, type_code):
        """(MODIFIED) 텍스트 모델(gemini-2.5-pro)을 사용하여 대본 재작성"""
        if self.text_model is None:
            return "❌ Gemini 텍스트 모델이 초기화되지 않아 대본 재작성이 불가능합니다."

        style = FINAL_CONFIG["styles"].get(type_code, FINAL_CONFIG["styles"]["A"])
        
        system_prompt = f"""
        You are an {FINAL_CONFIG['role']['identity']}.
        Rewrite the user's script following these strict rules:
        {chr(10).join(FINAL_CONFIG['role']['core_rules'])}

        ### TARGET STYLE: {style['name']}
        FOCUS: {style['focus']}
        GUIDELINES:
        {style['guide']}

        Output ONLY the rewritten script in Korean. Do not include any introductory or concluding remarks.
        """
        
        full_prompt = system_prompt + f"\n\n--- USER SCRIPT ---\n{script}"

        try:
            # (MODIFIED) 텍스트 모델로 API 호출
            response = self.text_model.generate_content(full_prompt)
            return response.text
        except Exception as e:
            return f"❌ 대본 재작성 오류 발생: Gemini API(Text) 호출 실패. {e}"

    # --- Gemini TTS를 위한 헬퍼 함수 ---
    def _base64_to_array_buffer(self, base64_str):
        """Base64 문자열을 디코딩하여 raw audio bytes로 반환"""
        return base64.b64decode(base64_str)

    def _pcm_to_wav(self, pcm_data, filename, channels=1, sample_width=2, frame_rate=24000):
        """RAW PCM 데이터를 WAV 파일 형식으로 변환"""
        # 참고: API가 24kHz, 16-bit, single-channel PCM을 반환한다고 가정합니다.
        try:
            with wave.open(filename, 'wb') as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(sample_width) # 16-bit = 2 bytes
                wf.setframerate(frame_rate)   # 24kHz
                wf.writeframes(pcm_data)
            return filename
        except Exception as e:
            print(f"WAV 파일 변환 오류: {e}")
            return None
    # --- (END 헬퍼 함수) ---

    def speak(self, text, filename="temp_tts_output.wav"):
        """(MODIFIED) TTS 모델(gemini-2.5-flash-preview-tts)을 사용하여 음성 합성 후 재생"""
        if self.tts_model is None: 
            print("Gemini TTS 모델이 없어 TTS를 재생할 수 없습니다.")
            return False
        
        print(f"🎙️ Gemini TTS 음성 합성 시작 (모델: {self.tts_model.model_name})...")
        
        try:
            # (FIX) 400 오류 수정: 'generation_config'를 최신 API 사양으로 변경
            # (FIX) 파이썬 SDK는 'text'를 contents=[...]로 감싸지 않고 직접 전달
            response = self.tts_model.generate_content(
                text, # (FIX) 텍스트 문자열을 직접 전달
                generation_config={
                    "responseModalities": ["AUDIO"], # (FIX) 'response_mime_type' 대신 사용
                }
            )

            # 응답에서 오디오 데이터(base64) 추출
            # .parts[0]가 텍스트일 수 있으므로 오디오(inlineData) 파트 검색
            audio_part = None
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    audio_part = part
                    break
            
            if not audio_part or not audio_part.inline_data.data:
                print("Gemini TTS 오류: 응답에 오디오 데이터가 없습니다.")
                return False

            audio_bytes_base64 = audio_part.inline_data.data
            
            # Base64 디코딩 (RAW PCM 데이터)
            pcm_data = self._base64_to_array_buffer(audio_bytes_base64)
            
            # PCM to WAV 파일로 저장
            saved_file = self._pcm_to_wav(pcm_data, filename)
            
            if not saved_file:
                print("Gemini TTS 오류: WAV 파일 저장에 실패했습니다.")
                return False

            print(f"✅ 완료! 파일이 저장되었습니다: {filename}")
            
            # 음성 재생 (별도 스레드)
            # (참고: winsound는 다른 소리를 중단시킬 수 있음)
            threading.Thread(target=lambda: winsound.PlaySound(filename, winsound.SND_FILENAME | winsound.SND_NOWAIT), daemon=True).start()
            return True
        
        except Exception as e:
            print(f"Gemini TTS 재생 오류: {e}")
            return False 