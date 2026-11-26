import boto3
import json
from datetime import datetime, timezone, timedelta
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('model_result_10m')


def lambda_handler(event, context):
    cutoff = datetime.now(timezone.utc) - timedelta(days=15)
    cutoff_str = cutoff.isoformat()

    response = table.query(
        KeyConditionExpression=
            Key('series_id').eq('occupancy') &
            Key('bucket_start').gte(cutoff_str),
        ScanIndexForward=True
    )

    items = response.get('Items', [])

    while 'LastEvaluatedKey' in response:
        response = table.query(
            KeyConditionExpression=
                Key('series_id').eq('occupancy') &
                Key('bucket_start').gte(cutoff_str),
            ScanIndexForward=True,
            ExclusiveStartKey=response['LastEvaluatedKey']
        )

        items.extend(response.get('Items', []))

    series = []

    for item in items:
        total = int(item['total'])
        occupied = int(item['occupied_count'])

        ratio = occupied / total if total > 0 else 0

        series.append({
            'timestamp': item['bucket_start'],
            'result': ratio > 0.75
        })

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json'
        },
        'body': json.dumps(series)
    }