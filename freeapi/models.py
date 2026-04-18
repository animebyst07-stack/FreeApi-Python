AI_MODELS = [
    {'id': 'gemini-1.5-robotics-er-preview', 'displayName': 'Gemini 1.5 Robotics 200k', 'tgCallback': 'select_gpt_model:gemini-robotics-er-1.5-preview', 'contextK': 200, 'supportsVision': True, 'isDefault': False, 'isPopular': False},
    {'id': 'gemini-2.5-mini', 'displayName': 'Gemini 2.5 Mini 200k', 'tgCallback': 'select_gpt_model:gemini-2.5-flash-lite-no-thinking', 'contextK': 200, 'supportsVision': True, 'isDefault': False, 'isPopular': False},
    {'id': 'gemini-2.5-mini-thinking', 'displayName': 'Gemini 2.5 Mini Thinking 200k', 'tgCallback': 'select_gpt_model:gemini-2.5-flash-lite', 'contextK': 200, 'supportsVision': True, 'isDefault': False, 'isPopular': False},
    {'id': 'gemini-2.5-flash', 'displayName': 'Gemini 2.5 Flash 200k', 'tgCallback': 'select_gpt_model:gemini-2.5-flash-no-thinking-200k', 'contextK': 200, 'supportsVision': True, 'isDefault': False, 'isPopular': False},
    {'id': 'gemini-2.5-flash-thinking', 'displayName': 'Gemini 2.5 Flash Thinking 200k', 'tgCallback': 'select_gpt_model:gemini-2.5-flash-200k', 'contextK': 200, 'supportsVision': True, 'isDefault': False, 'isPopular': False},
    {'id': 'gemini-3.0-flash', 'displayName': 'Gemini 3.0 Flash 200k', 'tgCallback': 'select_gpt_model:gemini-3-flash-preview-no-thinking-200k', 'contextK': 200, 'supportsVision': True, 'isDefault': False, 'isPopular': False},
    {'id': 'gemini-3.0-flash-thinking', 'displayName': 'Gemini 3.0 Flash Thinking 200k', 'tgCallback': 'select_gpt_model:gemini-3-flash-preview-200k', 'contextK': 200, 'supportsVision': True, 'isDefault': True, 'isPopular': False},
    {'id': 'gemini-2.5-flash-64k', 'displayName': 'Gemini 2.5 Flash 64k', 'tgCallback': 'select_gpt_model:gemini-2.5-flash-no-thinking', 'contextK': 64, 'supportsVision': True, 'isDefault': False, 'isPopular': True},
    {'id': 'gemini-2.5-flash-thinking-64k', 'displayName': 'Gemini 2.5 Flash Thinking 64k', 'tgCallback': 'select_gpt_model:gemini-2.5-flash', 'contextK': 64, 'supportsVision': True, 'isDefault': False, 'isPopular': False},
    {'id': 'gemini-3.0-flash-64k', 'displayName': 'Gemini 3.0 Flash 64k', 'tgCallback': 'select_gpt_model:gemini-3-flash-preview-no-thinking', 'contextK': 64, 'supportsVision': True, 'isDefault': False, 'isPopular': False},
    {'id': 'gemini-3.0-flash-thinking-64k', 'displayName': 'Gemini 3.0 Flash Thinking 64k', 'tgCallback': 'select_gpt_model:gemini-3-flash-preview', 'contextK': 64, 'supportsVision': True, 'isDefault': False, 'isPopular': False},
]
DEFAULT_MODEL_ID = 'gemini-3.0-flash-thinking'


def find_model(model_id):
    return next((m for m in AI_MODELS if m['id'] == model_id), None)


def is_valid_model_id(model_id):
    return find_model(model_id) is not None
