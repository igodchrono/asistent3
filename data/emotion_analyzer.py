# emotion_analyzer.py — единый анализатор эмоций (бывший EmotionalAnalyzerV2)
import re
import json
import os
from datetime import datetime
from collections import defaultdict, Counter
from typing import List, Dict, Optional, Tuple


class EmotionalAnalyzer:

    # Полный список NSFW (класс + instance) — должен совпадать с config.NSFW_EMOTIONS
    NSFW_EMOTIONS = [
        "undress", "undress_happy", "undress_sly", "undress_love",
        "undress_shy", "undress_playful", "undress_seductive",
        "undress_teasing", "undress_mischievous",
        "seductive", "seductive_happy",
        "flirty", "flirty_happy",
        "teasing", "teasing_sly",
        "dominant", "dominant_happy", "dominant_sly",
        "submissive", "submissive_happy", "submissive_shy",
        "lingerie", "lingerie_happy",
        "bath", "bath_shy", "bath_happy",
        "bed", "bed_love", "bed_shy",
        "naked", "naked_shy",
    ]
    """
    Расширенный анализатор эмоций для Лисички.
    Гибридный метод: ключевые слова + контекст + отрицания + эмодзи.
    """
    
    def __init__(self, memory_file="emotional_memory.json"):
        self.memory_file = memory_file
        self.emotion_history: List[str] = []
        self.conversation_history: List[Dict] = []
        self.user_patterns: Dict[str, Dict] = defaultdict(lambda: defaultdict(int))
        
        # Загружаем память
        self._load_memory()
        
        # Словарь эмодзи -> эмоция
        self.emoji_map = {
            # ❤️ Любовь
            '❤️': 'love', '💕': 'love', '💖': 'love', '💗': 'love', '💝': 'love',
            '💘': 'love', '😍': 'love', '🥰': 'love', '💋': 'flirty',
            
            # 😊 Радость
            '😊': 'happy', '😂': 'happy', '🤣': 'happy', '🎉': 'happy',
            '✨': 'happy', '🌟': 'happy', '⭐': 'happy', '💫': 'happy',
            '😄': 'happy', '😁': 'happy', '😆': 'happy', '👍': 'happy',
            
            # 😢 Грусть
            '😢': 'sad', '😭': 'sad', '💔': 'sad', '🥺': 'sad',
            '😞': 'sad', '😔': 'sad', '😟': 'sad',
            
            # 😡 Злость
            '😡': 'angry', '💢': 'angry', '🔥': 'angry', '👿': 'angry',
            '🤬': 'angry', '😤': 'angry_frustrated',
            
            # 😏 Флирт
            '😏': 'flirty', '😈': 'flirty', '🌶️': 'flirty', '🍑': 'flirty',
            '💦': 'flirty', '😜': 'playful', '😝': 'playful',
            
            # 🤔 Задумчивость
            '🤔': 'thinking', '🧐': 'thinking', '💭': 'thinking',
            
            # 😮 Удивление
            '😮': 'surprised', '😱': 'surprised', '🤯': 'surprised', '😲': 'surprised',
            
            # 😴 Усталость
            '😴': 'sleepy', '😩': 'tired', '💤': 'sleepy', '🥱': 'tired',
            
            # 🎵 Танцы
            '💃': 'dance', '🕺': 'dance', '🎵': 'dance', '🎶': 'dance',
        }
        
        # Расширенные ключевые слова с весом и контекстом
        self.keywords = {
            "love": {
                "words": [
                    "люблю", "обожаю", "сердце", "нежно", "ласково", "милый", "дорогой",
                    "родной", "тепло", "целую", "обнимаю", "признаюсь", "схожу с ума",
                    "ты моя", "самая лучшая", "обожаю тебя", "безумно люблю",
                    "love", "dear", "honey", "sweet", "baby", "darling", "cherish"
                ],
                "emojis": ["❤️", "💕", "💖", "💗", "💝", "💘", "😍", "🥰", "💋"],
                "weight": 3.0,
                "anim": "love_warm"
            },
            "hate": {
                "words": [
                    "ненавижу", "терпеть не могу", "бесит", "раздражает", "злой", "зла",
                    "возмущает", "нервирует", "выводит из себя", "не выношу",
                    "hate", "despise", "can't stand", "annoying"
                ],
                "emojis": ["😡", "💢", "🔥", "👿", "🤬"],
                "weight": 3.0,
                "anim": "angry"
            },
            "sad": {
                "words": [
                    "грустно", "печально", "жаль", "обидно", "тоска", "плачу", "слёзы",
                    "уныло", "депрессия", "хандра", "горестно", "скорбно",
                    "sad", "cry", "unhappy", "depressed", "broken"
                ],
                "emojis": ["😢", "😭", "💔", "🥺", "😞", "😔"],
                "weight": 2.5,
                "anim": "sad"
            },
            "happy": {
                "words": [
                    "счастлив", "рад", "весело", "здорово", "отлично", "круто",
                    "классно", "супер", "прекрасно", "улыбаюсь", "смеюсь",
                    "joy", "happy", "great", "awesome", "wonderful", "amazing",
                    "кайф", "прикольно", "замечательно", "великолепно", "огонь"
                ],
                "emojis": ["😊", "😂", "🤣", "🎉", "✨", "🌟", "⭐", "💫"],
                "weight": 2.5,
                "anim": "happy"
            },
            "angry": {
                "words": [
                    "злой", "зла", "раздражаюсь", "нервничаю", "возмущаюсь",
                    "гнев", "злость", "ярость", "бешенство", "недоволен",
                    "angry", "mad", "frustrated", "rage", "fury"
                ],
                "emojis": ["😡", "💢", "🔥", "👿", "🤬"],
                "weight": 2.5,
                "anim": "angry"
            },
            "flirty": {
                "words": [
                    "кокетливо", "флирт", "игриво", "соблазнительно", "пошло",
                    "шаловливо", "зазывно", "манит", "эротично", "возбуждённо",
                    "хочу тебя", "секс", "flirt", "tease",
                    "seductive", "horny", "sexy", "naughty", "dirty"
                ],
                "emojis": ["😏", "😈", "💋", "🔥", "🌶️", "🍑", "💦"],
                "weight": 3.0,
                "anim": "flirty"
            },
            "undress": {
                "words": [
                    "разденься", "раздень", "сними", "голая", "голую", "голым",
                    "без одежды", "обнажись", "обнажённая", "в белье", "трусики",
                    "undress", "nude", "naked", "strip", "take off", "lingerie"
                ],
                "emojis": ["🔞", "👙", "🔥"],
                "weight": 4.0,
                "anim": "undress"
            },
            "thinking": {
                "words": [
                    "думаю", "размышляю", "интересно", "наверное",
                    "возможно", "вероятно", "кажется", "похоже",
                    "think", "wonder", "maybe", "perhaps", "consider"
                ],
                "emojis": ["🤔", "🧐", "💭"],
                "weight": 1.5,
                "anim": "thinking"
            },
            "surprised": {
                "words": [
                    "удивлён", "шокирован", "неожиданно", "вот это", "ничего себе",
                    "офигеть", "обалдеть", "surprise", "shock", "wow",
                    "невероятно", "потрясающе", "ах", "ох"
                ],
                "emojis": ["😮", "😱", "🤯", "😲"],
                "weight": 2.0,
                "anim": "surprised"
            },
            "searching": {
                "words": [
                    "найди", "поищи", "найти", "искать", "поиск", "найду",
                    "search", "find", "look for"
                ],
                "emojis": ["🔍", "🔎"],
                "weight": 2.0,
                "anim": "searching"
            }
        }
        
        # Маппинг эмоций -> анимации
        self.emotion_to_anim = {
            "love": "love_warm",
            "love_shy": "love_shy",
            "hate": "angry",
            "sad": "sad",
            "happy": "happy",
            "angry": "angry",
            "angry_frustrated": "angry_frustrated",
            "flirty": "flirty",
            "thinking": "thinking",
            "surprised": "surprised",
            "dance": "dance",
            "neutral": "neutral",
            "tired": "tired",
            "sleepy": "sleepy",
            "searching": "searching",
            "undress": "undress",
            "flirty": "flirty",
            "teasing": "teasing",
            "naked": "undress",
        }
        
        # NSFW-эмоции (полный список, синхрон с config)
        try:
            import config as _cfg
            self.nsfw_emotions = list(getattr(_cfg, "NSFW_EMOTIONS", self.NSFW_EMOTIONS))
        except Exception:
            self.nsfw_emotions = list(self.NSFW_EMOTIONS)
        
        # Маппинг NSFW -> статика (для случаев без явной команды)
        self.nsfw_to_static = {
            # Только если файла undress нет — тогда мягкий fallback.
            # Сам undress НЕ маппим в love_warm.
            'undress': 'undress',
            'undress_happy': 'undress',
            'undress_sly': 'undress_sly',
            'undress_love': 'undress_love',
            'undress_shy': 'undress',
            'undress_playful': 'undress',
            'undress_seductive': 'undress',
            'undress_teasing': 'undress',
            'undress_mischievous': 'undress',
            'seductive': 'undress',
            'seductive_happy': 'undress',
            'flirty': 'teasing',
            'flirty_happy': 'teasing',
            'teasing': 'teasing',
            'teasing_sly': 'teasing',
            'dominant': 'confident',
            'dominant_happy': 'confident',
            'dominant_sly': 'sly',
            'submissive': 'love_shy',
            'submissive_happy': 'love_shy',
            'submissive_shy': 'love_shy',
            'lingerie': 'undress',
            'lingerie_happy': 'undress',
            'bath': 'undress',
            'bath_shy': 'undress',
            'bath_happy': 'undress',
            'bed': 'undress',
            'bed_love': 'undress_love',
            'bed_shy': 'undress',
            'naked': 'undress',
            'naked_shy': 'undress',
        }
        
        # Паттерны отрицаний
        self.negation_patterns = [
            r'\bне\s+',           # "не люблю", "не хочу"
            r'\bнет\b',           # "нет"
            r'\bни\s+',           # "ни капли"
            r'\bбез\s+',          # "без радости"
            r'\bникогда\s+не\s+', # "никогда не"
        ]
        
        print("🧠 EmotionalAnalyzer (единый) инициализирован")
        print(f"   📊 Ключевых слов: {sum(len(d['words']) for d in self.keywords.values())}")
        print(f"   😊 Эмоций: {len(self.keywords)}")
        print(f"   🔥 NSFW эмоций: {len(self.nsfw_emotions)}")
    
    def _load_memory(self):
        """Загружает память из файла."""
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.user_patterns = defaultdict(lambda: defaultdict(int))
                    for emotion, words in data.get("patterns", {}).items():
                        for word, count in words.items():
                            self.user_patterns[emotion][word] = count
                    self.emotion_history = data.get("history", [])
                print(f"📂 Загружена память: {len(self.emotion_history)} записей")
            except Exception as e:
                print(f"⚠️ Ошибка загрузки памяти: {e}")
    
    def _save_memory(self):
        """Сохраняет память в файл."""
        try:
            data = {
                "patterns": {k: dict(v) for k, v in self.user_patterns.items()},
                "history": self.emotion_history[-100:]
            }
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Ошибка сохранения памяти: {e}")
    
    def _has_negation(self, text: str) -> bool:
        """Проверяет наличие отрицаний в тексте."""
        for pattern in self.negation_patterns:
            if re.search(pattern, text):
                return True
        return False
    
    def _get_negated_phrases(self, text: str) -> List[str]:
        """Находит фразы с отрицанием."""
        phrases = []
        matches = re.findall(r'\bне\s+(\w+)', text)
        for match in matches:
            phrases.append(match)
        return phrases
    
    def _analyze_emojis(self, text: str) -> Dict[str, float]:
        """Анализирует эмодзи в тексте."""
        scores = defaultdict(float)
        for emoji, emotion in self.emoji_map.items():
            if emoji in text:
                count = text.count(emoji)
                scores[emotion] += count * 0.5
        return dict(scores)
    
    def _analyze_keywords(self, text: str, skip_negated: List[str] = None) -> Dict[str, float]:
        """Анализирует ключевые слова в тексте."""
        if skip_negated is None:
            skip_negated = []
        
        text_lower = text.lower()
        scores = defaultdict(float)
        
        for emotion, data in self.keywords.items():
            for word in data["words"]:
                if word in text_lower:
                    if any(word in neg for neg in skip_negated):
                        continue
                    count = text_lower.count(word)
                    scores[emotion] += data["weight"] * count * 0.6
        
        return dict(scores)
    
    def _get_context_emotion(self, text: str) -> Optional[str]:
        """Анализирует контекст фразы."""
        text_lower = text.lower()
        
        if 'люблю' in text_lower and ('книг' in text_lower or 'фильм' in text_lower or 'еда' in text_lower):
            if not any(word in text_lower for word in ['тебя', 'ты', 'вы', 'вас', 'её', 'его']):
                return 'neutral'
        
        if 'ненавижу' in text_lower and any(word in text_lower for word in ['погод', 'дожд', 'холод', 'жара']):
            return 'angry'
        
        return None
    
    def _detect_conflict(self, user_emotion: str, assistant_emotion: str) -> bool:
        """Определяет конфликт эмоций между пользователем и ассистентом."""
        love_emotions = ['love', 'love_shy', 'love_warm', 'love_happy']
        hate_emotions = ['hate', 'angry', 'angry_frustrated']
        
        if user_emotion in love_emotions and assistant_emotion in hate_emotions:
            return True
        if user_emotion in hate_emotions and assistant_emotion in love_emotions:
            return True
        return False
    
    def get_static_fallback(self, emotion: str) -> str:
        """Статическая альтернатива для NSFW. undress-семейство → undress, не love_warm."""
        e = (emotion or "").lower().strip()
        if e.startswith("undress") or e in ("naked", "naked_shy", "lingerie", "lingerie_happy",
                                               "bath", "bath_shy", "bath_happy", "bed", "bed_love", "bed_shy",
                                               "seductive", "seductive_happy"):
            return "undress"
        return self.nsfw_to_static.get(e, "neutral")
    
    def analyze_full_context(
        self,
        text: str,
        history: Optional[List[Dict]] = None,
        time_of_day: Optional[int] = None,
        user_emotion: Optional[str] = None
    ) -> Tuple[str, Dict[str, float]]:
        """Полный анализ контекста. Возвращает (эмоция, детали)."""
        if not text or not text.strip():
            return "neutral", {}
        
        text_lower = text.lower()
        scores = defaultdict(float)
        details = {}
        
        # ===== 1. ПРОВЕРКА ОТРИЦАНИЙ =====
        has_negation = self._has_negation(text_lower)
        negated_phrases = self._get_negated_phrases(text_lower) if has_negation else []
        details["has_negation"] = has_negation
        details["negated_phrases"] = negated_phrases
        
        # ===== 2. АНАЛИЗ ЭМОДЗИ =====
        emoji_scores = self._analyze_emojis(text)
        for emotion, score in emoji_scores.items():
            scores[emotion] += score * 1.0
        details["emojis"] = emoji_scores
        
        # ===== 3. АНАЛИЗ КЛЮЧЕВЫХ СЛОВ =====
        keyword_scores = self._analyze_keywords(text_lower, negated_phrases)
        for emotion, score in keyword_scores.items():
            scores[emotion] += score * 1.0
        details["keywords"] = keyword_scores
        
        # ===== 4. АНАЛИЗ КОНТЕКСТА =====
        context_emotion = self._get_context_emotion(text)
        if context_emotion:
            scores[context_emotion] += 1.0
            details["context"] = context_emotion
        
        # ===== 5. АНАЛИЗ ИСТОРИИ =====
        if history:
            history_emotion = self.analyze_history(history)
            if history_emotion != "neutral":
                scores[history_emotion] += 0.5
                details["history"] = history_emotion
        
        # ===== 6. ЕСЛИ ЕСТЬ ЯВНАЯ ЭМОЦИЯ ОТ ПОЛЬЗОВАТЕЛЯ =====
        if user_emotion and user_emotion in self.keywords:
            scores[user_emotion] += 2.0
            details["user_explicit"] = user_emotion
        
        # ===== 7. ЕСЛИ ЕСТЬ ANIM-ТЕГ =====
        anim_match = re.search(r'\[ANIM:(\w+)\]', text, re.IGNORECASE)
        if anim_match:
            anim = anim_match.group(1).lower()
            if anim in self.emotion_to_anim.values() or anim in self.nsfw_emotions:
                scores[anim] += 5.0
                details["explicit_anim"] = anim
                return anim, details
        
        # ===== 8. ВЫБОР ЭМОЦИИ =====
        if not scores:
            return "neutral", details
        
        best_emotion = max(scores, key=scores.get)
        best_score = scores[best_emotion]
        
        if best_score < 0.5:
            details["below_threshold"] = True
            return "neutral", details
        
        if best_emotion in self.nsfw_emotions:
            try:
                import config
                if not getattr(config, "NSFW_ENABLED", True):
                    details["nsfw_disabled"] = True
                    return "neutral", details
            except:
                pass
        
        details["best_score"] = best_score
        details["all_scores"] = dict(scores)
        
        self.emotion_history.append(best_emotion)
        if len(self.emotion_history) > 100:
            self.emotion_history = self.emotion_history[-100:]
        self._save_memory()
        
        return best_emotion, details
    
    def analyze_with_conflict(
        self,
        user_text: str,
        assistant_reply: str,
        history: Optional[List[Dict]] = None
    ) -> Tuple[str, Dict]:
        """
        Анализирует конфликт эмоций между пользователем и ассистентом.
        Возвращает (эмоция, детали).
        """
        user_emotion, user_details = self.analyze_full_context(user_text, history)
        assistant_emotion, assistant_details = self.analyze_full_context(assistant_reply, history)
        
        details = {
            "user_emotion": user_emotion,
            "assistant_emotion": assistant_emotion,
            "user_details": user_details,
            "assistant_details": assistant_details
        }
        
        if self._detect_conflict(user_emotion, assistant_emotion):
            details["conflict"] = True
            print(f"⚠️ Конфликт эмоций! Пользователь: {user_emotion}, Ассистент: {assistant_emotion}")
            return "neutral", details
        
        if user_emotion == assistant_emotion:
            details["matched"] = True
            return assistant_emotion, details
        
        if assistant_emotion != "neutral":
            return assistant_emotion, details
        
        return user_emotion or "neutral", details
    
    def analyze_history(self, history: List[Dict], limit: int = 5) -> str:
        """Анализирует историю диалога."""
        if not history:
            return "neutral"
        
        emotions = []
        for msg in history[-limit:]:
            if isinstance(msg, dict):
                content = msg.get("content", "")
                role = msg.get("role", "")
                if role == "user":
                    emotion, _ = self.analyze_full_context(content)
                    emotions.append(emotion)
        
        if emotions:
            counter = Counter(emotions)
            most_common = counter.most_common(1)[0][0]
            if counter[most_common] >= 2:
                return most_common
            return most_common
        
        return "neutral"
    

    

    # --- совместимость с HybridAnalyzer / emotion plugin ---
    def analyze_emotion(self, text: str):
        """Возвращает dict dominant/confidence/source как HybridAnalyzer."""
        try:
            emotion, details = self.analyze_full_context(text or "")
        except Exception:
            emotion, details = "neutral", {}
        scores = (details or {}).get("scores") or {}
        conf = float(max(scores.values()) if scores else (0.7 if emotion != "neutral" else 0.0))
        if conf > 1.0:
            conf = min(1.0, conf / 5.0)
        return {
            "dominant": emotion or "neutral",
            "confidence": conf,
            "source": "emotion_analyzer",
            "details": details or {},
            "anim": self.emotion_to_anim.get(emotion, emotion or "neutral"),
        }

    def analyze(self, text: str):
        return self.analyze_emotion(text)

    def is_nsfw_emotion(self, emotion: str) -> bool:
        """Проверка NSFW: точное имя или префикс (undress_shy → undress)."""
        if not emotion:
            return False
        e = emotion.lower().strip()
        if e in self.nsfw_emotions:
            return True
        # варианты undress_*, bed_* и т.д.
        for base in self.nsfw_emotions:
            if e.startswith(base + "_") or base.startswith(e + "_"):
                return True
        return False

    def get_animation(self, emotion: str) -> str:
        """Возвращает имя анимации для эмоции."""
        if self.is_nsfw_emotion(emotion):
            try:
                import config
                if not getattr(config, "NSFW_ENABLED", True):
                    return "neutral"
            except Exception:
                pass
            return emotion
        
        return self.emotion_to_anim.get(emotion, "neutral")
    
    def learn_pattern(self, text: str, emotion: str):
        """Обучает систему на новом примере."""
        text_lower = text.lower()
        for word in text_lower.split():
            if len(word) > 3:
                self.user_patterns[emotion][word] += 1
        self._save_memory()
    
    def get_stats(self) -> Dict:
        """Возвращает статистику анализатора."""
        return {
            "emotions_count": len(self.emotion_history),
            "patterns_count": sum(len(v) for v in self.user_patterns.values()),
            "available_emotions": list(self.keywords.keys()),
            "last_emotion": self.emotion_history[-1] if self.emotion_history else "neutral"
        }
    
    def clear_memory(self):
        """Очищает память."""
        self.emotion_history = []
        self.user_patterns = defaultdict(lambda: defaultdict(int))
        self._save_memory()
        print("🧹 Память эмоций очищена")