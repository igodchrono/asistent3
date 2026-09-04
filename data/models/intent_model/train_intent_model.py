# train_intent_model.py
"""
Скрипт для обучения модели интентов на ваших данных.
Запустите для дообучения модели на ваших примерах.
"""

import json
import os
import torch
from sklearn.model_selection import train_test_split
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    Trainer,
    TrainingArguments,
    EarlyStoppingCallback
)
from datasets import Dataset
import numpy as np
from typing import Dict, List

# ============================================================
# 1. ДАННЫЕ ДЛЯ ОБУЧЕНИЯ
# ============================================================

# Добавьте свои примеры! Чем больше, тем лучше.
TRAINING_DATA = [
    # ===== ПОИСК =====
    {"text": "найди картинки с лисами", "intent": "search"},
    {"text": "поищи рецепт пиццы", "intent": "search"},
    {"text": "что такое нейросети", "intent": "search"},
    {"text": "погода в москве сегодня", "intent": "search"},
    {"text": "гугл как сделать сайт", "intent": "search"},
    {"text": "найди фильм интерстеллар", "intent": "search"},
    {"text": "поиск информации по python", "intent": "search"},
    {"text": "яндекс новости", "intent": "search"},
    {"text": "покажи фото котиков", "intent": "search"},
    {"text": "найти википедию", "intent": "search"},
    {"text": "как приготовить блины", "intent": "search"},
    {"text": "что посмотреть вечером", "intent": "search"},
    {"text": "анекдоты смешные", "intent": "search"},
    {"text": "гороскоп на сегодня", "intent": "search"},
    
    # ===== ЗАПУСК ПРИЛОЖЕНИЙ =====
    {"text": "запусти калькулятор", "intent": "launch_app"},
    {"text": "открой браузер", "intent": "launch_app"},
    {"text": "запустить фотошоп", "intent": "launch_app"},
    {"text": "открыть chrome", "intent": "launch_app"},
    {"text": "запусти игру", "intent": "launch_app"},
    {"text": "открой блокнот", "intent": "launch_app"},
    {"text": "запусти vs code", "intent": "launch_app"},
    {"text": "открыть excel", "intent": "launch_app"},
    {"text": "запустить steam", "intent": "launch_app"},
    {"text": "открой дискорд", "intent": "launch_app"},
    
    # ===== УПРАВЛЕНИЕ ПК =====
    {"text": "выключи компьютер", "intent": "system_control"},
    {"text": "перезагрузи ноутбук", "intent": "system_control"},
    {"text": "заблокируй экран", "intent": "system_control"},
    {"text": "сверни все окна", "intent": "system_control"},
    {"text": "shutdown pc", "intent": "system_control"},
    {"text": "restart system", "intent": "system_control"},
    {"text": "lock computer", "intent": "system_control"},
    {"text": "разверни окна", "intent": "system_control"},
    
    # ===== УПРАВЛЕНИЕ ГРОМКОСТЬЮ =====
    {"text": "сделай громче", "intent": "volume_control"},
    {"text": "убавь звук", "intent": "volume_control"},
    {"text": "громкость 50", "intent": "volume_control"},
    {"text": "выключи звук", "intent": "volume_control"},
    {"text": "volume up", "intent": "volume_control"},
    {"text": "volume down", "intent": "volume_control"},
    {"text": "mute", "intent": "volume_control"},
    {"text": "звук тише", "intent": "volume_control"},
    
    # ===== ЛЮБОВЬ И ЭМОЦИИ =====
    {"text": "я тебя люблю", "intent": "love"},
    {"text": "ты мне нравишься", "intent": "love"},
    {"text": "обожаю тебя", "intent": "love"},
    {"text": "ты моя любимая", "intent": "love"},
    {"text": "люблю тебя очень сильно", "intent": "love"},
    {"text": "ты лучшая", "intent": "love"},
    {"text": "я без ума от тебя", "intent": "love"},
    
    # ===== НАПОМИНАНИЯ =====
    {"text": "напомни мне выпить воды", "intent": "reminder"},
    {"text": "напоминание через 5 минут", "intent": "reminder"},
    {"text": "set reminder for meeting", "intent": "reminder"},
    {"text": "напомни позвонить маме", "intent": "reminder"},
    {"text": "remind me to buy milk", "intent": "reminder"},
    
    # ===== ЗАМЕТКИ =====
    {"text": "запиши идею для проекта", "intent": "notes"},
    {"text": "создай заметку", "intent": "notes"},
    {"text": "сохрани мысль", "intent": "notes"},
    {"text": "записать рецепт", "intent": "notes"},
    {"text": "note: купить продукты", "intent": "notes"},
    
    # ===== СКРИНШОТЫ =====
    {"text": "сделай скриншот", "intent": "screenshot"},
    {"text": "снимок экрана", "intent": "screenshot"},
    {"text": "take screenshot", "intent": "screenshot"},
    {"text": "screen capture", "intent": "screenshot"},
    
    # ===== ОБЫЧНЫЙ РАЗГОВОР =====
    {"text": "как дела?", "intent": "chat"},
    {"text": "что нового?", "intent": "chat"},
    {"text": "расскажи шутку", "intent": "chat"},
    {"text": "привет", "intent": "chat"},
    {"text": "пока", "intent": "chat"},
    {"text": "как тебя зовут", "intent": "chat"},
    {"text": "кто ты", "intent": "chat"},
    {"text": "отлично выглядишь", "intent": "chat"},
    {"text": "спасибо", "intent": "chat"},
    {"text": "hello", "intent": "chat"},
    {"text": "hi", "intent": "chat"},
    {"text": "как настроение", "intent": "chat"},
    {"text": "что делаешь", "intent": "chat"},
]


