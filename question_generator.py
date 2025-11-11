import random
import google.generativeai as genai

class IMRADValidator:
    """[수정] 정보 전달형 대본의 논리적 허점을 AI 또는 규칙 기반으로 찾는 Validator"""
    def __init__(self, text_model=None):
        """[수정] Gemini 텍스트 모델을 주입받습니다."""
        self.text_model = text_model
        
        # --- 기존 규칙 (규칙 기반 질문 생성에 사용) ---
        self.rules = {
            '서론': {
                'triggers': ['기존', '선행', '차별', '다르', '독창', '새로', '차별점', '새로운'],
                'question': "[서론 경고] 기존 연구들과 구별되는 이 발표만의 '차별점(Novelty)'이 명확하지 않습니다.",
                'template_key': 'introduction' 
            },
            '방법': {
                'triggers': ['때문에', '이유', '선정', '고려하여', '채택', '위하여 선정'],
                'question': "[방법 경고] 선택한 연구 방법론에 대한 '구체적인 이유(Justification)'나 대안 고려가 부족합니다.",
                'template_key': 'methods'
            },
            '고찰': { 
                'triggers': ['한계', '아쉬', '부족', '후속', '향후', '제언', '아쉬운', '부족한', '향후 과제'],
                'question': "[고찰 경고] 연구의 '한계점(Limitation)'이나 향후 보완 계획에 대한 언급이 누락되었습니다.",
                'template_key': 'discussion'
            },
            '결과': { 
                'required_if': ['상관관계', '관련이 있', '나타났습'],
                'defense_triggers': ['추가 검증', '가능성', '해석에 주의', '인과관계', '후속', '인과관계일 가능성'],
                'question': "[결과 경고] 상관관계를 성급하게 인과관계로 단정 짓고 있지 않나요? '추가 검증'의 필요성을 언급하세요.",
                'template_key': 'results'
            }
        }
        self.imrad_templates = {
            'introduction': "기존 선행 연구들과 비교했을 때, 이 발표만이 가지는 가장 결정적인 차별점(Novelty)은 무엇입니까?",
            'methods': "선택하신 연구 방법론의 구체적인 선정 이유는 무엇이며, 다른 대안은 고려하지 않으셨나요?",
            'results': "결과에서 발견된 상관관계를 인과관계로 확정하기 위해 추가로 고려해야 할 변수가 있을까요?",
            'discussion': "연구를 진행하면서 가장 아쉬웠던 한계점이나, 후속 연구에서 보완하고 싶은 점은 무엇입니까?"
        }
        
        # --- AI 기반 질문 생성을 위한 프롬프트 ---
        self.ai_prompt_template = """
        당신은 발표자의 논리적 허점을 찾아내는 날카로운 학술 리뷰어입니다.
        다음 발표 대본을 읽고, IMRAD (서론, 방법, 결과, 고찰) 구조에 입각하여 가장 치명적이거나 의심스러운 부분에 대해 날카로운 반박 질문을 '하나만' 한국어로 생성하세요.

        [규칙]
        - 서론의 '목적'이 불분명하거나,
        - 방법론의 '선정 이유'가 부족하거나,
        - 결과의 '해석'이 과장되었거나,
        - 고찰의 '한계점'이 누락된 부분을 집중적으로 공격하세요.
        - 질문은 한 문장으로, 정중하지만 핵심을 꿰뚫어야 합니다.
        - 절대로 두 문장 이상으로 답하지 마세요.

        [대본]
        {script}

        [질문]
        """

    def _check_keywords(self, text, keywords):
        for keyword in keywords:
            if keyword in text:
                return True
        return False

    def validate_imrad_sections(self, script):
        """AI 심화 피드백에 사용될 논리 검증 리포트 생성"""
        report = []
        for section, rule in self.rules.items():
            if section == '결과': continue
            if not self._check_keywords(script, rule['triggers']):
                if rule['question'] not in report:
                    report.append(rule['question'])

        rule_results = self.rules['결과']
        needs_check = self._check_keywords(script, rule_results['required_if'])
        has_defense = self._check_keywords(script, rule_results['defense_triggers'])
        
        if needs_check and not has_defense:
            if rule_results['question'] not in report:
                report.append(rule_results['question'])
        return report

    def _get_rule_based_imrad_question(self, script):
        """기존의 규칙 기반 질문 생성 로직 (분리)"""
        rule_intro = self.rules['서론']
        if not self._check_keywords(script, rule_intro['triggers']):
            return self.imrad_templates[rule_intro['template_key']]

        rule_methods = self.rules['방법']
        if not self._check_keywords(script, rule_methods['triggers']):
            return self.imrad_templates[rule_methods['template_key']]

        rule_results = self.rules['결과']
        needs_check = self._check_keywords(script, rule_results['required_if'])
        has_defense = self._check_keywords(script, rule_results['defense_triggers'])
        if needs_check and not has_defense:
            return self.imrad_templates[rule_results['template_key']]

        rule_discussion = self.rules['고찰']
        if not self._check_keywords(script, rule_discussion['triggers']):
            return self.imrad_templates[rule_discussion['template_key']]
            
        return None # 허점 없음

    def _generate_ai_imrad_question(self, script):
        """AI를 사용하여 실시간으로 질문 생성"""
        if not self.text_model:
            print("IMRADValidator: AI 모델이 없어 AI 질문을 생성할 수 없습니다.")
            return None
        
        try:
            full_prompt = self.ai_prompt_template.format(script=script)
            response = self.text_model.generate_content(full_prompt)
            ai_question = response.text.strip().replace("\n", "")
            return ai_question
        except Exception as e:
            print(f"AI 질문 생성 실패 (IMRAD): {e}")
            return None

    def generate_imrad_question(self, script):
        """돌발 질문용: 50% 확률로 AI 또는 규칙 기반 질문 생성"""
        
        # 50% 확률로 AI 질문 생성 시도 (AI 모델이 있을 경우)
        if self.text_model and random.choice([True, False]):
            print("[질문 생성] AI (정보형) 질문 생성 시도...")
            ai_question = self._generate_ai_imrad_question(script)
            if ai_question:
                return ai_question
        
        print("[질문 생성] 규칙 기반 (정보형) 질문 생성 시도...")
        rule_question = self._get_rule_based_imrad_question(script)
        
        if rule_question:
            return rule_question
        else:
            return self.imrad_templates['discussion'] # '한계점' 질문을 기본값으로 사용

