import json

TOKEN_VALIDO = "<token>"

def lambda_handler(event, context):
    identity_sources = event.get('identitySource', [])
    token = identity_sources[0] if isinstance(identity_sources, list) else identity_sources

    if token.startswith('Bearer '):
        token = token[7:]

    if token == TOKEN_VALIDO:
        return {
            'isAuthorized': True,
            'context': {'user': 'autorizado'}
        }
    else:
        return {
            'isAuthorized': False
        }


