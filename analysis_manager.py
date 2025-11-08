import re
import numpy as np
from collections import Counter
# IMRADValidator를 question_generator에서 임포트
from question_generator import IMRADValidator 

class AnalysisManager:
    def __init__(self, stopwords, coaching_config):
        self.STOPWORDS = stopwords
        self.COACHING_CONFIG = coaching_config
        self.imrad_validator = IMRADValidator() # IMRAD 검증기 인스턴스화

    def extract_keywords_from_script(self, script, ai_available, gemini_model):
        """AI 또는 로컬 방식으로 대본에서 핵심 키워드 5개 추출"""
        extracted_keywords = []
        if ai_available and len(script) > 50 and gemini_model:
            try:
                prompt = (f"다음 발표 대본에서 가장 중요한 '핵심 명사' 5개만 추출해줘. "
                          f"추상적인 단어보다는 구체적인 소재나 데이터 관련 단어 위주로.\n"
                          f"결과는 쉼표로 구분해서 단어만 나열해줘 (예: 인공지능, 매출, 데이터, 고객, 설문조사):\n\n{script[:2000]}")
                response = gemini_model.generate_content(prompt)
                if response.text:
                    extracted_keywords = [k.strip() for k in response.text.split(',')]
                    print(f">>> [AI] 추출 키워드: {extracted_keywords}")
                    return extracted_keywords
            except Exception as e:
                 print(f"Gemini API 키워드 추출 실패 (로컬 분석으로 전환): {e}")
        
        # AI 실패 시 로컬 분석
        raw_words = re.findall(r'[가-힣a-zA-Z]{2,}', script)
        meaningful_words = []
        for w in raw_words:
            if w not in self.STOPWORDS and not any(w.startswith(sw) for sw in self.STOPWORDS if len(sw) > 1):
                 meaningful_words.append(w)
        counter = Counter(meaningful_words)
        extracted_keywords = [word for word, freq in counter.most_common(5)]
        print(f">>> [로컬] 추출 키워드: {extracted_keywords}")
        return extracted_keywords

    def calculate_smart_match(self, original, transcribed, mode):
        """대본과 STT 결과의 일치율 분석 (모드별 차등 적용)"""
        def clean_all(t): return re.sub(r'[^\w\s]', '', t).lower().split()
        if '정보' in mode:
            orig_set = set(clean_all(original)); trans_set = set(clean_all(transcribed)); label = "대본 정확도"
            if not orig_set: return 0, label
            orig_set = orig_set - self.STOPWORDS
            trans_set = trans_set - self.STOPWORDS
            if not orig_set: return 0, label
            return int((len(orig_set.intersection(trans_set)) / len(orig_set)) * 100), label
        else:
            raw_words = clean_all(original)
            keywords = set([w for w in raw_words if len(w) >= 2 and w not in self.STOPWORDS])
            trans_set = set([w for w in clean_all(transcribed) if w in keywords])
            label = "핵심 전달률"
            if not keywords: return 0, label
            return min(100, int((len(keywords.intersection(trans_set)) / len(keywords)) * 100 * 1.25)), label

    def analyze_vocal_energy(self, volume_data, mapped_mode):
        """볼륨 데이터의 표준편차로 에너지(역동성) 분석"""
        if not volume_data or len(volume_data) < 2: 
            return "⚠️ [에너지 분석] 오디오 데이터가 부족합니다."
        
        std_dev = np.std(volume_data)
        # audioop.rms (0~32768) 스케일에 맞춘 임계값
        energy_score = min(100, max(0, int((std_dev - 50) / 450 * 100))) 

        feedback = ""
        if mapped_mode == '열정적':
            if energy_score >= 70:
                feedback = f"🔥 [에너지 분석] 에너지가 넘칩니다! (점수: {energy_score}점) 열정적인 분위기가 잘 전달되었습니다.\n"
            else:
                feedback = f"⚠️ [에너지 분석] 에너지가 더 필요합니다. (점수: {energy_score}점) 강조할 부분에서 목소리를 확실히 키워보세요.\n"
        elif mapped_mode == '논리적':
            if energy_score <= 40:
                feedback = "✅ [에너지 분석] 차분하고 안정적인 톤으로 신뢰감을 주었습니다.\n"
            else:
                feedback = f"⚠️ [에너지 분석] 다소 흥분한 것처럼 들릴 수 있습니다. (점수: {energy_score}점) 차분한 톤을 유지해보세요.\n"
        else: # 친화적
            if 30 <= energy_score <= 70:
                 feedback = "✅ [에너지 분석] 듣기 편안한 안정적인 톤입니다.\n"
            elif energy_score < 30:
                 feedback = "⚠️ [에너지 분석] 자칫 지루하게 들릴 수 있습니다. 목소리에 조금 더 생기를 넣어보세요.\n"
            else:
                 feedback = "⚠️ [에너지 분석] 다소 과하거나 불안정하게 들릴 수 있습니다.\n"
        return feedback

    def analyze_speech_style(self, transcript, mapped_mode):
        """종결어미 패턴을 분석하여 어조(격식체/구어체) 피드백 생성"""
        formal_pattern = re.compile(r'(입니다|습니다|합니까|습니까|됩니다)\b')
        casual_pattern = re.compile(r'(에요|아요|어요|나요|하죠|되죠|인데요)\b')
        formal_count = len(formal_pattern.findall(transcript))
        casual_count = len(casual_pattern.findall(transcript))
        total = formal_count + casual_count
        if total == 0: return "⚠️ [어조 분석] 분석할 종결어미가 부족합니다."
        formal_ratio = (formal_count / total) * 100
        feedback = ""
        if mapped_mode == '논리적':
            if formal_ratio >= 80:
                feedback = "✅ [어조 분석] 논리적 분위기에 맞게 격식체(~입니다)를 잘 유지하셨습니다.\n"
            else:
                feedback = f"⚠️ [어조 분석] 더 신뢰감을 주기 위해 격식체 사용을 늘려보세요. (현재 격식체: {int(formal_ratio)}%)\n"
        elif mapped_mode == '친화적':
            if formal_ratio <= 50:
                 feedback = "✅ [어조 분석] 청중에게 친근하게 다가가는 부드러운 어조(~해요)가 돋보였습니다.\n"
            else:
                 feedback = f"⚠️ [어조 분석] 다소 딱딱하게 들릴 수 있습니다. 친화적인 분위기를 위해 '~해요'체를 섞어보세요. (현재 격식체: {int(formal_ratio)}%)\n"
        else: # 열정적
             feedback = "✅ [어조 분석] 역동적인 발표에 어울리는 자연스러운 어조입니다.\n"
        return feedback

    def generate_ai_feedback(self, gemini_model, script, target_type, delivery_metrics, style_feedback, energy_feedback, imrad_report):
        """Gemini를 사용하여 LLM에게 최종 리포트 생성 요청"""
        rubric = self.COACHING_CONFIG["rubrics"][target_type]
        print(f"🤖 [{rubric['type_name']}] 기준으로 Gemini 심층 코칭 리포트 작성 중...")

        imrad_data = "\n".join(imrad_report) if imrad_report else "논리적 허점 없음"

        system_prompt = f"""
        {self.COACHING_CONFIG['coach_persona']}
        목표 유형: [{rubric['type_name']}]
        평가 기준:\n{rubric['criteria']}
        
        [자동 분석 데이터]
        - 속도: {delivery_metrics['wpm']} WPM (적정: 130~150)
        - 어조 피드백 (텍스트 기반): "{style_feedback.strip()}"
        - 에너지 피드백 (오디오 기반): "{energy_feedback.strip()}"
        - (정보형) 논리 구조 검증: "{imrad_data}"

        위 데이터를 종합하여 다음 형식의 리포트를 작성하세요:
        ## 📋 AI 코칭 리포트: [{rubric['type_name']}]
        **👍 베스트 포인트** (1가지 - 주로 내용 칭찬)
        **🛠️ 개선 솔루션**
        1. (내용/구조 측면 1가지 - *'논리 구조 검증' 데이터를 최우선으로 참고*)
        2. (전달력/어조/에너지 측면 1가지 - *'자동 분석 데이터'를 근거로 제시*)
        **💡 총평** (따뜻한 격려)
        """
        
        full_prompt = system_prompt + f"\n\n--- USER SCRIPT (STT) ---\n{script}"

        try:
            response = gemini_model.generate_content(full_prompt)
            return response.text
        except Exception as e:
            print(f"Gemini 리포트 생성 실패: {e}")
            return None # 실패 시 None 반환