class DynamicQuestionGenerator:
    """[수정] 설득형(B) 및 공감형(C) 대본의 허점을 AI 또는 규칙 기반으로 찾는 질문 생성기"""
    def __init__(self, text_model=None):
        """[수정] Gemini 텍스트 모델을 주입받습니다."""
        self.text_model = text_model
        
        # --- 기존 규칙 (규칙 기반 질문 생성에 사용) ---
        self.question_db = {
            "B": {
                "action_check": {
                    "triggers": ["노력합시다", "관심 바랍니다", "기대합니다", "좋겠습니다"],
                    "questions": [
                        "좋은 제안입니다. 그렇다면 당장 내일부터 우리가 실행해야 할 '구체적인 첫 번째 행동'은 무엇입니까?",
                        "청중이 발표장을 나서자마자 바로 실천할 수 있는 가장 작은 행동 하나를 제안한다면 무엇인가요?"
                    ]
                },
                "urgency_check": {
                    "triggers": ["장기적으로", "언젠가", "앞으로", "차차"],
                    "questions": [
                        "왜 하필 '지금(NOW)' 이 행동을 해야 합니까? 다음 달로 미뤘을 때 발생하는 가장 큰 손실은 무엇인가요?",
                        "이 제안을 지금 당장 실행하지 않았을 때 우리가 감수해야 할 최악의 시나리오는 무엇입니까?"
                    ]
                },
                "obstacle_check": {
                    "triggers": ["최고의", "완벽한", "문제없는", "확실한 성공"],
                    "questions": [
                        "기대 효과는 인상적입니다. 하지만 이것을 실현하기 위해 넘어야 할 가장 큰 '현실적인 장애물'은 무엇이며, 어떻게 극복할 계획입니까?",
                        "이 제안에 반대하는 사람들이 가장 우려할 만한 점은 무엇이라고 생각하십니까?"
                    ]
                }
            },
            "C": {
                "relatability_check": {
                    "triggers": ["저는 성공했고", "제가 해냈습니다", "1등", "최고의 성과"],
                    "questions": [
                        "놀라운 성과네요. 그렇다면 그 개인적인 성공 경험이 여기 있는 평범한 청중들의 삶에는 어떻게 적용될 수 있을까요?",
                        "발표자님과 다른 상황에 처한 청중들도 그 이야기에 공감할 수 있는 연결 고리는 무엇입니까?"
                    ]
                },
                "vulnerability_check": {
                    "triggers": ["항상", "반드시", "완벽하게", "쉬웠습니다"],
                    "questions": [
                        "혹시 그 과정에서 포기하고 싶었거나 가장 부끄러웠던 '실패의 순간'은 언제였나요? 그 이야기를 듣고 싶습니다.",
                        "가장 힘들었던 순간에 자신을 지탱해준 단 하나의 생각은 무엇이었습니까?"
                    ]
                },
                 "empathy_action_check": {
                    "triggers": ["힘냅시다", "응원합니다", "다 잘될 겁니다"],
                    "questions": [
                        "따뜻한 위로 감사합니다. 지금 비슷한 힘든 시기를 겪는 사람에게 해주고 싶은 가장 '현실적인 조언' 한 가지는 무엇인가요?",
                        "당시의 발표자님에게 가장 필요했던 구체적인 도움은 무엇이었나요?"
                    ]
                }
            }
        }
        
        # ---AI 기반 질문 생성을 위한 프롬프트 템플릿 ---
        self.ai_prompt_templates = {
            "B": """
            당신은 발표자의 주장을 쉽게 믿지 않는 회의적인 투자자(VC)입니다.
            다음 '설득형' 발표 대본을 읽고, 청중의 행동을 이끌어내기에 '부족한 점'을 찾아 공격적인 질문을 '하나만' 한국어로 생성하세요.

            [규칙]
            - 주장의 '근거'가 빈약하거나,
            - '지금 당장' 행동해야 할 '시급성(Urgency)'이 부족하거나,
            - 제안한 행동의 '현실적인 장애물'을 간과한 부분을 집중적으로 공격하세요.
            - 질문은 한 문장으로, 핵심을 꿰뚫어야 합니다.
            - 절대로 두 문장 이상으로 답하지 마세요.

            [대본]
            {script}

            [질문]
            """,
            "C": """
            당신은 발표자의 이야기에 공감하고 싶지만, 과장이나 비약은 경계하는 청중입니다.
            다음 '공감형' 발표 대본을 읽고, 발표자의 '진정성'을 확인하거나 더 깊은 공감을 이끌어내기 위한 질문을 '하나만' 한국어로 생성하세요.

            [규칙]
            - 발표자의 '성공담'이 청중과 괴리되어 보일 때 (적용점 질문),
            - 발표자의 '경험'이 너무 완벽하게 묘사될 때 (실패/극복 과정 질문),
            - '위로'가 구체적인 조언 없이 피상적일 때를 파고드세요.
            - 질문은 한 문장으로, 따뜻하지만 깊이가 있어야 합니다.
            - 절대로 두 문장 이상으로 답하지 마세요.

            [대본]
            {script}

            [질문]
            """
        }

    def _get_rule_based_dynamic_question(self, script, target_type):
        """[신규] 기존의 규칙 기반 질문 생성 로직 (분리)"""
        type_db = self.question_db.get(target_type.upper())
        if not type_db: return None
        
        possible_questions = []
        for check_point, data in type_db.items():
            if any(trigger in script for trigger in data['triggers']):
                possible_questions.extend(data['questions'])
                
        if not possible_questions:
            # 기본 질문
            if target_type.upper() == "B": return "이 제안을 한 문장으로 요약했을 때, 청중이 꼭 기억해야 할 핵심 메시지는 무엇입니까?"
            elif target_type.upper() == "C": return "이 이야기를 통해 청중들이 어떤 감정을 느끼고 돌아가기를 가장 원하십니까?"
            else: return None
            
        return random.choice(possible_questions)

    def _generate_ai_dynamic_question(self, script, target_type):
        """[신규] AI를 사용하여 실시간으로 질문 생성"""
        if not self.text_model:
            print(f"DynamicGenerator: AI 모델이 없어 AI 질문 ({target_type})을 생성할 수 없습니다.")
            return None
            
        prompt_template = self.ai_prompt_templates.get(target_type.upper())
        if not prompt_template:
            return None 
        
        try:
            full_prompt = prompt_template.format(script=script)
            response = self.text_model.generate_content(full_prompt)
            ai_question = response.text.strip().replace("\n", "")
            return ai_question
        except Exception as e:
            print(f"AI 질문 생성 실패 (Dynamic {target_type}): {e}")
            return None

    def generate_question(self, script, target_type):
        """돌발 질문용: 50% 확률로 AI 또는 규칙 기반 질문 생성"""
        
        # 50% 확률로 AI 질문 생성 시도 (AI 모델이 있을 경우)
        if self.text_model and random.choice([True, False]):
            print(f"[질문 생성] AI ({target_type}형) 질문 생성 시도...")
            ai_question = self._generate_ai_dynamic_question(script, target_type)
            if ai_question:
                return ai_question
        
        print(f"[질문 생성] 규칙 기반 ({target_type}형) 질문 생성 시도...")
        return self._get_rule_based_dynamic_question(script, target_type)
