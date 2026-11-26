import json
import boto3
import uuid
import traceback
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('csi_data')

def lambda_handler(event, context):
    try:
        print(f"Lambda invocation: {context.aws_request_id}")
        print(f"Execution time: {datetime.now(timezone.utc).isoformat()}")

        body = json.loads(event.get('body', '{}'))

        item = {
            **body,
            'id': str(uuid.uuid4()),
            'timestamp_received': datetime.now(timezone.utc).isoformat()
        }

        print(f"Device ID: {item.get('device_id')}")
        print(f"Item ID: {item['id']}")

        response = table.put_item(
            Item=item,
            ReturnConsumedCapacity='TOTAL'
        )
    
    except Exception as e:
        print(f"ERRO: {str(e)}")
        print(traceback.format_exc())
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)})
        }
