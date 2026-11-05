"""AI gateway — admin panelda tanlangan provayder/model orqali so'rov yuboradi.

Model tanlanmagan bo'lsa, eski Gemini env zanjiriga qaytadi. Har bir so'rov
`AIUsage` jadvaliga yoziladi (qaysi bo'lim, provayder, model, token, xato).
"""

import os
import random
import time

import requests

from .gemini import DEFAULT_MODEL, call_gemini
from .models import AIModel, AIProvider, AIUsage

FEATURES = [
    ('writing', 'Writing feedback'),
    ('speaking', 'Speaking feedback'),
    ('tools', 'AI tools'),
    ('mock_extract', 'Mock HTML → JSON'),
]

DEFAULT_PROVIDERS = [
    {
        'slug': 'gemini',
        'name': 'Google Gemini',
        'kind': AIProvider.KIND_GEMINI,
        'base_url': 'https://generativelanguage.googleapis.com/v1beta',
        'api_key_env': 'GEMINI_KEY_1,GEMINI_KEY_2,GEMINI_KEY_3,GEMINI_KEY_4',
    },
    {
        'slug': 'groq',
        'name': 'Groq',
        'kind': AIProvider.KIND_OPENAI,
        'base_url': 'https://api.groq.com/openai/v1',
        'api_key_env': 'GROQ_KEY_1,GROQ_KEY_2',
    },
    {
        'slug': 'cerebras',
        'name': 'Cerebras',
        'kind': AIProvider.KIND_OPENAI,
        'base_url': 'https://api.cerebras.ai/v1',
        'api_key_env': 'CEREBRAS_KEY_1,CEREBRAS_KEY_2',
    },
    {
        'slug': 'openrouter',
        'name': 'OpenRouter',
        'kind': AIProvider.KIND_OPENAI,
        'base_url': 'https://openrouter.ai/api/v1',
        'api_key_env': 'OPENROUTER_KEY_1,OPENROUTER_KEY_2',
    },
    {
        'slug': 'mistral',
        'name': 'Mistral',
        'kind': AIProvider.KIND_OPENAI,
        'base_url': 'https://api.mistral.ai/v1',
        'api_key_env': 'MISTRAL_KEY_1,MISTRAL_KEY_2',
    },
]


def seed_default_providers():
    """Standart provayderlarni yaratadi (mavjudlariga tegmaydi)."""
    created = []
    for item in DEFAULT_PROVIDERS:
        _, was_created = AIProvider.objects.get_or_create(
            slug=item['slug'], defaults=item
        )
        if was_created:
            created.append(item['slug'])
    return created


def provider_keys(provider):
    names = [n.strip() for n in (provider.api_key_env or '').split(',') if n.strip()]
    keys = [os.environ.get(n, '') for n in names]
    return [k for k in keys if k]


def provider_env_ready(provider):
    if provider.kind == AIProvider.KIND_GEMINI:
        return bool(provider_keys(provider))
    return bool(provider_keys(provider))


def candidates_for(feature):
    models = (
        AIModel.objects.filter(enabled=True, provider__enabled=True)
        .select_related('provider')
        .order_by('priority', 'id')
    )
    out = []
    for model in models:
        features = model.features or []
        if '*' in features or feature in features:
            out.append(model)
    return out


def log_usage(*, feature, provider, model, success, latency_ms, user=None,
              tokens_in=0, tokens_out=0, error='', meta=None):
    try:
        AIUsage.objects.create(
            feature=feature,
            provider=provider or '',
            model=model or '',
            success=success,
            tokens_in=tokens_in or 0,
            tokens_out=tokens_out or 0,
            latency_ms=latency_ms or 0,
            error=(error or '')[:2000],
            meta=meta or {},
            user=user if getattr(user, 'is_authenticated', False) else None,
        )
    except Exception:  # noqa: BLE001
        # Logging hech qachon asosiy so'rovni buzmasligi kerak.
        pass


