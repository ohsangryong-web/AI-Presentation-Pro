import random
import google.generativeai as genai

class IMRADValidator:
    """[수정] 정보 전달형 대본의 논리적 허점을 찾는 Validator (50% 확률로 AI 사용)"""
    def __init__(self, text_model=None):
        self.text_model = text_model
        
        # 1. [기존 유지] 규칙 기반 로직 데이터
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
        
        # 2. [강화됨] AI 페르소나 및 프롬프트 (독설가 모드)
        self.ai_prompt_template = """
        당신은 이 분야의 최고 권위자이자, 아주 까다롭고 비판적인 '학술지 심사위원(Reviewer)'입니다.
        아래 발표 대본을 분석하여, 논리적으로 가장 취약하거나 근거가 부족한 부분을 찾아 '치명적인 반박 질문'을 하나 던지세요.

        [공격 포인트]
        1. '서론': 기존 연구와의 차별점이 단순히 "우리가 처음이다"라는 식이면 공격하세요.
        2. '방법': 왜 하필 그 방법을 썼는지, 더 나은 대안은 없었는지 따지세요.
        3. '결과': 상관관계를 인과관계인 것처럼 과장해서 해석했다면 즉시 지적하세요.
        4. '고찰': 연구의 한계점을 교묘하게 감추려 한다면 그 부분을 파고드세요.

        [출력 형식]
        - 질문은 한국어로 작성하세요.
        - **발표자의 발언 내용을 짧게 인용**하여 모순을 지적한 뒤 질문하세요. 
          (예: "발표 초반에는 ~라고 하셨는데, 결과에서는 ~게 나타났습니다. 이 모순을 어떻게 설명하시겠습니까?")
        - 단순히 "이유가 무엇인가요?" 같은 열린 질문은 금지합니다. 발표자가 당황할 만큼 구체적인 근거를 요구하세요.

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
        """AI 심화 피드백에 사용될 논리 검증 리포트 생성 (규칙 기반)"""
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
        """기존의 규칙 기반 질문 생성 로직"""
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
            
        return None 

    def _generate_ai_imrad_question(self, script):
        """AI를 사용하여 실시간으로 질문 생성 (강화된 프롬프트 사용)"""
        if not self.text_model: return None
        
        try:
            full_prompt = self.ai_prompt_template.format(script=script)
            # temperature를 높여서 창의적인 비판 유도
            response = self.text_model.generate_content(
                full_prompt,
                generation_config=genai.types.GenerationConfig(temperature=0.7)
            )
            return response.text.strip()
        except Exception as e:
            print(f"AI 질문 생성 실패 (IMRAD): {e}")
            return None

    def generate_imrad_question(self, script):
        """[핵심] 50% 확률로 AI 또는 규칙 기반 질문 생성"""
        
        # 1. 50% 확률로 AI 질문 시도
        if self.text_model and random.choice([True, False]):
            print("⚡️ [질문 생성] AI (정보형) 질문 생성 시도...")
            ai_question = self._generate_ai_imrad_question(script)
            if ai_question:
                return ai_question
        
        # 2. AI가 안 걸렸거나 실패하면 규칙 기반 실행
        print("⚙️ [질문 생성] 규칙 기반 (정보형) 질문 생성 시도...")
        rule_question = self._get_rule_based_imrad_question(script)
        
        if rule_question:
            return rule_question
        else:
            return self.imrad_templates['discussion'] # 기본값

class DynamicQuestionGenerator:
    """[수정] 설득형(B) 및 공감형(C) 질문 생성기 (50% 확률로 AI 사용)"""
    def __init__(self, text_model=None):
        self.text_model = text_model
        
        # 1. [기존 유지] 규칙 기반 데이터
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
        
        # 2. [강화됨] AI 프롬프트 템플릿 (독설가/멘토 모드)
        self.ai_prompt_templates = {
            "B": """
            당신은 돈을 잃는 것을 극도로 싫어하는 '보수적인 투자자(VC)'입니다.
            발표자는 당신에게 투자를 받거나 설득하려고 합니다. 대본을 읽고 가장 현실성이 떨어지거나, 위험해 보이는 부분을 찾아 '공격적인 질문'을 하나 던지세요.

            [공격 포인트]
            - "좋은 말인 건 알겠는데, 그래서 돈은 어떻게 법니까?" (수익성/실현가능성)
            - "지금 당장 해야 할 이유가 뭡니까? 내년에 해도 되지 않습니까?" (시급성 결여)
            - "경쟁사가 따라하면 그만 아닙니까? 당신만의 해자(Moat)가 뭡니까?" (차별성 부족)

            [출력 형식]
            - 질문은 한국어로 작성하세요.
            - 발표자의 막연한 희망 사항을 팩트로 반박하는 형식을 취하세요.
            - "구체적으로", "수치로", "근거를 들어"라는 표현을 사용하여 압박하세요.

            [대본]
            {script}

            [질문]
            """,
            "C": """
            당신은 산전수전 다 겪은 '인생 선배'이자 멘토입니다.
            발표자의 이야기가 진실되지 않거나, 겉멋이 들어 보이거나, 청중의 현실과는 동떨어진 '그들만의 성공담'으로 들릴 때 이를 지적해 주세요.

            [공격 포인트]
            - "당신이니까 성공한 것 아닙니까? 평범한 우리도 가능합니까?" (재현 가능성)
            - "실패나 좌절의 순간은 없었습니까? 너무 완벽하게만 포장된 것 아닙니까?" (진정성 검증)
            - "말로만 위로하지 말고, 당장 오늘 집에 가서 뭘 해야 합니까?" (실천적 조언 요구)

            [출력 형식]
            - 정중하지만 뼈 때리는 질문을 하세요.
            - "솔직히 말씀드리면...", "현실적으로 보자면..." 같은 화법을 사용하세요.

            [대본]
            {script}

            [질문]
            """
        }

    def _get_rule_based_dynamic_question(self, script, target_type):
        """기존 규칙 기반 질문 생성 로직"""
        type_db = self.question_db.get(target_type.upper())
        if not type_db: return None
        
        possible_questions = []
        for check_point, data in type_db.items():
            if any(trigger in script for trigger in data['triggers']):
                possible_questions.extend(data['questions'])
                
        if not possible_questions:
            if target_type.upper() == "B": return "이 제안을 한 문장으로 요약했을 때, 청중이 꼭 기억해야 할 핵심 메시지는 무엇입니까?"
            elif target_type.upper() == "C": return "이 이야기를 통해 청중들이 어떤 감정을 느끼고 돌아가기를 가장 원하십니까?"
            else: return None
            
        return random.choice(possible_questions)

    def _generate_ai_dynamic_question(self, script, target_type):
        """AI를 사용하여 실시간으로 질문 생성 (강화된 프롬프트 사용)"""
        if not self.text_model: return None
            
        prompt_template = self.ai_prompt_templates.get(target_type.upper())
        if not prompt_template: return None 
        
        try:
            full_prompt = prompt_template.format(script=script)
            # temperature를 높여서 다양한 관점 유도
            response = self.text_model.generate_content(
                full_prompt,
                generation_config=genai.types.GenerationConfig(temperature=0.8)
            )
            return response.text.strip()
        except Exception as e:
            print(f"AI 질문 생성 실패 (Dynamic {target_type}): {e}")
            return None

    def generate_question(self, script, target_type):
        """[핵심] 50% 확률로 AI 또는 규칙 기반 질문 생성"""
        
        # 1. 50% 확률로 AI 질문 시도
        if self.text_model and random.choice([True, False]):
            print(f"⚡️ [질문 생성] AI ({target_type}형) 질문 생성 시도...")
            ai_question = self._generate_ai_dynamic_question(script, target_type)
            if ai_question:
                return ai_question
        
        # 2. AI가 안 걸렸거나 실패하면 규칙 기반 실행
        print(f"⚙️ [질문 생성] 규칙 기반 ({target_type}형) 질문 생성 시도...")
        return self._get_rule_based_dynamic_question(script, target_type)