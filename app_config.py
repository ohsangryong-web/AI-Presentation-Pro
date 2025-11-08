import os
import google.generativeai as genai
from matplotlib import font_manager, rc
import json

# --- 한글 폰트 설정 ---
def set_korean_font():
    """Matplotlib 한글 폰트 설정"""
    try:
        font_path = "C:/Windows/Fonts/malgun.ttf"
        font = font_manager.FontProperties(fname=font_path).get_name()
        rc('font', family=font)
    except:
        print("한글 폰트(malgun.ttf)를 찾을 수 없습니다. 그래프의 한글이 깨질 수 있습니다.")

# --- API 키 로드/저장 함수 (Gemini 전용) ---
KEYS_FILE = "keys.json"

def load_api_keys():
    """keys.json 파일에서 GEMINI_API_KEY만 불러옵니다."""
    if not os.path.exists(KEYS_FILE):
        return None
    try:
        with open(KEYS_FILE, "r") as f:
            keys = json.load(f)
            return keys.get("GEMINI_API_KEY")
    except:
        return None

def save_api_keys(gemini_key):
    """GEMINI_API_KEY를 keys.json 파일에 저장합니다."""
    keys = { "GEMINI_API_KEY": gemini_key }
    try:
        with open(KEYS_FILE, "w") as f:
            json.dump(keys, f, indent=4)
    except Exception as e:
        print(f"API 키 저장 실패: {e}")

# --- AI 코칭 평가 기준 ---
COACHING_CONFIG = {
    "coach_persona": "당신은 날카롭지만 따뜻한 전문 발표 코치입니다. '샌드위치 피드백'(칭찬-개선점-격려)을 제공합니다.",
    "rubrics": {
        "A": {
            "type_name": "📘 정보 전달형",
            "tone_mode": "논리적",
            "criteria": "- [내용] IMRAD 구조/논리적 흐름\n- [표현] 정확한 수치/팩트 사용\n- [전달] 일정한 속도, 또렷한 발음"
        },
        "B": {
            "type_name": "🔥 설득/동기부여형",
            "tone_mode": "열정적",
            "criteria": "- [내용] 강력한 행동 촉구(Call to Action)\n- [설득 기법] 심리적 트리거(희소성, 권위 등) 활용\n- [전달] 속도와 성량의 드라마틱한 변화"
        },
        "C": {
            "type_name": "🤝 공감/소통형",
            "tone_mode": "친화적",
            "criteria": "- [내용] 진솔한 경험(취약성) 공유\n- [표현] 자연스러운 구어체(대화체) 사용\n- [전달] 편안하고 따뜻한 톤"
        }
    }
}

# --- 전역 상수 ---
FILLER_WORDS = ['어', '음', '그', '뭐', '막', '이제', '좀', '그러니까', '일단']
BACKUP_QUESTIONS = [
    "해당 주장의 핵심 근거는 무엇인가요?",
    "예상되는 가장 큰 리스크는?",
    "경쟁사 대비 차별점은?"
]
HISTORY_FILE = "score_history.json"
STOPWORDS = set([
    '있습니다', '하겠습니다', '합니다', '있는', '것입니다', '생각합니다', 
    '저는', '제가', '저희', '우리', '이번', '통해', '대해', '관한', '관련',
    '가장', '매우', '정말', '특히', '바로', '모두', '다시', '먼저', '다음',
    '때문에', '그리고', '하지만', '그러나', '그래서', '또한', '결국',
    '부분', '측면', '가지', '정도', '경우', '사실', '내용', '결과', '진행',
    '발표', '주제', '시간', '자료', '준비', '시작', '마무리', '이상', '감사',
    '은', '는', '이', '가', '을', '를', '에', '에서', '로', '으로', '하다', '이다'
])