def _call_openai_compatible(model, prompt, temperature, max_tokens,
                            response_schema, timeout):
    provider = model.provider
    keys = provider_keys(provider)
    if not keys:
        return {'success': False, 'error': f'{provider.name}: API key topilmadi.'}
    if not provider.base_url:
        return {'success': False, 'error': f'{provider.name}: base URL yo\'q.'}

    base = provider.base_url.rstrip('/')
    url = base if base.endswith('/chat/completions') else f'{base}/chat/completions'
    headers = {
        'Authorization': f'Bearer {random.choice(keys)}',
        'Content-Type': 'application/json',
    }
    if 'openrouter' in base:
        headers['HTTP-Referer'] = 'https://ieltsberuniy.netlify.app'
        headers['X-Title'] = 'IELTS Beruniy'

    payload = {
        'model': model.model_id,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': temperature,
        'max_tokens': max_tokens,
    }
    if response_schema:
        payload['response_format'] = {'type': 'json_object'}

    def _post(body):
        return requests.post(url, headers=headers, json=body, timeout=timeout)

    try:
        resp = _post(payload)
        if (resp.status_code == 400 and response_schema
                and 'response_format' in resp.text):
            payload.pop('response_format', None)
            resp = _post(payload)
    except requests.exceptions.Timeout:
        return {'success': False, 'error': f'{provider.name}: vaqt tugadi.'}
    except Exception as exc:  # noqa: BLE001
        return {'success': False, 'error': f'{provider.name}: {exc}'}

    if resp.status_code != 200:
        return {
            'success': False,
            'error': f'{provider.name} HTTP {resp.status_code}: {resp.text[:300]}',
        }

    try:
        data = resp.json()
        choice = (data.get('choices') or [{}])[0]
        message = choice.get('message') or {}
        text = message.get('content')
        if isinstance(text, list):
            text = ''.join(
                part.get('text', '') for part in text if isinstance(part, dict)
            )
        if not text:
            return {'success': False, 'error': f'{provider.name}: bo\'sh javob.'}
        usage = data.get('usage') or {}
        return {
            'success': True,
            'text': text,
            'model': data.get('model') or model.model_id,
            'tokens_in': usage.get('prompt_tokens') or 0,
            'tokens_out': usage.get('completion_tokens') or 0,
        }
    except Exception as exc:  # noqa: BLE001
        return {'success': False, 'error': f'{provider.name}: {exc}'}


def _call_gemini_model(model, prompt, temperature, max_tokens,
                       response_schema, timeout):
    keys = provider_keys(model.provider) or None
    return call_gemini(
        prompt,
        temperature=temperature,
        model=model.model_id,
        max_tokens=max_tokens,
        response_schema=response_schema,
        timeout=timeout,
        api_keys=keys,
    )


def call_ai(prompt, feature, *, user=None, temperature=None, max_tokens=None,
            response_schema=None, thinking='low', timeout=180, meta=None):
    """Tanlangan model(lar) orqali AI so'rovi. Natija: dict."""
    candidates = candidates_for(feature)
    last_error = 'AI model sozlanmagan.'

    for model in candidates:
        started = time.monotonic()
        temp = model.temperature if temperature is None else temperature
        tokens = max_tokens or model.max_tokens
        if model.provider.kind == AIProvider.KIND_GEMINI:
            result = _call_gemini_model(
                model, prompt, temp, tokens, response_schema, timeout
            )
        else:
            result = _call_openai_compatible(
                model, prompt, temp, tokens, response_schema, timeout
            )

        latency = int((time.monotonic() - started) * 1000)
        log_usage(
            feature=feature,
            provider=model.provider.name,
            model=result.get('model') or model.model_id,
            success=bool(result.get('success')),
            latency_ms=latency,
            user=user,
            tokens_in=result.get('tokens_in', 0),
            tokens_out=result.get('tokens_out', 0),
            error='' if result.get('success') else result.get('error', ''),
            meta=meta,
        )
        if result.get('success'):
            return {
                **result,
                'provider': model.provider.name,
                'provider_slug': model.provider.slug,
            }
        last_error = result.get('error') or last_error

    # Zaxira: eski env Gemini zanjiri (admin hali model sozlamagan bo'lsa).
    started = time.monotonic()
    legacy = call_gemini(
        prompt,
        temperature=0.7 if temperature is None else temperature,
        max_tokens=max_tokens or 8192,
        response_schema=response_schema,
        thinking=thinking,
        timeout=timeout,
    )
    latency = int((time.monotonic() - started) * 1000)
    log_usage(
        feature=feature,
        provider='Gemini (env)',
        model=legacy.get('model') or DEFAULT_MODEL,
        success=bool(legacy.get('success')),
        latency_ms=latency,
        user=user,
        tokens_in=legacy.get('tokens_in', 0),
        tokens_out=legacy.get('tokens_out', 0),
        error='' if legacy.get('success') else legacy.get('error', ''),
        meta=meta,
    )
    if legacy.get('success'):
        return {
            'success': True,
            'text': legacy['text'],
            'model': legacy.get('model') or DEFAULT_MODEL,
            'provider': 'Gemini (env)',
            'provider_slug': 'gemini-env',
        }
    return {
        'success': False,
        'error': legacy.get('error') or last_error,
    }
