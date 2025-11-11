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
    def __init__(self, text_model):
        """(MODIFIED) 텍스트 모델만 전달받음 (TTS 기능 삭제)"""
        self.text_model = text_model


    def rewrite(self, script, type_code):
        """(MODIFIED) 텍스트 모델(gemini-2.5-pro)을 사용하여 대본 재작성"""
        if self.text_model is None:
            return "❌ Gemini 텍스트 모델이 초기화되지 않아 대본 재작성이 불가능합니다."

        style = FINAL_CONFIG["styles"].get(type_code, FINAL_CONFIG["styles"]["A"])
        
        system_prompt = f"""
        You are an {FINAL_CONFIG['role']['identity']}.
        Rewrite the user's script following these strict rules:
        {'\n'.join(FINAL_CONFIG['role']['core_rules'])}

        ### TARGET STYLE: {style['name']}
        FOCUS: {style['focus']}
        GUIDELINES:
        {style['guide']}

        Output ONLY the rewritten script in Korean. Do not include any introductory or concluding remarks.
        """
        
        full_prompt = system_prompt + f"\n\n--- USER SCRIPT ---\n{script}"

        try:       
            response = self.text_model.generate_content(full_prompt)
            return response.text
        except Exception as e:
            return f"❌ 대본 재작성 오류 발생: Gemini API(Text) 호출 실패. {e}"