def prepare_dataset(data: List[Dict]) -> Dataset:
    """Подготовка датасета для обучения."""
    texts = [item['text'] for item in data]
    intents = [item['intent'] for item in data]
    
    # Создаем маппинг интентов
    unique_intents = sorted(list(set(intents)))
    intent_to_id = {intent: i for i, intent in enumerate(unique_intents)}
    id_to_intent = {i: intent for intent, i in intent_to_id.items()}
    
    labels = [intent_to_id[intent] for intent in intents]
    
    return Dataset.from_dict({
        'text': texts,
        'label': labels
    }), intent_to_id, id_to_intent


def tokenize_function(examples, tokenizer):
    """Токенизация для обучения."""
    return tokenizer(
        examples['text'],
        padding='max_length',
        truncation=True,
        max_length=128,
        return_tensors='pt'
    )


def train_intent_model(
    data: List[Dict] = None,
    model_name: str = "cointegrated/rubert-tiny",
    output_dir: str = "./intent_model",
    epochs: int = 10,
    batch_size: int = 16,
    learning_rate: float = 2e-5,
    test_size: float = 0.1
):
    """
    Обучение модели интентов.
    
    Args:
        data: Данные для обучения (если None, используется TRAINING_DATA)
        model_name: Имя модели
        output_dir: Путь для сохранения
        epochs: Количество эпох
        batch_size: Размер батча
        learning_rate: Скорость обучения
        test_size: Размер тестовой выборки
    """
    print("=" * 60)
    print("🚀 ОБУЧЕНИЕ МОДЕЛИ ИНТЕНТОВ")
    print("=" * 60)
    
    data = data or TRAINING_DATA
    print(f"📊 Всего примеров: {len(data)}")
    
    # Подготовка данных
    dataset, intent_to_id, id_to_intent = prepare_dataset(data)
    print(f"📋 Интенты: {list(intent_to_id.keys())}")
    
    # Разделяем на train/validation
    dataset = dataset.train_test_split(test_size=test_size)
    train_dataset = dataset['train']
    eval_dataset = dataset['test']
    print(f"📚 Обучающая выборка: {len(train_dataset)} примеров")
    print(f"📚 Валидационная выборка: {len(eval_dataset)} примеров")
    
    # Загружаем токенизатор
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    
    # Токенизация
    train_dataset = train_dataset.map(
        lambda x: tokenize_function(x, tokenizer),
        batched=True,
        remove_columns=['text']
    )
    eval_dataset = eval_dataset.map(
        lambda x: tokenize_function(x, tokenizer),
        batched=True,
        remove_columns=['text']
    )
    
    # Загружаем модель
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        num_labels=len(intent_to_id)
    )
    
    # Проверяем наличие GPU
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"💻 Устройство: {device}")
    
    # Настройки обучения
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size * 2,
        learning_rate=learning_rate,
        warmup_steps=100,
        weight_decay=0.01,
        logging_dir='./logs',
        logging_steps=50,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="accuracy",
        report_to="none",
        fp16=(device == "cuda"),
        gradient_accumulation_steps=2,
        save_total_limit=3,
        dataloader_num_workers=4,
    )
    
    # Функция вычисления метрик
    def compute_metrics(eval_pred):
        predictions = eval_pred.predictions
        labels = eval_pred.label_ids
        preds = np.argmax(predictions, axis=1)
        accuracy = (preds == labels).mean()
        return {
            'accuracy': accuracy,
        }
    
    # Создаем тренер
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
    )
    
    # Обучение
    print("\n🚀 Начинаем обучение...")
    trainer.train()
    
    # Сохраняем модель
    print(f"\n💾 Сохраняем модель в {output_dir}...")
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    
    # Сохраняем маппинг интентов
    with open(f'{output_dir}/intents.json', 'w', encoding='utf-8') as f:
        json.dump({
            'intents': list(intent_to_id.keys()),
            'intent_to_id': intent_to_id,
            'id_to_intent': id_to_intent
        }, f, ensure_ascii=False, indent=2)
    
    print("\n✅ Обучение завершено!")
    print(f"📁 Модель сохранена: {output_dir}")
    
    # Тестирование
    print("\n🧪 Тестирование модели:")
    test_texts = [
        "найди рецепт борща",
        "запусти калькулятор",
        "я тебя люблю",
        "выключи компьютер",
        "как дела?",
        "сделай скриншот",
        "напомни выпить воду",
        "громкость 30"
    ]
    
    # Загружаем обученную модель для теста
    test_tokenizer = AutoTokenizer.from_pretrained(output_dir)
    test_model = AutoModelForSequenceClassification.from_pretrained(output_dir)
    test_model.eval()
    test_model.to(device)
    
    print("\nРезультаты:")
    for text in test_texts:
        inputs = test_tokenizer(
            text,
            return_tensors='pt',
            truncation=True,
            padding=True,
            max_length=128
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = test_model(**inputs)
            probs = torch.softmax(outputs.logits, dim=1)
            confidence, predicted = torch.max(probs, dim=1)
            
            intent = id_to_intent[predicted.item()]
            confidence = confidence.item()
            
            print(f"  '{text}' → {intent} (уверенность: {confidence:.2f})")
    
    print("\n" + "=" * 60)
    print("✅ Готово! Модель можно использовать.")
    print("=" * 60)
    
    return output_dir


def add_training_data(text: str, intent: str):
    """Добавление нового примера в данные для обучения."""
    global TRAINING_DATA
    TRAINING_DATA.append({"text": text, "intent": intent})
    print(f"✅ Добавлен пример: '{text}' → {intent}")


def save_training_data(filename: str = "training_data.json"):
    """Сохранение данных для обучения в файл."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(TRAINING_DATA, f, ensure_ascii=False, indent=2)
    print(f"💾 Данные сохранены в {filename}")


def load_training_data(filename: str = "training_data.json"):
    """Загрузка данных для обучения из файла."""
    global TRAINING_DATA
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            TRAINING_DATA = json.load(f)
        print(f"📂 Загружено {len(TRAINING_DATA)} примеров из {filename}")
    else:
        print(f"⚠️ Файл {filename} не найден")


if __name__ == "__main__":
    # Загружаем сохраненные данные (если есть)
    load_training_data()
    
    # Обучаем модель
    train_intent_model(
        data=TRAINING_DATA,
        output_dir="./intent_model",
        epochs=5,
        batch_size=16
    )