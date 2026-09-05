Фикс голоса + эмоций
====================

Куда копировать:

  data/plugins/voice/plugin.py
  data/models/intent_model/micro_models.py

Перезапустить.

1) Голос
   Ошибка: 'NoneType' object has no attribute 'apply_tts'
   Причина: model.to("cpu") у Silero возвращает None.
   Теперь модель не затирается, если to() вернул None.
   Если Silero всё равно не встанет — автопереход на pyttsx3.

2) Эмоции
   Ошибка: index 5 is out of bounds for axis 0 with size 5
   Причина: берётся rubert-tiny-toxicity (5 меток), а код ждёт 7 эмоций.
   Теперь 5 меток мапятся в anger/disgust/fear/neutral.
   Если есть data/models/emotion_model — грузится она.
