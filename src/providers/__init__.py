"""Stateless text adapters; transport failures never expose response bodies or secrets."""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.ledger import canonical


class ProviderFailure(RuntimeError):
    pass


@dataclass
class Response:
    text: str
    input_tokens: object
    output_tokens: object
    metadata: dict


class FixtureProvider:
    """A scripted public-observation policy, never fresh model inference."""
    def __init__(self, model='fixture-reference-v1'):
        self.model = model

    def complete(self, request, max_output_tokens):
        public = request['public']
        evidence = public['evidence']
        if request['instruction'].startswith('Operate'):
            contract, goal = public['contract'], public['goal']
            if not evidence:
                decision = {'type': 'tool', 'name': contract['write_tool'],
                            'arguments': {'intent_id': goal['intent_id'], **goal['payload']}}
            elif len(evidence) == 1 and evidence[-1]['response']['status'] not in ('ok', 'rejected') and contract['verification'] != 'none':
                decision = {'type': 'tool', 'name': 'lookup', 'arguments': {'intent_id': goal['intent_id']}}
            else:
                decision = {'type': 'stop'}
            output = canonical(decision)
        elif request['instruction'].startswith('Write'):
            output = 'The available observations are recorded; I cannot confirm the settled outcome.'
        else:
            output = canonical({'claims': [], 'uncertainty': [{'predicate': 'completed', 'time': 'settled'}]})
        return Response(output, 0, 0, {'provider': 'fixture', 'requested_model': self.model,
            'returned_model': self.model, 'adapter_version': '1', 'fresh_inference': False})


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ProviderFailure('Provider redirects are disabled')


class ChatProvider:
    """OpenAI Chat Completions wire protocol; also supports local vLLM servers.

    No automatic retries, streaming, tool execution or implicit SDK options.
    """
    def __init__(self, config, transport=None):
        self.config = dict(config)
        self.model = config['model_id']
        base = config['base_url'].rstrip('/')
        parsed = urlsplit(base)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Invalid provider base URL')
        local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
        if parsed.scheme != 'https' and not local:
            raise ValueError('Remote providers require HTTPS')
        if config['adapter'] == 'local-chat' and not local:
            raise ValueError('Local model endpoint must be loopback')
        self.url = base + '/chat/completions'
        self.transport = transport or self._send

    def _send(self, body, headers):
        req = urllib.request.Request(self.url, data=canonical(body).encode(), headers=headers, method='POST')
        try:
            with urllib.request.build_opener(_NoRedirect()).open(req, timeout=self.config['timeout_seconds']) as res:
                raw = res.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ProviderFailure('Provider response exceeds byte limit')
            return json.loads(raw)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # Neither the body, URL, credentials nor server diagnostic is persisted.
            raise ProviderFailure('Provider transport or JSON failure') from None

    def complete(self, request, max_output_tokens):
        token_field = self.config['output_token_field']
        if token_field not in ('max_tokens', 'max_completion_tokens'):
            raise ValueError('Unsupported output token field')
        body = {'model': self.model, 'messages': [
            {'role': 'system', 'content': request['instruction']},
            {'role': 'user', 'content': canonical(request['public'])}], token_field: max_output_tokens,
            **self.config.get('settings', {})}
        headers = {'Content-Type': 'application/json'}
        key_name = self.config.get('api_key_env')
        if key_name:
            key = os.environ.get(key_name)
            if not key:
                raise ProviderFailure('Required credential is absent')
            headers['Authorization'] = 'Bearer ' + key
        start = time.monotonic()
        try:
            result = self.transport(body, headers)
            choices = result['choices']
            if len(choices) != 1 or choices[0]['message'].get('tool_calls'):
                raise ValueError('Unexpected choice or tool call')
            text = choices[0]['message']['content']
            if type(text) is not str or not text.strip():
                raise ValueError('Missing text')
            usage = result.get('usage') or {}
            input_tokens, output_tokens = usage.get('prompt_tokens'), usage.get('completion_tokens')
            for count in (input_tokens, output_tokens):
                if count is not None and (type(count) is not int or count < 0):
                    raise ValueError('Invalid usage')
            returned = result.get('model')
            if type(returned) is not str or not returned:
                raise ValueError('Missing returned model')
            return Response(text, input_tokens, output_tokens, {
                'provider': self.config['adapter'], 'adapter_version': '1', 'requested_model': self.model,
                'returned_model': returned, 'server_version': self.config['server_version'],
                'weights_revision': self.config.get('weights_revision'),
                'tokenizer_revision': self.config.get('tokenizer_revision'),
                'settings': self.config.get('settings', {}),
                'unsupported_options': self.config['unsupported_options'],
                'seed_reproducibility_guaranteed': False,
                'system_fingerprint': result.get('system_fingerprint'),
                'finish_reason': choices[0].get('finish_reason'),
                'elapsed_seconds': round(time.monotonic() - start, 6), 'fresh_inference': True,
                'response_sha256': hashlib.sha256(canonical(result).encode()).hexdigest()})
        except (KeyError, TypeError, ValueError, IndexError):
            raise ProviderFailure('Malformed provider completion') from None


def create(config):
    if config['adapter'] == 'fixture':
        return FixtureProvider(config['model_id'])
    if config['adapter'] in ('openai-chat', 'local-chat'):
        return ChatProvider(config)
    raise ValueError('Unsupported provider adapter')
