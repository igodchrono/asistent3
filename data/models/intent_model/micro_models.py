# micro_models.py
"""
Микро-модели для Лисички:
- Классификация интентов (rubert-tiny)
- Анализ эмоций (rubert-tiny-toxicity)
- Гибридный анализатор (ML + правила)
"""

import torch
import numpy as np
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from typing import Dict, List, Optional, Tuple
import json
import os
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class IntentClassifier:
    """
    Классификатор намерений на основе rubert-tiny.
    Определяет, что хочет пользователь: поиск, запуск, управление ПК или просто разговор.
    """
    
    # Интенты, которые мы будем распознавать
    INTENTS = [
        'search',          # Поиск в интернете
        'launch_app',      # Запуск программы
        'open_browser',    # Открыть браузер
        'file_operation',  # Работа с файлами
        'system_control',  # Управление ПК (громкость, окна, выключение)
        'reminder',        # Напоминания
        'notes',           # Заметки
        'chat',            # Просто разговор
        'love',            # Признания в любви
        'question',        # Вопросы (не требующие поиска)
        'screenshot',      # Скриншот
        'volume_control'   # Управление громкостью
    ]
    
    def __init__(self, model_path: Optional[str] = None, use_cache: bool = True):
        """
        Инициализация классификатора.
        
        Args:
            model_path: Путь к сохраненной модели (если есть)
            use_cache: Использовать кэш для быстрых ответов
        """
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model_name = "cointegrated/rubert-tiny"
        self.use_cache = use_cache
        
        try:
            # Загружаем базовую модель
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name,
                num_labels=len(self.INTENTS)
            )
            self.model.to(self.device)
            self.model.eval()
            logger.info(f"✅ Загружена базовая модель интентов ({self.model_name})")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки модели интентов: {e}")
            # Создаем заглушку
            self.tokenizer = None
            self.model = None
        
        # Если есть сохраненная модель — загружаем
        if model_path and os.path.exists(model_path):
            try:
                self.load(model_path)
                logger.info(f"✅ Загружена дообученная модель интентов: {model_path}")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось загрузить модель {model_path}: {e}")
        
        # Кэш для быстрых ответов
        self.cache = {}
        self.cache_size = 100
        
        # Fallback правила для точного распознавания специфичных фраз
        self.fallback_rules = self._init_fallback_rules()
        logger.info("🤖 IntentClassifier инициализирован")
    
    def _init_fallback_rules(self) -> Dict:
        """Правила для точного распознавания без ML."""
        return {
            'search': [
                'найди', 'поищи', 'найти', 'искать', 'гугл', 'яндекс',
                'search', 'find', 'look up', 'покажи', 'найди в интернете'
            ],
            'launch_app': [
                'запусти', 'открой программу', 'запустить', 'запуск',
                'launch', 'open app', 'открыть приложение', 'включи'
            ],
            'love': [
                'люблю', 'обожаю', 'love you', '❤️', '💕', 'милый', 'дорогой',
                'ты моя', 'самая лучшая', 'обожаю тебя', 'безумно люблю'
            ],
            'system_control': [
                'выключи', 'перезагрузи', 'заблокируй', 'shutdown', 'restart',
                'блокировка', 'завершение работы', 'выключение'
            ],
            'reminder': [
                'напомни', 'напоминание', 'remind', 'set reminder', 'напомни мне'
            ],
            'notes': [
                'заметка', 'запиши', 'note', 'save note', 'заметки', 'записать'
            ],
            'volume_control': [
                'громкость', 'громче', 'тише', 'звук', 'volume', 'mute', 'звук выключить'
            ],
            'screenshot': [
                'скриншот', 'screenshot', 'screen', 'снимок экрана', 'скрин'
            ]
        }
    
    def predict(self, text: str, threshold: float = 0.6) -> Dict:
        """
        Предсказание интента.
        
        Args:
            text: Текст запроса
            threshold: Порог уверенности (0-1)
            
        Returns:
            Dict с интентом, уверенностью и параметрами
        """
        if not text or not text.strip():
            return {'intent': 'chat', 'confidence': 0.0, 'params': {}}
        
        text_clean = text.strip()
        
        # Проверяем кэш
        if self.use_cache:
            cache_key = text_clean[:100]
            if cache_key in self.cache:
                return self.cache[cache_key]
        
        # Сначала проверяем fallback правила (быстро и точно)
        text_lower = text_clean.lower()
        for intent, triggers in self.fallback_rules.items():
            for trigger in triggers:
                if trigger in text_lower:
                    result = {
                        'intent': intent,
                        'confidence': 0.95,
                        'params': self._extract_params(text_clean, intent),
                        'source': 'rule'
                    }
                    self._cache_result(cache_key, result)
                    return result
        
        # Если модель не загружена — возвращаем chat
        if self.model is None or self.tokenizer is None:
            result = {
                'intent': 'chat',
                'confidence': 0.5,
                'params': {'text': text_clean},
                'source': 'fallback'
            }
            self._cache_result(cache_key, result)
            return result
        
        # ML-предсказание
        try:
            inputs = self.tokenizer(
                text_clean,
                return_tensors='pt',
                truncation=True,
                padding=True,
                max_length=128
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            with torch.no_grad():
                outputs = self.model(**inputs)
                probabilities = torch.softmax(outputs.logits, dim=1)
                confidence, predicted = torch.max(probabilities, dim=1)
                
                confidence = confidence.item()
                predicted_intent = self.INTENTS[predicted.item()]
                
                # Если уверенность низкая и это не chat — отправляем в chat
                if confidence < threshold and predicted_intent != 'chat':
                    predicted_intent = 'chat'
                    confidence = 0.4
                
                # Дополнительная проверка для love
                if predicted_intent == 'chat' and any(w in text_lower for w in ['люблю', 'обожаю']):
                    predicted_intent = 'love'
                    confidence = 0.8
                
                result = {
                    'intent': predicted_intent,
                    'confidence': confidence,
                    'params': self._extract_params(text_clean, predicted_intent),
                    'source': 'ml'
                }
                
                self._cache_result(cache_key, result)
                return result
                
        except Exception as e:
            logger.error(f"Ошибка ML предсказания: {e}")
            return {
                'intent': 'chat',
                'confidence': 0.3,
                'params': {'text': text_clean},
                'source': 'error'
            }
    
    def _extract_params(self, text: str, intent: str) -> Dict:
        """Извлечение параметров для конкретного интента."""
        params = {}
        text_lower = text.lower()
        
        if intent == 'search':
            # Извлекаем поисковый запрос
            triggers = ['найди', 'поищи', 'найти', 'искать', 'гугл', 'яндекс', 'search', 'find', 'покажи']
            query = text_lower
            for trigger in triggers:
                query = query.replace(trigger, '').strip()
            # Убираем лишние слова
            stop_words = ['пожалуйста', 'плиз', 'срочно', 'быстро', 'мне', 'надо', 'нужно']
            for word in stop_words:
                query = query.replace(word, '').strip()
            params['query'] = query or text
            
            # Определяем тип поиска (картинки, видео, новости)
            if any(w in text_lower for w in ['картинк', 'фото', 'изображен', 'рисунок', 'арт', 'image', 'picture']):
                params['intent'] = 'images'
            elif any(w in text_lower for w in ['видео', 'video', 'ютуб', 'youtube']):
                params['intent'] = 'video'
            elif any(w in text_lower for w in ['новост', 'news']):
                params['intent'] = 'news'
            else:
                params['intent'] = 'web'
                
        elif intent == 'launch_app':
            triggers = ['запусти', 'открой', 'запустить', 'открыть', 'запуск', 'launch', 'open']
            app = text_lower
            for trigger in triggers:
                app = app.replace(trigger, '').strip()
            params['app'] = app or text
            
        elif intent == 'volume_control':
            if any(w in text_lower for w in ['громче', 'увелич', '+']):
                params['action'] = 'up'
            elif any(w in text_lower for w in ['тише', 'уменьш', '-']):
                params['action'] = 'down'
            elif any(w in text_lower for w in ['выключ', 'mute', 'отключ']):
                params['action'] = 'mute'
            else:
                params['action'] = 'set'
                numbers = re.findall(r'\d+', text)
                if numbers:
                    params['level'] = int(numbers[0])
                    
        elif intent == 'system_control':
            if any(w in text_lower for w in ['выключи', 'shutdown', 'выключение']):
                params['action'] = 'shutdown'
            elif any(w in text_lower for w in ['перезагрузи', 'restart', 'перезагруз']):
                params['action'] = 'restart'
            elif any(w in text_lower for w in ['заблокируй', 'lock', 'блокировк']):
                params['action'] = 'lock'
            elif any(w in text_lower for w in ['сверни', 'minimize', 'свернуть']):
                params['action'] = 'minimize_all'
            elif any(w in text_lower for w in ['разверни', 'maximize']):
                params['action'] = 'maximize_all'
                
        elif intent == 'reminder':
            # Извлекаем текст и время
            time_match = re.search(r'через\s+(\d+)\s*(минут|минуты|минуту|секунд|сек|часов|час|ч)', text_lower)
            if time_match:
                params['amount'] = int(time_match.group(1))
                unit = time_match.group(2)
                if unit in ['секунд', 'сек']:
                    params['unit'] = 'seconds'
                elif unit in ['минут', 'минуты', 'минуту']:
                    params['unit'] = 'minutes'
                else:
                    params['unit'] = 'hours'
                # Убираем временную часть из текста
                reminder_text = re.sub(r'через\s+\d+\s*(минут|минуты|минуту|секунд|сек|часов|час|ч)', '', text_lower).strip()
                params['text'] = reminder_text or text
            else:
                params['text'] = text
                params['amount'] = 5
                params['unit'] = 'minutes'
                
        elif intent == 'notes':
            triggers = ['заметка', 'запиши', 'записать', 'сохрани', 'note', 'save']
            note = text_lower
            for trigger in triggers:
                note = note.replace(trigger, '').strip()
            params['text'] = note or text
            
        elif intent == 'love':
            params['type'] = 'declaration'
            
        elif intent == 'screenshot':
            params['type'] = 'fullscreen'
            
        return params
    
    def _cache_result(self, key: str, result: Dict):
        """Кэширование результата."""
        if not self.use_cache:
            return
        if len(self.cache) >= self.cache_size:
            keys = list(self.cache.keys())[:self.cache_size // 2]
            for k in keys:
                del self.cache[k]
        if key:
            self.cache[key] = result
    
    def save(self, path: str):
        """Сохранение модели."""
        if self.model is None:
            logger.warning("Модель не загружена, сохранение невозможно")
            return
        
        os.makedirs(path, exist_ok=True)
        self.model.save_pretrained(path)
        self.tokenizer.save_pretrained(path)
        with open(os.path.join(path, 'intents.json'), 'w', encoding='utf-8') as f:
            json.dump({'intents': self.INTENTS}, f, ensure_ascii=False)
        logger.info(f"💾 Модель интентов сохранена: {path}")
    
    def load(self, path: str):
        """Загрузка модели."""
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSequenceClassification.from_pretrained(path)
        self.model.to(self.device)
        self.model.eval()
        
        # Загружаем интенты
        intents_path = os.path.join(path, 'intents.json')
        if os.path.exists(intents_path):
            with open(intents_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'intents' in data:
                    self.INTENTS = data['intents']
        logger.info(f"📂 Загружена модель интентов: {path}")
    
    def get_stats(self) -> Dict:
        """Статистика работы классификатора."""
        return {
            'intents': self.INTENTS,
            'cache_size': len(self.cache),
            'device': str(self.device),
            'model_loaded': self.model is not None
        }


class EmotionAnalyzerML:
    """
    Анализатор эмоций на основе rubert-tiny-toxicity.
    Определяет эмоциональную окраску текста.
    """
    
    # Эмоции, которые распознает модель
    EMOTIONS = ['anger', 'disgust', 'fear', 'happiness', 'sadness', 'surprise', 'neutral']
    
    # Маппинг эмоций к анимациям Лисички
    EMOTION_TO_ANIM = {
        'anger': 'angry',
        'disgust': 'angry_frustrated',
        'fear': 'scared',
        'happiness': 'happy',
        'sadness': 'sad',
        'surprise': 'surprised',
        'neutral': 'neutral'
    }
    
    def __init__(self, use_cache: bool = True):
        """
        Инициализация анализатора эмоций.
        
        Args:
            use_cache: Использовать кэш для быстрых ответов
        """
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model_name = "cointegrated/rubert-tiny-toxicity"
        self.use_cache = use_cache
        
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
            self.model.to(self.device)
            self.model.eval()
            logger.info(f"✅ Загружена модель эмоций ({self.model_name})")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки модели эмоций: {e}")
            self.tokenizer = None
            self.model = None
        
        # Кэш
        self.cache = {}
        self.cache_size = 100
        
        # Специфичные паттерны для точного распознавания
        self.special_patterns = {
            'love': ['люблю', 'обожаю', '❤️', '💕', 'милый', 'дорогой', 'love you', 'нежно'],
            'flirty': ['😏', 'флирт', 'игриво', 'пошло', 'секс', 'раздень', 'соблазн', 'hot'],
            'playful': ['😜', 'шалить', 'играть', 'fun', 'play', 'весело', 'прикольно'],
            'angry': ['😡', 'бесит', 'ненавижу', 'злой', 'зла', 'возмущен', 'разозлил'],
            'sad': ['😢', 'грустно', 'печально', 'жаль', 'обидно', 'плачу', 'слёзы']
        }
        
        logger.info("🧠 EmotionAnalyzerML инициализирован")
    
    def analyze(self, text: str) -> Dict[str, float]:
        """
        Анализ эмоций в тексте.
        
        Returns:
            Словарь {эмоция: уверенность}
        """
        if not text or not text.strip():
            return {emotion: 0.0 for emotion in self.EMOTIONS}
        
        text_clean = text.strip()
        
        # Проверяем кэш
        if self.use_cache:
            cache_key = text_clean[:100]
            if cache_key in self.cache:
                return self.cache[cache_key]
        
        # Проверяем специальные паттерны (быстро)
        text_lower = text_clean.lower()
        for emotion, triggers in self.special_patterns.items():
            for trigger in triggers:
                if trigger in text_lower:
                    result = {emotion: 0.0 for emotion in self.EMOTIONS}
                    if emotion == 'love':
                        result['happiness'] = 0.8
                        result['neutral'] = 0.2
                    elif emotion == 'flirty':
                        result['happiness'] = 0.7
                        result['neutral'] = 0.3
                    elif emotion == 'angry':
                        result['anger'] = 0.8
                        result['neutral'] = 0.2
                    elif emotion == 'sad':
                        result['sadness'] = 0.8
                        result['neutral'] = 0.2
                    else:
                        result['happiness'] = 0.6
                        result['neutral'] = 0.4
                    
                    self._cache_result(cache_key, result)
                    return result
        
        # Если модель не загружена — возвращаем нейтральную эмоцию
        if self.model is None or self.tokenizer is None:
            result = {emotion: 0.0 for emotion in self.EMOTIONS}
            result['neutral'] = 0.8
            self._cache_result(cache_key, result)
            return result
        
        # ML-предсказание
        try:
            inputs = self.tokenizer(
                text_clean,
                return_tensors='pt',
                truncation=True,
                padding=True,
                max_length=128
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            with torch.no_grad():
                outputs = self.model(**inputs)
                probabilities = torch.softmax(outputs.logits, dim=1)
                scores = probabilities[0].cpu().numpy()
            
            result = {}
            for i, emotion in enumerate(self.EMOTIONS):
                result[emotion] = float(scores[i])
            
            self._cache_result(cache_key, result)
            return result
            
        except Exception as e:
            logger.error(f"Ошибка ML анализа эмоций: {e}")
            result = {emotion: 0.0 for emotion in self.EMOTIONS}
            result['neutral'] = 0.8
            return result
    
    def get_dominant_emotion(self, text: str, threshold: float = 0.3) -> Tuple[str, float]:
        """
        Получение доминирующей эмоции.
        
        Returns:
            (эмоция, уверенность)
        """
        scores = self.analyze(text)
        max_emotion = max(scores, key=scores.get)
        max_score = scores[max_emotion]
        
        # Если уверенность низкая — возвращаем neutral
        if max_score < threshold:
            return 'neutral', 0.0
        
        return max_emotion, max_score
    
    def get_animation(self, text: str) -> str:
        """
        Получение анимации на основе эмоций.
        """
        if not text:
            return 'neutral'
        
        text_lower = text.lower()
        
        # Сначала проверяем любовь/флирт по ключевым словам
        if any(word in text_lower for word in ['люблю', 'обожаю', '❤️', '💕', 'милый', 'дорогой']):
            return 'love_warm'
        if any(word in text_lower for word in ['😏', 'флирт', 'пошло', 'раздень', 'секс']):
            return 'flirty'
        if any(word in text_lower for word in ['😡', 'бесит', 'ненавижу']):
            return 'angry'
        if any(word in text_lower for word in ['😢', 'грустно', 'печально']):
            return 'sad'
        
        # Используем ML
        emotion, confidence = self.get_dominant_emotion(text)
        
        # Если неуверенны — проверяем через старый анализатор (правила)
        if confidence < 0.4:
            try:
                from emotion_analyzer import EmotionalAnalyzer
                old_analyzer = EmotionalAnalyzer()
                old_emotion, details = old_analyzer.analyze_full_context(text)
                if details.get('keywords'):
                    return old_analyzer.get_animation(old_emotion)
            except Exception as e:
                logger.debug(f"Rule-based fallback error: {e}")
        
        return self.EMOTION_TO_ANIM.get(emotion, 'neutral')
    
    def _cache_result(self, key: str, result: Dict):
        """Кэширование результата."""
        if not self.use_cache:
            return
        if len(self.cache) >= self.cache_size:
            keys = list(self.cache.keys())[:self.cache_size // 2]
            for k in keys:
                del self.cache[k]
        if key:
            self.cache[key] = result
    
    def get_stats(self) -> Dict:
        """Статистика работы анализатора."""
        return {
            'emotions': self.EMOTIONS,
            'cache_size': len(self.cache),
            'device': str(self.device),
            'model_loaded': self.model is not None
        }


class HybridAnalyzer:
    """
    Гибридный анализатор: объединяет старый rule-based и новые ML-модели.
    """
    
    def __init__(self, model_path: Optional[str] = None, use_micro_models: bool = True):
        """
        Инициализация гибридного анализатора.
        
        Args:
            model_path: Путь к сохраненной модели интентов
            use_micro_models: Использовать ML-модели
        """
        self.use_micro_models = use_micro_models
        
        # Инициализируем ML-модели
        if use_micro_models:
            try:
                self.ml_emotion = EmotionAnalyzerML()
                self.ml_intent = IntentClassifier(model_path=model_path)
                logger.info("🤖 ML-модели инициализированы")
            except Exception as e:
                logger.error(f"❌ Ошибка инициализации ML-моделей: {e}")
                self.use_micro_models = False
                self.ml_emotion = None
                self.ml_intent = None
        else:
            self.ml_emotion = None
            self.ml_intent = None
        
        # Rule-based анализатор (ленивая инициализация)
        self.rule_based = None
        
        # Пороги для переключения между rule-based и ML
        self.intent_threshold = 0.7
        self.emotion_threshold = 0.4
        
        logger.info(f"🤖 Гибридный анализатор инициализирован (ML={'включен' if use_micro_models else 'выключен'})")
    
    def _get_rule_based(self):
        """Ленивая инициализация rule-based анализатора."""
        if self.rule_based is None:
            try:
                from emotion_analyzer import EmotionalAnalyzer
                self.rule_based = EmotionalAnalyzer()
                logger.info("📝 Rule-based анализатор инициализирован")
            except Exception as e:
                logger.error(f"❌ Ошибка инициализации rule-based анализатора: {e}")
                self.rule_based = None
        return self.rule_based
    
    def analyze_intent(self, text: str) -> Dict:
        """
        Анализ интента с использованием ML + правил.
        
        Returns:
            Dict с интентом, уверенностью, параметрами и источником
        """
        if not text or not text.strip():
            return {'intent': 'chat', 'confidence': 0.0, 'params': {}, 'source': 'empty'}
        
        # Проверяем через старый парсер команд (самый быстрый)
        try:
            from command_parser import CommandParser
            commands = CommandParser.parse(text)
            if commands:
                cmd = commands[0]
                return {
                    'intent': cmd['type'].lower(),
                    'confidence': 0.9,
                    'params': cmd.get('params', {}),
                    'source': 'command_parser'
                }
        except Exception as e:
            logger.debug(f"CommandParser error: {e}")
        
        # Если ML отключен — используем только правила
        if not self.use_micro_models:
            return self._analyze_intent_rules(text)
        
        # Используем ML
        try:
            ml_result = self.ml_intent.predict(text)
            
            # Если ML неуверенна — проверяем правила
            if ml_result['confidence'] < self.intent_threshold:
                rule_result = self._analyze_intent_rules(text)
                if rule_result['confidence'] > ml_result['confidence']:
                    return rule_result
            
            return ml_result
            
        except Exception as e:
            logger.error(f"Ошибка ML анализа интента: {e}")
            return self._analyze_intent_rules(text)
    
    def _analyze_intent_rules(self, text: str) -> Dict:
        """Анализ интента только на основе правил."""
        text_lower = text.lower()
        
        # Проверяем все триггеры
        for intent, triggers in IntentClassifier.fallback_rules.items():
            if not hasattr(IntentClassifier, 'fallback_rules'):
                continue
            for trigger in triggers:
                if trigger in text_lower:
                    return {
                        'intent': intent,
                        'confidence': 0.85,
                        'params': self._extract_params_rules(text, intent),
                        'source': 'rule_only'
                    }
        
        return {
            'intent': 'chat',
            'confidence': 0.5,
            'params': {'text': text},
            'source': 'rule_fallback'
        }
    
    def _extract_params_rules(self, text: str, intent: str) -> Dict:
        """Извлечение параметров на основе правил."""
        params = {}
        text_lower = text.lower()
        
        if intent == 'search':
            triggers = ['найди', 'поищи', 'найти', 'искать', 'гугл', 'search', 'find']
            query = text_lower
            for trigger in triggers:
                query = query.replace(trigger, '').strip()
            params['query'] = query or text
            
        elif intent == 'launch_app':
            triggers = ['запусти', 'открой', 'запустить', 'открыть', 'launch', 'open']
            app = text_lower
            for trigger in triggers:
                app = app.replace(trigger, '').strip()
            params['app'] = app or text
            
        elif intent == 'volume_control':
            if 'громче' in text_lower or 'увелич' in text_lower:
                params['action'] = 'up'
            elif 'тише' in text_lower or 'уменьш' in text_lower:
                params['action'] = 'down'
            else:
                params['action'] = 'set'
                
        elif intent == 'system_control':
            if 'выключи' in text_lower or 'shutdown' in text_lower:
                params['action'] = 'shutdown'
            elif 'перезагрузи' in text_lower or 'restart' in text_lower:
                params['action'] = 'restart'
            elif 'сверни' in text_lower:
                params['action'] = 'minimize_all'
                
        return params
    
    def analyze_emotion(self, text: str) -> Dict:
        """
        Анализ эмоций с использованием ML + правил.
        
        Returns:
            Dict с эмоциями, доминантной эмоцией и источником
        """
        if not text or not text.strip():
            return {
                'emotions': {e: 0.0 for e in EmotionAnalyzerML.EMOTIONS},
                'dominant': 'neutral',
                'confidence': 0.0,
                'source': 'empty'
            }
        
        # Если ML отключен — используем только правила
        if not self.use_micro_models or self.ml_emotion is None:
            return self._analyze_emotion_rules(text)
        
        # Используем ML
        try:
            ml_result = self.ml_emotion.analyze(text)
            dominant_ml = max(ml_result, key=ml_result.get)
            ml_confidence = ml_result[dominant_ml]
            
            # Если ML неуверенна — используем правила
            if ml_confidence < self.emotion_threshold:
                rule_result = self._analyze_emotion_rules(text)
                # Комбинируем результаты
                combined = ml_result.copy()
                if rule_result['dominant'] in combined:
                    combined[rule_result['dominant']] = max(
                        combined[rule_result['dominant']],
                        rule_result['confidence'] * 0.6
                    )
                else:
                    combined[rule_result['dominant']] = rule_result['confidence'] * 0.6
                
                new_dominant = max(combined, key=combined.get)
                return {
                    'emotions': combined,
                    'dominant': new_dominant,
                    'confidence': max(ml_confidence, rule_result['confidence'] * 0.6),
                    'source': 'hybrid'
                }
            
            return {
                'emotions': ml_result,
                'dominant': dominant_ml,
                'confidence': ml_confidence,
                'source': 'ml'
            }
            
        except Exception as e:
            logger.error(f"Ошибка ML анализа эмоций: {e}")
            return self._analyze_emotion_rules(text)
    
    def _analyze_emotion_rules(self, text: str) -> Dict:
        """Анализ эмоций только на основе правил."""
        text_lower = text.lower()
        
        # Проверяем специальные паттерны
        for emotion, triggers in self.special_patterns.items():
            if not hasattr(self, 'special_patterns'):
                continue
            for trigger in triggers:
                if trigger in text_lower:
                    return {
                        'dominant': emotion,
                        'confidence': 0.85,
                        'source': 'rule_only',
                        'emotions': {e: 0.0 for e in EmotionAnalyzerML.EMOTIONS}
                    }
        
        # Используем старый анализатор
        try:
            rule_based = self._get_rule_based()
            if rule_based:
                emotion, details = rule_based.analyze_full_context(text)
                return {
                    'dominant': emotion,
                    'confidence': 0.7,
                    'source': 'rule_based',
                    'emotions': {e: 0.0 for e in EmotionAnalyzerML.EMOTIONS}
                }
        except Exception as e:
            logger.debug(f"Rule-based analyzer error: {e}")
        
        return {
            'dominant': 'neutral',
            'confidence': 0.0,
            'source': 'fallback',
            'emotions': {e: 0.0 for e in EmotionAnalyzerML.EMOTIONS}
        }
    
    @property
    def special_patterns(self) -> Dict:
        """Специальные паттерны для распознавания эмоций."""
        return {
            'love': ['люблю', 'обожаю', '❤️', '💕', 'милый', 'дорогой', 'love you'],
            'flirty': ['😏', 'флирт', 'игриво', 'пошло', 'секс', 'раздень'],
            'playful': ['😜', 'шалить', 'играть', 'fun', 'play'],
            'angry': ['😡', 'бесит', 'ненавижу', 'злой', 'зла'],
            'sad': ['😢', 'грустно', 'печально', 'жаль', 'обидно']
        }
    
    def get_animation(self, text: str) -> str:
        """
        Получение анимации через гибридный анализ.
        """
        if not text:
            return 'neutral'
        
        # Сначала пробуем ML
        if self.use_micro_models and self.ml_emotion:
            try:
                anim = self.ml_emotion.get_animation(text)
                if anim != 'neutral':
                    return anim
            except Exception as e:
                logger.debug(f"ML emotion error: {e}")
        
        # Fallback на правила
        text_lower = text.lower()
        if any(w in text_lower for w in ['люблю', 'обожаю', '❤️']):
            return 'love_warm'
        if any(w in text_lower for w in ['😏', 'флирт', 'пошло']):
            return 'flirty'
        if any(w in text_lower for w in ['😡', 'бесит', 'ненавижу']):
            return 'angry'
        if any(w in text_lower for w in ['😢', 'грустно', 'печально']):
            return 'sad'
        
        # Проверяем через старый анализатор
        try:
            rule_based = self._get_rule_based()
            if rule_based:
                emotion, _ = rule_based.analyze_full_context(text)
                if emotion != 'neutral':
                    return rule_based.get_animation(emotion)
        except Exception as e:
            logger.debug(f"Rule-based animation error: {e}")
        
        return 'neutral'
    
    def get_intent_animation(self, intent: str) -> str:
        """Получение анимации для интента."""
        intent_to_anim = {
            'search': 'searching',
            'launch_app': 'happy',
            'open_browser': 'happy',
            'system_control': 'neutral',
            'love': 'love_warm',
            'reminder': 'neutral',
            'notes': 'thinking',
            'chat': 'neutral',
            'question': 'thinking',
            'screenshot': 'neutral',
            'volume_control': 'neutral'
        }
        return intent_to_anim.get(intent, 'neutral')
    
    def get_stats(self) -> Dict:
        """Статистика работы гибридного анализатора."""
        stats = {
            'use_micro_models': self.use_micro_models,
            'intent_threshold': self.intent_threshold,
            'emotion_threshold': self.emotion_threshold
        }
        
        if self.use_micro_models:
            if self.ml_intent:
                stats['intent'] = self.ml_intent.get_stats()
            if self.ml_emotion:
                stats['emotion'] = self.ml_emotion.get_stats()
        
        return stats