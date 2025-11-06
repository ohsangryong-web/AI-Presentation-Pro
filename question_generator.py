import random
import re

class IMRADQuestionGenerator:
    """정보 전달형 (논문) 대본의 논리적 허점을 찾는 질문 생성기"""
    def __init__(self):
        self.templates = {
            'novelty': "기존 선행 연구들과 비교했을 때, 이 연구만이 가지는 가장 결정적인 차별점(Novelty)은 무엇입니까?",
            'method_justification': "선택하신 연구 방법론([{method_name}])의 구체적인 선정 이유는 무엇이며, 다른 대안은 고려하지 않으셨나요?",
            'causality_check': "결과에서 발견된 상관관계를 인과관계로 확정하기 위해 추가로 고려해야 할 변수가 있을까요?",
            'limitation': "연구를 진행하면서 가장 아쉬웠던 한계점이나, 후속 연구에서 보완하고 싶은 점은 무엇입니까?"
        }

    def _check_keywords(self, text, keywords):
        for keyword in keywords:
            if keyword in text:
                return True
        return False

    def _extract_method_entity(self, text):
        major_methods = ['설문조사', '인터뷰', '회귀분석', '실험', 'A/B 테스트']
        for method in major_methods:
            if method in text:
                return method
        return None

    def generate_question(self, script):
        """대본(script)을 분석하여 논리적 허점 질문을 1개 반환"""
        questions = []
        if not self._check_keywords(script, ['차별점', '독창성', '기존 연구와 달리', '새로운']):
            questions.append(f"[서론 질문] {self.templates['novelty']}")
        
        detected_method = self._extract_method_entity(script)
        if detected_method and not self._check_keywords(script, ['때문에', '이유는', '위하여 선정']):
             questions.append(f"[방법 질문] {self.templates['method_justification'].format(method_name=detected_method)}")
        
        if '상관관계' in script and not self._check_keywords(script, ['추가 검증', '인과관계일 가능성', '해석에 주의']):
            questions.append(f"[결과 질문] {self.templates['causality_check']}")
            
        if not self._check_keywords(script, ['한계', '아쉬운', '부족한', '후속 연구', '향후 과제']):
             questions.append(f"[고찰 질문] {self.templates['limitation']}")
             
        if not questions:
            return None # 허점 없음
        return random.choice(questions) # 발견된 허점 중 1개 랜덤 선택

class DynamicQuestionGenerator:
    """설득형(B) 및 공감형(C) 대본의 허점을 찾는 질문 생성기"""
    def __init__(self):
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

    def generate_question(self, script, target_type):
        type_db = self.question_db.get(target_type.upper())
        if not type_db:
            return None
        possible_questions = []
        for check_point, data in type_db.items():
            if any(trigger in script for trigger in data['triggers']):
                possible_questions.extend(data['questions'])
        if not possible_questions:
            if target_type == "B":
                return "이 제안을 한 문장으로 요약했을 때, 청중이 꼭 기억해야 할 핵심 메시지는 무엇입니까?"
            elif target_type == "C":
                return "이 이야기를 통해 청중들이 어떤 감정을 느끼고 돌아가기를 가장 원하십니까?"
            else:
                return None
        return random.choice(possible_questions)